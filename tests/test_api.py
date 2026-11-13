"""Tests for the Growatt web portal client against a fake portal."""

import importlib.util
import json
import pathlib
import sys

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

_API_PATH = pathlib.Path(__file__).parents[1] / "custom_components" / "growatt_web" / "api.py"
_spec = importlib.util.spec_from_file_location("growatt_web_api", _API_PATH)
api = importlib.util.module_from_spec(_spec)
sys.modules["growatt_web_api"] = api
_spec.loader.exec_module(api)

# Status response as measured on 2026-11-13, including the duplicate vAc1/vac1 keys.
STATUS_TEXT = (
    '{"result":1,"obj":{"pdisCharge1":0.32,"pactouser":0.0,"vBat":"425.5",'
    '"vAc1":"399.6","pactogrid":0.0,"pLocalLoad":0.32,"vPv2":"140.9",'
    '"chargePower":0.0,"vPv1":"123.1","SOC":"78","pPv2":"0.2","fAc":"50.03",'
    '"vac1":"399.6","pPv1":"0","ppv":0.0,"status":"5"}}'
)
DAY = {"result": 1, "obj": {"etouser": "0.7", "eCharge": "13.1", "eAcCharge": "3.7",
                            "elocalLoad": "10.1", "charts": {"ppv": [0.0]}}}
DEVICES = {"result": 1, "obj": {"datas": [{"sn": "SN1", "deviceModel": "SPH 10000TL3 BH-UP",
                                           "lastUpdateTime": "2026-11-13 17:20:35",
                                           "timezone": 1.0}]}}


class FakePortal:
    """Minimal fake of server.growatt.com with cookie sessions."""

    def __init__(self, password="pw"):
        self.password = password
        self.logins = 0
        self.valid_sessions = set()
        self.next_session = 0

    def expire_all(self):
        self.valid_sessions.clear()

    def _authorized(self, request):
        return request.cookies.get("JSESSIONID") in self.valid_sessions

    def _no_login(self):
        raise web.HTTPFound("/error.do?errorMess=errorNoLogin")

    async def login(self, request):
        form = await request.post()
        self.logins += 1
        if form.get("password") != self.password:
            return web.json_response({"result": 0, "msg": "502"})
        self.next_session += 1
        sid = f"S{self.next_session}"
        self.valid_sessions.add(sid)
        resp = web.json_response({"result": 1, "msg": ""})
        resp.set_cookie("JSESSIONID", sid)
        return resp

    async def plants(self, request):
        if not self._authorized(request):
            self._no_login()
        return web.json_response([{"id": "123", "plantName": "x"}])

    async def devices(self, request):
        if not self._authorized(request):
            self._no_login()
        return web.json_response(DEVICES)

    async def status(self, request):
        if not self._authorized(request):
            self._no_login()
        # Served as text/html like the real portal.
        return web.Response(text=STATUS_TEXT, content_type="text/html")

    async def day(self, request):
        if not self._authorized(request):
            self._no_login()
        return web.json_response(DAY)

    def app(self):
        app = web.Application()
        app.router.add_post("/login", self.login)
        app.router.add_get("/index/getPlantListTitle", self.plants)
        app.router.add_post("/panel/getDevicesByPlantList", self.devices)
        app.router.add_post("/panel/mix/getMIXStatusData", self.status)
        app.router.add_post("/panel/mix/getMIXEnergyDayChart", self.day)
        return app


@pytest.fixture
async def portal():
    fake = FakePortal()
    server = TestServer(fake.app())
    await server.start_server()
    fake.base_url = str(server.make_url(""))
    yield fake
    await server.close()


@pytest.fixture
async def session():
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as s:
        yield s


def make_client(session, portal, password="pw"):
    return api.GrowattWebClient(session, "user", password, base_url=portal.base_url)


async def test_login_and_discover(portal, session):
    client = make_client(session, portal)
    await client.login()
    device = await client.discover_device()
    assert device == api.GrowattDevice(plant_id="123", serial="SN1", model="SPH 10000TL3 BH-UP")


async def test_rejected_login_raises_auth_error(portal, session):
    client = make_client(session, portal, password="wrong")
    with pytest.raises(api.GrowattAuthError):
        await client.login()


async def test_fetch_returns_all_values(portal, session):
    client = make_client(session, portal)
    data = await client.fetch(api.GrowattDevice("123", "SN1"))
    assert data.status["SOC"] == "78"
    assert data.status["vAc1"] == "399.6"
    assert data.day_totals == {"etouser": "0.7", "eCharge": "13.1", "eAcCharge": "3.7",
                               "elocalLoad": "10.1"}
    assert data.device_info["lastUpdateTime"] == "2026-11-13 17:20:35"


async def test_session_is_reused(portal, session):
    client = make_client(session, portal)
    device = api.GrowattDevice("123", "SN1")
    await client.fetch(device)
    await client.fetch(device)
    assert portal.logins == 1


async def test_expired_session_relogs_once_within_same_fetch(portal, session):
    client = make_client(session, portal)
    device = api.GrowattDevice("123", "SN1")
    await client.fetch(device)
    portal.expire_all()
    data = await client.fetch(device)
    assert data.status["SOC"] == "78"
    assert portal.logins == 2


async def test_failed_relogin_raises(portal, session):
    client = make_client(session, portal)
    device = api.GrowattDevice("123", "SN1")
    await client.fetch(device)
    portal.expire_all()
    portal.password = "changed"
    with pytest.raises(api.GrowattAuthError):
        await client.fetch(device)
    assert portal.logins == 2


async def test_unreachable_server_raises_growatt_error(session):
    client = api.GrowattWebClient(session, "user", "pw", base_url="http://127.0.0.1:9")
    with pytest.raises(api.GrowattError):
        await client.login()


def test_parse_json_keeps_duplicate_keys_working():
    parsed = api.parse_json(STATUS_TEXT)
    assert parsed["obj"]["vAc1"] == "399.6"
    assert json.loads(STATUS_TEXT)["obj"]["SOC"] == "78"


def test_parse_json_rejects_html():
    with pytest.raises(api.GrowattError):
        api.parse_json("<html>login</html>")
