"""Growatt OpenAPI: Growatt SPH inverter values and settings via the official API, portal as fallback."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import GrowattDevice, GrowattWebClient
from .const import CONF_API_TOKEN, CONF_MODEL, CONF_PLANT_ID, CONF_SERIAL
from .coordinator import GrowattWebCoordinator
from .openapi import OpenApiClient
from .services import async_register_services
from .source import SourceController

PLATFORMS = [Platform.SENSOR]

type GrowattWebConfigEntry = ConfigEntry[GrowattWebCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: GrowattWebConfigEntry) -> bool:
    """Set up Growatt OpenAPI from a config entry."""
    # A dedicated session: the portal login lives in this session's cookie jar.
    session = async_create_clientsession(hass)
    client = GrowattWebClient(session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    device = GrowattDevice(
        plant_id=entry.data[CONF_PLANT_ID],
        serial=entry.data[CONF_SERIAL],
        model=entry.data.get(CONF_MODEL),
    )

    def save_token(token: str) -> None:
        hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_API_TOKEN: token})

    source = SourceController(
        client, OpenApiClient(session), device, entry.data.get(CONF_API_TOKEN), save_token
    )
    coordinator = GrowattWebCoordinator(hass, entry, source, device)
    # Not async_config_entry_first_refresh: a failed first poll would make Home
    # Assistant retry the whole setup within seconds, with a fresh controller and
    # a fresh portal login each time. A failed poll leaves the sensors unavailable;
    # the controller's own backoff decides when to try again.
    await coordinator.async_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GrowattWebConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
