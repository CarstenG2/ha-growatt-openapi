# OpenAPI Token as Primary Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read values from the official Growatt OpenAPI with a token that the integration obtains itself through the portal; the portal stays as fallback.

**Architecture:** New `openapi.py` (token API client + mapping of API fields to the existing portal-shaped `GrowattData`), portal client in `api.py` gains token read/reset, new `source.py` holds the source state machine (spec decisions 4-13) without Home Assistant imports, `coordinator.py` delegates to it, `__init__.py`/`config_flow.py` persist the token in the config entry.

**Tech Stack:** Python 3.13+, aiohttp, Home Assistant custom integration; tests with pytest + pytest-asyncio against aiohttp fake servers (no Home Assistant in the test environment).

**Spec:** `docs/superpowers/specs/2026-11-14-openapi-token-design.md`

## Global Constraints

- No new dependency (`manifest.json` `requirements` stays `[]`).
- Poll interval stays 5 minutes.
- The token is never logged.
- Every portal login, token read, token generation and source switch is logged at INFO or higher.
- Every `except` logs or re-raises (owner rule: no silent exception).

## Measured inputs (2026-11-14, live)

- Dead token: `POST device/mix/mix_last_data` and `GET plant/list` answer HTTP 200 `{"error_code":10011,"error_msg":"error_permission_denied"}`. A token disabled by reset also gave `plant/list` `error_code` 0 with no plants.
- `10012` = "Access Frequency Limitation of 5 Minutes/Time" (per endpoint, growattServer docs) -> disturbance, never "dead".
- `plant/details?plant_id=` returns `data.timezone` = `"GMT+1"`; `mix_last_data.time` = plant local time `yyyy-MM-dd HH:mm:ss`, identical snapshot to portal `lastUpdateTime`.
- Field mapping verified against the portal at the same snapshot (10:06:44):

| sensor (portal field) | API field | conversion | check |
|---|---|---|---|
| SOC | soc | - | 58 = 58 |
| vBat | vbat | - | ok |
| chargePower | pcharge1 | /1000 | 0.76 = 760 W |
| pdisCharge1 | pdischarge1 | /1000 | ok |
| pactogrid | pacToGridTotal | /1000 | 0.01 = 10 W |
| pactouser | pacToUserTotal | /1000 | ok |
| pLocalLoad | plocalLoadTotal | /1000 | 0.26 vs 280 W (rounding) |
| ppv | ppv | /1000 | 1.03 = 1039.1 W |
| vPv1, vPv2, pPv1, pPv2, vAc1, fAc | vpv1, vpv2, ppv1, ppv2, vac1, fac | - | ok |
| status | status | str | ok |
| elocalLoad (day) | elocalLoadToday | - | ok |
| epvToday, epvTotal, etoGridToday, edischarge1Today, edischarge1Total, elocalLoadToday, elocalLoadTotal | epvtoday, epvTotal, etoGridToday, edischarge1Today, edischarge1Total, elocalLoadToday, elocalLoadTotal | - | ok |
| etogridTotal | etogridTotal | - | differs (accepted, decision 13) |
| lastUpdateTime | time + plant/details timezone | - | ok |
| etouser, eCharge, eAcCharge, gridPowerToday, gridPowerTotal | none reliable | - | differ (e.g. eCharge 1.8 vs echarge1Today 0.5, gridPowerTotal 950.3 vs etoUserTotal 3134.7) |

The five sensors without a reliable API equivalent are left empty in API operation (no value, never a guessed value) and are put to the owner (spec: "bring to the owner before deciding").

## Review Focus

- Disturbance during recovery (portal 507/timeout) must not cause a login every poll -> backoff test in Task 3.
- 10012 rate limit must never generate a token -> test in Task 3.
- Restart with stored own-generated dead token generates at most once per start -> covered by "fresh controller" test in Task 3.
- Token read returning empty string -> generate (decision 12) -> test in Task 3.
- API numbers arrive as floats with long fractions (424.79998779296875) -> rounded in mapping test in Task 1.

---

### Task 1: OpenAPI client and mapping

**Files:** Create `custom_components/growatt_web/openapi.py`; Test `tests/test_openapi.py`; Create `tests/conftest.py` (loads `custom_components/growatt_web` as package `gw` without running its `__init__`).

**Interfaces:**
- Produces: `class GrowattTokenDead(GrowattError)`; `class OpenApiClient(session, base_url=OPENAPI_URL)` with `async plants(token) -> list[str]` (raises `GrowattTokenDead` on 10011 or empty list), `async last_data(token, serial) -> dict` (raises `GrowattTokenDead` on 10011), `async plant_timezone(token, plant_id) -> float | None`; `def to_growatt_data(last: dict, tz_hours: float | None) -> GrowattData`.
- Any other error_code, HTTP != 200, non-JSON, network error -> plain `GrowattError` (disturbance).

- [ ] Tests: `test_mapping_matches_portal_snapshot` (values from the table, e.g. `status["chargePower"] == 0.76`, `status["SOC"] == 58`, `totals["epvTotal"] == 30620.3`, `device_info == {"lastUpdateTime": "2026-11-14 10:06:44", "timezone": 1.0}`, unmapped five absent), `test_dead_token_10011_raises_token_dead`, `test_empty_plant_list_raises_token_dead`, `test_rate_limit_10012_is_disturbance`, `test_http_error_is_disturbance`, `test_timezone_parsed_from_gmt_string` (`"GMT+1"` -> 1.0, `"GMT-3:30"` -> -3.5).
- [ ] Run, see fail; implement; run, see pass; commit.

### Task 2: Portal token read/reset

**Files:** Modify `custom_components/growatt_web/api.py`; Test `tests/test_api.py`.

**Interfaces:**
- Produces: `GrowattWebClient.read_api_token() -> str` (`POST /set/getUserTokenData`, returns `obj.token`, may be `""`), `GrowattWebClient.reset_api_token() -> str` (`POST /set/resetApiToken`, returns `msg`, empty -> `GrowattError`); both log in if needed and re-login once on expired session, like `fetch`. `login()` logs "Growatt portal login" at INFO.

- [ ] Tests: `test_read_api_token_logs_in_once`, `test_read_api_token_reuses_session_after_fetch` (logins == 1), `test_reset_api_token_returns_new_token`, `test_read_token_relogs_on_expired_session`.
- [ ] Run, fail, implement, pass, commit.

### Task 3: Source state machine

**Files:** Create `custom_components/growatt_web/source.py`; Test `tests/test_source.py` (fake portal and fake API objects, injectable clock).

**Interfaces:**
- Consumes: `GrowattWebClient.fetch/read_api_token/reset_api_token`, `OpenApiClient.plants/last_data/plant_timezone`, `to_growatt_data`.
- Produces: `class SourceController(portal, openapi, device, token: str | None, save_token: Callable[[str], None], clock=time.monotonic)` with `async fetch() -> GrowattData`, properties `mode` (`"api"`/`"portal"`) and `token`. Backoff delays `RECOVERY_DELAYS = (300, 600, 1200, 2400, 3600)` seconds, last value repeats.

- [ ] Tests (one per spec decision): stored valid token -> API data, zero portal logins; disturbance -> raises, token unchanged, no portal call; 10012 -> same; dead -> read token differs -> adopted + saved, data from API; dead -> same token -> reset -> saved -> API; no token (None or "") -> read/generate; generated token dead -> portal mode, data from portal; portal mode: next poll second chance with own token once; portal mode: changed token read -> back to API; portal mode never resets; recovery failure -> raises, next attempts only after 300/600/1200/2400/3600 s, no portal call in between; success resets backoff.
- [ ] Run, fail, implement, pass, commit.

### Task 4: Wire into Home Assistant

**Files:** Modify `const.py` (`CONF_API_TOKEN = "api_token"`), `coordinator.py` (uses `SourceController`), `__init__.py` (build both clients, token from `entry.data.get(CONF_API_TOKEN)`, `save_token` -> `hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_API_TOKEN: t})`), `config_flow.py` (after login+discover read token, empty -> reset; failure logged, entry created without token), `manifest.json` version `0.2.0`, `README.md`.

- [ ] `py_compile` all modules; full test suite passes; commit.

### Task 5: Live test on Home Assistant

- [ ] Back up the deployed folder, copy the new one to the share, restart Home Assistant (owner asked for self-testing).
- [ ] Logger for `custom_components.growatt_web` to INFO temporarily; verify: one portal login, token read, API operation, sensors with values matching the table, token stored in config entry (presence only, never printed), next polls without login; restore logger level to default and verify.
- [ ] Not tested live on purpose: token generation (would disable the owner's current token); covered by Task 3 tests.
