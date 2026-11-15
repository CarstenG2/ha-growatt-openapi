"""Client for the official Growatt OpenAPI v1 (openapi.growatt.com) with an API token.

Every request carries the same token in the ``token`` header; there is no login
and no session. Error codes measured 2026-11-14: a dead token is answered with
HTTP 200 and ``error_code`` 10011; ``10012`` is the per-endpoint rate limit
("5 minutes/time"). See docs/superpowers/specs/2026-11-14-openapi-token-design.md.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import aiohttp

from .api import REQUEST_TIMEOUT, GrowattData, GrowattError, parse_json

_LOGGER = logging.getLogger(__name__)

OPENAPI_URL = "https://openapi.growatt.com/v1/"
ERROR_NO_PRIVILEGE = 10011
MAX_PARAMS = 18  # mixSet takes param1..param18

# API field -> (portal field, divisor). Verified against the portal on 2026-11-14.
STATUS_FIELDS: dict[str, tuple[str, float]] = {
    "soc": ("SOC", 1),
    "vbat": ("vBat", 1),
    "pcharge1": ("chargePower", 1000),
    "pdischarge1": ("pdisCharge1", 1000),
    "pacToGridTotal": ("pactogrid", 1000),
    "pacToUserTotal": ("pactouser", 1000),
    "plocalLoadTotal": ("pLocalLoad", 1000),
    "ppv": ("ppv", 1000),
    "vpv1": ("vPv1", 1),
    "ppv1": ("pPv1", 1),
    "vpv2": ("vPv2", 1),
    "ppv2": ("pPv2", 1),
    "vac1": ("vAc1", 1),
    "fac": ("fAc", 1),
    # Battery management (BMS) values, API mode only: charge current limit (A),
    # battery current (A, negative = discharging) and BMS battery temperature (degC).
    "bmsMaxCurr": ("bmsMaxCurr", 1),
    "bmsBatteryCurr": ("bmsBatteryCurr", 1),
    "bmsBatteryTemp": ("bmsBatteryTemp", 1),
}
DAY_FIELDS: dict[str, str] = {"elocalLoadToday": "elocalLoad"}
TOTAL_FIELDS: dict[str, str] = {
    "epvtoday": "epvToday",
    "epvTotal": "epvTotal",
    "etoGridToday": "etoGridToday",
    "etogridTotal": "etogridTotal",
    "edischarge1Today": "edischarge1Today",
    "edischarge1Total": "edischarge1Total",
    "elocalLoadToday": "elocalLoadToday",
    "elocalLoadTotal": "elocalLoadTotal",
}
# Portal fields the API does not deliver directly. The portal computes them
# from the same inverter counters (verified against the portal three times on
# 2026-11-14, exact to 0.1 kWh): (target dict, portal field, minuend, subtrahend).
DERIVED_FIELDS: tuple[tuple[str, str, str, str | None], ...] = (
    ("day_totals", "eCharge", "esystemtoday", None),
    ("day_totals", "eAcCharge", "esystemtoday", "eselftoday"),
    ("day_totals", "etouser", "elocalLoadToday", "eselftoday"),
    ("totals", "gridPowerToday", "elocalLoadToday", "eselftoday"),
    ("totals", "gridPowerTotal", "elocalLoadTotal", "eselftotal"),
)

_GMT_RE = re.compile(r"^GMT(?:([+-])(\d{1,2})(?::(\d{2}))?)?$")


class GrowattTokenDead(GrowattError):
    """Growatt answered validly and the answer shows the token is not authorised."""


def parse_gmt_offset(value: Any) -> float | None:
    """Parse a Growatt time zone string like "GMT+1" or "GMT-3:30" into hours."""
    if not value:
        return None
    match = _GMT_RE.match(str(value).strip())
    if not match:
        _LOGGER.warning("Unknown Growatt time zone format %r", value)
        return None
    sign, hours, minutes = match.groups()
    if sign is None:
        return 0.0
    offset = int(hours) + int(minutes or 0) / 60
    return -offset if sign == "-" else offset


def _number(value: Any, divisor: float) -> float | int | None:
    if value is None or value == "":
        return None
    try:
        number = float(value) / divisor
    except (TypeError, ValueError):
        _LOGGER.error("Cannot convert Growatt API value %r to a number", value)
        return None
    rounded = round(number, 3)
    return int(rounded) if rounded.is_integer() else rounded


def _derived(last: dict[str, Any], minuend: str, subtrahend: str | None) -> float | int | None:
    """minuend - subtrahend, clipped at 0 like the portal; None if an input is missing."""
    a = _number(last.get(minuend), 1)
    b = 0 if subtrahend is None else _number(last.get(subtrahend), 1)
    if a is None or b is None:
        return None
    return _number(max(0.0, a - b), 1)


def to_growatt_data(last: dict[str, Any], tz_hours: float | None) -> GrowattData:
    """Translate mix_last_data into the portal-shaped GrowattData the sensors use."""
    data = GrowattData()
    data.api = dict(last)
    for api_field, (portal_field, divisor) in STATUS_FIELDS.items():
        value = _number(last.get(api_field), divisor)
        if value is not None:
            data.status[portal_field] = value
    status = last.get("status")
    if status not in (None, ""):
        data.status["status"] = str(status)
    for api_field, portal_field in DAY_FIELDS.items():
        value = _number(last.get(api_field), 1)
        if value is not None:
            data.day_totals[portal_field] = value
    for api_field, portal_field in TOTAL_FIELDS.items():
        value = _number(last.get(api_field), 1)
        if value is not None:
            data.totals[portal_field] = value
    for target, portal_field, minuend, subtrahend in DERIVED_FIELDS:
        value = _derived(last, minuend, subtrahend)
        if value is not None:
            getattr(data, target)[portal_field] = value
    if last.get("time"):
        data.device_info["lastUpdateTime"] = last["time"]
        if tz_hours is not None:
            data.device_info["timezone"] = tz_hours
    return data


class OpenApiClient:
    """Stateless OpenAPI client; the token is passed per call."""

    def __init__(self, session: aiohttp.ClientSession, base_url: str = OPENAPI_URL) -> None:
        self._session = session
        self._base_url = base_url if base_url.endswith("/") else base_url + "/"

    async def _request(
        self,
        method: str,
        page: str,
        token: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> Any:
        try:
            async with self._session.request(
                method,
                self._base_url + page,
                headers={"token": token},
                params=params,
                data=data,
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                if resp.status != 200:
                    raise GrowattError(f"OpenAPI {page}: HTTP {resp.status}")
                text = await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise GrowattError(f"OpenAPI {page}: {type(err).__name__}: {err}") from err
        body = parse_json(text)
        if not isinstance(body, dict):
            raise GrowattError(f"OpenAPI {page}: unexpected response {text[:200]!r}")
        code = body.get("error_code")
        if code == ERROR_NO_PRIVILEGE:
            raise GrowattTokenDead(f"OpenAPI {page}: [{code}] {body.get('error_msg')}")
        if code != 0:
            raise GrowattError(f"OpenAPI {page}: [{code}] {body.get('error_msg')}")
        return body.get("data")

    async def plants(self, token: str) -> list[str]:
        """Plant ids visible to the token. An empty list means the token is dead."""
        data = await self._request("GET", "plant/list", token)
        try:
            plants = data["plants"]
        except (KeyError, TypeError) as err:
            raise GrowattError(f"OpenAPI plant/list: unexpected data {str(data)[:200]}") from err
        if not plants:
            raise GrowattTokenDead("OpenAPI plant/list: no plant visible to this token")
        return [str(p["plant_id"]) for p in plants if "plant_id" in p]

    async def last_data(self, token: str, serial: str) -> dict[str, Any]:
        """Latest values of a SPH ("mix") inverter."""
        data = await self._request(
            "POST", "device/mix/mix_last_data", token, data={"mix_sn": serial}
        )
        if not isinstance(data, dict) or not data:
            raise GrowattError(f"OpenAPI mix_last_data: unexpected data {str(data)[:200]}")
        return data

    async def data_info(self, token: str, serial: str) -> dict[str, Any]:
        """Settings of a SPH inverter (mix_data_info)."""
        data = await self._request(
            "GET", "device/mix/mix_data_info", token, params={"device_sn": serial}
        )
        if not isinstance(data, dict) or not data:
            raise GrowattError(f"OpenAPI mix_data_info: unexpected data {str(data)[:200]}")
        return data

    async def write(self, token: str, serial: str, type_id: str, params: list[str]) -> Any:
        """Set a SPH parameter (mixSet). ``params`` are param1..param18, "" if unused."""
        if len(params) > MAX_PARAMS:
            raise GrowattError(f"mixSet takes at most {MAX_PARAMS} parameters, got {len(params)}")
        form = {"mix_sn": serial, "type": type_id}
        for i in range(MAX_PARAMS):
            form[f"param{i + 1}"] = params[i] if i < len(params) else ""
        _LOGGER.info("Growatt write %s %s", type_id, [p for p in params if p != ""])
        return await self._request("POST", "mixSet", token, data=form)

    async def read_parameter(
        self, token: str, serial: str, param_id: str, start_addr: int = 0, end_addr: int = 0
    ) -> Any:
        """Read one SPH setting from the inverter (readMixParam)."""
        return await self._request(
            "POST",
            "readMixParam",
            token,
            data={
                "device_sn": serial,
                "paramId": param_id,
                "startAddr": start_addr,
                "endAddr": end_addr,
            },
        )

    async def history(
        self, token: str, serial: str, start_date: str, end_date: str, page: int, perpage: int
    ) -> Any:
        """Historical data of a SPH inverter (mix_data, at most 7 days)."""
        return await self._request(
            "POST",
            "device/mix/mix_data",
            token,
            data={
                "mix_sn": serial,
                "start_date": start_date,
                "end_date": end_date,
                "page": page,
                "perpage": perpage,
            },
        )

    async def alarms(self, token: str, serial: str, date: str | None, page: int, perpage: int) -> Any:
        """Alarm data of a SPH inverter (alarm_data)."""
        form: dict[str, Any] = {"mix_sn": serial, "page": page, "perpage": perpage}
        if date:
            form["date"] = date
        return await self._request("POST", "device/mix/alarm_data", token, data=form)

    async def plant_timezone(self, token: str, plant_id: str) -> float | None:
        """Time zone of the plant in hours, from plant/details ("GMT+1")."""
        data = await self._request("GET", "plant/details", token, params={"plant_id": plant_id})
        return parse_gmt_offset(data.get("timezone") if isinstance(data, dict) else None)
