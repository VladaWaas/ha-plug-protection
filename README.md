# 🛡️ Plug Protection

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/VladaWaas/ha-plug-protection?style=for-the-badge)](https://github.com/VladaWaas/ha-plug-protection/releases)
[![License](https://img.shields.io/github/license/VladaWaas/ha-plug-protection?style=for-the-badge)](LICENSE)

**Prevent your smart plug from being turned off while an appliance is running.**

A custom integration for [Home Assistant](https://www.home-assistant.io/) that watches the power consumption of a smart plug and blocks any turn-off attempt (UI, automations, physical button, Zigbee2MQTT, ZHA, other integrations) while the appliance is drawing power.

Requires Home Assistant **2026.3** or newer.

---

## ✨ Features

- **Power-based protection** – active while the power exceeds a configurable threshold
- **Cooldown** – protection stays on for a while after the power drops (pauses between washing-machine phases, a printer cooling down, …). The running cooldown **survives restarts and reloads**
- **Dual-layer protection** – a *protected switch* blocks turn-off from the UI and automations; a state listener catches turn-off from outside (physical button, Z2M, ZHA, …) and turns the plug back on (with retries)
- **Per-plug "Protection enabled" switch** – disable the protection of one plug (and enable it again) without touching the others; the choice survives restarts
- **Robust** – an unavailable power sensor does not drop the protection; renaming the plug or the sensor entity is followed automatically
- **Hides the original plug** (optional) so only the protected switch gets used
- **Clean UI** – entities join the device (and area) of the original plug, translated names, icon and logo, repair issue when an entity disappears
- **Timestamp sensor** for the end of the cooldown (live countdown in the UI) and a `plug_protection_blocked` event
- **UI configuration** incl. *Reconfigure* – no YAML
- English and Czech translations

## 📦 Installation

### HACS

1. HACS → ⋮ → **Custom repositories** → add `VladaWaas/ha-plug-protection` as **Integration**
2. Install **Plug Protection** and restart Home Assistant

### Manual

Copy `custom_components/plug_protection` to `config/custom_components/` and restart.

## ⚙️ Setup

**Settings → Devices & services → Add integration → Plug Protection**, then select

1. the plug (`switch` entity),
2. its power sensor (W),
3. the power threshold, the cooldown and whether notifications should be shown.

Repeat for every plug you want to protect. Threshold, cooldown and notification settings can be changed later under **Configure**; the plug and the power sensor under **Reconfigure** (⋮ menu of the entry).

| Parameter | Default | Description |
|---|---|---|
| Plug switch entity | – | The plug to protect |
| Power sensor | – | Sensor reporting the consumption in W |
| Power threshold | 10 W | Protection is active above this value |
| Cooldown | 300 s | Protection stays on for this long after the power drops (0 = off) |
| Notification | on | Persistent notification when a turn-off is blocked |
| Hide the original plug entity | on (new entries) | Hides the original `switch` in dashboards and entity lists; only the protected switch is meant to be used |
| Report an error when blocked | off | If on, turning the protected switch off fails with an error (an automation stops at that action); if off, the command is silently ignored |

### Recommended thresholds

| Appliance | Threshold | Cooldown |
|---|---|---|
| Washing machine / dishwasher | 5–10 W | 300–600 s |
| Dryer | 10–20 W | 300 s |
| 3D printer | 15–30 W | 120–300 s |
| Robot vacuum | 5–10 W | 120 s |
| NAS / PC | 10–20 W | 60 s |

## 🏗️ Entities

Per protected plug (they appear on the device of the original plug; names are translated):

| Entity | Purpose |
|---|---|
| `switch.<plug>_protected_switch` | Wraps the original plug – use this one in dashboards and automations |
| `switch.<plug>_protection_enabled` | Turns the protection of this plug on/off |
| `sensor.<plug>_protection_status` | `active` / `cooldown` / `idle` / `disabled` (enum, translated in the UI) |
| `sensor.<plug>_cooldown_ends` | Timestamp when the running cooldown ends (diagnostic) |

The protected switch exposes the attributes `original_entity`, `protected`, `protection_enabled`, `protection_state`, `current_power`, `power_threshold`, `cooldown_total`, `cooldown_end` and `last_block_time`.

### Protection logic

```
power > threshold                      → ACTIVE      turn-off is blocked
power ≤ threshold (plug still on)      → COOLDOWN    still blocked until the timer ends
cooldown over                          → IDLE        plug can be turned off
power > threshold during the cooldown  → ACTIVE again
"Protection enabled" switched off      → DISABLED    nothing is blocked or reverted
```

A blocked turn-off that comes from *outside* (e.g. the physical button) has already cut the power for a moment. The integration turns the plug back on (up to 3 attempts), raises a notification if that fails, and runs a full cooldown afterwards because the appliance has just lost power.

If the power sensor is unavailable, the current protection state is kept until it reports again. After a restart the previous state is restored: a running cooldown continues, an appliance that was running is treated as running until the sensor says otherwise.

## 🔘 Physical button and the original entity

Home Assistant cannot intercept a press on the plug's own button or a `switch.turn_off` aimed straight at the original entity. In those cases the plug really turns off for a moment and Plug Protection switches it back on (layer 2), so the appliance sees a short power cut. To avoid it:

- Use the **protected switch** in dashboards, automations and scripts (hiding the original entity helps).
- Turn on the plug's **child lock** (Zigbee2MQTT / ZHA entity `…_child_lock`) – the physical button then does nothing.

## 🛠️ Services

Both services take the protected switch (or the "Protection enabled" switch) of a plug as the target.

```yaml
action: plug_protection.force_off          # turn the plug off, ignoring the protection
target:
  entity_id: switch.washer_protected_switch
```

```yaml
action: plug_protection.reset_cooldown     # end a running cooldown now
target:
  entity_id: switch.washer_protected_switch
```

## 🔔 Event

Every blocked turn-off fires `plug_protection_blocked` with `entity_id`, `name`, `source` (`state_change` or `protected_switch`), `power` and `protection_state`.

```yaml
triggers:
  - trigger: event
    event_type: plug_protection_blocked
actions:
  - action: notify.mobile_app_phone
    data:
      message: "{{ trigger.event.data.name }}: turn-off blocked ({{ trigger.event.data.power }} W)"
```

## 📊 Examples

Notify when the appliance is done:

```yaml
triggers:
  - trigger: state
    entity_id: sensor.washer_protection_status
    from: cooldown
    to: idle
actions:
  - action: notify.mobile_app_phone
    data:
      message: "The washing machine has finished."
```

Dashboard:

```yaml
type: entities
entities:
  - switch.washer_protected_switch
  - switch.washer_protection_enabled
  - sensor.washer_protection_status
  - sensor.washer_cooldown_ends
```

## 🆘 Troubleshooting

```yaml
logger:
  default: warning
  logs:
    custom_components.plug_protection: debug
```

- **Protection does not activate** – check that the power sensor reports W and that the threshold is not too high (Developer tools → States).
- **The plug switches back on after pressing its button** – intended while the protection is active. Use `plug_protection.force_off`, switch the *Protection enabled* switch off or wait for the appliance to finish.
- **Stuck in cooldown** – call `plug_protection.reset_cooldown`.
- **Repair issue "entity not found"** – the plug or power sensor was removed or replaced; use *Reconfigure*.

## ⬆️ Upgrading from 1.1

See [CHANGELOG.md](CHANGELOG.md): services use an entity target now, the status sensor has lowercase enum states, `cooldown_remaining` was replaced by `cooldown_end`, and the entities move to the device of the original plug. Existing entries are migrated automatically.

## 🧪 Development

```bash
pip install -r requirements_test.txt
pytest
```

## 📄 License

Apache License 2.0 – see [LICENSE](LICENSE).
