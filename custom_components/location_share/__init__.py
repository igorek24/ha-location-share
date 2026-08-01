"""Location Share - Find My style location sharing for Home Assistant."""

from __future__ import annotations

import logging
from datetime import timedelta

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_ENTITY,
    ATTR_INCLUDE_LINK,
    ATTR_LABEL,
    ATTR_MESSAGE,
    ATTR_MINUTES,
    ATTR_NOTIFY,
    ATTR_PRECISION,
    ATTR_TOKEN,
    CONF_BASE_URL,
    CONF_DEFAULT_MINUTES,
    CONF_DEFAULT_SPEED_KMH,
    CONF_HOME_ZONE,
    DEFAULT_HOME_ZONE,
    DEFAULT_MINUTES,
    DEFAULT_SPEED_KMH,
    DOMAIN,
    EVENT_SHARE_CREATED,
    MAX_MINUTES,
    MIN_MINUTES,
    SERVICE_CREATE_SHARE,
    SERVICE_ON_MY_WAY,
    SERVICE_REVOKE_ALL,
    SERVICE_REVOKE_SHARE,
    UPDATE_SIGNAL,
)
from .http import LocationShareDataView, LocationSharePageView
from .locator import MovementTracker, describe_duration, haversine
from .share_manager import PRECISION_APPROXIMATE, PRECISION_EXACT, ShareManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]
PURGE_INTERVAL = timedelta(minutes=15)

type LocationShareEntry = ConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: LocationShareEntry) -> bool:
    manager = ShareManager(hass)
    await manager.async_load()

    runtime = hass.data.setdefault(DOMAIN, {})
    runtime["manager"] = manager
    runtime["entry"] = entry
    runtime.setdefault("live", {})
    runtime.setdefault("trackers", {})

    hass.http.register_view(LocationSharePageView(hass, manager))
    hass.http.register_view(LocationShareDataView(hass, manager))

    tracked = _tracked_entities(hass, entry)
    default_speed = entry.options.get(
        CONF_DEFAULT_SPEED_KMH, entry.data.get(CONF_DEFAULT_SPEED_KMH, DEFAULT_SPEED_KMH)
    )
    for entity_id in tracked:
        runtime["trackers"].setdefault(
            entity_id, MovementTracker(default_speed_mps=default_speed / 3.6)
        )
        _refresh_entity(hass, entry, entity_id)

    @callback
    def _state_listener(event) -> None:
        """Runs on the event loop: HA requires that for dispatcher sends."""
        try:
            _refresh_entity(hass, entry, event.data["entity_id"])
            async_dispatcher_send(hass, UPDATE_SIGNAL)
        except Exception:  # noqa: BLE001 - never break the subscription
            _LOGGER.exception("Failed to refresh %s", event.data.get("entity_id"))

    if tracked:
        entry.async_on_unload(
            async_track_state_change_event(hass, tracked, _state_listener)
        )

    async def _purge(_now) -> None:
        removed = await manager.async_purge_expired()
        if removed:
            _LOGGER.debug("Purged %d expired share(s)", removed)
            async_dispatcher_send(hass, UPDATE_SIGNAL)

    entry.async_on_unload(async_track_time_interval(hass, _purge, PURGE_INTERVAL))
    @callback
    def _shares_changed() -> None:
        async_dispatcher_send(hass, UPDATE_SIGNAL)

    manager.add_listener(_shares_changed)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LocationShareEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return unloaded


async def _update_listener(hass: HomeAssistant, entry: LocationShareEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _tracked_entities(hass: HomeAssistant, entry: LocationShareEntry) -> list[str]:
    configured = entry.options.get("entities", entry.data.get("entities"))
    if configured:
        return list(configured)
    return [s.entity_id for s in hass.states.async_all("person")]


def _home_coordinates(hass: HomeAssistant, entry: LocationShareEntry):
    zone_id = entry.options.get(
        CONF_HOME_ZONE, entry.data.get(CONF_HOME_ZONE, DEFAULT_HOME_ZONE)
    )
    zone = hass.states.get(zone_id)
    if zone and zone.attributes.get("latitude") is not None:
        return zone.attributes["latitude"], zone.attributes["longitude"]
    return hass.config.latitude, hass.config.longitude


def _refresh_entity(hass: HomeAssistant, entry: LocationShareEntry, entity_id: str) -> None:
    """Recompute distance/speed/ETA for one tracked entity."""
    state = hass.states.get(entity_id)
    if state is None:
        return
    latitude = state.attributes.get("latitude")
    longitude = state.attributes.get("longitude")
    runtime = hass.data.setdefault(DOMAIN, {})
    live = runtime.setdefault("live", {})
    trackers = runtime.setdefault("trackers", {})

    if latitude is None or longitude is None:
        live[entity_id] = {"zone": state.state}
        return

    default_speed = entry.options.get(
        CONF_DEFAULT_SPEED_KMH, entry.data.get(CONF_DEFAULT_SPEED_KMH, DEFAULT_SPEED_KMH)
    )
    tracker = trackers.setdefault(
        entity_id, MovementTracker(default_speed_mps=default_speed / 3.6)
    )
    tracker.update(latitude, longitude, state.last_updated or dt_util.utcnow())

    home_lat, home_lon = _home_coordinates(hass, entry)
    distance = haversine(latitude, longitude, home_lat, home_lon)
    eta = tracker.eta_seconds(distance, now=dt_util.utcnow())
    speed = tracker.speed_mps

    live[entity_id] = {
        "zone": state.state,
        "latitude": latitude,
        "longitude": longitude,
        "distance_home_m": round(distance),
        "eta_seconds": eta,
        "eta_text": describe_duration(eta),
        "speed_kmh": round(speed * 3.6, 1) if speed is not None else None,
        "heading": tracker.heading,
        "battery": state.attributes.get("battery_level"),
        "updated": (state.last_updated or dt_util.utcnow()).isoformat(),
    }


def _share_url(hass: HomeAssistant, entry: LocationShareEntry, token: str) -> str:
    base = entry.options.get(CONF_BASE_URL, entry.data.get(CONF_BASE_URL)) or ""
    if not base:
        base = hass.config.external_url or hass.config.internal_url or ""
    return f"{base.rstrip('/')}/api/location_share/{token}"


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_CREATE_SHARE):
        return

    def _runtime():
        return hass.data[DOMAIN]

    async def create_share(call: ServiceCall) -> ServiceResponse:
        runtime = _runtime()
        entry = runtime["entry"]
        entity_id = call.data[ATTR_ENTITY]
        minutes = call.data.get(
            ATTR_MINUTES,
            entry.options.get(CONF_DEFAULT_MINUTES, DEFAULT_MINUTES),
        )
        label = call.data.get(ATTR_LABEL)
        if not label:
            state = hass.states.get(entity_id)
            label = (state.name if state else entity_id)
        share = await runtime["manager"].async_create(
            entity_id,
            minutes,
            label,
            call.data.get(ATTR_PRECISION, PRECISION_EXACT),
        )
        url = _share_url(hass, entry, share.token)
        hass.bus.async_fire(
            EVENT_SHARE_CREATED,
            {"entity_id": entity_id, "url": url, "minutes": minutes, "label": label},
        )
        if target := call.data.get(ATTR_NOTIFY):
            await _notify(hass, target, call.data.get(ATTR_MESSAGE) or
                          f"{label} is sharing their location for {minutes} minutes: {url}")
        return {"url": url, "token": share.token, "expires": share.expires}

    async def revoke_share(call: ServiceCall) -> None:
        runtime = _runtime()
        if token := call.data.get(ATTR_TOKEN):
            await runtime["manager"].async_revoke(token)
        elif entity_id := call.data.get(ATTR_ENTITY):
            await runtime["manager"].async_revoke_entity(entity_id)

    async def revoke_all(call: ServiceCall) -> None:
        count = await _runtime()["manager"].async_revoke_all()
        _LOGGER.info("Revoked %d location share(s)", count)

    async def on_my_way(call: ServiceCall) -> ServiceResponse:
        runtime = _runtime()
        entry = runtime["entry"]
        entity_id = call.data[ATTR_ENTITY]
        _refresh_entity(hass, entry, entity_id)
        live = runtime["live"].get(entity_id, {})
        state = hass.states.get(entity_id)
        name = state.name if state else entity_id
        eta_text = live.get("eta_text")
        distance = live.get("distance_home_m")

        parts = [f"{name} is on the way home"]
        if eta_text:
            parts.append(f"about {eta_text} away")
        elif distance:
            parts.append(f"{round(distance / 1000, 1)} km away")
        message = call.data.get(ATTR_MESSAGE) or ", ".join(parts) + "."

        url = None
        if call.data.get(ATTR_INCLUDE_LINK, True):
            minutes = call.data.get(ATTR_MINUTES) or max(
                MIN_MINUTES, min(MAX_MINUTES, int((live.get("eta_seconds") or 1800) / 60) + 15)
            )
            share = await runtime["manager"].async_create(entity_id, minutes, name)
            url = _share_url(hass, entry, share.token)
            message = f"{message} {url}"

        if target := call.data.get(ATTR_NOTIFY):
            await _notify(hass, target, message)
        return {"message": message, "url": url, "eta": eta_text}

    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_SHARE,
        create_share,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ENTITY): cv.entity_id,
                vol.Optional(ATTR_MINUTES): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_MINUTES, max=MAX_MINUTES)
                ),
                vol.Optional(ATTR_LABEL): cv.string,
                vol.Optional(ATTR_PRECISION, default=PRECISION_EXACT): vol.In(
                    [PRECISION_EXACT, PRECISION_APPROXIMATE]
                ),
                vol.Optional(ATTR_NOTIFY): cv.string,
                vol.Optional(ATTR_MESSAGE): cv.string,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REVOKE_SHARE,
        revoke_share,
        schema=vol.Schema(
            {
                vol.Exclusive(ATTR_TOKEN, "which"): cv.string,
                vol.Exclusive(ATTR_ENTITY, "which"): cv.entity_id,
            }
        ),
    )
    hass.services.async_register(DOMAIN, SERVICE_REVOKE_ALL, revoke_all)
    hass.services.async_register(
        DOMAIN,
        SERVICE_ON_MY_WAY,
        on_my_way,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ENTITY): cv.entity_id,
                vol.Optional(ATTR_NOTIFY): cv.string,
                vol.Optional(ATTR_MESSAGE): cv.string,
                vol.Optional(ATTR_INCLUDE_LINK, default=True): cv.boolean,
                vol.Optional(ATTR_MINUTES): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_MINUTES, max=MAX_MINUTES)
                ),
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )


async def _notify(hass: HomeAssistant, target: str, message: str) -> None:
    service = target.split(".")[-1] if "." in target else target
    if not hass.services.has_service("notify", service):
        _LOGGER.warning("Notify service notify.%s not found", service)
        return
    await hass.services.async_call(
        "notify", service, {"message": message}, blocking=False
    )
