"""Tests for distance / movement / ETA maths."""

import datetime as dt
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "locator", ROOT / "custom_components" / "location_share" / "locator.py"
)
loc = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = loc
_spec.loader.exec_module(loc)

T0 = dt.datetime(2026, 8, 1, 12, 0, 0)


def test_haversine_known_distance():
    # Los Angeles -> New York, ~3936 km
    d = loc.haversine(34.0522, -118.2437, 40.7128, -74.0060)
    assert 3_930_000 < d < 3_950_000
    assert loc.haversine(10, 20, 10, 20) == 0


def test_bearing_and_compass():
    assert 350 < loc.bearing(0, 0, 1, 0) or loc.bearing(0, 0, 1, 0) < 10   # north
    assert loc.compass(0) == "N"
    assert loc.compass(90) == "E"
    assert loc.compass(180) == "S"
    assert loc.compass(270) == "W"


def test_speed_from_two_fixes():
    t = loc.MovementTracker()
    t.update(52.0000, 4.0000, T0)
    # ~111 m north in 10 s -> ~11 m/s
    t.update(52.0010, 4.0000, T0 + dt.timedelta(seconds=10))
    assert 9 < t.speed_mps < 13
    assert t.is_moving is True


def test_ignores_implausible_jump():
    t = loc.MovementTracker()
    t.update(52.0, 4.0, T0)
    t.update(60.0, 20.0, T0 + dt.timedelta(seconds=5))    # teleport
    assert t.speed_mps is None


def test_stationary_gives_no_eta():
    t = loc.MovementTracker()
    t.update(52.0, 4.0, T0)
    t.update(52.000001, 4.000001, T0 + dt.timedelta(seconds=30))   # jitter
    assert t.is_moving is False
    assert t.eta_seconds(5000, now=T0 + dt.timedelta(seconds=30)) is None


def test_eta_uses_measured_speed():
    t = loc.MovementTracker()
    t.update(52.0000, 4.0000, T0)
    t.update(52.0010, 4.0000, T0 + dt.timedelta(seconds=10))       # ~11 m/s
    eta = t.eta_seconds(11_000, now=T0 + dt.timedelta(seconds=10))
    assert eta is not None
    assert 800 < eta < 1300                                        # ~16 min


def test_eta_zero_at_destination():
    t = loc.MovementTracker()
    t.update(52.0, 4.0, T0)
    assert t.eta_seconds(0) == 0


def test_stale_fix_gives_no_eta():
    t = loc.MovementTracker()
    t.update(52.0000, 4.0000, T0)
    t.update(52.0010, 4.0000, T0 + dt.timedelta(seconds=10))
    late = T0 + dt.timedelta(minutes=45)
    assert t.eta_seconds(10_000, now=late) is None


def test_describe_duration():
    assert loc.describe_duration(None) is None
    assert loc.describe_duration(30) == "less than a minute"
    assert loc.describe_duration(720) == "12 min"
    assert loc.describe_duration(3600) == "1 h"
    assert loc.describe_duration(3900) == "1 h 5 min"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS {name}")
            except AssertionError as err:
                failures += 1; print(f"FAIL {name}: {err}")
    raise SystemExit(1 if failures else 0)
