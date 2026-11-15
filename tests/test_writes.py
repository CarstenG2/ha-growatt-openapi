"""Tests for the SPH setting types (param positions from the official doc page)."""

import pytest

from gw import writes


def test_fifteen_types_from_the_official_page():
    ids = [t.type_id for t in writes.SETTING_TYPES]
    assert ids == [
        "mix_ac_discharge_time_period", "mix_ac_charge_time_period", "backflow_setting",
        "pv_on_off", "pf_sys_year", "pv_grid_voltage_high", "pv_grid_voltage_low",
        "mix_off_grid_enable", "mix_ac_discharge_frequency", "mix_ac_discharge_voltage",
        "v_reactive_p_rate", "pv_power_factor", "mix_load_flast_value_multi",
        "mix_load_first_control", "mix_single_export",
    ]


def _charge(**over):
    values = {"charge_power": 100, "charge_stop_soc": 90, "grid_charge": False,
              "period1_start": "00:00:00", "period1_end": "04:30", "period1_enabled": True,
              "period2_start": "05:00", "period2_end": "06:15", "period2_enabled": False,
              "period3_start": "23:05", "period3_end": "23:59", "period3_enabled": True}
    values.update(over)
    return values


def test_charge_periods_fill_param1_to_param18():
    params = writes.build_params(writes.BY_SERVICE["set_charge_periods"], _charge())
    assert params == ["100", "90", "0",
                      "00", "00", "04", "30", "1",
                      "05", "00", "06", "15", "0",
                      "23", "05", "23", "59", "1"]


def test_discharge_periods_use_param3_to_param17():
    values = {"discharge_power": 50, "discharge_stop_soc": 10,
              "period1_start": "16:00", "period1_end": "20:00", "period1_enabled": True,
              "period2_start": "00:00", "period2_end": "00:00", "period2_enabled": False,
              "period3_start": "00:00", "period3_end": "00:00", "period3_enabled": False}
    params = writes.build_params(writes.BY_SERVICE["set_discharge_periods"], values)
    assert params == ["50", "10", "16", "00", "20", "00", "1",
                      "00", "00", "00", "00", "0", "00", "00", "00", "00", "0"]


def test_inverter_on_off_sends_0001_and_0000():
    t = writes.BY_SERVICE["set_inverter_on_off"]
    assert writes.build_params(t, {"on": True}) == ["0001"]
    assert writes.build_params(t, {"on": False}) == ["0000"]


@pytest.mark.parametrize("service,value,sent", [
    ("set_off_grid_frequency", {"frequency": "60"}, ["1"]),
    ("set_off_grid_voltage", {"voltage": "208"}, ["1"]),
    ("set_load_first_output", {"mode": "single_phase"}, ["1"]),
    ("set_export_limit", {"enabled": True, "power_percent": 30}, ["1", "30"]),
    ("set_grid_voltage_high", {"voltage": 270}, ["270"]),
    ("set_discharge_stop_soc", {"soc": 10}, ["10"]),
])
def test_enum_and_number_values(service, value, sent):
    assert writes.build_params(writes.BY_SERVICE[service], value) == sent


@pytest.mark.parametrize("bad", ["24:00", "12:60", "noon"])
def test_invalid_time_is_rejected(bad):
    with pytest.raises(ValueError):
        writes.build_params(writes.BY_SERVICE["set_charge_periods"], _charge(period1_end=bad))
