"""Build the field catalog of the integration and the attribute reference.

Inputs
- a local copy of the official Growatt OpenAPI documentation (Markdown pages, see
  docs/superpowers/specs/2026-11-15-publish-readiness-design.md); only the field
  description tables of the SPH pages are read
- one ``mix_last_data`` and one ``mix_data_info`` response of a real SPH inverter
  (JSON as returned by the API); only field names and value types are used

Outputs
- custom_components/growatt_web/catalog.py
- docs/attributes.md

Usage: python tools/build_catalog.py <doc dir> <last_data.json> <data_info.json>
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC_URL = "https://www.showdoc.com.cn/262556420217021"
LIVE_DOC = "052-get-the-latest-real-time-data-of-sph.md"
INFO_DOC = "051-get-basic-information-of-sph.md"

# Fields that identify the owner, the plant or the hardware, or that are not single
# values. They never become entities (privacy: entity states end up in shared logs
# and diagnostics).
EXCLUDED = {
    "alias", "batSerialNum", "calendar", "children", "dataLogSn", "dayMap",
    "energyDayMap", "id", "imgPath", "lastUpdateTime", "location", "mixBean",
    "otherEnergyDayTable", "parentID", "plantId", "plantname", "record",
    "serialNum", "tcpServerIp", "treeID", "treeName", "userName",
}

W, V, A, C, KWH, PCT, HZ = "W", "V", "A", "°C", "kWh", "%", "Hz"

# Units. "measured": value compared with the portal or checked against other
# fields of the same response (e.g. pacR + pacS + pacT = pac). "doc": the official
# description names the quantity (power, voltage, ...); the unit follows the
# measured fields of the same kind.
UNITS: dict[str, tuple[str, str]] = {}
for f in ("ppv", "ppv1", "ppv2", "pcharge1", "pdischarge1", "pacToGridTotal",
          "pacToUserTotal", "plocalLoadTotal", "pac", "pacR", "pacS", "pacT",
          "pself", "psystem"):
    UNITS[f] = (W, "measured")
for f in ("pac1", "pac2", "pac3", "pacToGridR", "pacToUserR", "plocalLoadR",
          "plocalLoadS", "plocalLoadT", "acChargePower", "upsPac1", "upsPac2", "upsPac3"):
    UNITS[f] = (W, "doc")
for f in ("vbat", "vpv1", "vpv2", "vac1", "vac2", "vac3", "bmsBatteryVolt", "vBatDsp"):
    UNITS[f] = (V, "measured")
for f in ("vBus1", "vBus2", "epsVac2", "epsVac3", "upsVac1", "chargeCutoffVolt",
          "dischargeCutoffVolt", "maxSingleCellVolt", "minSingleCellVolt"):
    UNITS[f] = (V, "doc")
for f in ("iac1", "iac2", "iac3", "bmsBatteryCurr", "bmsMaxCurr", "bmsMaxDischgCurr"):
    UNITS[f] = (A, "measured")
for f in ("temp1", "temp2", "temp3", "batteryTemperature", "bmsBatteryTemp",
          "maxSingleCellTem", "minSingleCellTem"):
    UNITS[f] = (C, "doc")
for f in ("soc", "bmsSOC"):
    UNITS[f] = (PCT, "measured")
UNITS["bmsSOH"] = (PCT, "doc")
UNITS["fac"] = (HZ, "measured")
UNITS["upsFac"] = (HZ, "doc")
for f in ("epvtoday", "epvTotal", "epv1Today", "epv1Total", "epv2Today", "epv2Total",
          "etoGridToday", "etogridTotal", "etoUserToday", "etoUserTotal",
          "edischarge1Today", "edischarge1Total",
          "elocalLoadToday", "elocalLoadTotal", "eselftoday", "eselftotal",
          "esystemtoday", "esystemtotal"):
    UNITS[f] = (KWH, "measured")
for f in ("eacToday", "eacTotal", "acChargeEnergyToday", "acChargeEnergyTotal",
          "echarge1Today", "echarge1Total"):
    UNITS[f] = (KWH, "doc")

# Own explanations where the official documentation has none or a misleading one.
# Every entry states how it was established.
OWN: dict[str, str] = {
    "eselftoday": "Self-consumed energy today (portal: grid import = elocalLoadToday - eselftoday; verified 2026-11-14)",
    "eselftotal": "Self-consumed energy, lifetime (portal: grid import total = elocalLoadTotal - eselftotal; verified 2026-11-14)",
    "esystemtoday": "System output energy today (portal value eCharge; export = esystemtoday - eselftoday; verified 2026-11-14)",
    "esystemtotal": "System output energy, lifetime (portal export total = esystemtotal - eselftotal; verified 2026-11-14)",
    "pself": "Self-consumed power (equal to the load power in the measured sample)",
    "psystem": "System output power (equal to pself in the measured sample)",
    "statusText": "Status as text, e.g. 'Bat Online' for status 6 (measured)",
    "socText": "Battery state of charge as text, e.g. '96%' (measured)",
    "ppvText": "PV power as text, e.g. '0.0 W' (measured)",
    "time": "Time stamp of the data set, plant local time",
    "etoUserToday": "Energy imported from the grid today (official text 'Grid Sunrise Electricity'; matched the metered import 2026-11-14)",
    "etoUserTotal": "Energy imported from the grid, lifetime",
    "etoGridToday": "Energy exported to the grid today",
    "etogridTotal": "Energy exported to the grid, lifetime (inverter counter; the portal shows esystemtotal - eselftotal instead)",
    "pacToGridTotal": "Power exported to the grid",
    "pacToUserTotal": "Power imported from the grid",
    "bmsMaxCurr": "Maximum charge and discharge current allowed by the battery management",
}

# Enum values. Source in brackets.
ENUMS: dict[str, str] = {
    "status": "Official doc, live data page: 0 waiting, 1 normal, 2 fault. Official doc, device page: 0 waiting, 1 self-check, 3 failure, 4 upgrading, 5-8 normal. Measured: 6 = 'Bat Online'.",
    "bctMode": "0 wired CT, 1 wireless CT, 2 meter (official doc)",
    "deviceType": "0 Mix6k, 1 Mix4-10k (official doc)",
    "acChargeEnable": "0 off, 1 on (measured: 0 with grid charging off)",
    "mix_ac_discharge_frequency": "0 50 Hz, 1 60 Hz (official doc, setting type of the same name)",
    "mix_ac_discharge_voltage": "0 230 V, 1 208 V, 2 240 V (official doc, setting type of the same name)",
}

# The 37 entities that existed before this catalog: API field -> existing unique key.
# Their unique id stays unchanged so the history in Home Assistant is kept.
LEGACY_KEYS = {
    "soc": "soc", "vbat": "vbat", "pcharge1": "chargepower", "pdischarge1": "pdischarge1",
    "pacToGridTotal": "pactogrid", "pacToUserTotal": "pactouser",
    "plocalLoadTotal": "plocalload", "ppv": "ppv", "vpv1": "vpv1", "ppv1": "ppv1",
    "vpv2": "vpv2", "ppv2": "ppv2", "vac1": "vac1", "fac": "fac", "status": "status",
    "bmsMaxCurr": "bmsmaxcurr", "bmsBatteryCurr": "bmsbatterycurr",
    "bmsBatteryTemp": "bmsbatterytemp", "epvtoday": "epvtoday", "epvTotal": "epvtotal",
    "etoGridToday": "etogridtoday", "etogridTotal": "etogridtotal",
    "edischarge1Today": "edischarge1today", "edischarge1Total": "edischarge1total",
    "elocalLoadToday": "elocalloadtoday", "elocalLoadTotal": "elocalloadtotal",
}


def doc_table(path: pathlib.Path, live: bool) -> dict[str, str]:
    """Field -> description from an SPH page's 'Return parameter description' table."""
    text = path.read_text(encoding="utf-8")
    text = text[text.index("Return parameter description"):]
    out = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        name = cells[1] if live else cells[0]
        desc = cells[2]
        name = re.split(r"[\s=;]", name)[0]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) and name not in ("Type", "Parameter"):
            out[name] = desc
    return out


def kind(value) -> str | None:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "text"
    return None


def entries(sample: dict, docs: dict, live: bool) -> list[dict]:
    rows = []
    for name in sorted(sample, key=str.lower):
        k = kind(sample[name])
        if name in EXCLUDED or k is None:
            continue
        unit, unit_src = UNITS.get(name, (None, None)) if live else (None, None)
        if name in OWN:
            desc, src = OWN[name], "own"
        elif name in docs:
            desc, src = docs[name], "doc"
        else:
            desc, src = "", "none"
        rows.append({
            "name": name, "kind": k, "unit": unit, "unit_source": unit_src,
            "description": desc, "source": src, "enum": ENUMS.get(name, ""),
            "legacy_key": LEGACY_KEYS.get(name) if live else None,
        })
    return rows


def write_catalog(live: list[dict], settings: list[dict]) -> None:
    def tup(rows):
        lines = []
        for r in rows:
            lines.append(
                f"    Field({r['name']!r}, {r['kind']!r}, {r['unit']!r}, {r['legacy_key']!r}),"
            )
        return "\n".join(lines)

    code = f'''"""Field catalog of the SPH ("mix") inverter, generated by tools/build_catalog.py.

Do not edit by hand. Explanations of every field: docs/attributes.md.
"""

from __future__ import annotations

from typing import NamedTuple


class Field(NamedTuple):
    name: str  # official API field name
    kind: str  # "number", "text" or "bool", as measured
    unit: str | None  # Home Assistant unit, None if not established
    legacy_key: str | None  # unique key of an entity that existed before the catalog


LIVE_FIELDS: tuple[Field, ...] = (
{tup(live)}
)

SETTING_FIELDS: tuple[Field, ...] = (
{tup(settings)}
)
'''
    (ROOT / "custom_components" / "growatt_web" / "catalog.py").write_text(code, encoding="utf-8")


def md_escape(text: str) -> str:
    return text.replace("|", "\\|")


def write_reference(live: list[dict], settings: list[dict]) -> None:
    src_text = {"doc": "official doc", "own": "own (see text)", "none": "-"}
    out = [
        "# Attribute reference",
        "",
        "Generated by `tools/build_catalog.py`. Field names are the official Growatt OpenAPI names;",
        f"descriptions marked *official doc* are taken from the [Growatt OpenAPI documentation]({DOC_URL}).",
        "Fields without a source are delivered by the inverter but documented nowhere; their meaning is unknown.",
        "",
        "Unit source: *measured* = compared with the Growatt portal or checked against other fields of the",
        "same response on an SPH 10000TL3 BH-UP; *doc* = the official description names the quantity and the",
        "unit follows the measured fields of the same kind. Fields without a unit are shown as raw values.",
        "",
        "## Live data (`mix_last_data`, every 5 minutes)",
        "",
        f"{len(live)} fields. Enabled by default: the fields marked **on**; all others are created disabled",
        "and can be enabled under *Settings > Devices & services > Growatt OpenAPI > Entities*.",
        "The enabled power entities show kW (the API value in W divided by 1000), as they did before",
        "the catalog existed, so their history stays continuous.",
        "",
        "| Field | Default | Unit | Unit source | Meaning | Source | Values |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in live:
        out.append(
            f"| `{r['name']}` | {'**on**' if r['legacy_key'] else 'off'} | {r['unit'] or ''} | "
            f"{r['unit_source'] or ''} | {md_escape(r['description']) or '*unknown*'} | "
            f"{src_text[r['source']]} | {md_escape(r['enum'])} |"
        )
    out += [
        "",
        "## Settings (`mix_data_info`, every 30 minutes)",
        "",
        f"{len(settings)} fields, all created disabled, shown as diagnostic entities with the raw value.",
        "",
        "| Field | Meaning | Source | Values |",
        "|---|---|---|---|",
    ]
    for r in settings:
        out.append(
            f"| `{r['name']}` | {md_escape(r['description']) or '*unknown*'} | "
            f"{src_text[r['source']]} | {md_escape(r['enum'])} |"
        )
    out += [
        "",
        "## Not shown",
        "",
        "These fields are delivered but never become entities, because they identify the owner, the plant",
        "or the hardware, or because they are not single values: "
        + ", ".join(f"`{n}`" for n in sorted(EXCLUDED, key=str.lower)) + ".",
        "",
    ]
    (ROOT / "docs" / "attributes.md").write_text("\n".join(out), encoding="utf-8")


def main() -> None:
    doc_dir = pathlib.Path(sys.argv[1])
    last = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))["data"]
    info = json.loads(pathlib.Path(sys.argv[3]).read_text(encoding="utf-8"))["data"]
    live = entries(last, doc_table(doc_dir / LIVE_DOC, live=True), live=True)
    settings = entries(info, doc_table(doc_dir / INFO_DOC, live=False), live=False)
    missing = set(LEGACY_KEYS) - {r["name"] for r in live}
    if missing:
        sys.exit(f"legacy fields missing in the sample: {sorted(missing)}")
    write_catalog(live, settings)
    write_reference(live, settings)
    print(f"live fields {len(live)}, settings {len(settings)}")


if __name__ == "__main__":
    main()
