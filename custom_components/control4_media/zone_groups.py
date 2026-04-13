"""Zone grouping service for Control4 Media.

Registers two HA services:
  control4_media.group_zones   — links a set of rooms to a leader room
  control4_media.ungroup_zones — unlinks rooms from their group

When zones are grouped, any volume/source change on the leader
is mirrored to all followers.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import Control4MediaCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_GROUP_ZONES = "group_zones"
SERVICE_UNGROUP_ZONES = "ungroup_zones"
SERVICE_SYNC_VOLUME = "sync_volume_to_group"

GROUP_ZONES_SCHEMA = vol.Schema(
    {
        vol.Required("leader_room_id"): cv.positive_int,
        vol.Required("follower_room_ids"): vol.All(
            cv.ensure_list, [cv.positive_int]
        ),
    }
)

UNGROUP_ZONES_SCHEMA = vol.Schema(
    {
        vol.Required("room_ids"): vol.All(cv.ensure_list, [cv.positive_int]),
    }
)

SYNC_VOLUME_SCHEMA = vol.Schema(
    {
        vol.Required("leader_room_id"): cv.positive_int,
    }
)


def async_register_services(hass: HomeAssistant) -> None:
    """Register zone grouping services."""

    def _get_coordinator(entry_id: str | None = None) -> Control4MediaCoordinator | None:
        domain_data = hass.data.get(DOMAIN, {})
        if entry_id:
            return domain_data.get(entry_id)
        # Return first coordinator if only one entry
        for coord in domain_data.values():
            return coord
        return None

    async def _handle_group_zones(call: ServiceCall) -> None:
        """Link follower rooms to a leader room."""
        leader_id: int = call.data["leader_room_id"]
        follower_ids: list[int] = call.data["follower_room_ids"]

        coord = _get_coordinator()
        if coord is None or coord.data is None:
            _LOGGER.error("Control4 coordinator not available")
            return

        # Record group in coordinator data
        groups: dict[int, list[int]] = coord.data.setdefault("groups", {})
        groups[leader_id] = follower_ids

        # Find leader's current state and apply to followers
        leader_room = next(
            (r for r in coord.data["rooms"] if r["id"] == leader_id), None
        )
        if leader_room is None:
            _LOGGER.warning("Leader room %s not found", leader_id)
            return

        for follower_id in follower_ids:
            try:
                # Match volume
                await coord.director.send_post_request(
                    f"/api/v1/items/{follower_id}/commands",
                    "SET_VOLUME_LEVEL",
                    {"LEVEL": leader_room["volume"]},
                )
                # Match audio source if set
                if leader_room.get("current_audio_source_id"):
                    await coord.director.send_post_request(
                        f"/api/v1/items/{follower_id}/commands",
                        "SELECT_AUDIO_DEVICE",
                        {"deviceid": leader_room["current_audio_source_id"]},
                    )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Failed to sync follower room %s: %s", follower_id, err
                )

        _LOGGER.info(
            "Grouped rooms %s → leader %s", follower_ids, leader_id
        )
        coord.async_set_updated_data(coord.data)

    async def _handle_ungroup_zones(call: ServiceCall) -> None:
        """Remove rooms from any group."""
        room_ids: list[int] = call.data["room_ids"]

        coord = _get_coordinator()
        if coord is None or coord.data is None:
            return

        groups: dict[int, list[int]] = coord.data.get("groups", {})

        # Remove these IDs as leaders or followers
        for rid in room_ids:
            groups.pop(rid, None)
            for leader, followers in list(groups.items()):
                if rid in followers:
                    followers.remove(rid)
                    if not followers:
                        del groups[leader]

        _LOGGER.info("Ungrouped rooms %s", room_ids)
        coord.async_set_updated_data(coord.data)

    async def _handle_sync_volume(call: ServiceCall) -> None:
        """Force-sync the leader's volume to all followers right now."""
        leader_id: int = call.data["leader_room_id"]

        coord = _get_coordinator()
        if coord is None or coord.data is None:
            return

        groups: dict[int, list[int]] = coord.data.get("groups", {})
        follower_ids = groups.get(leader_id, [])
        if not follower_ids:
            _LOGGER.warning("Room %s has no followers", leader_id)
            return

        leader_room = next(
            (r for r in coord.data["rooms"] if r["id"] == leader_id), None
        )
        if leader_room is None:
            return

        for follower_id in follower_ids:
            try:
                await coord.director.send_post_request(
                    f"/api/v1/items/{follower_id}/commands",
                    "SET_VOLUME_LEVEL",
                    {"LEVEL": leader_room["volume"]},
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Sync failed for room %s: %s", follower_id, err)

    hass.services.async_register(
        DOMAIN,
        SERVICE_GROUP_ZONES,
        _handle_group_zones,
        schema=GROUP_ZONES_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UNGROUP_ZONES,
        _handle_ungroup_zones,
        schema=UNGROUP_ZONES_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SYNC_VOLUME,
        _handle_sync_volume,
        schema=SYNC_VOLUME_SCHEMA,
    )
    _LOGGER.debug("Control4 zone grouping services registered")
