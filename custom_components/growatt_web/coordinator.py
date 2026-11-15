"""Polling coordinator for the Growatt Web integration."""

from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import GrowattData, GrowattDevice, GrowattError
from .const import DOMAIN, SCAN_INTERVAL
from .source import SourceController

_LOGGER = logging.getLogger(__name__)


class GrowattWebCoordinator(DataUpdateCoordinator[GrowattData]):
    """Polls Growatt every SCAN_INTERVAL through the SourceController.

    The controller reads the official API with a token and falls back to the
    web portal (see docs/superpowers/specs/2026-11-14-openapi-token-design.md).
    No extra retries: a failed poll makes the sensors unavailable until the
    next regular poll.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        source: SourceController,
        device: GrowattDevice,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.source = source
        self.device = device
        self.last_success: datetime | None = None

    async def _async_update_data(self) -> GrowattData:
        try:
            data = await self.source.fetch()
        except GrowattError as err:
            _LOGGER.error("Growatt poll failed: %s: %s", type(err).__name__, err)
            raise UpdateFailed(f"{type(err).__name__}: {err}") from err
        self.last_success = dt_util.utcnow()
        return data
