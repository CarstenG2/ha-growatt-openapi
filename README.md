# Growatt Web for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![Release](https://img.shields.io/github/v/release/CarstenG2/ha-growatt-web?label=Release&color=blue)](https://github.com/CarstenG2/ha-growatt-web/releases/latest)
[![Validate](https://github.com/CarstenG2/ha-growatt-web/actions/workflows/validate.yml/badge.svg)](https://github.com/CarstenG2/ha-growatt-web/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**424 values to read, 15 settings to write, every SPH command of the official Growatt API.**
It might be the most complete Growatt integration for Home Assistant.

Growatt Web connects Growatt SPH hybrid inverters through the **official Growatt OpenAPI**,
with nothing more than your Growatt username and password. It fetches the API token itself,
renews it only when Growatt really rejects it, and falls back to the Growatt web portal so
your sensors keep working when the API does not.

## What makes it different

| | Growatt Web |
|---|---|
| Live values | all **224** fields of the official live data (`mix_last_data`) as sensors |
| Settings | all **200** fields of the inverter settings (`mix_data_info`) as diagnostic sensors |
| Writing | all **15** SPH setting types of the official API as actions, plus a raw write for any type |
| Raw API access | read a single parameter from the inverter, 5-minute history of up to 7 days, alarm records |
| API token | obtained automatically from your login, no copying of tokens |
| Token renewal | only when Growatt answers "no privilege"; never on timeouts, outages or rate limits |
| Fallback | automatic switch to the Growatt web portal if the API is unusable, automatic return |
| Portal values | the portal's own daily figures (grid import, export, system output) computed exactly from the API counters |
| Battery management | BMS charge/discharge current limit, battery current, temperatures, cell voltages, cycles, SOH |
| Documentation | every field, every setting and every allowed value explained, with its source |

The core Home Assistant integration `growatt_server` offers, according to its documentation,
charge power, charge stop SOC, discharge power, discharge stop SOC, an AC charge switch and
time segment actions for token users. Growatt Web covers every setting type the official API
documents for SPH inverters.

## Supported devices

Growatt SPH ("mix", device type 5 in the Growatt API) hybrid inverters with a Growatt
datalogger (ShineWiFi, ShineLAN) and an account on `server.growatt.com`.
Developed and used with an **SPH 10000TL3 BH-UP** on Home Assistant 2026.10.

## Installation

### HACS

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=CarstenG2&repository=ha-growatt-web&category=integration)

1. **HACS** -> menu -> **Custom repositories**
2. Add `https://github.com/CarstenG2/ha-growatt-web`, type **Integration**
3. Search for **Growatt Web** -> **Download**
4. Restart Home Assistant

### Manual

1. Copy `custom_components/growatt_web` from the [latest release](https://github.com/CarstenG2/ha-growatt-web/releases/latest) into `config/custom_components/`
2. Restart Home Assistant

## Setup

**Settings** -> **Devices & services** -> **Add integration** -> **Growatt Web**, then enter the
username and password of your Growatt account (`server.growatt.com`). The integration finds
the inverter, reads the API token and starts polling. Credentials and token are kept in Home
Assistant's config entry storage, like for any other integration.

## Entities

- **Enabled after setup:** the 26 most important live values (PV, battery, grid, load powers
  and energies, battery management current and temperature), the portal's daily figures,
  the datalogger time and the time of the last successful poll.
- **Disabled after setup:** every other live value and all settings. Enable the ones you need
  under **Settings** -> **Devices & services** -> **Growatt Web** -> **Entities**.
- Entity names are the official API field names, so every value can be looked up in the
  [Growatt OpenAPI documentation](https://www.showdoc.com.cn/262556420217021).

Full list with meaning, unit, source and allowed values: [docs/attributes.md](docs/attributes.md).

## Actions

| Action | What it sets |
|---|---|
| `growatt_web.set_charge_periods` | battery first: charge power, charge stop SOC, grid charging, 3 time periods |
| `growatt_web.set_discharge_periods` | grid first: discharge power, discharge stop SOC, 3 time periods |
| `growatt_web.set_discharge_stop_soc` | discharge stop SOC |
| `growatt_web.set_export_limit` | anti-backflow (export limit) on/off and power |
| `growatt_web.set_single_phase_export_limit` | single-phase anti-backflow on/off |
| `growatt_web.set_inverter_on_off` | inverter on/off |
| `growatt_web.set_off_grid_enable` | off-grid (backup) operation on/off |
| `growatt_web.set_off_grid_frequency` | off-grid frequency 50/60 Hz |
| `growatt_web.set_off_grid_voltage` | off-grid voltage 230/208/240 V |
| `growatt_web.set_load_first_output` | load first: three-phase sum or single-phase output |
| `growatt_web.set_grid_voltage_high` | upper limit of the mains voltage |
| `growatt_web.set_grid_voltage_low` | lower limit of the mains voltage |
| `growatt_web.set_reactive_power_rate` | reactive power setting |
| `growatt_web.set_power_factor` | power factor |
| `growatt_web.set_time` | inverter time |
| `growatt_web.write_parameter` | any setting type with raw parameters |
| `growatt_web.read_parameter` | reads one setting directly from the inverter (response) |
| `growatt_web.get_history` | 5-minute data sets of up to 7 days (response) |
| `growatt_web.get_alarms` | alarm records (response) |

Parameters, ranges, enum values and an example: [docs/actions.md](docs/actions.md). Types,
parameters and value ranges follow the official
[SPH parameter settings](https://www.showdoc.com.cn/262556420217021/6129761750718760) page.
Actions need the official API; while the integration runs on the portal fallback they fail
with an error message.

## How it works

- **Polling:** every 5 minutes one live data request (`mix_last_data`); the settings
  (`mix_data_info`) every 30 minutes and again after a write. Growatt allows one request per
  endpoint every 5 minutes, and the datalogger uploads new values every 5 minutes, so polling
  more often brings no new data.
- **Token:** read through a portal login at setup and stored in the config entry. In normal
  operation there is no portal login at all.
- **Dead token:** only a valid Growatt answer "no privilege" (error 10011) or an empty plant
  list counts. Then the integration reads the current token through the portal; if it is the
  same dead token, it generates a new one. Network errors, timeouts and the rate limit
  (error 10012) never trigger this.
- **Fallback:** if even a new token does not work, the values come from the web portal until
  a working token appears. Failed attempts wait 5, 10, 20, 40 minutes, then once per hour.
- **Failed poll:** all sensors become unavailable until the next successful poll; no extra
  retries. `Last successful poll` keeps its time.
- **Stale data:** `lastUpdateTime` is the time the datalogger last reported to Growatt. If it
  stops advancing while polls succeed, Growatt is returning old values.

## Portal daily figures

The Growatt portal shows some daily values the API does not deliver. Growatt Web computes
them from the API counters exactly like the portal (checked against the portal three times):

| Entity | Meaning | Computed as |
|---|---|---|
| `eCharge` | system output today | `esystemtoday` |
| `eAcCharge` | export today, portal value | `esystemtoday - eselftoday` |
| `etouser` | grid import today, portal value | `elocalLoadToday - eselftoday` |
| `gridPowerToday` | grid import today | `elocalLoadToday - eselftoday` |
| `gridPowerTotal` | grid import, lifetime | `elocalLoadTotal - eselftotal` |
| `elocalLoad` | load consumption today | `elocalLoadToday` |

## Troubleshooting

Enable debug logging:

```yaml
logger:
  logs:
    custom_components.growatt_web: debug
```

Then reload the integration and check **Settings** -> **System** -> **Logs**. Every portal login
and every write is logged at info level. Please include the log and your inverter model when
you [open an issue](https://github.com/CarstenG2/ha-growatt-web/issues).

## Development

```
pip install aiohttp pytest pytest-asyncio
pytest -o asyncio_mode=auto tests            # clients, token handling, setting types

pip install pytest-homeassistant-custom-component
pytest -o asyncio_mode=auto tests_ha         # setup, entities and actions in Home Assistant
```

`custom_components/growatt_web/catalog.py`, `docs/attributes.md`, `services.yaml` and
`docs/actions.md` are generated by the scripts in `tools/`.

## License

MIT, see [LICENSE](LICENSE). Not affiliated with Growatt.
