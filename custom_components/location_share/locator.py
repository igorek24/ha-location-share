"""Distance, movement and ETA maths.

Deliberately free of Home Assistant imports so it can be unit tested.

ETA is derived from the tracker's own movement rather than a routing
service: successive fixes give a speed, which is smoothed and used with
the remaining distance. That keeps the integration self-contained; if you
want road-accurate numbers, feed a Waze/Google travel-time sensor in
instead (see the README).
"""

from __future__ import annotations

import datetime as dt
import math
from collections import deque
from dataclasses import dataclass

EARTH_RADIUS_M = 6_371_000.0

# Movement below this is treated as GPS jitter, not travel.
MIN_SPEED_MPS = 0.7            # ~2.5 km/h
# Ignore absurd jumps (bad fixes, plane mode, teleporting GPS).
MAX_SPEED_MPS = 70.0           # ~250 km/h
DEFAULT_SPEED_MPS = 11.1       # ~40 km/h, a sane urban default
SPEED_SAMPLES = 5
# A fix older than this should not drive an ETA.
STALE_AFTER = dt.timedelta(minutes=15)


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing in degrees (0 = north)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_lambda = math.radians(lon2 - lon1)
    y = math.sin(d_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(
        d_lambda
    )
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def compass(degrees: float) -> str:
    points = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    ]
    return points[round(degrees / 22.5) % 16]


@dataclass
class Fix:
    latitude: float
    longitude: float
    when: dt.datetime


class MovementTracker:
    """Turns a stream of position fixes into speed, heading and ETA."""

    def __init__(self, default_speed_mps: float = DEFAULT_SPEED_MPS) -> None:
        self.default_speed_mps = default_speed_mps
        self._last: Fix | None = None
        self._speeds: deque[float] = deque(maxlen=SPEED_SAMPLES)
        self.heading: float | None = None

    def update(self, latitude: float, longitude: float, when: dt.datetime) -> None:
        fix = Fix(latitude, longitude, when)
        previous, self._last = self._last, fix
        if previous is None:
            return
        seconds = (when - previous.when).total_seconds()
        if seconds <= 0:
            return
        distance = haversine(
            previous.latitude, previous.longitude, latitude, longitude
        )
        speed = distance / seconds
        if speed > MAX_SPEED_MPS:
            return                       # implausible jump, ignore
        if speed >= MIN_SPEED_MPS:
            self._speeds.append(speed)
            self.heading = bearing(
                previous.latitude, previous.longitude, latitude, longitude
            )
        else:
            # standing still: decay towards a stop so a stale speed does not
            # keep producing an optimistic ETA
            self._speeds.append(0.0)

    @property
    def speed_mps(self) -> float | None:
        if not self._speeds:
            return None
        moving = [s for s in self._speeds if s > 0]
        if not moving:
            return 0.0
        return sum(moving) / len(moving)

    @property
    def is_moving(self) -> bool:
        speed = self.speed_mps
        return speed is not None and speed >= MIN_SPEED_MPS

    def eta_seconds(
        self,
        distance_m: float,
        now: dt.datetime | None = None,
    ) -> int | None:
        """Seconds to cover `distance_m` at the current pace."""
        if distance_m <= 0:
            return 0
        if self._last is None:
            return None
        if now is not None and now - self._last.when > STALE_AFTER:
            return None
        speed = self.speed_mps
        if not speed or speed < MIN_SPEED_MPS:
            if not self.is_moving:
                return None              # stationary: no meaningful ETA
            speed = self.default_speed_mps
        return int(distance_m / speed)


def describe_duration(seconds: int | None) -> str | None:
    """'12 min', '1 h 5 min' - for notifications."""
    if seconds is None:
        return None
    minutes = max(0, round(seconds / 60))
    if minutes < 1:
        return "less than a minute"
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h" if rest == 0 else f"{hours} h {rest} min"
