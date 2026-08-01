"""Config flow for Location Share."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BASE_URL,
    CONF_DEFAULT_MINUTES,
    CONF_DEFAULT_SPEED_KMH,
    CONF_ENTITIES,
    CONF_HOME_ZONE,
    DEFAULT_HOME_ZONE,
    DEFAULT_MINUTES,
    DEFAULT_SPEED_KMH,
    DOMAIN,
    MAX_MINUTES,
    MIN_MINUTES,
)


def _schema(hass, defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_ENTITIES, default=defaults.get(CONF_ENTITIES, [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["person", "device_tracker"], multiple=True
                )
            ),
            vol.Optional(
                CONF_BASE_URL,
                description={"suggested_value": defaults.get(CONF_BASE_URL)},
            ): str,
            vol.Required(
                CONF_HOME_ZONE, default=defaults.get(CONF_HOME_ZONE, DEFAULT_HOME_ZONE)
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="zone")),
            vol.Required(
                CONF_DEFAULT_MINUTES,
                default=defaults.get(CONF_DEFAULT_MINUTES, DEFAULT_MINUTES),
            ): vol.All(vol.Coerce(int), vol.Range(min=MIN_MINUTES, max=MAX_MINUTES)),
            vol.Required(
                CONF_DEFAULT_SPEED_KMH,
                default=defaults.get(CONF_DEFAULT_SPEED_KMH, DEFAULT_SPEED_KMH),
            ): vol.All(vol.Coerce(int), vol.Range(min=5, max=200)),
        }
    )


class LocationShareConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(title="Location Share", data=user_input)
        suggested = {
            CONF_BASE_URL: self.hass.config.external_url
            or self.hass.config.internal_url
            or ""
        }
        return self.async_show_form(
            step_id="user", data_schema=_schema(self.hass, suggested)
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> LocationShareOptionsFlow:
        return LocationShareOptionsFlow()


class LocationShareOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        defaults = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init", data_schema=_schema(self.hass, defaults)
        )
