# Publish readiness: reference documentation, read and write attributes, HACS

Status: draft, all owner decisions taken, awaiting owner approval.

## Intent

The repository will be published. Anyone who adds it to HACS must understand from the
repository alone what the integration does, which values it reads, which it can set,
and what each value and each allowed setting means. Every claim in the documentation
must be backed by the code, a test or a measurement on a real device; nothing invented.

## Decisions by the owner (2026-11-15)

1. The Growatt OpenAPI documentation is **not** copied into the repository. The README
   links to the official documentation: https://www.showdoc.com.cn/262556420217021
2. The repository has its **own reference**: a feature list, an explanation of every
   variable/attribute, and the allowed values (enums) of every setting.
3. Explanations and enums are written where the official documentation is missing,
   incomplete or unclear (measured on 2026-11-15: it describes 107 of the 230 live
   fields and 93 of the 219 setting fields the SPH 10000TL3 BH-UP delivers; units and
   enum values are mostly missing).

4. Entity names are the **official API field names** (e.g. `pcharge1` instead of
   `chargePower`), so every name can be looked up in the official documentation. The
   unique id of existing entities stays unchanged, so their history is kept.

5. **Every** live field becomes a sensor. The important ones are enabled by default,
   all others are created disabled (one click in Home Assistant enables them).
   "Important" = the sensors that exist today (owner, 2026-11-15; 34 entities).

6. **All 15** SPH setting types of the official documentation become writable.
   Writes are **not tested on the real inverter** (owner, 2026-11-15: "alles was geht,
   aber NICHT testen"). Tests run only against a fake server. The official API
   documentation is the authoritative source for setting types, parameters and value
   ranges (owner: "wir vertrauen der api doc").
   The README states only that the settings follow the official API documentation; it
   carries no "untested" warning (owner, 2026-11-15).

7. Full HACS packaging: `hacs.json`, MIT license, GitHub releases with version
   numbers, HACS install button in the README, and an automatic HACS validation
   check on every push (as in 0xAHA/Growatt_ModbusTCP).

8. README and reference are written in **English**.

## Facts the design builds on

- Read via API token: `device/mix/mix_last_data` (230 live fields) and
  `device/mix/mix_data_info` (219 setting fields), each limited to one call per
  5 minutes per endpoint.
- Write via API token: `mixSet` with `type` and `param1`..`param18`; the official
  documentation lists 15 SPH setting types. None has been written by us yet.
- The Home Assistant core integration `growatt_server` already offers, with API token
  and for this inverter: charge power, charge stop SOC, discharge power, discharge stop
  SOC (numbers), AC charge (switch), time segment actions.
- Today our sensors use portal field names (e.g. `chargePower`), the API uses other
  names (e.g. `pcharge1`).

## Source rule for every explanation and enum

Each entry in the reference carries its source: official documentation, Growatt Python
library, portal web source, or own measurement (date). An entry without a source is
marked "meaning unknown" and gets no invented explanation.
