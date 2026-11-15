"""Build services.yaml and docs/actions.md from custom_components/growatt_web/writes.py.

Usage: python tools/build_actions.py
"""

from __future__ import annotations

import importlib
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "custom_components" / "growatt_web"
DOC_URL = "https://www.showdoc.com.cn/262556420217021/6129761750718760"

pkg = types.ModuleType("gw")
pkg.__path__ = [str(PKG)]
sys.modules["gw"] = pkg
writes = importlib.import_module("gw.writes")

ENTRY = {
    "name": "Config entry",
    "description": "Growatt OpenAPI entry to use; only needed with more than one inverter.",
    "selector": {"config_entry": {"integration": "growatt_web"}},
}


def selector(p) -> dict:
    if p.kind == "bool":
        return {"boolean": {}}
    if p.kind == "time":
        return {"time": {}}
    if p.kind == "select":
        return {"select": {"options": list(p.options)}}
    if p.kind in ("int", "float"):
        number = {"mode": "box"}
        if p.minimum is not None:
            number["min"] = p.minimum
        if p.maximum is not None:
            number["max"] = p.maximum
        if p.kind == "float":
            number["step"] = "any"
        return {"number": number}
    return {"text": {}}


def yaml_value(value, indent: int) -> list[str]:
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            return [pad + "{}"]
        lines = []
        for k, v in value.items():
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{key(k)}:")
                lines += yaml_value(v, indent + 2)
            else:
                lines.append(f"{pad}{key(k)}: {scalar(v)}")
        return lines
    if isinstance(value, list):
        return [f"{pad}- {scalar(v)}" for v in value]
    return [pad + scalar(value)]


# YAML 1.1 (used by Home Assistant) reads these unquoted keys as booleans.
YAML_BOOL_WORDS = {"y", "n", "yes", "no", "on", "off", "true", "false"}


def key(k) -> str:
    return f'"{k}"' if str(k).lower() in YAML_BOOL_WORDS else str(k)


def scalar(v) -> str:
    if v == {}:
        return "{}"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


RAW = {
    "write_parameter": {
        "name": "Write any parameter",
        "description": "Sends any setting type of the official API (mixSet) with up to 18 raw parameters.",
        "fields": {
            "config_entry_id": ENTRY,
            "type": {"name": "Type", "description": "Setting type id, e.g. pv_on_off", "required": True,
                     "selector": {"text": {}}},
            "params": {"name": "Parameters", "description": "param1..param18 in order, as text",
                       "selector": {"text": {"multiple": True}}},
        },
    },
    "read_parameter": {
        "name": "Read parameter",
        "description": "Reads one setting directly from the inverter (readMixParam) and returns the answer.",
        "fields": {
            "config_entry_id": ENTRY,
            "param_id": {"name": "Parameter id", "description": "e.g. pv_on_off, or set_any_reg with addresses",
                         "required": True, "selector": {"text": {}}},
            "start_address": {"name": "Start register", "description": "Only with set_any_reg",
                              "selector": {"number": {"mode": "box", "min": 0}}},
            "end_address": {"name": "End register", "description": "Only with set_any_reg",
                            "selector": {"number": {"mode": "box", "min": 0}}},
        },
    },
    "get_history": {
        "name": "Get history",
        "description": "Returns the stored 5-minute data sets of up to 7 days (mix_data).",
        "fields": {
            "config_entry_id": ENTRY,
            "start_date": {"name": "Start date", "description": "YYYY-MM-DD", "required": True,
                           "selector": {"date": {}}},
            "end_date": {"name": "End date", "description": "YYYY-MM-DD, at most 7 days after the start",
                         "required": True, "selector": {"date": {}}},
            "page": {"name": "Page", "description": "Page number, default 1",
                     "selector": {"number": {"mode": "box", "min": 1}}},
            "perpage": {"name": "Per page", "description": "Data sets per page, 1-100, default 100",
                        "selector": {"number": {"mode": "box", "min": 1, "max": 100}}},
        },
    },
    "get_alarms": {
        "name": "Get alarms",
        "description": "Returns the alarm records of the inverter (alarm_data).",
        "fields": {
            "config_entry_id": ENTRY,
            "date": {"name": "Date", "description": "Optional day, YYYY-MM-DD", "selector": {"date": {}}},
            "page": {"name": "Page", "description": "Page number, default 1",
                     "selector": {"number": {"mode": "box", "min": 1}}},
            "perpage": {"name": "Per page", "description": "Records per page, 1-100, default 100",
                        "selector": {"number": {"mode": "box", "min": 1, "max": 100}}},
        },
    },
}


def main() -> None:
    services = {}
    for t in writes.SETTING_TYPES:
        fields = {"config_entry_id": ENTRY}
        for p in t.params:
            fields[p.name] = {"name": p.name.replace("_", " ").capitalize(), "description": p.description,
                              "required": True, "selector": selector(p)}
        services[t.service] = {"name": t.title, "description": f"{t.description} (type {t.type_id})",
                               "fields": fields}
    services.update(RAW)
    lines = ["# Generated by tools/build_actions.py from writes.py. Do not edit by hand.", ""]
    for name, svc in services.items():
        lines.append(f"{name}:")
        lines += yaml_value(svc, 2)
        lines.append("")
    (PKG / "services.yaml").write_text("\n".join(lines), encoding="utf-8")

    md = [
        "# Actions",
        "",
        "Generated by `tools/build_actions.py`. Every SPH setting type of the official",
        f"[Growatt OpenAPI page \"SPH parameter settings\"]({DOC_URL}) is one action. Types, parameter",
        "positions, ranges and values follow that page. Actions need the official API (API token);",
        "while the integration runs on the portal fallback they fail with an error.",
        "",
        "After a write the settings entities are read again with the next poll that is at least",
        "5 minutes after the last settings read (Growatt rate limit).",
        "",
    ]
    for t in writes.SETTING_TYPES:
        md += [f"## `growatt_web.{t.service}`", "", f"{t.description}", "", f"API type: `{t.type_id}`", "",
               "| Field | Values | Sent as |", "|---|---|---|"]
        for p in t.params:
            if p.kind == "bool":
                values, sent = "true / false", f"param{p.positions[0]} = {p.true_false[0]} / {p.true_false[1]}"
            elif p.kind == "time":
                values, sent = "HH:MM", f"param{p.positions[0]} = hour, param{p.positions[1]} = minute"
            elif p.kind == "select":
                values = ", ".join(p.options)
                sent = f"param{p.positions[0]} = " + ", ".join(f"{k}->{v}" for k, v in p.options.items())
            elif p.kind in ("int", "float"):
                rng = f"{p.minimum:g}-{p.maximum:g}" if p.minimum is not None else "number"
                values, sent = rng, f"param{p.positions[0]}"
            else:
                values, sent = "text", f"param{p.positions[0]} unchanged"
            md.append(f"| `{p.name}` ({p.description}) | {values} | {sent} |")
        md.append("")
    md += [
        "## Raw access",
        "",
        "| Action | What it does |",
        "|---|---|",
    ]
    for name, svc in RAW.items():
        md.append(f"| `growatt_web.{name}` | {svc['description']} |")
    md += [
        "",
        "`read_parameter`, `get_history` and `get_alarms` return the answer of the API as action",
        "response (`response_variable` in a script or automation).",
        "",
        "## Example",
        "",
        "```yaml",
        "action: growatt_web.set_charge_periods",
        "data:",
        "  charge_power: 100",
        "  charge_stop_soc: 100",
        "  grid_charge: false",
        '  period1_start: "00:00"',
        '  period1_end: "04:00"',
        "  period1_enabled: true",
        '  period2_start: "00:00"',
        '  period2_end: "00:00"',
        "  period2_enabled: false",
        '  period3_start: "00:00"',
        '  period3_end: "00:00"',
        "  period3_enabled: false",
        "```",
        "",
    ]
    (ROOT / "docs" / "actions.md").write_text("\n".join(md), encoding="utf-8")
    print("services", len(services))


if __name__ == "__main__":
    main()
