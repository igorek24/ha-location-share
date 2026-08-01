"""Storage and lifecycle for location shares.

A share is a revocable, expiring capability: whoever holds the token can
see one entity's position until it expires. Tokens are the only secret,
so they are long and random, expiry is enforced on every read, and every
view is recorded so you can see if a link was used.
"""

from __future__ import annotations

import datetime as dt
import logging
import secrets
from dataclasses import asdict, dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "location_share.shares"
STORAGE_VERSION = 1

TOKEN_BYTES = 32          # ~43 url-safe characters
PRECISION_EXACT = "exact"
PRECISION_APPROXIMATE = "approximate"
APPROXIMATE_METERS = 500


@dataclass
class Share:
    token: str
    entity_id: str
    label: str
    created: str
    expires: str
    precision: str = PRECISION_EXACT
    views: int = 0
    last_viewed: str | None = None

    @property
    def expires_at(self) -> dt.datetime:
        return dt_util.parse_datetime(self.expires) or dt_util.utcnow()

    @property
    def is_expired(self) -> bool:
        return dt_util.utcnow() >= self.expires_at

    @property
    def seconds_remaining(self) -> int:
        return max(0, int((self.expires_at - dt_util.utcnow()).total_seconds()))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ShareManager:
    """Owns the set of active shares and persists them."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._shares: dict[str, Share] = {}
        self._listeners: list = []

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        for raw in data.get("shares", []):
            try:
                share = Share(**raw)
            except TypeError:
                continue
            if not share.is_expired:
                self._shares[share.token] = share
        _LOGGER.debug("Loaded %d active share(s)", len(self._shares))

    async def _async_save(self) -> None:
        await self._store.async_save(
            {"shares": [s.as_dict() for s in self._shares.values()]}
        )
        self._notify()

    def add_listener(self, callback) -> None:
        self._listeners.append(callback)

    def _notify(self) -> None:
        for callback in list(self._listeners):
            try:
                callback()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Share listener failed")

    # -- lifecycle ----------------------------------------------------------

    async def async_create(
        self,
        entity_id: str,
        minutes: int,
        label: str | None = None,
        precision: str = PRECISION_EXACT,
    ) -> Share:
        now = dt_util.utcnow()
        share = Share(
            token=secrets.token_urlsafe(TOKEN_BYTES),
            entity_id=entity_id,
            label=label or entity_id,
            created=now.isoformat(),
            expires=(now + dt.timedelta(minutes=minutes)).isoformat(),
            precision=precision,
        )
        self._shares[share.token] = share
        await self._async_save()
        _LOGGER.info(
            "Created location share for %s, valid %d minute(s)", entity_id, minutes
        )
        return share

    async def async_revoke(self, token: str) -> bool:
        if self._shares.pop(token, None) is None:
            return False
        await self._async_save()
        _LOGGER.info("Revoked a location share")
        return True

    async def async_revoke_entity(self, entity_id: str) -> int:
        tokens = [t for t, s in self._shares.items() if s.entity_id == entity_id]
        for token in tokens:
            self._shares.pop(token, None)
        if tokens:
            await self._async_save()
        return len(tokens)

    async def async_revoke_all(self) -> int:
        count = len(self._shares)
        self._shares.clear()
        await self._async_save()
        return count

    async def async_purge_expired(self) -> int:
        expired = [t for t, s in self._shares.items() if s.is_expired]
        for token in expired:
            self._shares.pop(token, None)
        if expired:
            await self._async_save()
        return len(expired)

    # -- reads --------------------------------------------------------------

    def get(self, token: str) -> Share | None:
        share = self._shares.get(token)
        if share is None or share.is_expired:
            return None
        return share

    @property
    def active(self) -> list[Share]:
        return [s for s in self._shares.values() if not s.is_expired]

    async def async_record_view(self, token: str) -> None:
        share = self._shares.get(token)
        if share is None:
            return
        share.views += 1
        share.last_viewed = dt_util.utcnow().isoformat()
        await self._async_save()
