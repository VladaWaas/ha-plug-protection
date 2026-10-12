"""Plug Protection – prevent smart plug turn-off while an appliance is running."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_PLUG_ENTITY,
    CONF_PLUG_REGISTRY_ID,
    CONF_POWER_REGISTRY_ID,
    CONF_POWER_SENSOR,
    PLATFORMS,
)
from .manager import ProtectionManager

_LOGGER = logging.getLogger(__name__)

type PlugProtectionConfigEntry = ConfigEntry[ProtectionManager]


async def async_setup_entry(
    hass: HomeAssistant, entry: PlugProtectionConfigEntry
) -> bool:
    """Set up Plug Protection from a config entry."""
    manager = ProtectionManager(hass, entry)
    entry.runtime_data = manager

    # Persisted data (e.g. the "protection enabled" flag) must be known
    # before the entities are created
    await manager.async_load()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Entities may have moved from our own device to the plug's device
    manager.async_remove_unused_devices()

    # Start listening after the platforms are ready
    await manager.async_start()

    # Settings changed in the options flow → reload (state is persisted)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: PlugProtectionConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_stop()
    return unload_ok


async def async_remove_entry(
    hass: HomeAssistant, entry: PlugProtectionConfigEntry
) -> None:
    """Clean up persisted data when the entry is deleted."""
    manager = ProtectionManager(hass, entry)
    await manager.async_remove_data()


async def _async_update_listener(
    hass: HomeAssistant, entry: PlugProtectionConfigEntry
) -> None:
    """Handle options update – reload the entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old entries (v1.0 – v1.1) to store entity registry IDs."""
    if entry.version == 1 and entry.minor_version < 2:
        registry = er.async_get(hass)
        data = {**entry.data}
        for entity_key, registry_key in (
            (CONF_PLUG_ENTITY, CONF_PLUG_REGISTRY_ID),
            (CONF_POWER_SENSOR, CONF_POWER_REGISTRY_ID),
        ):
            reg_entry = registry.async_get(data[entity_key])
            data[registry_key] = reg_entry.id if reg_entry else None
        hass.config_entries.async_update_entry(entry, data=data, minor_version=2)
        _LOGGER.info("Migrated Plug Protection entry %s to 1.2", entry.title)
    return True
