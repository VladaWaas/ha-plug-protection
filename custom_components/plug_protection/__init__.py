"""Plug Protection – prevent smart plug turn-off while appliance is running."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EVENT_HOMEASSISTANT_STARTED,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    Event,
    HomeAssistant,
    ServiceCall,
    callback,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
)
from homeassistant.components.persistent_notification import (
    async_create as pn_create,
    async_dismiss as pn_dismiss,
)

from .const import (
    ATTR_ORIGINAL_ENTITY,
    CONF_COOLDOWN_SECONDS,
    CONF_ENABLE_NOTIFICATION,
    CONF_PLUG_ENTITY,
    CONF_POWER_SENSOR,
    CONF_POWER_THRESHOLD,
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_ENABLE_NOTIFICATION,
    DEFAULT_POWER_THRESHOLD,
    DOMAIN,
    PLATFORMS,
    SERVICE_FORCE_OFF,
    SERVICE_RESET_COOLDOWN,
    STATE_ACTIVE,
    STATE_COOLDOWN,
    STATE_IDLE,
)

_LOGGER = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Setup / Unload
# ─────────────────────────────────────────────────────────────

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Plug Protection from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    manager = ProtectionManager(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = manager

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Start listening after platforms are ready
    await manager.async_start()

    # Re-evaluate on options update
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Register services (once, idempotent)
    _async_register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    manager: ProtectionManager = hass.data[DOMAIN].get(entry.entry_id)
    if manager:
        manager.async_stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok


async def _async_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Handle options update – reload the entry."""
    await hass.config_entries.async_reload(entry.entry_id)


# ─────────────────────────────────────────────────────────────
# Services
# ─────────────────────────────────────────────────────────────

SERVICE_SCHEMA = vol.Schema(
    {vol.Required(ATTR_ORIGINAL_ENTITY): cv.entity_id}
)


@callback
def _async_register_services(hass: HomeAssistant) -> None:
    """Register plug_protection services (idempotent)."""

    if hass.services.has_service(DOMAIN, SERVICE_FORCE_OFF):
        return

    async def _handle_force_off(call: ServiceCall) -> None:
        entity_id = call.data[ATTR_ORIGINAL_ENTITY]
        for manager in hass.data[DOMAIN].values():
            if isinstance(manager, ProtectionManager):
                if manager.plug_entity == entity_id:
                    await manager.async_force_off()
                    return
        _LOGGER.warning("No protection manager found for %s", entity_id)

    async def _handle_reset_cooldown(call: ServiceCall) -> None:
        entity_id = call.data[ATTR_ORIGINAL_ENTITY]
        for manager in hass.data[DOMAIN].values():
            if isinstance(manager, ProtectionManager):
                if manager.plug_entity == entity_id:
                    manager.async_reset_cooldown()
                    return
        _LOGGER.warning("No protection manager found for %s", entity_id)

    hass.services.async_register(
        DOMAIN, SERVICE_FORCE_OFF, _handle_force_off, schema=SERVICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_COOLDOWN,
        _handle_reset_cooldown,
        schema=SERVICE_SCHEMA,
    )


# ─────────────────────────────────────────────────────────────
# Protection Manager – core logic for one protected plug
# ─────────────────────────────────────────────────────────────

class ProtectionManager:
    """Manages protection state and listeners for a single plug."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry

        # Config
        self.plug_entity: str = entry.data[CONF_PLUG_ENTITY]
        self.power_sensor: str = entry.data[CONF_POWER_SENSOR]

        # Options (with fallback to data for initial setup)
        self.power_threshold: float = entry.options.get(
            CONF_POWER_THRESHOLD,
            entry.data.get(CONF_POWER_THRESHOLD, DEFAULT_POWER_THRESHOLD),
        )
        self.cooldown_seconds: int = entry.options.get(
            CONF_COOLDOWN_SECONDS,
            entry.data.get(CONF_COOLDOWN_SECONDS, DEFAULT_COOLDOWN_SECONDS),
        )
        self.enable_notification: bool = entry.options.get(
            CONF_ENABLE_NOTIFICATION,
            entry.data.get(CONF_ENABLE_NOTIFICATION, DEFAULT_ENABLE_NOTIFICATION),
        )

        # State
        self._protection_state: str = STATE_IDLE
        self._cooldown_unsub: Any | None = None
        self._cooldown_end: datetime | None = None
        self._listeners: list[Any] = []
        self._update_callbacks: list[Any] = []
        self._last_block_time: datetime | None = None

    # ── Properties ───────────────────────────────────────────

    @property
    def protection_state(self) -> str:
        """Current protection state: active / cooldown / idle."""
        return self._protection_state

    @property
    def is_protected(self) -> bool:
        """True if plug should not be turned off."""
        return self._protection_state in (STATE_ACTIVE, STATE_COOLDOWN)

    @property
    def current_power(self) -> float:
        """Current power reading from sensor."""
        state = self.hass.states.get(self.power_sensor)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return 0.0
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return 0.0

    @property
    def power_above_threshold(self) -> bool:
        """True if current power exceeds threshold."""
        return self.current_power > self.power_threshold

    @property
    def cooldown_remaining(self) -> int:
        """Remaining cooldown seconds, 0 if not in cooldown."""
        if self._cooldown_end is None:
            return 0
        remaining = (
            self._cooldown_end - datetime.now()
        ).total_seconds()
        return max(0, int(remaining))

    @property
    def last_block_time(self) -> datetime | None:
        """Timestamp of the last blocked turn-off attempt."""
        return self._last_block_time

    # ── Lifecycle ────────────────────────────────────────────

    async def async_start(self) -> None:
        """Start listening for state changes."""
        # Listen for original plug state changes (catch direct off)
        self._listeners.append(
            async_track_state_change_event(
                self.hass,
                self.plug_entity,
                self._async_on_plug_state_change,
            )
        )

        # Listen for power sensor changes
        self._listeners.append(
            async_track_state_change_event(
                self.hass,
                self.power_sensor,
                self._async_on_power_change,
            )
        )

        # Evaluate initial state
        self._update_protection_state()

        _LOGGER.info(
            "Plug Protection started for %s (threshold: %s W, cooldown: %s s)",
            self.plug_entity,
            self.power_threshold,
            self.cooldown_seconds,
        )

    @callback
    def async_stop(self) -> None:
        """Stop all listeners and timers."""
        for unsub in self._listeners:
            unsub()
        self._listeners.clear()

        if self._cooldown_unsub is not None:
            self._cooldown_unsub()
            self._cooldown_unsub = None

        _LOGGER.info("Plug Protection stopped for %s", self.plug_entity)

    # ── Callback registration (for entities to get updates) ──

    @callback
    def async_add_update_callback(self, cb: Any) -> None:
        """Register a callback that is called on state changes."""
        self._update_callbacks.append(cb)

    @callback
    def async_remove_update_callback(self, cb: Any) -> None:
        """Remove an update callback."""
        self._update_callbacks = [
            c for c in self._update_callbacks if c != cb
        ]

    @callback
    def _fire_update(self) -> None:
        """Notify all registered entities about state change."""
        for cb in self._update_callbacks:
            cb()

    # ── State evaluation ─────────────────────────────────────

    @callback
    def _update_protection_state(self) -> None:
        """Evaluate and set the current protection state."""
        old = self._protection_state

        if self.power_above_threshold:
            self._protection_state = STATE_ACTIVE
            # Cancel any running cooldown – device is clearly active
            self._cancel_cooldown()
        elif self._cooldown_unsub is not None:
            self._protection_state = STATE_COOLDOWN
        else:
            self._protection_state = STATE_IDLE

        if old != self._protection_state:
            _LOGGER.debug(
                "Protection state for %s: %s → %s",
                self.plug_entity,
                old,
                self._protection_state,
            )
            self._fire_update()

    # ── Event handlers ───────────────────────────────────────

    @callback
    def _async_on_plug_state_change(self, event: Event) -> None:
        """Handle original plug entity state change."""
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")

        if new_state is None:
            return

        # Plug turned off while protected → BLOCK
        if new_state.state == STATE_OFF and (
            old_state is None or old_state.state == STATE_ON
        ):
            if self.is_protected:
                # BLOCK: turn it back on immediately
                _LOGGER.warning(
                    "Blocked turn-off of %s (state: %s, power: %.1f W)",
                    self.plug_entity,
                    self._protection_state,
                    self.current_power,
                )
                self._last_block_time = datetime.now()
                self.hass.async_create_task(self._async_revert_off())

        # Always notify entities about plug state changes
        # so the protected switch mirrors the original state
        self._fire_update()

    @callback
    def _async_on_power_change(self, event: Event) -> None:
        """Handle power sensor state change."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in (
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        ):
            return

        try:
            power = float(new_state.state)
        except (ValueError, TypeError):
            return

        plug_state = self.hass.states.get(self.plug_entity)
        plug_is_on = plug_state is not None and plug_state.state == STATE_ON

        if power > self.power_threshold:
            # Power above threshold → active protection
            if self._protection_state != STATE_ACTIVE:
                self._cancel_cooldown()
                self._protection_state = STATE_ACTIVE
                _LOGGER.debug(
                    "%s: power %.1f W > threshold → ACTIVE",
                    self.plug_entity,
                    power,
                )
                self._fire_update()
        else:
            # Power below threshold
            if self._protection_state == STATE_ACTIVE and plug_is_on:
                # Was active, now below → start cooldown
                self._start_cooldown()
                _LOGGER.debug(
                    "%s: power %.1f W < threshold → COOLDOWN (%d s)",
                    self.plug_entity,
                    power,
                    self.cooldown_seconds,
                )
            elif self._protection_state == STATE_ACTIVE and not plug_is_on:
                # Plug is off and power dropped → just go idle
                self._protection_state = STATE_IDLE
                self._fire_update()

    # ── Cooldown management ──────────────────────────────────

    @callback
    def _start_cooldown(self) -> None:
        """Start the cooldown timer."""
        self._cancel_cooldown()

        if self.cooldown_seconds <= 0:
            self._protection_state = STATE_IDLE
            self._fire_update()
            return

        self._protection_state = STATE_COOLDOWN
        self._cooldown_end = datetime.now() + timedelta(
            seconds=self.cooldown_seconds
        )
        self._cooldown_unsub = async_call_later(
            self.hass,
            self.cooldown_seconds,
            self._async_cooldown_finished,
        )
        self._fire_update()

    @callback
    def _cancel_cooldown(self) -> None:
        """Cancel running cooldown if any."""
        if self._cooldown_unsub is not None:
            self._cooldown_unsub()
            self._cooldown_unsub = None
            self._cooldown_end = None

    @callback
    def _async_cooldown_finished(self, _now: Any) -> None:
        """Called when cooldown timer expires."""
        self._cooldown_unsub = None
        self._cooldown_end = None
        self._protection_state = STATE_IDLE
        _LOGGER.info(
            "%s: cooldown finished → IDLE (plug can be turned off)",
            self.plug_entity,
        )

        # Dismiss notification if any
        if self.enable_notification:
            pn_dismiss(
                self.hass,
                f"plug_protection_{self.entry.entry_id}",
            )

        self._fire_update()

    # ── Revert (blocked turn-off) ────────────────────────────

    async def _async_revert_off(self) -> None:
        """Turn the plug back on after a blocked turn-off."""
        await self.hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": self.plug_entity},
            blocking=True,
        )

        if self.enable_notification:
            friendly = self._get_friendly_name()
            pn_create(
                self.hass,
                (
                    f"Turn-off of **{friendly}** was blocked!\n\n"
                    f"Current power: {self.current_power:.1f} W "
                    f"(threshold: {self.power_threshold} W)\n\n"
                    f"Protection state: {self._protection_state}"
                ),
                title="🛡️ Plug Protection",
                notification_id=f"plug_protection_{self.entry.entry_id}",
            )

        self._fire_update()

    # ── Service handlers ─────────────────────────────────────

    async def async_force_off(self) -> None:
        """Force turn off the plug, bypassing protection."""
        _LOGGER.info("Force-off requested for %s", self.plug_entity)
        self._cancel_cooldown()
        self._protection_state = STATE_IDLE
        self._fire_update()

        await self.hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": self.plug_entity},
            blocking=True,
        )

        if self.enable_notification:
            pn_dismiss(
                self.hass,
                f"plug_protection_{self.entry.entry_id}",
            )

    @callback
    def async_reset_cooldown(self) -> None:
        """Reset cooldown, immediately go to idle."""
        _LOGGER.info("Cooldown reset for %s", self.plug_entity)
        self._cancel_cooldown()
        if self._protection_state == STATE_COOLDOWN:
            self._protection_state = STATE_IDLE

        if self.enable_notification:
            pn_dismiss(
                self.hass,
                f"plug_protection_{self.entry.entry_id}",
            )

        self._fire_update()

    # ── Helpers ───────────────────────────────────────────────

    def _get_friendly_name(self) -> str:
        """Get the friendly name of the plug entity."""
        state = self.hass.states.get(self.plug_entity)
        if state and state.attributes.get("friendly_name"):
            return state.attributes["friendly_name"]
        return self.plug_entity
