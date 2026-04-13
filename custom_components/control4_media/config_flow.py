"""Config flow for Control4 Media."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
from pyControl4.account import C4Account
from pyControl4.director import C4Director
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import CONF_INCLUDE_HIDDEN_ROOMS, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_HOST): str,
    }
)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_INCLUDE_HIDDEN_ROOMS, default=False): bool,
    }
)


async def _validate_connection(
    hass: HomeAssistant, data: dict[str, Any]
) -> dict[str, Any]:
    """Try to authenticate and connect to the Director. Return info dict or raise."""
    session = async_create_clientsession(hass, verify_ssl=False)
    account = C4Account(data[CONF_USERNAME], data[CONF_PASSWORD], session)
    await account.getAccountBearerToken()
    controllers = await account.getAccountControllers()
    common_name = controllers["controllerCommonName"]
    token_data = await account.getDirectorBearerToken(common_name)
    director_token = token_data["token"]

    director = C4Director(data[CONF_HOST], director_token, session)
    # Quick sanity check: list items
    await director.get_all_item_info()

    return {"title": f"Control4 ({data[CONF_HOST]})", "token": director_token}


class Control4MediaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await _validate_connection(self.hass, user_input)
            except aiohttp.ClientError:
                errors["base"] = "cannot_connect"
            except KeyError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during Control4 setup")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(user_input[CONF_HOST])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return Control4MediaOptionsFlow(config_entry)


class Control4MediaOptionsFlow(config_entries.OptionsFlow):
    """Handle options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_INCLUDE_HIDDEN_ROOMS,
                        default=self.config_entry.options.get(
                            CONF_INCLUDE_HIDDEN_ROOMS, False
                        ),
                    ): bool,
                }
            ),
        )
