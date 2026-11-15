"""Actions of the Growatt Web integration: every SPH setting type, plus raw API access."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import GrowattError
from .const import DOMAIN
from .openapi import MAX_PARAMS
from .writes import SETTING_TYPES, Param, SettingType, build_params

_LOGGER = logging.getLogger(__name__)

ATTR_ENTRY = "config_entry_id"
ENTRY_FIELD = {vol.Optional(ATTR_ENTRY): cv.string}


def _validator(p: Param) -> Any:
    if p.kind == "bool":
        return cv.boolean
    if p.kind == "select":
        return vol.In(list(p.options))
    if p.kind == "time":
        return cv.string
    if p.kind in ("int", "float"):
        number = vol.Coerce(int) if p.kind == "int" else vol.Coerce(float)
        return vol.All(number, vol.Range(min=p.minimum, max=p.maximum))
    return cv.string


def _schema(setting: SettingType) -> vol.Schema:
    fields = {vol.Required(p.name): _validator(p) for p in setting.params}
    return vol.Schema({**ENTRY_FIELD, **fields})


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> Any:
    entries = [
        e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED
    ]
    wanted = call.data.get(ATTR_ENTRY)
    if wanted:
        entries = [e for e in entries if e.entry_id == wanted]
    if len(entries) != 1:
        raise ServiceValidationError(
            "Name the Growatt Web entry with config_entry_id"
            if len(entries) > 1
            else "No loaded Growatt Web entry found"
        )
    return entries[0].runtime_data


async def _run(hass: HomeAssistant, call: ServiceCall, what: str, job) -> Any:
    coordinator = _coordinator(hass, call)
    try:
        return await job(coordinator.source)
    except GrowattError as err:
        _LOGGER.error("Growatt %s failed: %s: %s", what, type(err).__name__, err)
        raise HomeAssistantError(f"Growatt {what} failed: {err}") from err


def async_register_services(hass: HomeAssistant) -> None:
    """Register all actions once per Home Assistant instance."""
    if hass.services.has_service(DOMAIN, "write_parameter"):
        return

    for setting in SETTING_TYPES:

        async def handle(call: ServiceCall, setting: SettingType = setting) -> None:
            try:
                params = build_params(setting, call.data)
            except ValueError as err:
                raise ServiceValidationError(str(err)) from err
            await _run(hass, call, setting.type_id, lambda s: s.write(setting.type_id, params))

        hass.services.async_register(DOMAIN, setting.service, handle, schema=_schema(setting))

    async def write_parameter(call: ServiceCall) -> None:
        params = [str(p) for p in call.data.get("params", [])]
        await _run(hass, call, call.data["type"], lambda s: s.write(call.data["type"], params))

    hass.services.async_register(
        DOMAIN,
        "write_parameter",
        write_parameter,
        schema=vol.Schema(
            {
                **ENTRY_FIELD,
                vol.Required("type"): cv.string,
                vol.Optional("params", default=[]): vol.All(
                    cv.ensure_list, vol.Length(max=MAX_PARAMS), [cv.string]
                ),
            }
        ),
    )

    async def read_parameter(call: ServiceCall) -> ServiceResponse:
        data = await _run(
            hass,
            call,
            "read_parameter",
            lambda s: s.read_parameter(
                call.data["param_id"], call.data["start_address"], call.data["end_address"]
            ),
        )
        return {"data": data}

    hass.services.async_register(
        DOMAIN,
        "read_parameter",
        read_parameter,
        schema=vol.Schema(
            {
                **ENTRY_FIELD,
                vol.Required("param_id"): cv.string,
                vol.Optional("start_address", default=0): vol.Coerce(int),
                vol.Optional("end_address", default=0): vol.Coerce(int),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    async def get_history(call: ServiceCall) -> ServiceResponse:
        data = await _run(
            hass,
            call,
            "get_history",
            lambda s: s.history(
                call.data["start_date"], call.data["end_date"], call.data["page"], call.data["perpage"]
            ),
        )
        return {"data": data}

    hass.services.async_register(
        DOMAIN,
        "get_history",
        get_history,
        schema=vol.Schema(
            {
                **ENTRY_FIELD,
                vol.Required("start_date"): cv.string,
                vol.Required("end_date"): cv.string,
                vol.Optional("page", default=1): vol.Coerce(int),
                vol.Optional("perpage", default=100): vol.All(vol.Coerce(int), vol.Range(1, 100)),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    async def get_alarms(call: ServiceCall) -> ServiceResponse:
        data = await _run(
            hass,
            call,
            "get_alarms",
            lambda s: s.alarms(call.data.get("date"), call.data["page"], call.data["perpage"]),
        )
        return {"data": data}

    hass.services.async_register(
        DOMAIN,
        "get_alarms",
        get_alarms,
        schema=vol.Schema(
            {
                **ENTRY_FIELD,
                vol.Optional("date"): cv.string,
                vol.Optional("page", default=1): vol.Coerce(int),
                vol.Optional("perpage", default=100): vol.All(vol.Coerce(int), vol.Range(1, 100)),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
