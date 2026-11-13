# Growatt Web

Read-only Home Assistant integration for Growatt inverters. It reads the values from the Growatt web portal (`server.growatt.com`) with your normal portal account, the same way the portal's own web pages do.

Tested with an SPH 10000TL3 BH-UP (Growatt device type `mix`). Other device types are not supported.

The portal API is undocumented. Sensor names are the original Growatt field names; their meanings and units are derived from those names and may be wrong.

## Installation

1. HACS -> Integrations -> three-dot menu -> Custom repositories -> add `https://github.com/CarstenG2/ha-growatt-web` as type "Integration".
2. Install "Growatt Web" and restart Home Assistant.
3. Settings -> Devices & services -> Add integration -> "Growatt Web", enter your Growatt portal username and password.

Credentials are stored by Home Assistant in its config entry storage, like any other integration. They are not stored in this repository.

## Behaviour

- Polls every 5 minutes. The portal session is reused; if it has expired, the integration logs in once more within the same poll.
- If a poll fails, all sensors become unavailable until the next successful poll. There are no extra retries.
- `Last successful poll` keeps the time of the last successful poll even while polling fails.
- `lastUpdateTime` is the time the inverter's datalogger last reported to Growatt. If it stops advancing while polls succeed, Growatt is returning stale values.

## Sensors

| Sensor | Assumed meaning | Unit |
|---|---|---|
| SOC | battery state of charge | % |
| vBat | battery voltage | V |
| chargePower | battery charge power | kW |
| pdisCharge1 | battery discharge power | kW |
| pactogrid | grid export power | kW |
| pactouser | grid import power | kW |
| pLocalLoad | load power | kW |
| ppv | total PV power | kW |
| vPv1, vPv2 | PV string voltage | V |
| pPv1, pPv2 | PV string power | not yet verified, no unit |
| vAc1 | grid voltage | V |
| fAc | grid frequency | Hz |
| status | inverter status, raw value | |
| etouser | grid import today | kWh |
| elocalLoad | load consumption today | kWh |
| eCharge | battery charged today | kWh |
| eAcCharge | battery charged from grid today | kWh |
| lastUpdateTime | last datalogger upload | timestamp |
| Last successful poll | last successful poll by this integration | timestamp |

## Development

Tests for the portal client run without Home Assistant:

```
pip install aiohttp pytest pytest-asyncio
pytest -o asyncio_mode=auto tests
```
