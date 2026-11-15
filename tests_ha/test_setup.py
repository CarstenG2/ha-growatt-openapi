"""Setup, entities and actions inside a real Home Assistant core (no network)."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growatt_web.api import GrowattData
from custom_components.growatt_web.const import DOMAIN
from custom_components.growatt_web.openapi import to_growatt_data

LAST = {
    "soc": 58, "pcharge1": 760, "ppv": 1039.1, "status": 5, "bmsMaxCurr": 25,
    "elocalLoadToday": 1.9, "eselftoday": 1.8, "esystemtoday": 2.0, "elocalLoadTotal": 9853.9,
    "eselftotal": 8904.3, "vBus1": 693.8, "statusText": "Bat Online", "serialNum": "SN1",
    "time": "2026-11-14 10:06:44",
}
SETTINGS = {"chargePowerCommand": 20, "acChargeEnable": 0}


def _data():
    data = to_growatt_data(LAST, 1.0)
    data.settings = dict(SETTINGS)
    return data


@pytest.fixture
async def entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="SN1",
        data={"username": "u", "password": "p", "plant_id": "1", "serial": "SN1",
              "model": "SPH", "api_token": "T"},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.growatt_web.source.SourceController.fetch",
        AsyncMock(return_value=_data()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_legacy_entity_keeps_unique_id_and_gets_api_name(hass, entry):
    reg = er.async_get(hass)
    entity_id = reg.async_get_entity_id("sensor", DOMAIN, "SN1_chargepower")
    assert entity_id
    state = hass.states.get(entity_id)
    assert state.attributes["friendly_name"].endswith("pcharge1")
    assert float(state.state) == 0.76


async def test_other_fields_exist_disabled(hass, entry):
    reg = er.async_get(hass)
    entity_id = reg.async_get_entity_id("sensor", DOMAIN, "SN1_api_vbus1")
    assert entity_id
    assert reg.async_get(entity_id).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    setting_id = reg.async_get_entity_id("sensor", DOMAIN, "SN1_settings_chargepowercommand")
    assert reg.async_get(setting_id).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert reg.async_get_entity_id("sensor", DOMAIN, "SN1_api_serialnum") is None


async def test_all_actions_registered(hass, entry):
    services = hass.services.async_services()[DOMAIN]
    assert len(services) == 19


async def test_charge_periods_action_writes_param1_to_18(hass, entry):
    write = AsyncMock(return_value="")
    with patch("custom_components.growatt_web.source.SourceController.write", write):
        await hass.services.async_call(
            DOMAIN, "set_charge_periods",
            {"charge_power": 100, "charge_stop_soc": 100, "grid_charge": False,
             "period1_start": "00:00:00", "period1_end": "04:00:00", "period1_enabled": True,
             "period2_start": "00:00", "period2_end": "00:00", "period2_enabled": False,
             "period3_start": "00:00", "period3_end": "00:00", "period3_enabled": False},
            blocking=True,
        )
    write.assert_awaited_once_with(
        "mix_ac_charge_time_period",
        ["100", "100", "0", "00", "00", "04", "00", "1",
         "00", "00", "00", "00", "0", "00", "00", "00", "00", "0"],
    )


async def test_out_of_range_value_is_rejected(hass, entry):
    import voluptuous as vol

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "set_discharge_stop_soc", {"soc": 101}, blocking=True
        )


async def test_read_parameter_returns_response(hass, entry):
    with patch(
        "custom_components.growatt_web.source.SourceController.read_parameter",
        AsyncMock(return_value="1"),
    ):
        result = await hass.services.async_call(
            DOMAIN, "read_parameter", {"param_id": "pv_on_off"}, blocking=True, return_response=True
        )
    assert result == {"data": "1"}


async def test_services_yaml_parses_with_every_field(hass, entry):
    """Home Assistant must read services.yaml; each action lists every schema field by name."""
    from homeassistant.helpers.service import async_get_all_descriptions

    descriptions = (await async_get_all_descriptions(hass))[DOMAIN]
    services = hass.services.async_services()[DOMAIN]
    assert set(descriptions) == set(services)
    for name, service in services.items():
        fields = descriptions[name]["fields"]
        assert all(isinstance(k, str) for k in fields), name
        assert {str(k) for k in service.schema.schema} == set(fields), name
