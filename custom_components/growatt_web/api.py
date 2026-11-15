"""Read-only client for the Growatt web portal (server.growatt.com).

The portal API is undocumented. Endpoints and field names were measured
against a live account on 2026-11-13 (see docs/superpowers/specs).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, TypeVar

import aiohttp

_LOGGER = logging.getLogger(__name__)
T = TypeVar("T")

BASE_URL = "https://server.growatt.com"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)
NO_LOGIN_MARKER = "errorNoLogin"


class GrowattError(Exception):
    """Any failure talking to the Growatt web portal."""


class GrowattAuthError(GrowattError):
    """Growatt rejected the login."""


class GrowattSessionExpired(GrowattError):
    """The portal session is no longer valid."""


@dataclass
class GrowattDevice:
    """Plant and inverter identity, determined at setup."""

    plant_id: str
    serial: str
    model: str | None = None


@dataclass
class GrowattData:
    """One complete poll result."""

    status: dict[str, Any] = field(default_factory=dict)
    day_totals: dict[str, Any] = field(default_factory=dict)
    totals: dict[str, Any] = field(default_factory=dict)
    device_info: dict[str, Any] = field(default_factory=dict)
    # Raw official API data, empty in portal operation: mix_last_data and the
    # last mix_data_info read (settings are read less often, see source.py).
    api: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)


def parse_json(text: str) -> Any:
    """Parse a portal response.

    The status response contains the keys ``vAc1`` and ``vac1``; JSON parsers
    that reject case-insensitive duplicates must not be used. Python's json
    keeps both keys, which is fine.
    """
    try:
        return json.loads(text)
    except ValueError as err:
        raise GrowattError(f"Response is not JSON: {text[:200]!r}") from err


class GrowattWebClient:
    """Session-based client. The session lives in the aiohttp cookie jar."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        base_url: str = BASE_URL,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._base_url = base_url.rstrip("/")
        self._logged_in = False

    async def _request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self._base_url}{path}"
        try:
            async with self._session.request(
                method,
                url,
                data=data,
                params=params,
                allow_redirects=False,
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location", "")
                    if NO_LOGIN_MARKER in location:
                        raise GrowattSessionExpired(f"{path}: redirected to {location}")
                    raise GrowattError(f"{path}: unexpected redirect to {location}")
                if resp.status != 200:
                    raise GrowattError(f"{path}: HTTP {resp.status}")
                text = await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise GrowattError(f"{path}: {type(err).__name__}: {err}") from err
        return parse_json(text)

    async def login(self) -> None:
        """Log in. Raises GrowattAuthError if Growatt rejects it."""
        _LOGGER.info("Growatt portal login")
        self._logged_in = False
        result = await self._request(
            "POST",
            "/login",
            data={"account": self._username, "password": self._password},
        )
        if not isinstance(result, dict) or result.get("result") != 1:
            msg = result.get("msg") if isinstance(result, dict) else None
            code = result.get("result") if isinstance(result, dict) else None
            raise GrowattAuthError(f"Login rejected (result={code!r}, msg={msg!r})")
        self._logged_in = True

    async def discover_device(self) -> GrowattDevice:
        """Find the first plant and its first inverter."""
        plants = await self._request("GET", "/index/getPlantListTitle")
        if not isinstance(plants, list) or not plants or "id" not in plants[0]:
            raise GrowattError(f"No plant found: {str(plants)[:200]}")
        plant_id = str(plants[0]["id"])
        info = await self._device_info(plant_id)
        serial = info.get("sn")
        if not serial:
            raise GrowattError(f"No inverter found in plant {plant_id}")
        return GrowattDevice(plant_id=plant_id, serial=str(serial), model=info.get("deviceModel"))

    async def _device_info(self, plant_id: str) -> dict[str, Any]:
        result = await self._request(
            "POST",
            "/panel/getDevicesByPlantList",
            data={"currPage": 1, "plantId": plant_id},
        )
        try:
            return result["obj"]["datas"][0]
        except (KeyError, IndexError, TypeError) as err:
            raise GrowattError(f"Unexpected device list: {str(result)[:200]}") from err

    async def _fetch(self, device: GrowattDevice) -> GrowattData:
        status = await self._request(
            "POST",
            "/panel/mix/getMIXStatusData",
            params={"plantId": device.plant_id},
            data={"mixSn": device.serial},
        )
        day = await self._request(
            "POST",
            "/panel/mix/getMIXEnergyDayChart",
            data={
                "date": date.today().isoformat(),
                "plantId": device.plant_id,
                "mixSn": device.serial,
            },
        )
        totals = await self._request(
            "POST",
            "/panel/mix/getMIXTotalData",
            params={"plantId": device.plant_id},
            data={"mixSn": device.serial},
        )
        info = await self._device_info(device.plant_id)
        try:
            status_obj = status["obj"]
            day_obj = {k: v for k, v in day["obj"].items() if k != "charts"}
            totals_obj = totals["obj"]
        except (KeyError, TypeError, AttributeError) as err:
            raise GrowattError(
                f"Unexpected data response: status={str(status)[:200]} "
                f"day={str(day)[:200]} totals={str(totals)[:200]}"
            ) from err
        if not isinstance(status_obj, dict) or not isinstance(totals_obj, dict):
            raise GrowattError(
                f"Unexpected data objects: status={str(status_obj)[:200]} "
                f"totals={str(totals_obj)[:200]}"
            )
        return GrowattData(
            status=status_obj, day_totals=day_obj, totals=totals_obj, device_info=info
        )

    async def _logged_in_call(self, call: Callable[[], Awaitable[T]]) -> T:
        """Run a call that needs a session.

        Reuses the current session. If it has expired, logs in once more and
        repeats the call. Any further failure is raised.
        """
        if not self._logged_in:
            await self.login()
            return await call()
        try:
            return await call()
        except GrowattSessionExpired as err:
            _LOGGER.info("Growatt session expired (%s), logging in again", err)
            await self.login()
            return await call()

    async def fetch(self, device: GrowattDevice) -> GrowattData:
        """Fetch all values through the portal."""
        return await self._logged_in_call(lambda: self._fetch(device))

    async def read_api_token(self) -> str:
        """Read the account's OpenAPI token. Empty if none was ever generated."""

        async def call() -> str:
            result = await self._request("POST", "/set/getUserTokenData")
            try:
                if result["result"] != 1:
                    raise GrowattError(f"getUserTokenData failed: msg={result.get('msg')!r}")
                return str(result["obj"].get("token") or "")
            except (KeyError, TypeError, AttributeError) as err:
                raise GrowattError("getUserTokenData: unexpected response") from err

        token = await self._logged_in_call(call)
        _LOGGER.info("Read Growatt API token from the portal (%s)", "set" if token else "empty")
        return token

    async def reset_api_token(self) -> str:
        """Generate a new OpenAPI token. The previous token stops working."""

        async def call() -> str:
            result = await self._request("POST", "/set/resetApiToken")
            try:
                ok = result["result"] == 1
                token = str(result.get("msg") or "")
            except (KeyError, TypeError, AttributeError) as err:
                raise GrowattError("resetApiToken: unexpected response") from err
            if not ok or not token:
                raise GrowattError("resetApiToken: Growatt did not return a new token")
            return token

        token = await self._logged_in_call(call)
        _LOGGER.warning("Generated a new Growatt API token; the previous token no longer works")
        return token
