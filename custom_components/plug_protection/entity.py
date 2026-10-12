"""Base entity for Plug Protection."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.entity import Entity

from .manager import ProtectionManager


class ProtectionEntity(Entity):
    """Common behaviour of all Plug Protection entities."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: ProtectionManager, suffix: str) -> None:
        self._manager = manager
        self._attr_unique_id = f"{manager.entry.entry_id}_{suffix}"
        # Link to the device of the original plug (the pattern for helpers since
        # HA 2026.8: set `device_entry`, never return another integration's
        # identifiers from device_info). Plugs without a device get their own.
        if (source := manager.source_device) is not None:
            self.device_entry = source
        else:
            self._attr_device_info = manager.own_device_info

    async def async_added_to_hass(self) -> None:
        """Subscribe to manager updates."""
        self.async_on_remove(
            self._manager.async_add_update_callback(self._handle_manager_update)
        )

    @callback
    def _handle_manager_update(self) -> None:
        self.async_write_ha_state()

    # Entity services (registered on the switch platform) ------------------

    async def async_force_off(self) -> None:
        """Service plug_protection.force_off."""
        await self._manager.async_force_off()

    async def async_reset_cooldown(self) -> None:
        """Service plug_protection.reset_cooldown."""
        self._manager.async_reset_cooldown()
