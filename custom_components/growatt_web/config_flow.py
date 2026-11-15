"""Config flow for the Growatt Web integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .api import GrowattAuthError, GrowattError, GrowattWebClient
from .const import (
    CONF_API_TOKEN,
    CONF_LIVE_INTERVAL,
    CONF_MODEL,
    CONF_PLANT_ID,
    CONF_SERIAL,
    CONF_SETTINGS_INTERVAL,
    DEFAULT_LIVE_INTERVAL,
    DEFAULT_SETTINGS_INTERVAL,
    DOMAIN,
    LIVE_INTERVAL_RANGE,
    SETTINGS_INTERVAL_RANGE,
)

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class GrowattWebConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for credentials, validate them with a login, find the inverter."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return GrowattWebOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            session = async_create_clientsession(self.hass)
            client = GrowattWebClient(
                session, user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            try:
                await client.login()
                device = await client.discover_device()
            except GrowattAuthError as err:
                _LOGGER.error("Growatt login rejected during setup: %s", err)
                errors["base"] = "invalid_auth"
            except GrowattError as err:
                _LOGGER.error("Growatt setup failed: %s: %s", type(err).__name__, err)
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(device.serial)
                self._abort_if_unique_id_configured()
                data = {
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_PLANT_ID: device.plant_id,
                    CONF_SERIAL: device.serial,
                    CONF_MODEL: device.model,
                }
                token = await self._obtain_token(client)
                if token:
                    data[CONF_API_TOKEN] = token
                return self.async_create_entry(
                    title=f"Growatt {device.model or device.serial}", data=data
                )

        return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA, errors=errors)

    async def _obtain_token(self, client: GrowattWebClient) -> str | None:
        """Read the account's API token; generate one only if the account has none.

        A failure is logged and the entry is created without a token; the
        integration then obtains it on its first poll.
        """
        try:
            token = await client.read_api_token()
            if not token:
                token = await client.reset_api_token()
        except GrowattError as err:
            _LOGGER.error(
                "Could not obtain the Growatt API token during setup: %s: %s",
                type(err).__name__,
                err,
            )
            return None
        return token


def _minutes(value_range: tuple[int, int]) -> Any:
    low, high = value_range
    return vol.All(
        NumberSelector(
            NumberSelectorConfig(
                min=low, max=high, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement="min"
            )
        ),
        vol.Coerce(int),
        vol.Range(min=low, max=high),
    )


class GrowattWebOptionsFlow(OptionsFlow):
    """Poll intervals for the live data and the settings, in minutes."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_LIVE_INTERVAL,
                    default=options.get(CONF_LIVE_INTERVAL, DEFAULT_LIVE_INTERVAL),
                ): _minutes(LIVE_INTERVAL_RANGE),
                vol.Required(
                    CONF_SETTINGS_INTERVAL,
                    default=options.get(CONF_SETTINGS_INTERVAL, DEFAULT_SETTINGS_INTERVAL),
                ): _minutes(SETTINGS_INTERVAL_RANGE),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
