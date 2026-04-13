"""DataUpdateCoordinator for Control4 Media — compatible with pyControl4 v2.x"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from pyControl4.director import C4Director
from pyControl4.websocket import C4Websocket

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class Control4MediaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator fetches all room state in one pass and caches it."""

    def __init__(
        self,
        hass: HomeAssistant,
        director: C4Director,
        update_interval: timedelta,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.director = director
        self.director_token: str = director.director_bearer_token
        self.websocket: C4Websocket | None = None
        self._ws_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Core fetch
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._fetch_all()
        except Exception as err:
            raise UpdateFailed(
                f"Error communicating with Control4 Director: {err}"
            ) from err

    async def _fetch_all(self) -> dict[str, Any]:
        ui_config = await self.director.get_ui_configuration()
        all_items = await self.director.get_all_item_info()

        item_map: dict[int, dict] = {item["id"]: item for item in all_items}
        experiences: list[dict] = ui_config.get("experiences", [])

        room_ids: set[int] = set()
        for exp in experiences:
            room_ids.add(int(exp["room_id"]))

        room_var_tasks = {
            room_id: asyncio.ensure_future(self._fetch_room_vars(room_id))
            for room_id in room_ids
        }
        room_vars: dict[int, dict] = {}
        for room_id, task in room_var_tasks.items():
            try:
                room_vars[room_id] = await task
            except Exception as err:
                _LOGGER.warning("Failed to fetch vars for room %s: %s", room_id, err)
                room_vars[room_id] = {}

        room_audio_sources: dict[int, list[dict]] = {}
        room_video_sources: dict[int, list[dict]] = {}

        for exp in experiences:
            room_id = int(exp["room_id"])
            exp_type = exp.get("type")
            sources = exp.get("sources", {}).get("source", [])
            if isinstance(sources, dict):
                sources = [sources]

            for src in sources:
                src_id = int(src["id"])
                src_info = item_map.get(src_id, {})
                entry = {
                    "id": src_id,
                    "name": src.get("name") or src_info.get("name", f"Source {src_id}"),
                    "type": src.get("type", "UNKNOWN"),
                }
                if exp_type == "listen":
                    room_audio_sources.setdefault(room_id, []).append(entry)
                elif exp_type == "watch":
                    room_video_sources.setdefault(room_id, []).append(entry)

        existing_groups: dict = {}
        if self.data:
            existing_groups = self.data.get("groups", {})

        rooms: list[dict[str, Any]] = []
        seen_rooms: set[int] = set()
        for room_id in room_ids:
            if room_id in seen_rooms:
                continue
            seen_rooms.add(room_id)

            info = item_map.get(room_id, {})
            vars_ = room_vars.get(room_id, {})

            rooms.append(
                {
                    "id": room_id,
                    "name": info.get("name", f"Room {room_id}"),
                    "is_on": bool(int(vars_.get("POWER_STATE", 0))),
                    "is_muted": bool(int(vars_.get("IS_MUTED", 0))),
                    "volume": int(vars_.get("CURRENT_VOLUME", 0)),
                    "current_audio_source_id": _parse_int_or_none(
                        vars_.get("CURRENT_SELECTED_DEVICE")
                    ),
                    "current_video_source_id": _parse_int_or_none(
                        vars_.get("CURRENT_VIDEO_DEVICE")
                    ),
                    "audio_sources": room_audio_sources.get(room_id, []),
                    "video_sources": room_video_sources.get(room_id, []),
                }
            )

        return {"rooms": rooms, "groups": existing_groups}

    async def _fetch_room_vars(self, room_id: int) -> dict[str, Any]:
        var_names = [
            "POWER_STATE",
            "IS_MUTED",
            "CURRENT_VOLUME",
            "CURRENT_SELECTED_DEVICE",
            "CURRENT_VIDEO_DEVICE",
        ]
        result: dict[str, Any] = {}
        for var in var_names:
            try:
                val = await self.director.get_item_variable_value(room_id, var)
                if val is not None:
                    result[var] = val
            except Exception:
                pass
        return result

    # ------------------------------------------------------------------
    # Websocket — pyControl4 v2 API
    # v2 uses: add_item_callback(item_id, fn) + sio_connect(token)
    # ------------------------------------------------------------------

    async def async_start_websocket(self) -> None:
        if self.websocket is None:
            return

        def _make_room_callback(room_id: int):
            def _on_item_message(message: dict) -> None:
                if self.data is None:
                    return

                updates = message if isinstance(message, list) else [message]

                changed = False
                for update in updates:
                    var_name = update.get("varName") or update.get("name", "")
                    value = update.get("value")
                    if value is None:
                        continue

                    for room in self.data["rooms"]:
                        if room["id"] != room_id:
                            continue
                        if var_name == "CURRENT_VOLUME":
                            room["volume"] = int(value)
                        elif var_name == "IS_MUTED":
                            room["is_muted"] = bool(int(value))
                        elif var_name == "POWER_STATE":
                            room["is_on"] = bool(int(value))
                        elif var_name == "CURRENT_SELECTED_DEVICE":
                            room["current_audio_source_id"] = _parse_int_or_none(value)
                        elif var_name == "CURRENT_VIDEO_DEVICE":
                            room["current_video_source_id"] = _parse_int_or_none(value)
                        else:
                            break

                        groups: dict[int, list[int]] = self.data.get("groups", {})
                        follower_ids = groups.get(room_id, [])
                        if follower_ids and var_name in (
                            "CURRENT_VOLUME",
                            "IS_MUTED",
                            "CURRENT_SELECTED_DEVICE",
                            "CURRENT_VIDEO_DEVICE",
                        ):
                            asyncio.ensure_future(
                                self._mirror_to_followers(
                                    follower_ids, var_name, value, room
                                )
                            )
                        changed = True
                        break

                if changed:
                    self.hass.loop.call_soon_threadsafe(
                        self.async_set_updated_data, self.data
                    )

            return _on_item_message

        if self.data:
            for room in self.data["rooms"]:
                self.websocket.add_item_callback(
                    room["id"], _make_room_callback(room["id"])
                )

        async def _ws_loop() -> None:
            while True:
                try:
                    _LOGGER.debug("Control4 websocket connecting...")
                    await self.websocket.sio_connect(self.director_token)
                    _LOGGER.debug("Control4 websocket connected")
                except Exception as err:
                    _LOGGER.warning(
                        "Control4 websocket disconnected, retrying in 30s: %s", err
                    )
                    await asyncio.sleep(30)

        self._ws_task = asyncio.ensure_future(_ws_loop())

    async def _mirror_to_followers(
        self,
        follower_ids: list[int],
        var_name: str,
        value: Any,
        leader_room: dict[str, Any],
    ) -> None:
        for fid in follower_ids:
            try:
                if var_name == "CURRENT_VOLUME":
                    await self.director.send_post_request(
                        f"/api/v1/items/{fid}/commands",
                        "SET_VOLUME_LEVEL",
                        {"LEVEL": int(value)},
                    )
                elif var_name == "IS_MUTED":
                    cmd = "MUTE_ON" if bool(int(value)) else "MUTE_OFF"
                    await self.director.send_post_request(
                        f"/api/v1/items/{fid}/commands", cmd, {}
                    )
                elif var_name == "CURRENT_SELECTED_DEVICE":
                    src_id = _parse_int_or_none(value)
                    if src_id:
                        await self.director.send_post_request(
                            f"/api/v1/items/{fid}/commands",
                            "SELECT_AUDIO_DEVICE",
                            {"deviceid": src_id},
                        )
                elif var_name == "CURRENT_VIDEO_DEVICE":
                    src_id = _parse_int_or_none(value)
                    if src_id:
                        await self.director.send_post_request(
                            f"/api/v1/items/{fid}/commands",
                            "SELECT_VIDEO_DEVICE",
                            {"deviceid": src_id},
                        )
            except Exception as err:
                _LOGGER.warning(
                    "Failed to mirror %s to follower room %s: %s", var_name, fid, err
                )

    async def async_stop_websocket(self) -> None:
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        if self.websocket:
            try:
                await self.websocket.sio_disconnect()
            except Exception:
                pass


def _parse_int_or_none(value: Any) -> int | None:
    try:
        v = int(value)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None
