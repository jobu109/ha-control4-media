"""Control4 number platform — exposes volume as a 0-100 slider."""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
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
    entities = [
        Control4VolumeNumber(coordinator, room["id"])
        for room in coordinator.data["rooms"]
    ]
    async_add_entities(entities)


class Control4VolumeNumber(Control4MediaEntity, NumberEntity):
    """Volume slider for a Control4 room (0–100)."""

    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:volume-high"
    _attr_name = "Volume"

    def __init__(self, coordinator: Control4MediaCoordinator, room_id: int) -> None:
        super().__init__(coordinator, room_id)
        self._attr_unique_id = f"{DOMAIN}_volume_{room_id}"

    @property
    def native_value(self) -> float | None:
        room = self._room
        return float(room["volume"]) if room else None

    async def async_set_native_value(self, value: float) -> None:
        level = round(value)
        await self.coordinator.director.send_post_request(
            f"/api/v1/items/{self._room_id}/commands",
            "SET_VOLUME_LEVEL",
            {"LEVEL": level},
        )
        if self._room is not None:
            self._room["volume"] = level
        self.async_write_ha_state()
