# Growatt OpenAPI: official API with token as primary source -- Design

Date: 2026-11-14. Status: draft for owner approval.

## Intent

Today the integration reads all values through the Growatt web portal (`server.growatt.com`) with username, password and a cookie session. Every portal login carries the risk of Growatt locking the account when logins happen too often (Home Assistant docs: the password-based "classic API" has strict rate limits and can lock the account for up to 24 hours; the token-based official API "does not have this limitation").

Goal: in normal operation the integration does not log in to the portal at all. It reads values from the official Growatt OpenAPI v1 with an API token, and obtains that token itself through the portal. The portal path stays as a fallback.

## Facts this design rests on (measured 2026-11-14)

- Official API: `https://openapi.growatt.com/v1/`, header `token: <api token>`. No login, no session token, no refresh token: the same token goes with every request.
- With a valid token: `GET plant/list` returned plant `1000001` (same id as the portal), `GET device/list?plant_id=1000001` returned the inverter as `type` 5 (SPH), `POST device/mix/mix_last_data` (form `mix_sn=<serial>`) returned live data with `error_code` 0, data timestamp a few minutes old.
- Live data contains `soc`, `pacToGridTotal`, `pacToUserTotal`, `plocalLoadTotal`, `ppv`, `ppv1`, `ppv2`, `vpv1`, `vpv2`, `vbat`, `pcharge1`, `pdischarge1`, `vac1`, `fac`, `status`, `time`, today/total energies (`epvtoday`, `epvTotal`, `etoGridToday`, `etogridTotal`, `etoUserToday`, `etoUserTotal`, `elocalLoadToday`, `elocalLoadTotal`, `echarge1Today`, `edischarge1Today`, `edischarge1Total`, `acChargeEnergyToday`, ...). Powers are in W (portal: kW).
- Totals differ between sources: `etogridTotal` API 20516.6 kWh vs portal 20460.9 kWh at about the same time.
- Token via portal session (Fiddler capture of the portal "API Key" page, 2026-11-14), both with the normal portal session cookie and empty body:
  - `POST https://server.growatt.com/set/getUserTokenData` -> `{"result":1,"obj":{"token":"<token>", ...}}`
  - `POST https://server.growatt.com/set/resetApiToken` -> `{"result":1,"msg":"<new token>"}`; a following `getUserTokenData` returns that new token.
- After a reset, the old token is dead, but the API does not report an error: `plant/list` answers `error_code` 0 with an empty plant list.
- The growattServer library knows the generic error code `10011` "No privilege access". Whether a dead token produces it is not verified.

## Decisions (owner, 2026-11-14)

1. **Setup:** the user enters only username and password, as today. The integration logs in to the portal once and reads the API token itself.
2. **Token storage:** the token is stored persistently in the config entry data (where username and password already are, unencrypted). After a restart the stored token is used without a portal login.
3. **Normal operation:** all values come from the official API with the token. No portal login.
4. **Token counts as dead** only if Growatt answers validly and the answer itself shows the token is not authorised: an empty plant list with `error_code` 0, or `error_code` 10011. Nothing else marks a token dead.
5. **Disturbance** (no connection, timeout, HTTP/server error, unreadable response, rate limit): the token stays as it is; the poll fails, all sensors become unavailable until the next regular poll (as today). No switch to the portal, no portal login.
6. **Dead token:** log in to the portal and read the current token. If it differs from the dead one, use and store it. If it is the same dead token, generate a new one (`resetApiToken`), store and use it. Generating is done only here and in decision 12, never in any other situation.
7. **Fallback:** the newly generated token is checked right away. If it is also dead, the integration switches to portal operation: values come from the portal as today (session reused, single re-login on expiry).
8. **Way back:** in portal operation, every poll also reads the token through the existing portal session (no extra login). If it differs from the dead one, the integration tries the API with it; if it works, it is back in normal operation and stores the token. In portal operation the integration never generates a token itself.
   Consequence accepted: after a Home Assistant restart the flow starts over, so with a still-dead token the integration generates at most one new token per start (about once a day with the nightly NAS shutdown).
9. **Sensors unchanged:** same 31 sensors, same entity names, powers in kW, regardless of source. API values are mapped internally to the portal field names and units.
10. **Failed recovery:** if obtaining a new token fails partway (portal login rejected, 507, timeout, rate limit, disturbance on `getUserTokenData`/`resetApiToken`), the poll fails and sensors are unavailable. The next recovery attempt waits 5 min, then 10, 20, 40 min, then at most once per hour. After a successful recovery the normal 5-minute rhythm applies again. No portal login happens between attempts.
11. **Own generated token, second chance:** in portal operation, the token the integration generated itself is tried exactly once more on the API at the next poll (in case Growatt activates it with a delay). This needs no login, the token is stored.
12. **Account without token:** if `getUserTokenData` returns an empty token at setup (or at the first start of an existing entry), the integration generates one. There is no old token that this could disable.
13. **Energy counter jumps accepted:** API and portal report slightly different counter values. On a source switch the energy statistics may jump a little (Home Assistant treats a drop of less than 10 % on a `total_increasing` sensor as a warning only, a larger drop as a new meter cycle). This is accepted; source switches are rare.

## Approaches

- **A (chosen): own small API client in the existing code.** A second, slim aiohttp client for the few OpenAPI endpoints next to the portal client; the API response is translated into the same `GrowattData` shape the sensors already consume (portal field names, kW); a small source controller in the coordinator applies decisions 4-8. No new dependency, same style as the existing code.
- **B: use the `growattServer` library** (used by the built-in HA integration). Knows the endpoints, but adds a dependency with a different (synchronous `requests`) style for a handful of calls.
- **C: separate second integration for the API.** Rejected: sensors must stay the same and the fallback needs both paths in one place.

## Goals / non-goals

- Goal: no portal logins in normal operation; existing sensors and automations keep working unchanged.
- Non-goal of this project: new sensors for API-only values (battery temperature, SOH, cycles, ...) and any writing/control through the API. Both are wanted by the owner, as separate follow-up projects in this order: (2) read as much as the API offers, (3) control. Each gets its own design. As the last step, (4) the value differences between API and portal (e.g. `etogridTotal`) are investigated as a project of their own; until then decision 13 applies.
- Anti-goal: generating a new token because of a disturbance; any login loop.

## Left to the builder

- **Field mapping, to be verified first:** for each of the 31 sensors, the API field and conversion, checked by reading both sources at the same time and comparing. Not yet certain, e.g. grid import today (`gridPowerToday` portal vs. `etoUserToday` API?), `lastUpdateTime` (API `time`), the day-chart fields (`etouser`, `elocalLoad`, `eCharge`, `eAcCharge`). Sensors without a reliable API equivalent: bring to the owner before deciding.
- Which API calls each poll needs, and how decision 4 is detected in each poll (e.g. what `mix_last_data` returns for a dead token; the old, dead token from 2026-11-14 is available for one such check).
- Existing config entries have no token: on the first start after the update they behave like decision 1 (one portal login to read the token, then store it). (Builder's call: no reconfiguration needed by the user.)
- After a successful token recovery, the same poll fetches the values with the new token. (Builder's call.)
- Every portal login, token read, token generation and source switch is logged at INFO level or higher, so the number of logins can be counted from the log. (Builder's call.)
- The token is never written to the log.
- Unknown: rate limits of the official API.
