"""Protected switch entity for Plug Protection."""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ProtectionManager
from .const import (
    ATTR_COOLDOWN_REMAINING,
    ATTR_COOLDOWN_TOTAL,
    ATTR_CURRENT_POWER,
    ATTR_LAST_BLOCK_TIME,
    ATTR_ORIGINAL_ENTITY,
    ATTR_POWER_THRESHOLD,
    ATTR_PROTECTED,
    ATTR_PROTECTION_STATE,
    CONF_PLUG_ENTITY,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the protected switch from a config entry."""
    manager: ProtectionManager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ProtectedPlugSwitch(manager, entry)])


class ProtectedPlugSwitch(SwitchEntity):
    """Switch entity that wraps an original plug with protection logic."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, manager: ProtectionManager, entry: ConfigEntry
    ) -> None:
        self._manager = manager
        self._entry = entry
        self._plug_entity = entry.data[CONF_PLUG_ENTITY]

        self._attr_unique_id = f"{entry.entry_id}_protected_switch"
        self._attr_name = "Protected switch"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "Plug Protection",
            "model": "Protected Smart Plug",
            "sw_version": "1.0.0",
        }

    async def async_added_to_hass(self) -> None:
        """Register update callback when entity is added."""
        self._manager.async_add_update_callback(self._on_manager_update)

    async def async_will_remove_from_hass(self) -> None:
        """Clean up callback when entity is removed."""
        self._manager.async_remove_update_callback(self._on_manager_update)

    @callback
    def _on_manager_update(self) -> None:
        """Handle manager state update."""
        self.async_write_ha_state()

    # ── State ────────────────────────────────────────────────

    @property
    def is_on(self) -> bool | None:
        """Return true if the original plug is on."""
        state = self.hass.states.get(self._plug_entity)
        if state is None or state.state in (
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        ):
            return None
        return state.state == STATE_ON

    @property
    def available(self) -> bool:
        """Return True if the original plug is available."""
        state = self.hass.states.get(self._plug_entity)
        return state is not None and state.state not in (
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        )

    @property
    def icon(self) -> str:
        """Icon based on protection state."""
        if self._manager.is_protected:
            return "mdi:power-plug-battery"
        if self.is_on:
            return "mdi:power-plug"
        return "mdi:power-plug-off"

    # ── Actions ──────────────────────────────────────────────

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on – always allowed, pass through."""
        await self.hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": self._plug_entity},
            blocking=True,
        )

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off – blocked if protection is active."""
        if self._manager.is_protected:
            _LOGGER.warning(
                "Turn-off via protected switch blocked for %s "
                "(state: %s, power: %.1f W)",
                self._plug_entity,
                self._manager.protection_state,
                self._manager.current_power,
            )
            # Don't forward the command. Original plug stays on.
            # Show notification about the block.
            if self._manager.enable_notification:
                from homeassistant.components.persistent_notification import (
                    async_create as pn_create,
                )

                friendly = self._manager._get_friendly_name()
                pn_create(
                    self.hass,
                    (
                        f"Turn-off of **{friendly}** was blocked!\n\n"
                        f"Current power: {self._manager.current_power:.1f} W "
                        f"(threshold: {self._manager.power_threshold} W)\n\n"
                        f"Protection state: {self._manager.protection_state}"
                    ),
                    title="🛡️ Plug Protection",
                    notification_id=(
                        f"plug_protection_{self._entry.entry_id}"
                    ),
                )
            return

        await self.hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": self._plug_entity},
            blocking=True,
        )

    # ── Extra attributes ─────────────────────────────────────

    @property
    def extra_state_attributes(self) -> dict:
        """Expose protection details as attributes."""
        attrs = {
            ATTR_ORIGINAL_ENTITY: self._plug_entity,
            ATTR_PROTECTED: self._manager.is_protected,
            ATTR_PROTECTION_STATE: self._manager.protection_state,
            ATTR_CURRENT_POWER: round(self._manager.current_power, 1),
            ATTR_POWER_THRESHOLD: self._manager.power_threshold,
            ATTR_COOLDOWN_TOTAL: self._manager.cooldown_seconds,
            ATTR_COOLDOWN_REMAINING: self._manager.cooldown_remaining,
        }
        if self._manager.last_block_time:
            attrs[ATTR_LAST_BLOCK_TIME] = (
                self._manager.last_block_time.isoformat()
            )
        return attrs
