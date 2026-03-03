# 🛡️ Plug Protection

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/VladaWaas/ha-plug-protection?style=for-the-badge)](https://github.com/VladaWaas/ha-plug-protection/releases)
[![License](https://img.shields.io/github/license/VladaWaas/ha-plug-protection?style=for-the-badge)](LICENSE)

**Prevent your smart plug from being turned off while an appliance is running.**

A custom component for [Home Assistant](https://www.home-assistant.io/) that monitors power consumption on a smart plug and blocks any turn-off attempt (from UI, automations, physical button, or other integrations) when the appliance is actively consuming power.

---

## ✨ Features

- **Power-based protection** – monitors real-time power consumption and activates protection when it exceeds a configurable threshold
- **Cooldown timer** – after power drops below the threshold, protection stays active for a configurable duration (protects against pauses between appliance cycles, e.g. washing machine between rinse phases)
- **Dual-layer protection** – a protected switch entity blocks turn-off from UI/automations, while a state listener catches direct turn-off from physical buttons, Zigbee2MQTT, ZHA, or other sources
- **UI configuration** – full setup through the Home Assistant UI, no YAML needed
- **Adjustable settings** – change threshold, cooldown, and notification preferences at any time through the options flow
- **Force-off service** – `plug_protection.force_off` to override protection when you really need to
- **HACS compatible** – install and update through the Home Assistant Community Store
- **Multilingual** – English and Czech translations included

## 📦 Installation

### HACS (recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu → **Custom repositories**
3. Add `VladaWaas/ha-plug-protection` as an **Integration**
4. Search for "Plug Protection" and install it
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/plug_protection` directory into your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

## ⚙️ Setup

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **Plug Protection**
3. Select your smart plug switch entity
4. Select the corresponding power sensor
5. Set the power threshold and cooldown duration
6. Done! ✅

### Configuration Options

| Parameter | Default | Description |
|---|---|---|
| **Plug switch entity** | — | The switch entity of the smart plug to protect |
| **Power sensor** | — | Sensor reporting current power consumption (W) |
| **Power threshold** | 10 W | Protection activates when power exceeds this value |
| **Cooldown** | 300 s | After power drops, protection stays active for this duration |
| **Notifications** | On | Show persistent notification when turn-off is blocked |

All settings except the plug and sensor entities can be changed after setup through **Settings** → **Devices & Services** → **Plug Protection** → **Configure**.

### Recommended Thresholds

| Appliance | Threshold | Cooldown |
|---|---|---|
| Washing machine | 5–10 W | 300–600 s |
| Dishwasher | 5–10 W | 300–600 s |
| Dryer | 10–20 W | 300 s |
| 3D printer | 15–30 W | 120–300 s |
| Robot vacuum | 5–10 W | 120 s |
| NAS / PC | 10–20 W | 60 s |

## 🏗️ How It Works

When you add a protected plug, the integration creates:

| Entity | Purpose |
|---|---|
| `switch.protection_<name>_protected_switch` | Wraps the original plug – use this in your dashboard |
| `sensor.protection_<name>_protection_status` | Shows: Active / Cooldown / Idle |

### Protection Logic

```
Power rises above threshold
  → Protection state: ACTIVE
  → Any turn-off attempt is blocked and reverted

Power drops below threshold (plug still ON)
  → Protection state: COOLDOWN
  → Timer starts counting down
  → Turn-off still blocked during cooldown

Cooldown timer expires
  → Protection state: IDLE
  → Plug can be turned off normally

Power rises again during cooldown
  → Cooldown cancelled
  → Back to ACTIVE
```

### Dual-Layer Protection

**Layer 1 – Protected Switch Entity:**
When you (or an automation) toggle the protected switch off, the `turn_off` method checks protection state before forwarding the command to the original plug. If protected, the command is silently dropped and a notification is shown.

**Layer 2 – State Change Listener:**
The integration also watches the original plug entity for state changes. If something turns it off directly (physical button, Zigbee command, another automation targeting the original entity), the integration immediately turns it back on.

## 🛠️ Services

### `plug_protection.force_off`

Force turn off a protected plug, bypassing all protection. The protection state resets to idle.

```yaml
service: plug_protection.force_off
data:
  original_entity: switch.washing_machine_plug
```

### `plug_protection.reset_cooldown`

Cancel the cooldown timer and transition to idle. The plug can then be turned off normally.

```yaml
service: plug_protection.reset_cooldown
data:
  original_entity: switch.washing_machine_plug
```

## 📊 Dashboard Examples

### Minimal (no custom cards needed)

```yaml
type: entities
title: "🔌 Washing Machine"
entities:
  - entity: switch.protection_washing_machine_protected_switch
    name: Plug
  - entity: sensor.protection_washing_machine_protection_status
    name: Protection
state_color: true
```

### Mushroom Cards

```yaml
type: vertical-stack
cards:
  - type: custom:mushroom-entity-card
    entity: switch.protection_washing_machine_protected_switch
    name: Washing Machine
    icon: mdi:washing-machine
    tap_action:
      action: toggle
    layout: horizontal

  - type: custom:mushroom-chips-card
    chips:
      - type: entity
        entity: sensor.washing_machine_plug_power
        icon: mdi:flash
      - type: template
        entity: sensor.protection_washing_machine_protection_status
        icon: |-
          {% set s = states('sensor.protection_washing_machine_protection_status') %}
          {% if s == 'Active' %}mdi:shield-lock
          {% elif s == 'Cooldown' %}mdi:timer-sand
          {% else %}mdi:shield-off-outline{% endif %}
        content: "{{ states('sensor.protection_washing_machine_protection_status') }}"
        icon_color: |-
          {% set s = states('sensor.protection_washing_machine_protection_status') %}
          {% if s == 'Active' %}red
          {% elif s == 'Cooldown' %}orange
          {% else %}green{% endif %}
```

### Using the Protected Switch Attributes

The protected switch exposes useful attributes:

| Attribute | Example | Description |
|---|---|---|
| `protected` | `true` | Whether the plug is currently protected |
| `protection_state` | `active` | Current state: active / cooldown / idle |
| `current_power` | `245.3` | Current power in watts |
| `power_threshold` | `10` | Configured threshold |
| `cooldown_remaining` | `180` | Remaining cooldown in seconds |
| `cooldown_total` | `300` | Configured cooldown duration |
| `original_entity` | `switch.plug` | The wrapped original entity |
| `last_block_time` | `2025-01-15T...` | Timestamp of last blocked attempt |

These attributes can be used in templates, automations, and conditional cards.

## 🔧 Automation Examples

### Notify when appliance finishes

```yaml
automation:
  - alias: "Washing machine finished"
    trigger:
      - platform: state
        entity_id: sensor.protection_washing_machine_protection_status
        from: "Cooldown"
        to: "Idle"
    action:
      - service: notify.mobile_app_phone
        data:
          title: "Washing Machine"
          message: "Cycle finished! You can unload now."
```

### Force-off with confirmation

```yaml
script:
  force_off_washing_machine:
    alias: "Force Off Washing Machine"
    sequence:
      - service: plug_protection.force_off
        data:
          original_entity: switch.washing_machine_plug
```

## 🆘 Troubleshooting

Enable debug logging:

```yaml
logger:
  default: warning
  logs:
    custom_components.plug_protection: debug
```

### Common Issues

**Protection not activating:**
Check that the power sensor reports values in Watts and that the threshold is set correctly. You can verify the current reading in Developer Tools → States.

**Plug turns back on after physical button press:**
This is intended behavior! The state change listener detects the turn-off and reverts it. Use `plug_protection.force_off` service or wait for the appliance to finish.

**Protection stuck in Active/Cooldown:**
Use `plug_protection.reset_cooldown` service to manually reset to idle state.

## 📄 License

This project is licensed under the Apache License 2.0 – see the [LICENSE](LICENSE) file for details.
