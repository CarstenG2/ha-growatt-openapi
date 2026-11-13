"""Growatt Web: read-only Growatt inverter values via the Growatt web portal."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import GrowattDevice, GrowattWebClient
from .const import CONF_MODEL, CONF_PLANT_ID, CONF_SERIAL
from .coordinator import GrowattWebCoordinator

PLATFORMS = [Platform.SENSOR]

type GrowattWebConfigEntry = ConfigEntry[GrowattWebCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: GrowattWebConfigEntry) -> bool:
    """Set up Growatt Web from a config entry."""
    # A dedicated session: the portal login lives in this session's cookie jar.
    session = async_create_clientsession(hass)
    client = GrowattWebClient(session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    device = GrowattDevice(
        plant_id=entry.data[CONF_PLANT_ID],
        serial=entry.data[CONF_SERIAL],
        model=entry.data.get(CONF_MODEL),
    )
    coordinator = GrowattWebCoordinator(hass, entry, client, device)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GrowattWebConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
