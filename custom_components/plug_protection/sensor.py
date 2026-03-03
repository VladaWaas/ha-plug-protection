"""Protection status sensor for Plug Protection."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ProtectionManager
from .const import (
    ATTR_COOLDOWN_REMAINING,
    ATTR_COOLDOWN_TOTAL,
    ATTR_CURRENT_POWER,
    ATTR_ORIGINAL_ENTITY,
    ATTR_POWER_THRESHOLD,
    CONF_PLUG_ENTITY,
    DOMAIN,
    STATE_ACTIVE,
    STATE_COOLDOWN,
    STATE_IDLE,
)

_LOGGER = logging.getLogger(__name__)

ICON_MAP = {
    STATE_ACTIVE: "mdi:shield-lock",
    STATE_COOLDOWN: "mdi:timer-sand",
    STATE_IDLE: "mdi:shield-off-outline",
}

TRANSLATION_MAP = {
    STATE_ACTIVE: "Active",
    STATE_COOLDOWN: "Cooldown",
    STATE_IDLE: "Idle",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the protection status sensor from a config entry."""
    manager: ProtectionManager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ProtectionStatusSensor(manager, entry)])


class ProtectionStatusSensor(SensorEntity):
    """Sensor showing the protection state of a plug."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, manager: ProtectionManager, entry: ConfigEntry
    ) -> None:
        self._manager = manager
        self._entry = entry

        self._attr_unique_id = f"{entry.entry_id}_protection_status"
        self._attr_name = "Protection status"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
        }

    async def async_added_to_hass(self) -> None:
        """Register update callback."""
        self._manager.async_add_update_callback(self._on_manager_update)

    async def async_will_remove_from_hass(self) -> None:
        """Clean up callback."""
        self._manager.async_remove_update_callback(self._on_manager_update)

    @callback
    def _on_manager_update(self) -> None:
        """Handle manager state update."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        """Return the protection state."""
        return TRANSLATION_MAP.get(
            self._manager.protection_state, self._manager.protection_state
        )

    @property
    def icon(self) -> str:
        """Return icon based on state."""
        return ICON_MAP.get(
            self._manager.protection_state, "mdi:shield-outline"
        )

    @property
    def extra_state_attributes(self) -> dict:
        """Expose details as attributes."""
        return {
            ATTR_ORIGINAL_ENTITY: self._entry.data[CONF_PLUG_ENTITY],
            ATTR_CURRENT_POWER: round(self._manager.current_power, 1),
            ATTR_POWER_THRESHOLD: self._manager.power_threshold,
            ATTR_COOLDOWN_TOTAL: self._manager.cooldown_seconds,
            ATTR_COOLDOWN_REMAINING: self._manager.cooldown_remaining,
        }
