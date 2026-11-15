"""Chooses between the official API (token) and the portal (password) per poll.

Implements decisions 3-12 of docs/superpowers/specs/2026-11-14-openapi-token-design.md.
No Home Assistant imports, so it can be tested on its own.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from .api import GrowattData, GrowattDevice, GrowattError
from .openapi import GrowattTokenDead, to_growatt_data

_LOGGER = logging.getLogger(__name__)

MODE_API = "api"
MODE_PORTAL = "portal"
# Waits before the next token recovery attempt after a failed one (seconds).
RECOVERY_DELAYS = (300, 600, 1200, 2400, 3600)
# Settings (mix_data_info) are read every settings interval (integration options,
# default SETTINGS_INTERVAL) and again after a write, but never twice within
# RATE_LIMIT (Growatt allows one call per endpoint per 5 min).
SETTINGS_INTERVAL = 3600
RATE_LIMIT = 300


class SourceController:
    """Holds the token and the current source; one call to fetch() per poll."""

    def __init__(
        self,
        portal: Any,
        openapi: Any,
        device: GrowattDevice,
        token: str | None,
        save_token: Callable[[str], None],
        clock: Callable[[], float] = time.monotonic,
        settings_interval: float = SETTINGS_INTERVAL,
    ) -> None:
        self._portal = portal
        self._openapi = openapi
        self._device = device
        self._token = token or None
        self._save_token = save_token
        self._clock = clock
        self._settings_interval = settings_interval
        self._mode = MODE_API
        self._dead: str | None = None
        self._own_token: str | None = None
        self._second_chance = False
        self._failures = 0
        self._next_recovery = float("-inf")
        self._tz: float | None = None
        self._tz_loaded = False
        self._settings: dict[str, Any] = {}
        self._settings_read_at = float("-inf")
        self._settings_due = True

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def token(self) -> str | None:
        return self._token

    async def fetch(self) -> GrowattData:
        if self._mode == MODE_PORTAL:
            return await self._fetch_portal_mode()
        if not self._token:
            return await self._recover("No Growatt API token stored")
        try:
            return await self._fetch_api(self._token)
        except GrowattTokenDead as err:
            self._dead = self._token
            return await self._recover(f"Growatt API token rejected ({err})")

    async def _fetch_api(self, token: str) -> GrowattData:
        last = await self._openapi.last_data(token, self._device.serial)
        if not self._tz_loaded:
            try:
                self._tz = await self._openapi.plant_timezone(token, self._device.plant_id)
                self._tz_loaded = True
            except GrowattTokenDead:
                raise
            except GrowattError as err:
                _LOGGER.warning("Growatt plant time zone not available yet: %s", err)
        data = to_growatt_data(last, self._tz)
        await self._refresh_settings(token)
        data.settings = dict(self._settings)
        return data

    async def _refresh_settings(self, token: str) -> None:
        now = self._clock()
        if now - self._settings_read_at < RATE_LIMIT:
            return
        if not self._settings_due and now - self._settings_read_at < self._settings_interval:
            return
        self._settings_read_at = now
        try:
            self._settings = await self._openapi.data_info(token, self._device.serial)
            self._settings_due = False
        except GrowattTokenDead:
            raise
        except GrowattError as err:
            _LOGGER.warning("Reading the Growatt settings failed, keeping the last values: %s", err)

    def _api_token(self) -> str:
        if self._mode != MODE_API or not self._token:
            raise GrowattError("This needs the official Growatt API, which is not available right now")
        return self._token

    async def write(self, type_id: str, params: list[str]) -> Any:
        """Set an inverter parameter through the official API; settings are re-read next poll."""
        result = await self._openapi.write(self._api_token(), self._device.serial, type_id, params)
        self._settings_due = True
        return result

    async def read_parameter(self, param_id: str, start_addr: int, end_addr: int) -> Any:
        return await self._openapi.read_parameter(
            self._api_token(), self._device.serial, param_id, start_addr, end_addr
        )

    async def history(self, start_date: str, end_date: str, page: int, perpage: int) -> Any:
        return await self._openapi.history(
            self._api_token(), self._device.serial, start_date, end_date, page, perpage
        )

    async def alarms(self, date: str | None, page: int, perpage: int) -> Any:
        return await self._openapi.alarms(self._api_token(), self._device.serial, date, page, perpage)

    async def _token_usable(self, token: str) -> bool:
        """True if the token works, False if dead. A disturbance raises."""
        try:
            await self._openapi.plants(token)
        except GrowattTokenDead as err:
            _LOGGER.warning("Growatt API token is not authorised: %s", err)
            return False
        return True

    def _adopt(self, token: str, how: str) -> None:
        if token != self._token:
            self._save_token(token)
        if self._mode != MODE_API or token != self._token:
            _LOGGER.info("Using Growatt API token (%s); source: official API", how)
        self._token = token
        self._mode = MODE_API
        self._dead = None
        self._own_token = None
        self._second_chance = False
        self._failures = 0
        self._next_recovery = float("-inf")

    def _recovery_failed(self, err: Exception) -> None:
        self._failures += 1
        delay = RECOVERY_DELAYS[min(self._failures, len(RECOVERY_DELAYS)) - 1]
        self._next_recovery = self._clock() + delay
        _LOGGER.error(
            "Obtaining a Growatt API token failed (%s: %s); next attempt in %d s",
            type(err).__name__,
            err,
            delay,
        )

    async def _recover(self, reason: str) -> GrowattData:
        now = self._clock()
        if now < self._next_recovery:
            raise GrowattError(
                f"{reason}; next token recovery attempt in {int(self._next_recovery - now)} s"
            )
        _LOGGER.warning("%s; reading the token through the portal", reason)
        try:
            token = await self._portal.read_api_token()
        except GrowattError as err:
            self._recovery_failed(err)
            raise
        if token and token != self._dead:
            try:
                usable = await self._token_usable(token)
            except GrowattError:
                self._adopt(token, "read from portal, not yet checked")
                raise
            if usable:
                self._adopt(token, "read from portal")
                return await self._fetch_api(token)
            self._dead = token
        try:
            new = await self._portal.reset_api_token()
        except GrowattError as err:
            self._recovery_failed(err)
            raise
        self._save_token(new)
        self._token = new
        try:
            usable = await self._token_usable(new)
        except GrowattError:
            self._adopt(new, "generated, not yet checked")
            raise
        if usable:
            self._adopt(new, "generated")
            return await self._fetch_api(new)
        _LOGGER.warning("Generated Growatt API token does not work either; switching to the portal")
        self._mode = MODE_PORTAL
        self._dead = new
        self._own_token = new
        self._second_chance = True
        self._failures = 0
        self._next_recovery = float("-inf")
        return await self._portal.fetch(self._device)

    async def _fetch_portal_mode(self) -> GrowattData:
        data = await self._portal.fetch(self._device)
        if self._second_chance:
            self._second_chance = False
            candidate: str | None = self._own_token
        else:
            try:
                token = await self._portal.read_api_token()
            except GrowattError as err:
                _LOGGER.warning("Reading the Growatt API token failed: %s", err)
                return data
            candidate = token if token and token != self._dead else None
        if candidate:
            try:
                usable = await self._token_usable(candidate)
            except GrowattError as err:
                _LOGGER.warning("Checking the Growatt API token failed, staying on the portal: %s", err)
                return data
            if usable:
                self._adopt(candidate, "portal operation ended")
            else:
                self._dead = candidate
        return data
