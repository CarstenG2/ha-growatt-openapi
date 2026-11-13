# Growatt web integration for Home Assistant -- design

Status: 2026-11-13, draft for approval.

## Purpose and background

The built-in Home Assistant integration `growatt_server` fails repeatedly. On 2026-11-13 it stopped delivering values; after a reload, login failed with "Growatt login failed: 507". At the same time, logging in to the Growatt web portal (`server.growatt.com`) with the same account worked, and all values were available there. This was shown by an existing PowerShell script that uses the web portal, run successfully on 2026-11-13.

The new integration `ha-growatt-web` reads the values via exactly this web portal path and provides them as sensors in Home Assistant. For the owner's installation it replaces the built-in integration.

The token login of the built-in integration and the official Growatt OpenAPI are not an option: according to the Home Assistant docs, token login is only intended for MIN/TLX inverters. The target inverter is an SPH 10000TL3 BH-UP (Growatt device type `mix`).

## Goals

- All values listed below as sensors in Home Assistant, polled every 5 minutes.
- Credentials only via the Home Assistant setup dialog, never in code.
- Installation and updates by copying the integration folder into the Home Assistant configuration directory and restarting Home Assistant (owner decision 2026-11-13; no HACS, no public repository).

## Non-goals

- No write access to the inverter or the Growatt account, no settings, no control.
- No daily charts (5-minute series) as sensors.
- No home automation logic. The integration knows nothing about any automation that consumes its sensors. Such logic lives in the user's Home Assistant automations and is documented there only. It does not appear in this repository, including README and comments.

## Anti-goals

- A locked Growatt account caused by too many logins. A forum post reports an account being locked after a Growatt integration was enabled.
- Credentials in the repository, in logs, or in error messages.

## Constraints

- Repository: private (owner decision 2026-11-13, to avoid drawing Growatt's attention to the portal API).
- Home Assistant 2026.10.4, HACS is installed.
- Sensor names are the original Growatt field names (owner decision 2026-11-13). Everything else in the repository is in English: code, logs, docstrings, README, and setup dialog texts (owner decision 2026-11-13: Growatt and Home Assistant are international).
- Every exception is logged, no silent `except`. Every network call has an explicit timeout.
- Real calls against `server.growatt.com` with the owner's account are allowed during development, but sparingly: single logins and requests several minutes apart, never in loops (owner decision 2026-11-13).

## Credentials

Setup via a Home Assistant config flow with username and password. Home Assistant stores them in its own configuration on the Home Assistant host, in the same place as the built-in integration does. They are stored unencrypted there; the owner knows and accepts this. The dialog validates the credentials with a login before completing setup.

## Growatt web portal interface (measured 2026-11-13)

Undocumented; everything below comes from the script and from calls on 2026-11-13.

1. Login: `POST https://server.growatt.com/login`, form fields `account`, `password`. Success: JSON with `result` = 1. The session is held in cookies.
2. Plant: `GET https://server.growatt.com/index/getPlantListTitle` returns a list; `id` of the first entry is the plant ID.
3. Device: `POST https://server.growatt.com/panel/getDevicesByPlantList`, form `currPage=1`, `plantId`. First entry in `obj.datas`: `sn` (serial number), `deviceTypeName` (here `mix`), `deviceModel` (here SPH 10000TL3 BH-UP), `lastUpdateTime` (local time of the plant, format `yyyy-MM-dd HH:mm:ss`; time zone in field `timezone`, here 1.0).
4. Live values: `POST https://server.growatt.com/panel/mix/getMIXStatusData?plantId=<id>`, form `mixSn=<sn>`. Response `obj` with the fields below. Caution: the response contains the keys `vAc1` and `vac1` with the same value; a parser must not fail on this. PowerShell received the response as text rather than as a JSON object.
5. Daily totals: `POST https://server.growatt.com/panel/mix/getMIXEnergyDayChart`, form `date=<yyyy-MM-dd>`, `plantId`, `mixSn`. Response `obj` with daily totals (numbers as strings) and `charts` (series, not needed).
6. Logout: `GET https://server.growatt.com/logout`. On 2026-11-13 this returned an error while following the redirect; whether the session was actually ended is unverified.

## Sensors

The meanings are derived from the field names; Growatt does not document them. Only one plausibility check exists: at night without PV and without grid import, `pdisCharge1` equalled `pLocalLoad` (0.24 each). Grid export and grid import were both 0 during the measurement and are therefore unverified.

Live values from step 4:

| Sensor (Growatt field name) | Assumed meaning | Unit (assumed) |
|---|---|---|
| `SOC` | battery state of charge | % |
| `vBat` | battery voltage | V |
| `chargePower` | battery charge power | kW |
| `pdisCharge1` | battery discharge power | kW |
| `pactogrid` | grid export power | kW |
| `pactouser` | grid import power | kW |
| `pLocalLoad` | load power | kW |
| `ppv` | total PV power | kW |
| `vPv1` | PV1 voltage | V |
| `pPv1` | PV1 power | open, see below |
| `vPv2` | PV2 voltage | V |
| `pPv2` | PV2 power | open, see below |
| `vAc1` | grid voltage | V |
| `fAc` | grid frequency | Hz |
| `status` | inverter status | raw value, text mapping unknown |

Open unit for PV1/PV2 power: on 2026-11-13 at night, `pPv2` reported 2.4 while `ppv` was 0.0. If both were kW, this would not fit. Assumption: `pPv1`/`pPv2` are W. Before installing in Home Assistant, check in daylight with a real request whether `ppv` matches the sum of `pPv1` and `pPv2` in W or in kW, and only then fix the unit (owner decision 2026-11-13). Installation waits for this check.

Daily totals from step 5:

| Sensor (Growatt field name) | Assumed meaning | Unit (assumed) |
|---|---|---|
| `etouser` | grid import today | kWh |
| `elocalLoad` | load consumption today | kWh |
| `eCharge` | battery charged today | kWh |
| `eAcCharge` | battery charged from grid today | kWh |

Timestamps:

| Sensor | Source | Behaviour on failure |
|---|---|---|
| Last successful poll (no Growatt field) | time at which a poll last completed successfully | keeps its last value, does not become unavailable |
| `lastUpdateTime` | `lastUpdateTime` from step 3 (time the datalogger last reported) | like the other sensors |

The second timestamp shows whether the inverter's datalogger still reports to Growatt. If only the datalogger fails, polling keeps succeeding, but Growatt returns stale values.

## Polling

- Every 5 minutes. Reason: the daily charts have 288 values per day, i.e. 5-minute resolution.
- The session is reused as long as Growatt accepts it. A new login happens only when it has expired.
- If it has expired, the integration logs in once more within the same poll and fetches the values right away (owner decision 2026-11-13). If this re-login fails, the poll counts as failed.
- Expired session, measured 2026-11-13: a request without a valid session gets HTTP 302 with `Location: /error.do?errorMess=errorNoLogin`. The client does not follow redirects and treats this as an expired session.
- Plant ID and serial number are determined during setup.

## Failure behaviour

- If a poll fails (login rejected, no response, timeout, unusable response), all sensors become unavailable. The exception is "Last successful poll", which keeps the last success time.
- No additional immediate retries. The next attempt is the next regular poll after 5 minutes. The only exception is the single re-login on an expired session (see Polling).
- A rejected login is treated like any other failure: keep trying every 5 minutes, without distinguishing a wrong password from Growatt-side errors such as 507 (owner decision 2026-11-13; the lockout risk with a wrong password is known).
- Every failure is logged with its cause in the Home Assistant log, without credentials.

## Decided by the author, not explicitly by the owner

- Entity IDs prefixed with `growatt_web_` (device name "Growatt Web").

## Left to the builder

- Python package layout, HTTP library, test structure.
- Tests cover exactly the behaviour described here, no additional checks.
