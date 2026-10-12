"""Switch entities for Plug Protection."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PlugProtectionConfigEntry
from .const import (
    ATTR_COOLDOWN_END,
    ATTR_COOLDOWN_TOTAL,
    ATTR_CURRENT_POWER,
    ATTR_ENABLED,
    ATTR_LAST_BLOCK_TIME,
    ATTR_ORIGINAL_ENTITY,
    ATTR_POWER_THRESHOLD,
    ATTR_PROTECTED,
    ATTR_PROTECTION_STATE,
    DOMAIN,
    SERVICE_FORCE_OFF,
    SERVICE_RESET_COOLDOWN,
)
from .entity import ProtectionEntity
from .manager import ProtectionManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PlugProtectionConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switch entities from a config entry."""
    manager = entry.runtime_data
    async_add_entities([ProtectedPlugSwitch(manager), ProtectionEnabledSwitch(manager)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(SERVICE_FORCE_OFF, None, "async_force_off")
    platform.async_register_entity_service(
        SERVICE_RESET_COOLDOWN, None, "async_reset_cooldown"
    )


class ProtectedPlugSwitch(ProtectionEntity, SwitchEntity):
    """Switch that wraps the original plug with protection logic."""

    _attr_translation_key = "protected_switch"
    _unrecorded_attributes = frozenset(
        {ATTR_CURRENT_POWER, ATTR_COOLDOWN_END, ATTR_LAST_BLOCK_TIME}
    )

    def __init__(self, manager: ProtectionManager) -> None:
        super().__init__(manager, "protected_switch")

    @property
    def is_on(self) -> bool | None:
        """Return true if the original plug is on."""
        state = self.hass.states.get(self._manager.plug_entity)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        return state.state == STATE_ON

    @property
    def available(self) -> bool:
        """Available while the original plug is available."""
        return self._manager.plug_available

    @property
    def icon(self) -> str:
        """Icon based on protection state."""
        if self._manager.is_protected:
            return "mdi:power-plug-battery"
        if self.is_on:
            return "mdi:power-plug"
        return "mdi:power-plug-off"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on – always allowed."""
        await self.hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": self._manager.plug_entity},
            blocking=True,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off – blocked while protection is active."""
        if self._manager.is_protected:
            self._manager.async_register_block("protected_switch")
            if self._manager.raise_on_block:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="turn_off_blocked",
                    translation_placeholders={"name": self._manager.plug_name},
                )
            return

        await self.hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": self._manager.plug_entity},
            blocking=True,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose protection details as attributes."""
        m = self._manager
        attrs: dict[str, Any] = {
            ATTR_ORIGINAL_ENTITY: m.plug_entity,
            ATTR_PROTECTED: m.is_protected,
            ATTR_ENABLED: m.enabled,
            ATTR_PROTECTION_STATE: m.protection_state,
            ATTR_CURRENT_POWER: (
                round(m.current_power, 1) if m.current_power is not None else None
            ),
            ATTR_POWER_THRESHOLD: m.power_threshold,
            ATTR_COOLDOWN_TOTAL: m.cooldown_seconds,
        }
        if m.cooldown_end:
            attrs[ATTR_COOLDOWN_END] = m.cooldown_end.isoformat()
        if m.last_block_time:
            attrs[ATTR_LAST_BLOCK_TIME] = m.last_block_time.isoformat()
        return attrs


class ProtectionEnabledSwitch(ProtectionEntity, SwitchEntity):
    """Switch that turns the protection of this plug on or off."""

    _attr_translation_key = "protection_enabled"

    def __init__(self, manager: ProtectionManager) -> None:
        super().__init__(manager, "protection_enabled")

    @property
    def is_on(self) -> bool:
        """True while protection is enabled."""
        return self._manager.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable protection."""
        await self._manager.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable protection."""
        await self._manager.async_set_enabled(False)
