"""Polling coordinator for the Growatt Web integration."""

from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import GrowattData, GrowattDevice, GrowattError, GrowattWebClient
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class GrowattWebCoordinator(DataUpdateCoordinator[GrowattData]):
    """Polls the Growatt web portal every SCAN_INTERVAL.

    No extra retries: a failed poll makes the sensors unavailable until the
    next regular poll. The only retry is the single re-login on an expired
    session inside GrowattWebClient.fetch.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: GrowattWebClient,
        device: GrowattDevice,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self.device = device
        self.last_success: datetime | None = None

    async def _async_update_data(self) -> GrowattData:
        try:
            data = await self.client.fetch(self.device)
        except GrowattError as err:
            _LOGGER.error("Growatt poll failed: %s: %s", type(err).__name__, err)
            raise UpdateFailed(f"{type(err).__name__}: {err}") from err
        self.last_success = dt_util.utcnow()
        return data
