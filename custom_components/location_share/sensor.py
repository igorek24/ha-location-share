"""Sensors: active shares, plus per-person distance and ETA home."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, UPDATE_SIGNAL


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    from . import _tracked_entities  # local import avoids a cycle at load time

    entities: list[SensorEntity] = [ActiveSharesSensor(hass, entry)]
    for entity_id in _tracked_entities(hass, entry):
        entities.append(DistanceHomeSensor(hass, entry, entity_id))
        entities.append(EtaHomeSensor(hass, entry, entity_id))
    async_add_entities(entities)


class LocationShareEntity(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, UPDATE_SIGNAL, self._updated)
        )

    @callback
    def _updated(self) -> None:
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Location Share",
            manufacturer="Home Assistant",
            entry_type="service",
        )


class ActiveSharesSensor(LocationShareEntity):
    _attr_name = "Active shares"
    _attr_icon = "mdi:link-variant"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_active_shares"

    @property
    def native_value(self) -> int:
        manager = self.hass.data.get(DOMAIN, {}).get("manager")
        return len(manager.active) if manager else 0

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("manager")
        if not manager:
            return {}
        return {
            "shares": [
                {
                    "label": s.label,
                    "entity_id": s.entity_id,
                    "expires_in_minutes": round(s.seconds_remaining / 60),
                    "precision": s.precision,
                    "views": s.views,
                    "last_viewed": s.last_viewed,
                }
                for s in manager.active
            ]
        }


class TrackedEntitySensor(LocationShareEntity):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, entity_id: str) -> None:
        super().__init__(hass, entry)
        self._tracked = entity_id
        state = hass.states.get(entity_id)
        self._person_name = state.name if state else entity_id.split(".")[-1]

    @property
    def _live(self) -> dict:
        return self.hass.data.get(DOMAIN, {}).get("live", {}).get(self._tracked, {})

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry.entry_id}_{self._tracked}")},
            via_device=(DOMAIN, self._entry.entry_id),
            name=self._person_name,
            manufacturer="Home Assistant",
            model="Tracked person",
        )


class DistanceHomeSensor(TrackedEntitySensor):
    _attr_name = "Distance home"
    _attr_icon = "mdi:map-marker-distance"
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, hass, entry, entity_id: str) -> None:
        super().__init__(hass, entry, entity_id)
        self._attr_unique_id = f"{entry.entry_id}_{entity_id}_distance_home"

    @property
    def native_value(self) -> float | None:
        metres = self._live.get("distance_home_m")
        return None if metres is None else round(metres / 1000, 2)

    @property
    def extra_state_attributes(self) -> dict:
        live = self._live
        return {
            "zone": live.get("zone"),
            "speed_kmh": live.get("speed_kmh"),
            "heading": live.get("heading"),
            "source": self._tracked,
        }


class EtaHomeSensor(TrackedEntitySensor):
    _attr_name = "ETA home"
    _attr_icon = "mdi:home-clock"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass, entry, entity_id: str) -> None:
        super().__init__(hass, entry, entity_id)
        self._attr_unique_id = f"{entry.entry_id}_{entity_id}_eta_home"

    @property
    def native_value(self) -> int | None:
        seconds = self._live.get("eta_seconds")
        return None if seconds is None else max(0, round(seconds / 60))

    @property
    def extra_state_attributes(self) -> dict:
        live = self._live
        return {
            "eta_text": live.get("eta_text"),
            "distance_km": (
                round(live["distance_home_m"] / 1000, 2)
                if live.get("distance_home_m") is not None
                else None
            ),
            "moving": (live.get("speed_kmh") or 0) > 2,
            "source": self._tracked,
        }
