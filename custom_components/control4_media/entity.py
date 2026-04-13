"""Base entity for Control4 Media."""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Control4MediaCoordinator


class Control4MediaEntity(CoordinatorEntity[Control4MediaCoordinator]):
    """Base class that pulls its room dict from the coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Control4MediaCoordinator,
        room_id: int,
    ) -> None:
        super().__init__(coordinator)
        self._room_id = room_id

    @property
    def _room(self) -> dict[str, Any] | None:
        if self.coordinator.data is None:
            return None
        for room in self.coordinator.data["rooms"]:
            if room["id"] == self._room_id:
                return room
        return None

    @property
    def device_info(self):
        room = self._room
        name = room["name"] if room else f"Room {self._room_id}"
        return {
            "identifiers": {(DOMAIN, str(self._room_id))},
            "name": name,
            "manufacturer": "Control4",
            "model": "Audio/Video Zone",
        }
