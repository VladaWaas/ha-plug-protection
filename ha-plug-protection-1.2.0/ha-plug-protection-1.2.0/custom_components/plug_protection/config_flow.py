"""Config flow for Plug Protection."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONF_COOLDOWN_SECONDS,
    CONF_ENABLE_NOTIFICATION,
    CONF_PLUG_ENTITY,
    CONF_PLUG_REGISTRY_ID,
    CONF_POWER_REGISTRY_ID,
    CONF_POWER_SENSOR,
    CONF_POWER_THRESHOLD,
    CONF_RAISE_ON_BLOCK,
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_ENABLE_NOTIFICATION,
    DEFAULT_POWER_THRESHOLD,
    DEFAULT_RAISE_ON_BLOCK,
    DOMAIN,
)
from .manager import resolve_entity_id

_LOGGER = logging.getLogger(__name__)

_THRESHOLD_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0.1,
        max=3600,
        step=0.1,
        unit_of_measurement="W",
        mode=selector.NumberSelectorMode.BOX,
    )
)
_COOLDOWN_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0,
        max=7200,
        step=1,
        unit_of_measurement="s",
        mode=selector.NumberSelectorMode.BOX,
    )
)


def _registry_id(hass: HomeAssistant, entity_id: str) -> str | None:
    """Entity registry ID (UUID) for an entity, None if it has no registry entry."""
    entry = er.async_get(hass).async_get(entity_id)
    return entry.id if entry else None


def _entity_schema(defaults: dict[str, Any] | None = None) -> dict:
    """Plug + power sensor selectors (shared by setup and reconfigure)."""
    defaults = defaults or {}
    return {
        vol.Required(
            CONF_PLUG_ENTITY, default=defaults.get(CONF_PLUG_ENTITY, vol.UNDEFINED)
        ): selector.EntitySelector(selector.EntitySelectorConfig(domain="switch")),
        vol.Required(
            CONF_POWER_SENSOR, default=defaults.get(CONF_POWER_SENSOR, vol.UNDEFINED)
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor", device_class="power")
        ),
    }


def _settings_schema(current: dict[str, Any] | None = None) -> dict:
    """Threshold, cooldown and behaviour toggles (setup and options)."""
    current = current or {}
    return {
        vol.Required(
            CONF_POWER_THRESHOLD,
            default=current.get(CONF_POWER_THRESHOLD, DEFAULT_POWER_THRESHOLD),
        ): _THRESHOLD_SELECTOR,
        vol.Required(
            CONF_COOLDOWN_SECONDS,
            default=current.get(CONF_COOLDOWN_SECONDS, DEFAULT_COOLDOWN_SECONDS),
        ): _COOLDOWN_SELECTOR,
        vol.Required(
            CONF_ENABLE_NOTIFICATION,
            default=current.get(CONF_ENABLE_NOTIFICATION, DEFAULT_ENABLE_NOTIFICATION),
        ): selector.BooleanSelector(),
        vol.Required(
            CONF_RAISE_ON_BLOCK,
            default=current.get(CONF_RAISE_ON_BLOCK, DEFAULT_RAISE_ON_BLOCK),
        ): selector.BooleanSelector(),
    }


class PlugProtectionConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Plug Protection."""

    VERSION = 1
    MINOR_VERSION = 2

    def _plug_in_use(self, plug_id: str, exclude_entry_id: str | None = None) -> bool:
        for entry in self._async_current_entries():
            if entry.entry_id == exclude_entry_id:
                continue
            if plug_id in (
                entry.unique_id,
                entry.data.get(CONF_PLUG_REGISTRY_ID),
                entry.data.get(CONF_PLUG_ENTITY),
            ):
                return True
        return False

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Initial step – select plug, power sensor and settings."""
        errors: dict[str, str] = {}

        if user_input is not None:
            plug = user_input[CONF_PLUG_ENTITY]
            sensor = user_input[CONF_POWER_SENSOR]
            plug_reg_id = _registry_id(self.hass, plug)

            if self._plug_in_use(plug_reg_id or plug):
                return self.async_abort(reason="already_configured")

            await self.async_set_unique_id(plug_reg_id or plug)
            self._abort_if_unique_id_configured()

            state = self.hass.states.get(plug)
            title = (state.attributes.get("friendly_name") if state else None) or plug

            return self.async_create_entry(
                title=title,
                data={
                    **user_input,
                    CONF_PLUG_REGISTRY_ID: plug_reg_id,
                    CONF_POWER_REGISTRY_ID: _registry_id(self.hass, sensor),
                },
            )

        schema = vol.Schema({**_entity_schema(), **_settings_schema()})
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the protected plug or its power sensor."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            plug = user_input[CONF_PLUG_ENTITY]
            sensor = user_input[CONF_POWER_SENSOR]
            plug_reg_id = _registry_id(self.hass, plug)

            if self._plug_in_use(plug_reg_id or plug, entry.entry_id):
                errors["base"] = "already_configured"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=plug_reg_id or plug,
                    data_updates={
                        CONF_PLUG_ENTITY: plug,
                        CONF_POWER_SENSOR: sensor,
                        CONF_PLUG_REGISTRY_ID: plug_reg_id,
                        CONF_POWER_REGISTRY_ID: _registry_id(self.hass, sensor),
                    },
                )

        # Show the *current* entity ids (they may have been renamed)
        current = {
            CONF_PLUG_ENTITY: resolve_entity_id(
                self.hass,
                entry.data.get(CONF_PLUG_REGISTRY_ID),
                entry.data[CONF_PLUG_ENTITY],
            ),
            CONF_POWER_SENSOR: resolve_entity_id(
                self.hass,
                entry.data.get(CONF_POWER_REGISTRY_ID),
                entry.data[CONF_POWER_SENSOR],
            ),
        }
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(_entity_schema(current)),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow handler."""
        return PlugProtectionOptionsFlow()


class PlugProtectionOptionsFlow(OptionsFlow):
    """Edit threshold, cooldown and behaviour after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(_settings_schema(current))
        )
