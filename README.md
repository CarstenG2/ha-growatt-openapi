# Growatt Web

Read-only Home Assistant integration for Growatt inverters. It reads the values from the official Growatt OpenAPI with your account's API token, which it obtains itself through the Growatt web portal (`server.growatt.com`); the portal is also the fallback source.

Tested with an SPH 10000TL3 BH-UP (Growatt device type `mix`). Other device types are not supported.

The portal API is undocumented. Sensor names are the original Growatt field names; their meanings and units are derived from those names and may be wrong.

## Installation

1. Copy the folder `custom_components/growatt_web` into the `custom_components` folder of your Home Assistant configuration directory.
2. Restart Home Assistant.
3. Settings -> Devices & services -> Add integration -> "Growatt Web", enter your Growatt portal username and password.

Updates: copy the folder again and restart Home Assistant.

Credentials are stored by Home Assistant in its config entry storage, like any other integration. They are not stored in this repository.

## Behaviour

- Values come from the official Growatt OpenAPI (`openapi.growatt.com`) with the account's API token. The integration reads the token itself through a portal login at setup and stores it in the config entry; in normal operation there is no portal login at all.
- The token counts as dead only if Growatt answers validly with "no privilege" (error 10011) or an empty plant list. Then the integration logs in to the portal and reads the current token; if it is the same dead token, it generates a new one (the previous token stops working). Network errors, timeouts and Growatt's rate limit (error 10012) never trigger this.
- If even a newly generated token does not work, values come from the web portal (username and password) until a working token appears. If obtaining a token fails, the next attempt waits 5, 10, 20, 40 minutes, then at most once per hour.
- In API operation, `etouser`, `eCharge`, `eAcCharge`, `gridPowerToday` and `gridPowerTotal` are computed from the inverter counters exactly as the portal does (e.g. grid import = house load minus self-consumption).
- Polls every 5 minutes. In portal operation the portal session is reused; if it has expired, the integration logs in once more within the same poll.
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
| bmsMaxCurr | battery charge current limit from the battery management (API operation only) | A |
| bmsBatteryCurr | battery current, negative while discharging (API operation only) | A |
| bmsBatteryTemp | battery temperature from the battery management (API operation only) | °C |
| fAc | grid frequency | Hz |
| status | inverter status, raw value | |
| etouser | grid import today, portal value (on 2026-11-13 it matched gridPowerToday, not the app's "purchased energy") | kWh |
| elocalLoad | load consumption today | kWh |
| eCharge | battery charged today | kWh |
| eAcCharge | battery charged from grid today | kWh |
| epvToday, epvTotal | PV energy today / lifetime | kWh |
| etoGridToday, etogridTotal | grid export today / lifetime | kWh |
| gridPowerToday, gridPowerTotal | grid import today / lifetime, portal value | kWh |
| edischarge1Today, edischarge1Total | battery discharged today / lifetime | kWh |
| elocalLoadToday, elocalLoadTotal | load consumption today / lifetime | kWh |
| lastUpdateTime | last datalogger upload | timestamp |
| Last successful poll | last successful poll by this integration | timestamp |

## Development

Tests for the portal client run without Home Assistant:

```
pip install aiohttp pytest pytest-asyncio
pytest -o asyncio_mode=auto tests
```
