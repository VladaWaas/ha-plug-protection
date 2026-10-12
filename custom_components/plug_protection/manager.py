"""Protection manager – core logic for one protected plug."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components.persistent_notification import (
    async_create as pn_create,
)
from homeassistant.components.persistent_notification import (
    async_dismiss as pn_dismiss,
)
from homeassistant.const import (
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    device as dr_helper,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers import (
    issue_registry as ir,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import (
    async_call_later,
    async_track_entity_registry_updated_event,
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

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
    EVENT_BLOCKED,
    NOTIFICATION_TEXTS,
    NOTIFICATION_TITLE,
    REVERT_ATTEMPTS,
    REVERT_POLL_SECONDS,
    REVERT_RETRY_DELAY,
    REVERT_WAIT_SECONDS,
    STATE_ACTIVE,
    STATE_COOLDOWN,
    STATE_DISABLED,
    STATE_IDLE,
    STORAGE_SAVE_DELAY,
    STORAGE_VERSION,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

_INVALID_STATES = (STATE_UNAVAILABLE, STATE_UNKNOWN)


def resolve_entity_id(
    hass: HomeAssistant, registry_id: str | None, fallback: str
) -> str:
    """Return the current entity_id for a registry ID (falls back to the stored id)."""
    if registry_id:
        entry = er.async_get(hass).async_get(registry_id)
        if entry is not None:
            return entry.entity_id
    return fallback


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = dt_util.parse_datetime(str(value))
    if parsed is None:
        return None
    return dt_util.as_utc(parsed)


class ProtectionManager:
    """Manages protection state and listeners for a single plug."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )

        # Entities (resolved through the entity registry so renames survive)
        self.plug_entity: str = resolve_entity_id(
            hass,
            entry.data.get(CONF_PLUG_REGISTRY_ID),
            entry.data[CONF_PLUG_ENTITY],
        )
        self.power_sensor: str = resolve_entity_id(
            hass,
            entry.data.get(CONF_POWER_REGISTRY_ID),
            entry.data[CONF_POWER_SENSOR],
        )

        # Settings (options override the data from the initial setup)
        self.power_threshold: float = self._setting(
            CONF_POWER_THRESHOLD, DEFAULT_POWER_THRESHOLD
        )
        self.cooldown_seconds: int = int(
            self._setting(CONF_COOLDOWN_SECONDS, DEFAULT_COOLDOWN_SECONDS)
        )
        self.enable_notification: bool = self._setting(
            CONF_ENABLE_NOTIFICATION, DEFAULT_ENABLE_NOTIFICATION
        )
        self.raise_on_block: bool = self._setting(
            CONF_RAISE_ON_BLOCK, DEFAULT_RAISE_ON_BLOCK
        )

        # Runtime state
        self._enabled = True
        self._state: str = STATE_IDLE  # underlying state (ignores `enabled`)
        self._power: float | None = None  # last known valid reading
        self._cooldown_end: datetime | None = None
        self._cooldown_unsub: CALLBACK_TYPE | None = None
        self._last_block_time: datetime | None = None
        self._reverting = False

        # Persisted values loaded by async_load()
        self._stored_state: str = STATE_IDLE
        self._stored_cooldown_end: datetime | None = None

        self._listeners: list[CALLBACK_TYPE] = []
        self._update_callbacks: list[Callable[[], None]] = []
        self._loaded = False

    def _setting(self, key: str, default: Any) -> Any:
        return self.entry.options.get(key, self.entry.data.get(key, default))

    # ── Properties ───────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        """True if protection is switched on for this plug."""
        return self._enabled

    @property
    def protection_state(self) -> str:
        """State exposed to the user: active / cooldown / idle / disabled."""
        if not self._enabled:
            return STATE_DISABLED
        return self._state

    @property
    def is_protected(self) -> bool:
        """True if a turn-off of the plug must be blocked right now."""
        return self._enabled and self._state in (STATE_ACTIVE, STATE_COOLDOWN)

    @property
    def current_power(self) -> float | None:
        """Last known valid power reading (None if never seen)."""
        return self._power

    @property
    def cooldown_end(self) -> datetime | None:
        """UTC time the running cooldown ends (None if no cooldown)."""
        return self._cooldown_end

    @property
    def last_block_time(self) -> datetime | None:
        """UTC time of the last blocked turn-off attempt."""
        return self._last_block_time

    @property
    def plug_available(self) -> bool:
        """True if the original plug currently reports a usable state."""
        state = self.hass.states.get(self.plug_entity)
        return state is not None and state.state not in _INVALID_STATES

    @property
    def plug_name(self) -> str:
        """Friendly name of the original plug."""
        state = self.hass.states.get(self.plug_entity)
        if state and state.attributes.get("friendly_name"):
            return state.attributes["friendly_name"]
        return self.entry.title or self.plug_entity

    @property
    def device_info(self) -> DeviceInfo:
        """Attach entities to the device of the original plug if it has one."""
        linked = dr_helper.async_device_info_to_link_from_entity(
            self.hass,
            self.entry.data.get(CONF_PLUG_REGISTRY_ID) or self.plug_entity,
        )
        if linked is not None:
            return linked
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=self.entry.title,
            manufacturer="Plug Protection",
            model="Protected Smart Plug",
        )

    # ── Helpers ──────────────────────────────────────────────

    def _read_power(self) -> float | None:
        """Read the power sensor; None if unavailable / not numeric."""
        state = self.hass.states.get(self.power_sensor)
        return self._parse_power(state.state if state else None)

    @staticmethod
    def _parse_power(raw: str | None) -> float | None:
        if raw is None or raw in _INVALID_STATES:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _plug_state(self) -> str | None:
        state = self.hass.states.get(self.plug_entity)
        return state.state if state else None

    def _text(self, key: str, **kwargs: Any) -> str:
        lang = (self.hass.config.language or "en").split("-")[0].lower()
        texts = NOTIFICATION_TEXTS.get(lang, NOTIFICATION_TEXTS["en"])
        return texts[key].format(**kwargs)

    @property
    def _notification_id(self) -> str:
        return f"{DOMAIN}_{self.entry.entry_id}"

    @property
    def _issue_id(self) -> str:
        return f"entity_missing_{self.entry.entry_id}"

    # ── Persistence ──────────────────────────────────────────

    def _data_to_save(self) -> dict[str, Any]:
        return {
            "enabled": self._enabled,
            "state": self._state,
            "cooldown_end": (
                self._cooldown_end.isoformat() if self._cooldown_end else None
            ),
            "last_block_time": (
                self._last_block_time.isoformat() if self._last_block_time else None
            ),
        }

    @callback
    def _schedule_save(self) -> None:
        if self._loaded:
            self._store.async_delay_save(self._data_to_save, STORAGE_SAVE_DELAY)

    async def async_load(self) -> None:
        """Load persisted data (enabled flag, block time) before entities exist."""
        data = await self._store.async_load() or {}
        self._enabled = bool(data.get("enabled", True))
        self._last_block_time = _parse_dt(data.get("last_block_time"))
        self._stored_state: str = data.get("state", STATE_IDLE)
        self._stored_cooldown_end = _parse_dt(data.get("cooldown_end"))
        self._loaded = True

    async def async_remove_data(self) -> None:
        """Delete persisted data when the config entry is removed."""
        await self._store.async_remove()
        ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)
        pn_dismiss(self.hass, self._notification_id)

    # ── Lifecycle ────────────────────────────────────────────

    async def async_start(self) -> None:
        """Start listening and restore the protection state."""
        self._power = self._read_power()

        self._listeners.append(
            async_track_state_change_event(
                self.hass, self.plug_entity, self._async_on_plug_state_change
            )
        )
        self._listeners.append(
            async_track_state_change_event(
                self.hass, self.power_sensor, self._async_on_power_change
            )
        )
        registry_ids = [
            self.plug_entity,
            self.power_sensor,
        ]
        self._listeners.append(
            async_track_entity_registry_updated_event(
                self.hass, registry_ids, self._async_on_registry_update
            )
        )
        self._listeners.append(async_at_started(self.hass, self._async_check_entities))

        self._restore_state()
        self._fire_update()

        _LOGGER.info(
            "Plug Protection started for %s (threshold: %s W, cooldown: %s s, "
            "state: %s, enabled: %s)",
            self.plug_entity,
            self.power_threshold,
            self.cooldown_seconds,
            self._state,
            self._enabled,
        )

    @callback
    def _restore_state(self) -> None:
        """Pick the initial protection state after (re)start."""
        now = dt_util.utcnow()
        thr = self.power_threshold
        plug = self._plug_state()

        if plug == STATE_OFF:
            # Nothing to protect while the plug is off
            self._state = STATE_IDLE
        elif self._power is not None and self._power > thr:
            self._state = STATE_ACTIVE
        elif self._stored_cooldown_end is not None and self._stored_cooldown_end > now:
            # Resume the cooldown that was running before restart / reload
            self._begin_cooldown_until(self._stored_cooldown_end)
        elif self._stored_state == STATE_ACTIVE:
            if self._power is None:
                # Sensor not up yet – stay protected until it reports
                self._state = STATE_ACTIVE
            else:
                # Appliance was running before restart and now reads low:
                # play safe and run a full cooldown
                self._start_cooldown()
        else:
            self._state = STATE_IDLE
        self._schedule_save()

    async def async_stop(self) -> None:
        """Stop all listeners and timers and flush state to disk."""
        for unsub in self._listeners:
            unsub()
        self._listeners.clear()

        if self._cooldown_unsub is not None:
            self._cooldown_unsub()
            self._cooldown_unsub = None

        if self._loaded:
            await self._store.async_save(self._data_to_save())

        _LOGGER.info("Plug Protection stopped for %s", self.plug_entity)

    # ── Callback registration (entities get notified) ────────

    @callback
    def async_add_update_callback(self, cb: Callable[[], None]) -> CALLBACK_TYPE:
        """Register a callback for state changes; returns an unsubscribe."""
        self._update_callbacks.append(cb)

        @callback
        def _remove() -> None:
            if cb in self._update_callbacks:
                self._update_callbacks.remove(cb)

        return _remove

    @callback
    def _fire_update(self) -> None:
        for cb in list(self._update_callbacks):
            cb()

    @callback
    def _set_state(self, new: str) -> None:
        if new == self._state:
            return
        _LOGGER.debug(
            "Protection state for %s: %s → %s", self.plug_entity, self._state, new
        )
        self._state = new
        self._schedule_save()

    # ── Public controls ──────────────────────────────────────

    async def async_set_enabled(self, enabled: bool) -> None:
        """Switch protection on/off for this plug."""
        if enabled == self._enabled:
            return
        self._enabled = enabled
        _LOGGER.info(
            "Protection %s for %s",
            "enabled" if enabled else "disabled",
            self.plug_entity,
        )
        if not enabled:
            pn_dismiss(self.hass, self._notification_id)
        else:
            # Re-evaluate with the latest data so protection is right at once
            self._power = self._read_power() if self._power is None else self._power
            if self._power is not None and self._power > self.power_threshold:
                self._cancel_cooldown()
                self._set_state(STATE_ACTIVE)
        self._schedule_save()
        self._fire_update()

    async def async_force_off(self) -> None:
        """Turn the plug off, bypassing protection."""
        _LOGGER.info("Force-off requested for %s", self.plug_entity)
        self._cancel_cooldown()
        self._set_state(STATE_IDLE)
        self._fire_update()

        await self.hass.services.async_call(
            "switch", "turn_off", {"entity_id": self.plug_entity}, blocking=True
        )
        pn_dismiss(self.hass, self._notification_id)

    @callback
    def async_reset_cooldown(self) -> None:
        """End a running cooldown immediately."""
        _LOGGER.info("Cooldown reset for %s", self.plug_entity)
        self._cancel_cooldown()
        if self._state == STATE_COOLDOWN:
            self._set_state(STATE_IDLE)
        pn_dismiss(self.hass, self._notification_id)
        self._fire_update()

    @callback
    def async_register_block(self, source: str) -> None:
        """Record a blocked turn-off attempt (event, notification, timestamp)."""
        self._last_block_time = dt_util.utcnow()
        self._schedule_save()
        _LOGGER.warning(
            "Blocked turn-off of %s via %s (state: %s, power: %s W)",
            self.plug_entity,
            source,
            self._state,
            self._power,
        )
        self.hass.bus.async_fire(
            EVENT_BLOCKED,
            {
                "entity_id": self.plug_entity,
                "name": self.plug_name,
                "source": source,
                "power": self._power,
                "protection_state": self._state,
            },
        )
        if self.enable_notification:
            self._notify(
                self._text(
                    "blocked",
                    name=self.plug_name,
                    power=(f"{self._power:.1f} W" if self._power is not None else "?"),
                    threshold=self.power_threshold,
                    state=self._state,
                )
            )
        self._fire_update()

    @callback
    def _notify(self, message: str) -> None:
        pn_create(
            self.hass,
            message,
            title=NOTIFICATION_TITLE,
            notification_id=self._notification_id,
        )

    # ── Event handlers ───────────────────────────────────────

    @callback
    def _async_on_plug_state_change(self, event: Event) -> None:
        """Original plug changed state."""
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None:
            return

        turned_off = (
            new_state.state == STATE_OFF
            and old_state is not None
            and old_state.state == STATE_ON
        )
        if turned_off:
            if self.is_protected:
                if not self._reverting:
                    self.async_register_block("state_change")
                    self._reverting = True
                    self.entry.async_create_background_task(
                        self.hass,
                        self._async_revert_off(),
                        name=f"{DOMAIN} revert {self.plug_entity}",
                    )
            elif not self._reverting:
                # Legitimately off (idle, disabled or forced) – nothing to protect
                self._cancel_cooldown()
                self._set_state(STATE_IDLE)

        self._fire_update()

    @callback
    def _async_on_power_change(self, event: Event) -> None:
        """Power sensor changed."""
        new_state = event.data.get("new_state")
        value = self._parse_power(new_state.state if new_state else None)
        if value is None:
            # Unavailable sensor: hold the current protection state
            self._fire_update()
            return

        self._power = value
        self._evaluate_power()
        self._fire_update()

    @callback
    def _evaluate_power(self) -> None:
        power = self._power
        if power is None:
            return

        if power > self.power_threshold:
            self._cancel_cooldown()
            self._set_state(STATE_ACTIVE)
            return

        # At or below the threshold
        if self._state != STATE_ACTIVE:
            return
        if self._reverting:
            # A blocked turn-off is being reverted; the dip is caused by it
            return
        if self._plug_state() == STATE_OFF:
            self._set_state(STATE_IDLE)
        else:
            self._start_cooldown()

    @callback
    def _async_on_registry_update(self, event: Event) -> None:
        """Entity registry changed for the plug or the power sensor."""
        action = event.data.get("action")
        if action == "update" and "entity_id" in event.data.get("changes", {}):
            _LOGGER.info(
                "Entity renamed %s → %s, reloading Plug Protection",
                event.data["changes"]["entity_id"],
                event.data["entity_id"],
            )
            self.hass.config_entries.async_schedule_reload(self.entry.entry_id)
        elif action == "remove":
            # the entity's state disappears a moment later – check then
            self._listeners.append(
                async_call_later(self.hass, 2, self._async_check_entities)
            )

    @callback
    def _async_check_entities(self, *_: Any) -> None:
        """Raise a repair issue if a configured entity no longer exists."""
        missing = [
            entity
            for entity in (self.plug_entity, self.power_sensor)
            if self.hass.states.get(entity) is None
            and er.async_get(self.hass).async_get(entity) is None
        ]
        if missing:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="entity_missing",
                translation_placeholders={
                    "name": self.entry.title,
                    "entities": ", ".join(missing),
                },
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)

    # ── Cooldown management ──────────────────────────────────

    @callback
    def _start_cooldown(self) -> None:
        """Start a full cooldown (or go idle if cooldown is disabled)."""
        self._cancel_cooldown()
        if self.cooldown_seconds <= 0:
            self._set_state(STATE_IDLE)
            return
        self._begin_cooldown_until(
            dt_util.utcnow() + timedelta(seconds=self.cooldown_seconds)
        )

    @callback
    def _begin_cooldown_until(self, end: datetime) -> None:
        self._cancel_cooldown()
        self._cooldown_end = end
        self._cooldown_unsub = async_track_point_in_utc_time(
            self.hass, self._async_cooldown_finished, end
        )
        self._set_state(STATE_COOLDOWN)
        self._schedule_save()
        _LOGGER.debug("%s: cooldown until %s", self.plug_entity, end)

    @callback
    def _cancel_cooldown(self) -> None:
        if self._cooldown_unsub is not None:
            self._cooldown_unsub()
            self._cooldown_unsub = None
        if self._cooldown_end is not None:
            self._cooldown_end = None
            self._schedule_save()

    @callback
    def _async_cooldown_finished(self, _now: datetime) -> None:
        self._cooldown_unsub = None
        self._cooldown_end = None
        if self._power is not None and self._power > self.power_threshold:
            self._set_state(STATE_ACTIVE)
        else:
            self._set_state(STATE_IDLE)
            _LOGGER.info(
                "%s: cooldown finished → idle (plug can be turned off)",
                self.plug_entity,
            )
        pn_dismiss(self.hass, self._notification_id)
        self._schedule_save()
        self._fire_update()

    # ── Revert (blocked turn-off) ────────────────────────────

    async def _async_revert_off(self) -> None:
        """Turn the plug back on after a blocked turn-off (with retries)."""
        success = False
        try:
            for attempt in range(1, REVERT_ATTEMPTS + 1):
                try:
                    await self.hass.services.async_call(
                        "switch",
                        "turn_on",
                        {"entity_id": self.plug_entity},
                        blocking=True,
                    )
                except HomeAssistantError as err:
                    _LOGGER.warning(
                        "Revert attempt %d/%d for %s failed: %s",
                        attempt,
                        REVERT_ATTEMPTS,
                        self.plug_entity,
                        err,
                    )
                else:
                    if await self._async_wait_for_plug_on():
                        success = True
                        break
                if attempt < REVERT_ATTEMPTS:
                    await asyncio.sleep(attempt * REVERT_RETRY_DELAY)
        finally:
            self._reverting = False

        if success:
            # The appliance lost power for a moment: keep it protected through a
            # full cooldown unless it is clearly drawing power again.
            power = self._power
            if power is None or power <= self.power_threshold:
                self._start_cooldown()
        else:
            _LOGGER.error(
                "Could not turn %s back on after a blocked turn-off",
                self.plug_entity,
            )
            if self.enable_notification:
                self._notify(self._text("revert_failed", name=self.plug_name))
        self._fire_update()

    async def _async_wait_for_plug_on(self) -> bool:
        loop = asyncio.get_running_loop()
        end = loop.time() + REVERT_WAIT_SECONDS
        while True:
            if self._plug_state() == STATE_ON:
                return True
            if loop.time() >= end:
                return False
            await asyncio.sleep(REVERT_POLL_SECONDS)
