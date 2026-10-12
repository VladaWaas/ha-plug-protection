"""Config flow tests."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.plug_protection.const import DOMAIN

from .conftest import PLUG, POWER, make_entry

USER_INPUT = {
    "plug_entity": PLUG,
    "power_sensor": POWER,
    "power_threshold": 15,
    "cooldown_seconds": 200,
    "enable_notification": True,
    "raise_on_block": False,
    "hide_original": True,
}


async def test_user_flow_creates_entry_with_registry_ids(hass, plug, registry_ids):
    hass.states.async_set(POWER, "0")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Washer"
    assert result["data"]["plug_registry_id"] == registry_ids[0]
    assert result["data"]["power_registry_id"] == registry_ids[1]
    assert result["data"]["cooldown_seconds"] == 200  # not limited to steps of 30


async def test_duplicate_plug_aborts(hass, plug, registry_ids):
    hass.states.async_set(POWER, "0")
    make_entry(registry_ids).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow(hass, plug, registry_ids, setup_entry):
    entry = await setup_entry()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "power_threshold": 25,
            "cooldown_seconds": 90,
            "enable_notification": False,
            "raise_on_block": True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    manager = entry.runtime_data
    assert manager.power_threshold == 25 and manager.cooldown_seconds == 90
    assert manager.raise_on_block is True and manager.enable_notification is False


async def test_reconfigure_flow_changes_sensor(hass, plug, registry_ids, setup_entry):
    from homeassistant.helpers import entity_registry as er

    entry = await setup_entry()
    reg = er.async_get(hass)
    new = reg.async_get_or_create(
        "sensor", "test", "other_power", suggested_object_id="other_power"
    )
    hass.states.async_set(new.entity_id, "5")

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"plug_entity": PLUG, "power_sensor": new.entity_id}
    )
    assert (
        result["type"] is FlowResultType.ABORT
        and result["reason"] == "reconfigure_successful"
    )
    await hass.async_block_till_done()
    assert entry.data["power_registry_id"] == new.id
    assert entry.runtime_data.power_sensor == new.entity_id
