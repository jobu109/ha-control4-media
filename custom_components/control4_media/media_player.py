"""Control4 media_player platform.

Each Control4 room becomes a MediaPlayer entity that supports:
- Source selection (audio + video)
- Volume + mute
- Play / Pause / Stop transport
- MediaPlayerEntityFeature.BROWSE_MEDIA via the HA media browser protocol
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import Control4MediaCoordinator
from .entity import Control4MediaEntity

_LOGGER = logging.getLogger(__name__)

SUPPORT_C4_ROOM = (
    MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.BROWSE_MEDIA
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: Control4MediaCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        Control4RoomMediaPlayer(coordinator, room["id"])
        for room in coordinator.data["rooms"]
    ]
    async_add_entities(entities)


class Control4RoomMediaPlayer(Control4MediaEntity, MediaPlayerEntity):
    """A Control4 room as a HA media_player."""

    _attr_device_class = MediaPlayerDeviceClass.RECEIVER

    def __init__(self, coordinator: Control4MediaCoordinator, room_id: int) -> None:
        super().__init__(coordinator, room_id)
        self._attr_unique_id = f"{DOMAIN}_media_player_{room_id}"

    @property
    def name(self) -> str:
        room = self._room
        return room["name"] if room else f"Room {self._room_id}"

    @property
    def state(self) -> MediaPlayerState | None:
        room = self._room
        if room is None:
            return None
        if not room["is_on"]:
            return MediaPlayerState.OFF
        return MediaPlayerState.PLAYING

    @property
    def volume_level(self) -> float | None:
        room = self._room
        if room is None:
            return None
        return room["volume"] / 100.0

    @property
    def is_volume_muted(self) -> bool | None:
        room = self._room
        if room is None:
            return None
        return room["is_muted"]

    @property
    def source(self) -> str | None:
        room = self._room
        if room is None:
            return None
        # Prefer audio source; fall back to video
        src_id = room.get("current_audio_source_id") or room.get("current_video_source_id")
        if src_id is None:
            return None
        for src in room["audio_sources"] + room["video_sources"]:
            if src["id"] == src_id:
                return src["name"]
        return str(src_id)

    @property
    def source_list(self) -> list[str]:
        room = self._room
        if room is None:
            return []
        names = []
        seen: set[str] = set()
        for src in room["audio_sources"] + room["video_sources"]:
            n = src["name"]
            if n not in seen:
                names.append(n)
                seen.add(n)
        return names

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        return SUPPORT_C4_ROOM

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def async_turn_off(self) -> None:
        await self.coordinator.director.send_post_request(
            f"/api/v1/items/{self._room_id}/commands", "ROOM_OFF", {}
        )
        await self.coordinator.async_request_refresh()

    async def async_set_volume_level(self, volume: float) -> None:
        level = round(volume * 100)
        await self.coordinator.director.send_post_request(
            f"/api/v1/items/{self._room_id}/commands",
            "SET_VOLUME_LEVEL",
            {"LEVEL": level},
        )
        # Optimistic update
        if self._room is not None:
            self._room["volume"] = level
        self.async_write_ha_state()

    async def async_mute_volume(self, mute: bool) -> None:
        cmd = "MUTE_ON" if mute else "MUTE_OFF"
        await self.coordinator.director.send_post_request(
            f"/api/v1/items/{self._room_id}/commands", cmd, {}
        )
        if self._room is not None:
            self._room["is_muted"] = mute
        self.async_write_ha_state()

    async def async_volume_up(self) -> None:
        await self.coordinator.director.send_post_request(
            f"/api/v1/items/{self._room_id}/commands", "PULSE_VOL_UP", {}
        )
        await self.coordinator.async_request_refresh()

    async def async_volume_down(self) -> None:
        await self.coordinator.director.send_post_request(
            f"/api/v1/items/{self._room_id}/commands", "PULSE_VOL_DOWN", {}
        )
        await self.coordinator.async_request_refresh()

    async def async_media_play(self) -> None:
        await self.coordinator.director.send_post_request(
            f"/api/v1/items/{self._room_id}/commands", "PLAY", {}
        )

    async def async_media_pause(self) -> None:
        await self.coordinator.director.send_post_request(
            f"/api/v1/items/{self._room_id}/commands", "PAUSE", {}
        )

    async def async_media_stop(self) -> None:
        await self.coordinator.director.send_post_request(
            f"/api/v1/items/{self._room_id}/commands", "STOP", {}
        )

    async def async_select_source(self, source: str) -> None:
        """Select audio or video source by name."""
        room = self._room
        if room is None:
            return

        # Search audio sources first, then video
        for src in room["audio_sources"]:
            if src["name"] == source:
                await self.coordinator.director.send_post_request(
                    f"/api/v1/items/{self._room_id}/commands",
                    "SELECT_AUDIO_DEVICE",
                    {"deviceid": src["id"]},
                )
                room["current_audio_source_id"] = src["id"]
                self.async_write_ha_state()
                return

        for src in room["video_sources"]:
            if src["name"] == source:
                await self.coordinator.director.send_post_request(
                    f"/api/v1/items/{self._room_id}/commands",
                    "SELECT_VIDEO_DEVICE",
                    {"deviceid": src["id"]},
                )
                room["current_video_source_id"] = src["id"]
                self.async_write_ha_state()
                return

        _LOGGER.warning("Source '%s' not found for room %s", source, self._room_id)

    # ------------------------------------------------------------------
    # Browse Media
    # ------------------------------------------------------------------

    async def async_browse_media(
        self,
        media_content_type: str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Implement the media browser.

        Top level: two folders — Audio Sources, Video Sources.
        Drill in to see individual sources.
        """
        room = self._room

        if media_content_id is None or media_content_id == "root":
            children = []
            if room and room["audio_sources"]:
                children.append(
                    BrowseMedia(
                        title="Audio Sources",
                        media_class="directory",
                        media_content_type=MediaType.MUSIC,
                        media_content_id="audio",
                        can_play=False,
                        can_expand=True,
                    )
                )
            if room and room["video_sources"]:
                children.append(
                    BrowseMedia(
                        title="Video Sources",
                        media_class="directory",
                        media_content_type=MediaType.VIDEO,
                        media_content_id="video",
                        can_play=False,
                        can_expand=True,
                    )
                )
            return BrowseMedia(
                title=room["name"] if room else "Sources",
                media_class="directory",
                media_content_type="directory",
                media_content_id="root",
                can_play=False,
                can_expand=True,
                children=children,
            )

        if media_content_id == "audio" and room:
            children = [
                BrowseMedia(
                    title=src["name"],
                    media_class="music",
                    media_content_type=MediaType.MUSIC,
                    media_content_id=f"audio:{src['id']}",
                    can_play=True,
                    can_expand=False,
                    thumbnail=None,
                )
                for src in room["audio_sources"]
            ]
            return BrowseMedia(
                title="Audio Sources",
                media_class="directory",
                media_content_type=MediaType.MUSIC,
                media_content_id="audio",
                can_play=False,
                can_expand=True,
                children=children,
            )

        if media_content_id == "video" and room:
            children = [
                BrowseMedia(
                    title=src["name"],
                    media_class="video",
                    media_content_type=MediaType.VIDEO,
                    media_content_id=f"video:{src['id']}",
                    can_play=True,
                    can_expand=False,
                    thumbnail=None,
                )
                for src in room["video_sources"]
            ]
            return BrowseMedia(
                title="Video Sources",
                media_class="directory",
                media_content_type=MediaType.VIDEO,
                media_content_id="video",
                can_play=False,
                can_expand=True,
                children=children,
            )

        raise ValueError(f"Unknown media_content_id: {media_content_id}")

    async def async_play_media(
        self, media_type: str, media_id: str, **kwargs: Any
    ) -> None:
        """Handle play from the browser — media_id is 'audio:<id>' or 'video:<id>'."""
        try:
            kind, raw_id = media_id.split(":", 1)
            device_id = int(raw_id)
        except (ValueError, AttributeError):
            _LOGGER.error("Cannot parse media_id: %s", media_id)
            return

        cmd = "SELECT_AUDIO_DEVICE" if kind == "audio" else "SELECT_VIDEO_DEVICE"
        await self.coordinator.director.send_post_request(
            f"/api/v1/items/{self._room_id}/commands",
            cmd,
            {"deviceid": device_id},
        )
        room = self._room
        if room is not None:
            if kind == "audio":
                room["current_audio_source_id"] = device_id
            else:
                room["current_video_source_id"] = device_id
        self.async_write_ha_state()
