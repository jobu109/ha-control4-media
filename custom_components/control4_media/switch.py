"""Control4 switch platform.

Two switches per room:
  1. Power  — turns the room ON/OFF
  2. Mute   — mutes/unmutes the room
"""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import Control4MediaCoordinator
from .entity import Control4MediaEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: Control4MediaCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SwitchEntity] = []
    for room in coordinator.data["rooms"]:
        entities.append(Control4PowerSwitch(coordinator, room["id"]))
        entities.append(Control4MuteSwitch(coordinator, room["id"]))
    async_add_entities(entities)


class Control4PowerSwitch(Control4MediaEntity, SwitchEntity):
    """Power switch for a Control4 room."""

    _attr_icon = "mdi:power"
    _attr_name = "Power"

    def __init__(self, coordinator: Control4MediaCoordinator, room_id: int) -> None:
        super().__init__(coordinator, room_id)
        self._attr_unique_id = f"{DOMAIN}_power_{room_id}"

    @property
    def is_on(self) -> bool | None:
        room = self._room
        return room["is_on"] if room else None

    async def async_turn_on(self, **kwargs) -> None:
        # Control4 turns on a room by selecting a source; we send a generic ON
        # via the media player approach. If your system has a standalone ROOM_ON
        # command, substitute it here.
        await self.coordinator.director.send_post_request(
            f"/api/v1/items/{self._room_id}/commands", "ROOM_ON", {}
        )
        if self._room is not None:
            self._room["is_on"] = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.director.send_post_request(
            f"/api/v1/items/{self._room_id}/commands", "ROOM_OFF", {}
        )
        if self._room is not None:
            self._room["is_on"] = False
        self.async_write_ha_state()


class Control4MuteSwitch(Control4MediaEntity, SwitchEntity):
    """Mute switch for a Control4 room."""

    _attr_icon = "mdi:volume-mute"
    _attr_name = "Mute"

    def __init__(self, coordinator: Control4MediaCoordinator, room_id: int) -> None:
        super().__init__(coordinator, room_id)
        self._attr_unique_id = f"{DOMAIN}_mute_{room_id}"

    @property
    def is_on(self) -> bool | None:
        room = self._room
        return room["is_muted"] if room else None

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.director.send_post_request(
            f"/api/v1/items/{self._room_id}/commands", "MUTE_ON", {}
        )
        if self._room is not None:
            self._room["is_muted"] = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.director.send_post_request(
            f"/api/v1/items/{self._room_id}/commands", "MUTE_OFF", {}
        )
        if self._room is not None:
            self._room["is_muted"] = False
        self.async_write_ha_state()
