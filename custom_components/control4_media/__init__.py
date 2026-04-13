"""Control4 Media Integration for Home Assistant."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import aiohttp
from pyControl4.account import C4Account
from pyControl4.director import C4Director
from pyControl4.websocket import C4Websocket

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import DOMAIN, SCAN_INTERVAL
from .coordinator import Control4MediaCoordinator
from .zone_groups import async_register_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.DIAGNOSTICS,
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.SWITCH,
]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register domain-level services once."""
    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Control4 Media from a config entry."""
    host = entry.data[CONF_HOST]
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    # Create a no-SSL-verify session (Control4 uses self-signed certs)
    session = async_create_clientsession(hass, verify_ssl=False)

    try:
        account = C4Account(username, password, session)
        await account.getAccountBearerToken()
        controllers = await account.getAccountControllers()
        common_name = controllers["controllerCommonName"]
        token_data = await account.getDirectorBearerToken(common_name)
        director_token = token_data["token"]
    except aiohttp.ClientError as err:
        raise ConfigEntryNotReady(f"Cannot connect to Control4 account: {err}") from err
    except KeyError as err:
        raise ConfigEntryAuthFailed(f"Invalid credentials or account data: {err}") from err

    director = C4Director(host, director_token, session)

    coordinator = Control4MediaCoordinator(
        hass,
        director=director,
        update_interval=timedelta(seconds=SCAN_INTERVAL),
    )

    await coordinator.async_config_entry_first_refresh()

    # Start websocket for real-time variable updates
    # v2 API: token is passed at sio_connect(), not at init
    websocket = C4Websocket(host, session_no_verify_ssl=session)
    coordinator.websocket = websocket
    await coordinator.async_start_websocket()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: Control4MediaCoordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_stop_websocket()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle an options update."""
    await hass.config_entries.async_reload(entry.entry_id)
