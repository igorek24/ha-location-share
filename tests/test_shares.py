"""Token lifecycle tests for ShareManager (storage stubbed out)."""

import asyncio, datetime as dt, importlib.util, sys, types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# stub the HA modules share_manager imports
ha = types.ModuleType("homeassistant"); sys.modules["homeassistant"] = ha
core = types.ModuleType("homeassistant.core"); core.HomeAssistant = object
sys.modules["homeassistant.core"] = core
storage = types.ModuleType("homeassistant.helpers.storage")
class _Store:
    def __init__(self, *a, **k): self.data = None
    async def async_load(self): return self.data
    async def async_save(self, data): self.data = data
storage.Store = _Store
helpers = types.ModuleType("homeassistant.helpers"); sys.modules["homeassistant.helpers"] = helpers
sys.modules["homeassistant.helpers.storage"] = storage
util = types.ModuleType("homeassistant.util"); sys.modules["homeassistant.util"] = util
dt_util = types.ModuleType("homeassistant.util.dt")
dt_util.utcnow = lambda: dt.datetime.now(dt.timezone.utc)
dt_util.parse_datetime = lambda s: dt.datetime.fromisoformat(s)
sys.modules["homeassistant.util.dt"] = dt_util

_spec = importlib.util.spec_from_file_location(
    "share_manager", ROOT / "custom_components" / "location_share" / "share_manager.py")
sm = importlib.util.module_from_spec(_spec); sys.modules[_spec.name] = sm
_spec.loader.exec_module(sm)


def _mgr():
    m = sm.ShareManager(hass=None)
    asyncio.run(m.async_load())
    return m


def test_create_returns_usable_token():
    m = _mgr()
    s = asyncio.run(m.async_create("person.igor", 60, "Igor"))
    assert len(s.token) >= 40                       # 256 bits, url-safe
    assert m.get(s.token) is s
    assert len(m.active) == 1
    assert 3500 < s.seconds_remaining <= 3600


def test_tokens_are_unique():
    m = _mgr()
    tokens = {asyncio.run(m.async_create("person.igor", 10)).token for _ in range(25)}
    assert len(tokens) == 25


def test_expired_share_is_invisible():
    m = _mgr()
    s = asyncio.run(m.async_create("person.igor", 60))
    s.expires = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)).isoformat()
    assert s.is_expired and s.seconds_remaining == 0
    assert m.get(s.token) is None
    assert m.active == []


def test_revoke_by_token_and_entity():
    m = _mgr()
    a = asyncio.run(m.async_create("person.igor", 60))
    b = asyncio.run(m.async_create("person.mia", 60))
    assert asyncio.run(m.async_revoke(a.token)) is True
    assert m.get(a.token) is None and m.get(b.token) is not None
    assert asyncio.run(m.async_revoke("nonexistent")) is False
    assert asyncio.run(m.async_revoke_entity("person.mia")) == 1
    assert m.active == []


def test_revoke_all_and_purge():
    m = _mgr()
    for _ in range(3):
        asyncio.run(m.async_create("person.igor", 60))
    old = asyncio.run(m.async_create("person.igor", 60))
    old.expires = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)).isoformat()
    assert asyncio.run(m.async_purge_expired()) == 1
    assert asyncio.run(m.async_revoke_all()) == 3
    assert m.active == []


def test_view_counting():
    m = _mgr()
    s = asyncio.run(m.async_create("person.igor", 60))
    assert s.views == 0 and s.last_viewed is None
    asyncio.run(m.async_record_view(s.token))
    asyncio.run(m.async_record_view(s.token))
    assert s.views == 2 and s.last_viewed is not None


def test_expired_shares_dropped_on_load():
    m = _mgr()
    live = asyncio.run(m.async_create("person.igor", 60))
    dead = asyncio.run(m.async_create("person.mia", 60))
    dead.expires = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)).isoformat()
    asyncio.run(m._async_save())

    reloaded = sm.ShareManager(hass=None)
    reloaded._store = m._store
    asyncio.run(reloaded.async_load())
    assert reloaded.get(live.token) is not None
    assert reloaded.get(dead.token) is None


def test_precision_defaults_to_exact():
    m = _mgr()
    s = asyncio.run(m.async_create("person.igor", 60))
    assert s.precision == sm.PRECISION_EXACT
    f = asyncio.run(m.async_create("person.igor", 60, precision=sm.PRECISION_APPROXIMATE))
    assert f.precision == sm.PRECISION_APPROXIMATE


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS {name}")
            except AssertionError as err:
                failures += 1; print(f"FAIL {name}: {err}")
    raise SystemExit(1 if failures else 0)
