"""Tests for the official Growatt OpenAPI client and the field mapping."""

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from gw import api, openapi

# mix_last_data as measured on 2026-11-14 10:06:44 (subset), numbers as Growatt sends them.
LAST = {
    "soc": 58, "vbat": 424.79998779296875, "pcharge1": 760, "pdischarge1": 0,
    "pacToGridTotal": 10, "pacToUserTotal": 0, "plocalLoadTotal": 280, "ppv": 1039.1,
    "vpv1": 337, "ppv1": 478.4, "vpv2": 390.20001220703125, "ppv2": 560.7,
    "vac1": 395.8999938964844, "fac": 49.9900016784668, "status": 5,
    "bmsMaxCurr": 25, "bmsBatteryCurr": -3.0999999046325684, "bmsBatteryTemp": 26.299999237060547,
    "elocalLoadToday": 1.9, "epvtoday": 1.100000023841858, "epvTotal": 30620.300000000003,
    "etoGridToday": 0, "etogridTotal": 20516.6, "edischarge1Today": 1.4,
    "edischarge1Total": 4366.4, "elocalLoadTotal": 9853.9, "time": "2026-11-14 10:06:44",
    # Fields without a reliable portal equivalent; must not leak into the mapping.
    "etoUserToday": 0, "etoUserTotal": 3134.7, "echarge1Today": 0.5, "acChargeEnergyToday": 0.1,
}

GOOD = "good-token"
DEAD = "dead-token"


class FakeOpenApi:
    def __init__(self):
        self.plants = [{"plant_id": 1000001, "name": "x"}]
        self.code = 0
        self.http_status = 200
        self.calls = []

    def _check(self, request):
        self.calls.append(request.path)
        if self.http_status != 200:
            raise web.HTTPInternalServerError()
        if self.code:
            return web.json_response({"error_code": self.code, "error_msg": "x", "data": ""})
        if request.headers.get("token") == DEAD:
            return web.json_response(
                {"error_code": 10011, "error_msg": "error_permission_denied", "data": ""}
            )
        return None

    async def plant_list(self, request):
        return self._check(request) or web.json_response(
            {"error_code": 0, "error_msg": "", "data": {"count": len(self.plants), "plants": self.plants}}
        )

    async def plant_details(self, request):
        return self._check(request) or web.json_response(
            {"error_code": 0, "error_msg": "", "data": {"timezone": "GMT+1", "plant": {}}}
        )

    async def last_data(self, request):
        form = await request.post()
        assert form.get("mix_sn") == "SN1"
        return self._check(request) or web.json_response(
            {"error_code": 0, "error_msg": "", "data": LAST}
        )

    async def mix_set(self, request):
        self.written = dict(await request.post())
        return self._check(request) or web.json_response(
            {"error_code": 0, "error_msg": "Set Successful mix return", "data": ""}
        )

    def app(self):
        app = web.Application()
        app.router.add_post("/v1/mixSet", self.mix_set)
        app.router.add_get("/v1/plant/list", self.plant_list)
        app.router.add_get("/v1/plant/details", self.plant_details)
        app.router.add_post("/v1/device/mix/mix_last_data", self.last_data)
        return app


@pytest.fixture
async def fake():
    f = FakeOpenApi()
    server = TestServer(f.app())
    await server.start_server()
    f.base_url = str(server.make_url("/v1/"))
    yield f
    await server.close()


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as s:
        yield s


def test_mapping_matches_portal_snapshot():
    data = openapi.to_growatt_data(LAST, 1.0)
    assert data.status["SOC"] == 58
    assert data.status["vBat"] == 424.8
    assert data.status["chargePower"] == 0.76
    assert data.status["pdisCharge1"] == 0
    assert data.status["pactogrid"] == 0.01
    assert data.status["pactouser"] == 0
    assert data.status["pLocalLoad"] == 0.28
    assert data.status["ppv"] == 1.039
    assert data.status["vPv1"] == 337
    assert data.status["pPv1"] == 478.4
    assert data.status["vPv2"] == 390.2
    assert data.status["pPv2"] == 560.7
    assert data.status["vAc1"] == 395.9
    assert data.status["fAc"] == 49.99
    assert data.status["status"] == "5"
    assert data.status["bmsMaxCurr"] == 25
    assert data.status["bmsBatteryCurr"] == -3.1
    assert data.status["bmsBatteryTemp"] == 26.3
    assert data.day_totals == {"elocalLoad": 1.9}
    assert data.totals == {
        "epvToday": 1.1, "epvTotal": 30620.3, "etoGridToday": 0, "etogridTotal": 20516.6,
        "edischarge1Today": 1.4, "edischarge1Total": 4366.4, "elocalLoadToday": 1.9,
        "elocalLoadTotal": 9853.9,
    }
    assert data.device_info == {"lastUpdateTime": "2026-11-14 10:06:44", "timezone": 1.0}


# mix_last_data counters and the portal values read at the same time (2026-11-14 13:54).
COMPARE_API = {
    "esystemtoday": 7.300000190734863, "eselftoday": 4.599999904632568, "elocalLoadToday": 4.7,
    "elocalLoadTotal": 9856.7, "eselftotal": 8906.400390625,
}
COMPARE_PORTAL_DAY = {"eCharge": 7.3, "eAcCharge": 2.7, "etouser": 0.1}
COMPARE_PORTAL_TOTALS = {"gridPowerToday": 0.1, "gridPowerTotal": 950.3}


def test_derived_fields_match_portal():
    data = openapi.to_growatt_data(COMPARE_API, None)
    for field, value in COMPARE_PORTAL_DAY.items():
        assert data.day_totals[field] == value
    for field, value in COMPARE_PORTAL_TOTALS.items():
        assert data.totals[field] == value


def test_derived_fields_missing_input_gives_no_value():
    data = openapi.to_growatt_data({"esystemtoday": 7.3, "elocalLoadToday": 4.7}, None)
    assert data.day_totals == {"elocalLoad": 4.7, "eCharge": 7.3}
    assert "gridPowerToday" not in data.totals and "gridPowerTotal" not in data.totals


def test_derived_fields_clipped_at_zero():
    data = openapi.to_growatt_data({"esystemtoday": 2.0, "eselftoday": 2.1}, None)
    assert data.day_totals["eAcCharge"] == 0


def test_mapping_skips_missing_and_empty_fields():
    data = openapi.to_growatt_data({"soc": 58, "ppv": "", "time": ""}, None)
    assert data.status == {"SOC": 58}
    assert data.device_info == {}


@pytest.mark.parametrize(
    ("raw", "hours"), [("GMT+1", 1.0), ("GMT-3:30", -3.5), ("GMT", 0.0), ("", None), (None, None), ("CET", None)]
)
def test_timezone_parsed_from_gmt_string(raw, hours):
    assert openapi.parse_gmt_offset(raw) == hours


async def test_plants_and_last_data(fake, session):
    client = openapi.OpenApiClient(session, base_url=fake.base_url)
    assert await client.plants(GOOD) == ["1000001"]
    assert (await client.last_data(GOOD, "SN1"))["soc"] == 58
    assert await client.plant_timezone(GOOD, "1000001") == 1.0


async def test_dead_token_10011_raises_token_dead(fake, session):
    client = openapi.OpenApiClient(session, base_url=fake.base_url)
    with pytest.raises(openapi.GrowattTokenDead):
        await client.last_data(DEAD, "SN1")
    with pytest.raises(openapi.GrowattTokenDead):
        await client.plants(DEAD)


async def test_empty_plant_list_raises_token_dead(fake, session):
    fake.plants = []
    client = openapi.OpenApiClient(session, base_url=fake.base_url)
    with pytest.raises(openapi.GrowattTokenDead):
        await client.plants(GOOD)


async def test_rate_limit_10012_is_disturbance(fake, session):
    fake.code = 10012
    client = openapi.OpenApiClient(session, base_url=fake.base_url)
    with pytest.raises(api.GrowattError) as info:
        await client.last_data(GOOD, "SN1")
    assert not isinstance(info.value, openapi.GrowattTokenDead)


async def test_http_error_is_disturbance(fake, session):
    fake.http_status = 500
    client = openapi.OpenApiClient(session, base_url=fake.base_url)
    with pytest.raises(api.GrowattError) as info:
        await client.plants(GOOD)
    assert not isinstance(info.value, openapi.GrowattTokenDead)


async def test_unreachable_is_disturbance(session):
    client = openapi.OpenApiClient(session, base_url="http://127.0.0.1:9/v1/")
    with pytest.raises(api.GrowattError) as info:
        await client.plants(GOOD)
    assert not isinstance(info.value, openapi.GrowattTokenDead)


async def test_write_sends_type_and_all_18_params(fake, session):
    client = openapi.OpenApiClient(session, fake.base_url)
    await client.write(GOOD, "SN1", "pv_on_off", ["0001"])
    assert fake.written["mix_sn"] == "SN1"
    assert fake.written["type"] == "pv_on_off"
    assert fake.written["param1"] == "0001"
    assert [fake.written[f"param{i}"] for i in range(2, 19)] == [""] * 17


async def test_write_error_code_is_raised(fake, session):
    fake.code = 10008  # parameter value out of range
    client = openapi.OpenApiClient(session, fake.base_url)
    with pytest.raises(api.GrowattError, match="10008"):
        await client.write(GOOD, "SN1", "pv_on_off", ["0001"])
