"""Tests for the source state machine (spec decisions 3-12)."""

import pytest

from gw import api, openapi, source

DEVICE = api.GrowattDevice(plant_id="1000001", serial="SN1")
PORTAL_DATA = api.GrowattData(status={"SOC": "11"})
LAST = {"soc": 58, "time": "2026-11-14 10:06:44"}


class FakePortal:
    def __init__(self, token="T1"):
        self.token = token
        self.logins = 0
        self.reads = 0
        self.resets = 0
        self.fetches = 0
        self.fail = None  # exception raised by every call
        self.new_tokens = iter(["G1", "G2", "G3"])

    def _call(self):
        self.logins += 0  # logins are counted by the real client; calls are what matters here
        if self.fail:
            raise self.fail

    async def fetch(self, device):
        self._call()
        self.fetches += 1
        return PORTAL_DATA

    async def read_api_token(self):
        self._call()
        self.reads += 1
        return self.token

    async def reset_api_token(self):
        self._call()
        self.resets += 1
        self.token = next(self.new_tokens)
        return self.token


class FakeApi:
    def __init__(self, good=("T1",)):
        self.good = set(good)
        self.fail = None  # disturbance for every call
        self.calls = []

    def _check(self, name, token):
        self.calls.append((name, token))
        if self.fail:
            raise self.fail
        if token not in self.good:
            raise openapi.GrowattTokenDead("10011")

    async def plants(self, token):
        self._check("plants", token)
        return ["1000001"]

    async def last_data(self, token, serial):
        self._check("last_data", token)
        return LAST

    async def plant_timezone(self, token, plant_id):
        self._check("tz", token)
        return 1.0

    # Settings and writes are recorded separately so the call lists of the token
    # tests above stay as they are.
    info_calls: list
    info_fail = None

    async def data_info(self, token, serial):
        self.__dict__.setdefault("info_calls", []).append(token)
        if self.info_fail:
            raise self.info_fail
        return {"chargePowerCommand": 20, "acChargeEnable": 0}

    async def write(self, token, serial, type_id, params):
        self.__dict__.setdefault("writes", []).append((token, serial, type_id, params))
        return ""


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make(token="T1", portal=None, api_=None, clock=None, **kwargs):
    saved = []
    ctrl = source.SourceController(
        portal or FakePortal(), api_ or FakeApi(), DEVICE, token, saved.append, clock or Clock(),
        **kwargs,
    )
    return ctrl, saved


async def test_stored_valid_token_uses_api_without_portal():
    portal = FakePortal()
    ctrl, saved = make("T1", portal)
    data = await ctrl.fetch()
    assert data.status["SOC"] == 58
    assert data.device_info["timezone"] == 1.0
    assert (portal.reads, portal.fetches, portal.resets) == (0, 0, 0)
    assert ctrl.mode == "api" and saved == []


async def test_timezone_is_read_once():
    fake_api = FakeApi()
    ctrl, _ = make("T1", api_=fake_api)
    await ctrl.fetch()
    await ctrl.fetch()
    assert [c for c in fake_api.calls if c[0] == "tz"] == [("tz", "T1")]


@pytest.mark.parametrize("error", [api.GrowattError("timeout"), api.GrowattError("[10012] rate limit")])
async def test_disturbance_fails_poll_and_keeps_token(error):
    portal, fake_api = FakePortal(), FakeApi()
    fake_api.fail = error
    ctrl, saved = make("T1", portal, fake_api)
    with pytest.raises(api.GrowattError):
        await ctrl.fetch()
    assert ctrl.token == "T1" and ctrl.mode == "api" and saved == []
    assert (portal.reads, portal.fetches, portal.resets) == (0, 0, 0)


async def test_dead_token_adopts_changed_token_from_portal():
    portal, fake_api = FakePortal(token="T2"), FakeApi(good=("T2",))
    ctrl, saved = make("T1", portal, fake_api)
    data = await ctrl.fetch()
    assert data.status["SOC"] == 58
    assert ctrl.token == "T2" and saved == ["T2"] and portal.resets == 0


async def test_dead_token_same_as_portal_generates_new_one():
    portal, fake_api = FakePortal(token="T1"), FakeApi(good=("G1",))
    ctrl, saved = make("T1", portal, fake_api)
    data = await ctrl.fetch()
    assert data.status["SOC"] == 58
    assert portal.resets == 1 and ctrl.token == "G1" and saved == ["G1"] and ctrl.mode == "api"


async def test_read_token_also_dead_generates_new_one():
    portal, fake_api = FakePortal(token="T2"), FakeApi(good=("G1",))
    ctrl, saved = make("T1", portal, fake_api)
    await ctrl.fetch()
    assert portal.resets == 1 and ctrl.token == "G1"


@pytest.mark.parametrize("stored", [None, ""])
async def test_no_stored_token_reads_from_portal(stored):
    portal = FakePortal(token="T1")
    ctrl, saved = make(stored, portal)
    data = await ctrl.fetch()
    assert data.status["SOC"] == 58 and saved == ["T1"] and portal.resets == 0


async def test_account_without_token_generates_one():
    portal, fake_api = FakePortal(token=""), FakeApi(good=("G1",))
    ctrl, saved = make(None, portal, fake_api)
    await ctrl.fetch()
    assert portal.resets == 1 and saved == ["G1"]


async def test_generated_token_dead_switches_to_portal():
    portal, fake_api = FakePortal(token="T1"), FakeApi(good=())
    ctrl, saved = make("T1", portal, fake_api)
    data = await ctrl.fetch()
    assert data is PORTAL_DATA and ctrl.mode == "portal"
    assert portal.resets == 1 and saved == ["G1"]


async def test_portal_mode_second_chance_for_own_token():
    portal, fake_api = FakePortal(token="T1"), FakeApi(good=())
    ctrl, _ = make("T1", portal, fake_api)
    await ctrl.fetch()  # -> portal mode with own token G1
    fake_api.good.add("G1")  # Growatt activated it with a delay
    data = await ctrl.fetch()
    assert data is PORTAL_DATA
    assert ctrl.mode == "api" and ctrl.token == "G1"
    assert (await ctrl.fetch()).status["SOC"] == 58


async def test_portal_mode_second_chance_only_once_and_never_generates():
    portal, fake_api = FakePortal(token="T1"), FakeApi(good=())
    ctrl, _ = make("T1", portal, fake_api)
    await ctrl.fetch()
    for _ in range(4):
        assert await ctrl.fetch() is PORTAL_DATA
    own_tries = [c for c in fake_api.calls if c[1] == "G1"]
    assert len(own_tries) == 2  # right after generating, plus one second chance
    assert portal.resets == 1 and ctrl.mode == "portal"


async def test_portal_mode_returns_to_api_on_changed_token():
    portal, fake_api = FakePortal(token="T1"), FakeApi(good=())
    ctrl, saved = make("T1", portal, fake_api)
    await ctrl.fetch()
    await ctrl.fetch()  # second chance used
    portal.token = "U1"  # owner generated a token by hand
    fake_api.good.add("U1")
    assert await ctrl.fetch() is PORTAL_DATA
    assert ctrl.mode == "api" and ctrl.token == "U1" and saved[-1] == "U1"


async def test_portal_mode_api_disturbance_stays_on_portal():
    portal, fake_api = FakePortal(token="T1"), FakeApi(good=())
    ctrl, _ = make("T1", portal, fake_api)
    await ctrl.fetch()
    fake_api.fail = api.GrowattError("timeout")
    assert await ctrl.fetch() is PORTAL_DATA
    assert ctrl.mode == "portal"


async def test_failed_recovery_backs_off():
    clock = Clock()
    portal, fake_api = FakePortal(token="T2"), FakeApi(good=("T2",))
    portal.fail = api.GrowattAuthError("507")
    ctrl, _ = make("T1", portal, fake_api, clock)
    expected_waits = [300, 600, 1200, 2400, 3600, 3600]
    for wait in expected_waits:
        attempts = portal.reads
        with pytest.raises(api.GrowattError):
            await ctrl.fetch()
        assert portal.reads == attempts  # read raised before counting
        clock.now += wait - 1
        with pytest.raises(api.GrowattError):
            await ctrl.fetch()  # still waiting: no portal call
        clock.now += 1
    portal.fail = None
    data = await ctrl.fetch()
    assert data.status["SOC"] == 58 and ctrl.token == "T2"


async def test_no_portal_call_during_backoff():
    clock = Clock()
    portal = FakePortal(token="T2")
    portal.fail = api.GrowattError("timeout")
    calls = []
    orig = portal.read_api_token

    async def counting():
        calls.append(clock.now)
        return await orig()

    portal.read_api_token = counting
    ctrl, _ = make("T1", portal, FakeApi(good=("T2",)), clock)
    for _ in range(12):  # one hour of 5-minute polls
        with pytest.raises(api.GrowattError):
            await ctrl.fetch()
        clock.now += 300
    assert calls == [1000.0, 1300.0, 1900.0, 3100.0]


async def test_success_resets_backoff():
    clock = Clock()
    portal, fake_api = FakePortal(token="T2"), FakeApi(good=("T2",))
    portal.fail = api.GrowattError("timeout")
    ctrl, _ = make("T1", portal, fake_api, clock)
    with pytest.raises(api.GrowattError):
        await ctrl.fetch()
    clock.now += 300
    portal.fail = None
    await ctrl.fetch()  # recovered with T2
    fake_api.good = {"T3"}
    portal.token = "T3"
    portal.fail = api.GrowattError("timeout")
    with pytest.raises(api.GrowattError):
        await ctrl.fetch()
    clock.now += 300  # first delay again, not 600
    portal.fail = None
    await ctrl.fetch()
    assert ctrl.token == "T3"


async def test_disturbance_while_checking_new_token_keeps_it():
    portal, fake_api = FakePortal(token="T2"), FakeApi(good=("T2",))
    ctrl, saved = make("T1", portal, fake_api)
    real_plants = fake_api.plants

    async def flaky(token):
        raise api.GrowattError("[10012] rate limit")

    fake_api.plants = flaky
    with pytest.raises(api.GrowattError):
        await ctrl.fetch()
    assert ctrl.token == "T2" and saved == ["T2"] and portal.resets == 0
    fake_api.plants = real_plants
    assert (await ctrl.fetch()).status["SOC"] == 58


async def test_restart_with_dead_own_token_generates_at_most_once():
    portal, fake_api = FakePortal(token="G1"), FakeApi(good=())
    portal.new_tokens = iter(["G2", "G3"])
    ctrl, _ = make("G1", portal, fake_api)  # fresh controller after a restart
    for _ in range(5):
        await ctrl.fetch()
    assert portal.resets == 1


async def test_settings_read_with_first_poll_then_every_60_minutes_by_default():
    clock = Clock()
    api_ = FakeApi()
    ctrl, _ = make(api_=api_, clock=clock)
    data = await ctrl.fetch()
    assert data.settings == {"chargePowerCommand": 20, "acChargeEnable": 0}
    assert data.api["soc"] == LAST["soc"]
    clock.now += 300
    data = await ctrl.fetch()
    assert len(api_.info_calls) == 1
    assert data.settings["chargePowerCommand"] == 20  # cached values stay
    clock.now += 3299
    await ctrl.fetch()
    assert len(api_.info_calls) == 1
    clock.now += 1
    await ctrl.fetch()
    assert len(api_.info_calls) == 2


async def test_settings_interval_from_options():
    clock = Clock()
    api_ = FakeApi()
    ctrl, _ = make(api_=api_, clock=clock, settings_interval=1800)
    await ctrl.fetch()
    clock.now += 1799
    await ctrl.fetch()
    assert len(api_.info_calls) == 1
    clock.now += 1
    await ctrl.fetch()
    assert len(api_.info_calls) == 2


async def test_write_rereads_settings_but_not_within_5_minutes():
    clock = Clock()
    api_ = FakeApi()
    ctrl, _ = make(api_=api_, clock=clock)
    await ctrl.fetch()
    await ctrl.write("pv_on_off", ["0001"])
    assert api_.writes == [("T1", DEVICE.serial, "pv_on_off", ["0001"])]
    clock.now += 100
    await ctrl.fetch()
    assert len(api_.info_calls) == 1  # rate limit: not yet
    clock.now += 200
    await ctrl.fetch()
    assert len(api_.info_calls) == 2


async def test_failed_settings_read_keeps_poll_and_last_values():
    clock = Clock()
    api_ = FakeApi()
    ctrl, _ = make(api_=api_, clock=clock)
    await ctrl.fetch()
    api_.info_fail = api.GrowattError("10012")
    clock.now += 3600
    data = await ctrl.fetch()
    assert data.settings["chargePowerCommand"] == 20


async def test_write_needs_api_mode():
    ctrl, _ = make(token=None, portal=FakePortal(token=""), api_=FakeApi(good=()))
    with pytest.raises(api.GrowattError):
        await ctrl.write("pv_on_off", ["0001"])
