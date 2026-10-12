"""Config flow for Plug Protection integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_COOLDOWN_SECONDS,
    CONF_ENABLE_NOTIFICATION,
    CONF_PLUG_ENTITY,
    CONF_POWER_SENSOR,
    CONF_POWER_THRESHOLD,
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_ENABLE_NOTIFICATION,
    DEFAULT_POWER_THRESHOLD,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Config Flow (initial setup)
# ─────────────────────────────────────────────────────────────

class PlugProtectionConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Plug Protection."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step – select plug and power sensor."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate: plug and sensor must be different entities
            if user_input[CONF_PLUG_ENTITY] == user_input[CONF_POWER_SENSOR]:
                errors["base"] = "same_entity"
            else:
                # Check for duplicate entries (same plug)
                await self.async_set_unique_id(user_input[CONF_PLUG_ENTITY])
                self._abort_if_unique_id_configured()

                # Use friendly name for the entry title
                plug_state = self.hass.states.get(
                    user_input[CONF_PLUG_ENTITY]
                )
                title = (
                    plug_state.attributes.get("friendly_name")
                    if plug_state
                    else user_input[CONF_PLUG_ENTITY]
                )

                return self.async_create_entry(
                    title=f"Protection: {title}",
                    data=user_input,
                )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_PLUG_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
                vol.Required(CONF_POWER_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        device_class="power",
                    )
                ),
                vol.Required(
                    CONF_POWER_THRESHOLD,
                    default=DEFAULT_POWER_THRESHOLD,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=3600,
                        step=1,
                        unit_of_measurement="W",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_COOLDOWN_SECONDS,
                    default=DEFAULT_COOLDOWN_SECONDS,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=3600,
                        step=30,
                        unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
                vol.Required(
                    CONF_ENABLE_NOTIFICATION,
                    default=DEFAULT_ENABLE_NOTIFICATION,
                ): selector.BooleanSelector(),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlow:
        """Get the options flow handler."""
        return PlugProtectionOptionsFlow(config_entry)


# ─────────────────────────────────────────────────────────────
# Options Flow (edit settings after setup)
# ─────────────────────────────────────────────────────────────

class PlugProtectionOptionsFlow(OptionsFlow):
    """Handle options flow – edit threshold, cooldown, notifications."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {
            **self._config_entry.data,
            **self._config_entry.options,
        }

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_POWER_THRESHOLD,
                    default=current.get(
                        CONF_POWER_THRESHOLD, DEFAULT_POWER_THRESHOLD
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=3600,
                        step=1,
                        unit_of_measurement="W",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_COOLDOWN_SECONDS,
                    default=current.get(
                        CONF_COOLDOWN_SECONDS, DEFAULT_COOLDOWN_SECONDS
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=3600,
                        step=30,
                        unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
                vol.Required(
                    CONF_ENABLE_NOTIFICATION,
                    default=current.get(
                        CONF_ENABLE_NOTIFICATION,
                        DEFAULT_ENABLE_NOTIFICATION,
                    ),
                ): selector.BooleanSelector(),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
        )
