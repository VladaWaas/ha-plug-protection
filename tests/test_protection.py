"""Behaviour tests for Plug Protection."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers import (
    issue_registry as ir,
)
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.plug_protection.const import DOMAIN, EVENT_BLOCKED

from .conftest import PLUG, POWER


def eid(hass: HomeAssistant, entry, suffix: str) -> str:
    """Entity id of one of our entities, found by unique id."""
    reg = er.async_get(hass)
    found = [
        e.entity_id
        for e in er.async_entries_for_config_entry(reg, entry.entry_id)
        if e.unique_id == f"{entry.entry_id}_{suffix}"
    ]
    assert found, f"no entity with suffix {suffix}"
    return found[0]


def status(hass, entry) -> str:
    return hass.states.get(eid(hass, entry, "protection_status")).state


async def set_power(hass: HomeAssistant, value: str) -> None:
    hass.states.async_set(POWER, value)
    await hass.async_block_till_done(wait_background_tasks=True)


async def elapse(hass: HomeAssistant, seconds: int) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done(wait_background_tasks=True)


# ── Setup & entities ─────────────────────────────────────────


async def test_setup_creates_entities(hass, setup_entry):
    entry = await setup_entry()
    for suffix in (
        "protected_switch",
        "protection_enabled",
        "protection_status",
        "cooldown_end",
    ):
        assert hass.states.get(eid(hass, entry, suffix)) is not None
    assert status(hass, entry) == "idle"
    assert hass.states.get(eid(hass, entry, "protection_enabled")).state == "on"
    assert hass.states.get(eid(hass, entry, "protected_switch")).state == "on"


async def test_entities_attach_to_source_device(hass, plug, registry_ids, setup_entry):
    """If the plug belongs to a device, our entities join that device."""
    dev_reg = dr.async_get(hass)
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    host = MockConfigEntry(domain="test")
    host.add_to_hass(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=host.entry_id,
        identifiers={("test", "washer")},
        name="Washer plug",
    )
    er.async_get(hass).async_update_entity(PLUG, device_id=device.id)

    entry = await setup_entry()
    ent = er.async_get(hass).async_get(eid(hass, entry, "protected_switch"))
    assert ent.device_id == device.id


# ── State machine ────────────────────────────────────────────


async def test_power_cycle_active_cooldown_idle(hass, setup_entry):
    entry = await setup_entry()
    await set_power(hass, "133")
    assert status(hass, entry) == "active"

    await set_power(hass, "2")
    assert status(hass, entry) == "cooldown"
    assert hass.states.get(eid(hass, entry, "cooldown_end")).state not in (
        "unknown",
        "unavailable",
    )

    await elapse(hass, 301)
    assert status(hass, entry) == "idle"
    assert hass.states.get(eid(hass, entry, "cooldown_end")).state == "unknown"


async def test_power_back_up_cancels_cooldown(hass, setup_entry):
    entry = await setup_entry()
    await set_power(hass, "133")
    await set_power(hass, "1")
    assert status(hass, entry) == "cooldown"
    await set_power(hass, "50")
    assert status(hass, entry) == "active"
    await set_power(hass, "1")
    await elapse(hass, 120)
    assert status(hass, entry) == "cooldown"  # fresh cooldown, not the old one


async def test_unavailable_power_sensor_holds_state(hass, setup_entry):
    """Regression: unavailable sensor used to read as 0 W and drop protection."""
    entry = await setup_entry()
    await set_power(hass, "133")
    await set_power(hass, "unavailable")
    assert status(hass, entry) == "active"
    await set_power(hass, "unknown")
    assert status(hass, entry) == "active"


# ── Blocking ─────────────────────────────────────────────────


async def test_physical_off_is_reverted(hass, plug, setup_entry):
    entry = await setup_entry()
    events = async_capture_events(hass, EVENT_BLOCKED)
    await set_power(hass, "133")

    plug.physical_off()
    await hass.async_block_till_done(wait_background_tasks=True)

    assert plug.count("turn_on") == 1
    assert hass.states.get(PLUG).state == "on"
    assert len(events) == 1 and events[0].data["source"] == "state_change"
    assert hass.states.get(eid(hass, entry, "protected_switch")).attributes[
        "last_block_time"
    ]
    # the dip caused by the glitch must not drop protection → full cooldown
    await set_power(hass, "0")
    assert status(hass, entry) == "cooldown"


async def test_power_dip_during_revert_does_not_idle(hass, plug, setup_entry):
    """Regression: 0 W reported while plug is off used to reset protection to idle."""
    entry = await setup_entry()
    await set_power(hass, "133")
    plug.fail_turn_on = 1  # first revert attempt fails → plug stays off for a moment
    plug.physical_off()
    await set_power(hass, "0")  # sensor reports 0 W while the plug is off
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(PLUG).state == "on"
    assert status(hass, entry) in ("cooldown", "active")


async def test_revert_retries_then_succeeds(hass, plug, setup_entry):
    await setup_entry()
    await set_power(hass, "133")
    plug.fail_turn_on = 2
    plug.physical_off()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert plug.count("turn_on") == 3
    assert hass.states.get(PLUG).state == "on"


async def test_revert_gives_up_and_notifies(hass, plug, setup_entry):
    await setup_entry()
    await set_power(hass, "133")
    plug.fail_turn_on = 99
    plug.physical_off()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert plug.count("turn_on") == 3
    from homeassistant.components import persistent_notification as pn

    notifications = pn._async_get_or_create_notifications(hass)
    assert any("Washer" in n["message"] for n in notifications.values())


async def test_not_blocked_when_idle(hass, plug, setup_entry):
    entry = await setup_entry()
    plug.physical_off()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert plug.count("turn_on") == 0
    assert hass.states.get(PLUG).state == "off"
    assert status(hass, entry) == "idle"


async def test_wrapper_switch_blocks_and_passes_through(hass, plug, setup_entry):
    entry = await setup_entry()
    wrapper = eid(hass, entry, "protected_switch")

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": wrapper}, blocking=True
    )
    assert plug.count("turn_off") == 1  # idle → passed through
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": wrapper}, blocking=True
    )

    await set_power(hass, "133")
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": wrapper}, blocking=True
    )
    assert plug.count("turn_off") == 1  # blocked → not forwarded
    assert hass.states.get(PLUG).state == "on"


async def test_wrapper_raises_when_configured(hass, plug, setup_entry):
    entry = await setup_entry(raise_on_block=True)
    wrapper = eid(hass, entry, "protected_switch")
    await set_power(hass, "133")
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": wrapper}, blocking=True
        )
    assert plug.count("turn_off") == 0


# ── Per-plug enable switch ───────────────────────────────────


async def test_disable_protection_switch(hass, plug, setup_entry):
    entry = await setup_entry()
    enable = eid(hass, entry, "protection_enabled")
    wrapper = eid(hass, entry, "protected_switch")
    await set_power(hass, "133")

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": enable}, blocking=True
    )
    assert status(hass, entry) == "disabled"
    assert hass.states.get(enable).state == "off"

    # physical off is no longer reverted ...
    plug.physical_off()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert plug.count("turn_on") == 0
    assert hass.states.get(PLUG).state == "off"

    # ... and the wrapper passes commands through
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": wrapper}, blocking=True
    )
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": wrapper}, blocking=True
    )
    assert plug.count("turn_off") == 1


async def test_reenable_protection_with_high_power_is_active(hass, plug, setup_entry):
    entry = await setup_entry()
    enable = eid(hass, entry, "protection_enabled")
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": enable}, blocking=True
    )
    await set_power(hass, "200")
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": enable}, blocking=True
    )
    assert status(hass, entry) == "active"
    plug.physical_off()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(PLUG).state == "on"


# ── Services ─────────────────────────────────────────────────


async def test_force_off_and_reset_cooldown_services(hass, plug, setup_entry):
    entry = await setup_entry()
    wrapper = eid(hass, entry, "protected_switch")
    await set_power(hass, "133")
    await set_power(hass, "1")
    assert status(hass, entry) == "cooldown"

    await hass.services.async_call(
        DOMAIN, "reset_cooldown", {"entity_id": wrapper}, blocking=True
    )
    assert status(hass, entry) == "idle"

    await set_power(hass, "133")
    await hass.services.async_call(
        DOMAIN, "force_off", {"entity_id": wrapper}, blocking=True
    )
    assert plug.count("turn_off") == 1
    assert hass.states.get(PLUG).state == "off"
    assert plug.count("turn_on") == 0  # force-off must not be reverted


# ── Persistence ──────────────────────────────────────────────


async def test_cooldown_and_enabled_flag_survive_reload(hass, setup_entry):
    entry = await setup_entry()
    await set_power(hass, "133")
    await set_power(hass, "1")
    end_before = hass.states.get(eid(hass, entry, "cooldown_end")).state
    enable = eid(hass, entry, "protection_enabled")
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": enable}, blocking=True
    )

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get(enable).state == "off"  # per-plug switch persisted
    assert hass.states.get(eid(hass, entry, "cooldown_end")).state == end_before
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": enable}, blocking=True
    )
    assert status(hass, entry) == "cooldown"  # still protected through the old cooldown


async def test_active_state_survives_restart_with_sensor_down(hass, setup_entry):
    """Sensor unavailable right after restart must not drop protection."""
    entry = await setup_entry()
    await set_power(hass, "133")
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    hass.states.async_set(POWER, "unavailable")

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert status(hass, entry) == "active"
    await set_power(hass, "0")  # sensor is back and reads low
    assert status(hass, entry) == "cooldown"


async def test_plug_unavailable_marks_entities_unavailable(hass, setup_entry):
    entry = await setup_entry()
    hass.states.async_set(PLUG, "unavailable")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(eid(hass, entry, "protected_switch")).state == "unavailable"
    assert hass.states.get(eid(hass, entry, "protection_status")).state == "unavailable"
    # the enable switch stays usable
    assert hass.states.get(eid(hass, entry, "protection_enabled")).state == "on"


# ── Rename / missing entity ──────────────────────────────────


async def test_plug_rename_is_followed(hass, plug, setup_entry):
    entry = await setup_entry()
    reg = er.async_get(hass)
    reg.async_update_entity(PLUG, new_entity_id="switch.washing_machine")
    hass.states.async_remove(PLUG)
    hass.states.async_set("switch.washing_machine", "on", {"friendly_name": "Washer"})
    plug.entity_id = "switch.washing_machine"
    await hass.async_block_till_done(wait_background_tasks=True)
    await hass.async_block_till_done(wait_background_tasks=True)

    manager = entry.runtime_data
    assert manager.plug_entity == "switch.washing_machine"
    await set_power(hass, "133")
    hass.states.async_set("switch.washing_machine", "off")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("switch.washing_machine").state == "on"  # still protected


async def test_missing_entity_creates_repair_issue(
    hass, plug, registry_ids, setup_entry
):
    entry = await setup_entry()
    reg = er.async_get(hass)
    reg.async_remove(POWER)
    hass.states.async_remove(POWER)
    await hass.async_block_till_done(wait_background_tasks=True)
    await elapse(hass, 3)
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"entity_missing_{entry.entry_id}"
    )
    assert issue is not None


# ── Migration ────────────────────────────────────────────────


async def test_migration_from_v1_adds_registry_ids(hass, plug, registry_ids):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    hass.states.async_set(POWER, "0")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Washer",
        version=1,
        minor_version=1,
        unique_id=PLUG,
        data={
            "plug_entity": PLUG,
            "power_sensor": POWER,
            "power_threshold": 10,
            "cooldown_seconds": 300,
            "enable_notification": True,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.minor_version == 2
    assert entry.data["plug_registry_id"] == registry_ids[0]
    assert entry.data["power_registry_id"] == registry_ids[1]


async def test_removing_entry_cleans_up(hass, plug, setup_entry):
    entry = await setup_entry()
    await set_power(hass, "133")
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert not er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
