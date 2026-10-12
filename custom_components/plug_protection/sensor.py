"""Sensor entities for Plug Protection."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PlugProtectionConfigEntry
from .const import (
    ATTR_COOLDOWN_TOTAL,
    ATTR_CURRENT_POWER,
    ATTR_LAST_BLOCK_TIME,
    ATTR_ORIGINAL_ENTITY,
    ATTR_POWER_SENSOR,
    ATTR_POWER_THRESHOLD,
    PROTECTION_STATES,
)
from .entity import ProtectionEntity
from .manager import ProtectionManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PlugProtectionConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors from a config entry."""
    manager = entry.runtime_data
    async_add_entities([ProtectionStatusSensor(manager), CooldownEndSensor(manager)])


class ProtectionStatusSensor(ProtectionEntity, SensorEntity):
    """Sensor showing the protection state of a plug."""

    _attr_translation_key = "protection_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = PROTECTION_STATES
    _unrecorded_attributes = frozenset({ATTR_CURRENT_POWER, ATTR_LAST_BLOCK_TIME})

    def __init__(self, manager: ProtectionManager) -> None:
        super().__init__(manager, "protection_status")

    @property
    def available(self) -> bool:
        """Unavailable while the original plug is unavailable."""
        return self._manager.plug_available

    @property
    def native_value(self) -> str:
        """Return the protection state (active/cooldown/idle/disabled)."""
        return self._manager.protection_state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose details as attributes."""
        m = self._manager
        attrs: dict[str, Any] = {
            ATTR_ORIGINAL_ENTITY: m.plug_entity,
            ATTR_POWER_SENSOR: m.power_sensor,
            ATTR_CURRENT_POWER: (
                round(m.current_power, 1) if m.current_power is not None else None
            ),
            ATTR_POWER_THRESHOLD: m.power_threshold,
            ATTR_COOLDOWN_TOTAL: m.cooldown_seconds,
        }
        if m.last_block_time:
            attrs[ATTR_LAST_BLOCK_TIME] = m.last_block_time.isoformat()
        return attrs


class CooldownEndSensor(ProtectionEntity, SensorEntity):
    """Timestamp at which the running cooldown ends."""

    _attr_translation_key = "cooldown_end"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, manager: ProtectionManager) -> None:
        super().__init__(manager, "cooldown_end")

    @property
    def native_value(self) -> datetime | None:
        """End of the cooldown, or unknown if none is running."""
        return self._manager.cooldown_end
