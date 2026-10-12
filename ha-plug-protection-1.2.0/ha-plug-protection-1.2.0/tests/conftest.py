"""Shared fixtures for Plug Protection tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant, ServiceRegistry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.plug_protection.const import (
    CONF_COOLDOWN_SECONDS,
    CONF_ENABLE_NOTIFICATION,
    CONF_PLUG_ENTITY,
    CONF_PLUG_REGISTRY_ID,
    CONF_POWER_REGISTRY_ID,
    CONF_POWER_SENSOR,
    CONF_POWER_THRESHOLD,
    DOMAIN,
)

PLUG = "switch.washer"
POWER = "sensor.washer_power"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of custom integrations in all tests."""
    return


@pytest.fixture(autouse=True)
def fast_sleep():
    """Make the revert retry back-off instant."""
    with (
        patch("custom_components.plug_protection.manager.REVERT_RETRY_DELAY", 0),
        patch("custom_components.plug_protection.manager.REVERT_POLL_SECONDS", 0.01),
        patch("custom_components.plug_protection.manager.REVERT_WAIT_SECONDS", 0.05),
    ):
        yield


class Plug:
    """A fake smart plug: records service calls and mirrors them to the state.

    Calls to switch.turn_on/turn_off for the plug entity are intercepted (the real
    switch component would otherwise swallow them); everything else is passed on.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.calls: list[tuple[str, str]] = []
        self.fail_turn_on = 0  # number of turn_on calls that should raise
        self.entity_id = PLUG
        hass.states.async_set(PLUG, "on", {"friendly_name": "Washer"})

        real_call = ServiceRegistry.async_call

        async def intercept(
            registry, domain, service, service_data=None, *args, **kwargs
        ):
            if (
                domain == "switch"
                and service in ("turn_on", "turn_off")
                and (service_data or {}).get("entity_id") == self.entity_id
            ):
                await self._handle(service, service_data)
                return None
            return await real_call(
                registry, domain, service, service_data, *args, **kwargs
            )

        self._patch = patch.object(ServiceRegistry, "async_call", intercept)
        self._patch.start()

    def stop(self) -> None:
        self._patch.stop()

    async def _handle(self, service: str, data: dict) -> None:
        self.calls.append((service, data["entity_id"]))
        if service == "turn_on":
            if self.fail_turn_on > 0:
                self.fail_turn_on -= 1
                raise HomeAssistantError("zigbee timeout")
            self.hass.states.async_set(
                self.entity_id, "on", {"friendly_name": "Washer"}
            )
        else:
            self.hass.states.async_set(
                self.entity_id, "off", {"friendly_name": "Washer"}
            )

    def physical_off(self) -> None:
        """Someone pressed the physical button (state changes without a service call)."""
        self.hass.states.async_set(self.entity_id, "off", {"friendly_name": "Washer"})

    def count(self, name: str) -> int:
        return sum(1 for c in self.calls if c[0] == name)


@pytest.fixture
def plug(hass: HomeAssistant, registry_ids):
    fake = Plug(hass)
    yield fake
    fake.stop()


@pytest.fixture
def registry_ids(hass: HomeAssistant) -> tuple[str, str]:
    reg = er.async_get(hass)
    p = reg.async_get_or_create(
        "switch", "test", "washer", suggested_object_id="washer"
    )
    s = reg.async_get_or_create(
        "sensor", "test", "washer_power", suggested_object_id="washer_power"
    )
    assert p.entity_id == PLUG and s.entity_id == POWER
    return p.id, s.id


def make_entry(registry_ids, **overrides) -> MockConfigEntry:
    data = {
        CONF_PLUG_ENTITY: PLUG,
        CONF_POWER_SENSOR: POWER,
        CONF_PLUG_REGISTRY_ID: registry_ids[0],
        CONF_POWER_REGISTRY_ID: registry_ids[1],
        CONF_POWER_THRESHOLD: 10,
        CONF_COOLDOWN_SECONDS: 300,
        CONF_ENABLE_NOTIFICATION: True,
    }
    data.update(overrides)
    return MockConfigEntry(
        domain=DOMAIN,
        title="Washer",
        data=data,
        unique_id=registry_ids[0],
        version=1,
        minor_version=2,
    )


@pytest.fixture
async def setup_entry(hass: HomeAssistant, plug: Plug, registry_ids):
    """Factory that sets the integration up (power sensor starts at 0 W)."""

    async def _setup(power: str = "0", **overrides) -> MockConfigEntry:
        hass.states.async_set(POWER, power)
        entry = make_entry(registry_ids, **overrides)
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    return _setup
