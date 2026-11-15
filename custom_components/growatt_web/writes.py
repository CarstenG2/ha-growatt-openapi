"""The SPH setting types of the official Growatt OpenAPI (mixSet), one action each.

Source of every type, parameter position, range and value: the official page
"SPH parameter settings" (https://www.showdoc.com.cn/262556420217021/6129761750718760).
Where that page is unclear, the field description says so. No Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .openapi import MAX_PARAMS


@dataclass(frozen=True)
class Param:
    """One action field, written to one or two of param1..param18."""

    name: str
    kind: str  # "int", "float", "bool", "time", "select", "text"
    positions: tuple[int, ...]  # 1-based param numbers; "time" uses (hour, minute)
    description: str
    minimum: float | None = None
    maximum: float | None = None
    options: dict[str, str] = field(default_factory=dict)  # option -> value sent
    true_false: tuple[str, str] = ("1", "0")  # values sent for a "bool"


@dataclass(frozen=True)
class SettingType:
    service: str
    type_id: str
    title: str
    description: str
    params: tuple[Param, ...]


def _period(n: int, first: int, verb: str) -> tuple[Param, ...]:
    return (
        Param(f"period{n}_start", "time", (first, first + 1), f"{verb} period {n} start (HH:MM)"),
        Param(f"period{n}_end", "time", (first + 2, first + 3), f"{verb} period {n} end (HH:MM)"),
        Param(f"period{n}_enabled", "bool", (first + 4,), f"{verb} period {n} enabled"),
    )


PCT = {"minimum": 0, "maximum": 100}

SETTING_TYPES: tuple[SettingType, ...] = (
    SettingType(
        "set_discharge_periods", "mix_ac_discharge_time_period", "Grid first: discharge periods",
        "Grid priority setting: discharge power, discharge stop SOC and three time periods.",
        (
            Param("discharge_power", "int", (1,), "Discharge power in % (0-100)", **PCT),
            Param("discharge_stop_soc", "int", (2,), "Discharge stop SOC in % (0-100)", **PCT),
            *_period(1, 3, "Discharge"), *_period(2, 8, "Discharge"), *_period(3, 13, "Discharge"),
        ),
    ),
    SettingType(
        "set_charge_periods", "mix_ac_charge_time_period", "Battery first: charge periods",
        "Battery priority setting: charging power, charge stop SOC, charging from the grid "
        "(mains) and three time periods.",
        (
            Param("charge_power", "int", (1,), "Charging power in % (0-100)", **PCT),
            Param("charge_stop_soc", "int", (2,), "Charge stop SOC in % (0-100)", **PCT),
            Param("grid_charge", "bool", (3,), "Charge from the grid (mains) enabled"),
            *_period(1, 4, "Charge"), *_period(2, 9, "Charge"), *_period(3, 14, "Charge"),
        ),
    ),
    SettingType(
        "set_export_limit", "backflow_setting", "Anti-backflow (export limit)",
        "Anti-backflow setting: on or off, and the allowed export as % of the power.",
        (
            Param("enabled", "bool", (1,), "Anti-backflow on"),
            Param("power_percent", "int", (2,), "Anti-backflow power percentage (0-100)", **PCT),
        ),
    ),
    SettingType(
        "set_inverter_on_off", "pv_on_off", "Inverter on/off",
        "Switches the inverter on or off.",
        (Param("on", "bool", (1,), "Inverter on", true_false=("0001", "0000")),),
    ),
    SettingType(
        "set_time", "pf_sys_year", "Inverter time",
        "Sets the time of the inverter. The official page gives the value as "
        "'00 (hour): 00 (minute) ~ 00 (hour): 00 (minute)'; the text is sent unchanged.",
        (Param("value", "text", (1,), "Value exactly in the format of the official page"),),
    ),
    SettingType(
        "set_grid_voltage_high", "pv_grid_voltage_high", "Upper limit of mains voltage",
        "Sets the upper limit of the mains voltage. The official page shows the value 270.",
        (Param("voltage", "float", (1,), "Voltage in V"),),
    ),
    SettingType(
        "set_grid_voltage_low", "pv_grid_voltage_low", "Lower limit of mains voltage",
        "Sets the lower limit of the mains voltage. The official page shows the value 180.",
        (Param("voltage", "float", (1,), "Voltage in V"),),
    ),
    SettingType(
        "set_off_grid_enable", "mix_off_grid_enable", "Off-grid enable",
        "Enables or disables off-grid (backup) operation.",
        (Param("enabled", "bool", (1,), "Off-grid enabled"),),
    ),
    SettingType(
        "set_off_grid_frequency", "mix_ac_discharge_frequency", "Off-grid frequency",
        "Sets the off-grid output frequency.",
        (Param("frequency", "select", (1,), "Off-grid frequency", options={"50": "0", "60": "1"}),),
    ),
    SettingType(
        "set_off_grid_voltage", "mix_ac_discharge_voltage", "Off-grid voltage",
        "Sets the off-grid output voltage.",
        (Param("voltage", "select", (1,), "Off-grid voltage in V",
               options={"230": "0", "208": "1", "240": "2"}),),
    ),
    SettingType(
        "set_reactive_power_rate", "v_reactive_p_rate", "Reactive power",
        "Setting type v_reactive_p_rate. The table of the official page has more column "
        "headings than types here (store PF commands, active power, reactive power, PF "
        "value); which one this type is, the page does not say unambiguously. The value "
        "is sent unchanged.",
        (Param("value", "text", (1,), "Value as given on the official page"),),
    ),
    SettingType(
        "set_power_factor", "pv_power_factor", "Power factor",
        "Setting type pv_power_factor (see the note on set_reactive_power_rate). The official "
        "page lists the range -0.8 to -1 and 0.8 to 1 for the PF value. The value is sent unchanged.",
        (Param("value", "text", (1,), "Value as given on the official page"),),
    ),
    SettingType(
        "set_discharge_stop_soc", "mix_load_flast_value_multi", "Discharge stop SOC",
        "Sets the discharge stop SOC.",
        (Param("soc", "int", (1,), "Discharge stop SOC in % (0-100)", **PCT),),
    ),
    SettingType(
        "set_load_first_output", "mix_load_first_control", "Load first: three-phase output",
        "LoadFirst three-phase independent output.",
        (Param("mode", "select", (1,), "Output mode",
               options={"three_phase_sum": "0", "single_phase": "1"}),),
    ),
    SettingType(
        "set_single_phase_export_limit", "mix_single_export", "Single-phase anti-backflow",
        "Single-phase anti-reverse flow on or off.",
        (Param("enabled", "bool", (1,), "Single-phase anti-backflow on"),),
    ),
)

BY_SERVICE = {t.service: t for t in SETTING_TYPES}


def build_params(setting: SettingType, values: dict[str, Any]) -> list[str]:
    """Translate action field values into param1..param18 (strings, "" if unused)."""
    params = [""] * MAX_PARAMS
    for p in setting.params:
        value = values[p.name]
        if p.kind == "time":
            hour, minute = _parse_time(value)
            params[p.positions[0] - 1] = f"{hour:02d}"
            params[p.positions[1] - 1] = f"{minute:02d}"
            continue
        if p.kind == "bool":
            text = p.true_false[0] if value else p.true_false[1]
        elif p.kind == "select":
            text = p.options[str(value)]
        elif p.kind == "int":
            text = str(int(value))
        elif p.kind == "float":
            text = f"{float(value):g}"
        else:
            text = str(value)
        params[p.positions[0] - 1] = text
    last = max((i for i, v in enumerate(params) if v != ""), default=-1)
    return params[: last + 1]


def _parse_time(value: Any) -> tuple[int, int]:
    """'HH:MM' or 'HH:MM:SS' (Home Assistant time selector) -> (hour, minute)."""
    parts = str(value).split(":")
    if len(parts) < 2:
        raise ValueError(f"time {value!r} is not HH:MM")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"time {value!r} is out of range")
    return hour, minute
