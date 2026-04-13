"""Diagnostics support for Control4 Media.

Accessible via Settings → Devices & Services → Control4 Media → Download Diagnostics.
All sensitive fields (tokens, passwords) are redacted automatically by HA core,
but we do an extra pass here for safety.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import Control4MediaCoordinator

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME, "token", "bearer_token"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: Control4MediaCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Build a sanitised snapshot of coordinator data
    rooms_snapshot = []
    if coordinator.data:
        for room in coordinator.data.get("rooms", []):
            rooms_snapshot.append(
                {
                    "id": room["id"],
                    "name": room["name"],
                    "is_on": room["is_on"],
                    "is_muted": room["is_muted"],
                    "volume": room["volume"],
                    "current_audio_source_id": room.get("current_audio_source_id"),
                    "current_video_source_id": room.get("current_video_source_id"),
                    "audio_source_count": len(room.get("audio_sources", [])),
                    "video_source_count": len(room.get("video_sources", [])),
                    "audio_sources": room.get("audio_sources", []),
                    "video_sources": room.get("video_sources", []),
                }
            )

    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "room_count": len(rooms_snapshot),
            "groups": coordinator.data.get("groups", {}) if coordinator.data else {},
            "rooms": rooms_snapshot,
        },
    }
