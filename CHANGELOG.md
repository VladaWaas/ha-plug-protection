# Changelog

## 1.3.0

### New
- **Hide the original plug entity** (new option, on by default for new entries): the original `switch` is hidden in dashboards and entity lists so that only the protected switch is used. Only the "hidden by integration" flag is managed – an entity you hid or unhid yourself is never touched. The entity is shown again when you turn the option off or delete the entry. Existing entries keep the plug visible until you enable the option under **Configure**.

## 1.2.0

### New
- **"Protection enabled" switch** per plug – turns the protection of one plug off and on without touching the others. The state survives restarts. While disabled the status is `disabled`, nothing is blocked or reverted.
- Brand images (`custom_components/plug_protection/brand/`) – the integration finally has an icon and logo in Home Assistant (HA 2026.3+), including dark variants.
- **Cooldown end** timestamp sensor – shows a live countdown in the UI.
- `plug_protection_blocked` event fired whenever a turn-off is blocked (use it for your own notifications).
- Optional "report an error when a turn-off is blocked" setting (default off = old behaviour).
- Reconfigure flow – change the protected plug or its power sensor without deleting the entry.
- Repair issue when a configured entity no longer exists.
- Notifications are translated (English / Czech).

### Fixed
- An unavailable power sensor is no longer read as 0 W; protection is held until the sensor reports again.
- Protection state and a running cooldown now survive Home Assistant restarts and reloads.
- A power dip caused by the blocked turn-off itself no longer resets protection to idle.
- The revert after a blocked turn-off is retried (3×) and a notification is raised if it fails.
- Renaming the plug or the sensor entity no longer silently disables the protection (entity registry IDs are stored).
- Status sensor and protected switch become unavailable together with the plug.
- Timestamps are timezone-aware (UTC).
- `current_power` attribute is refreshed on every power update; volatile attributes are excluded from the recorder.
- Cooldown can be set to any number of seconds (previously steps of 30).

### Changed (breaking)
- **Services** `force_off` and `reset_cooldown` now target the protected switch (or the "Protection enabled" switch) of a plug as an entity target instead of the `original_entity` field.
- **Status sensor** is now an enum sensor: its states are `active`, `cooldown`, `idle`, `disabled` (shown translated). Automations comparing with `"Active"` / `"Cooldown"` / `"Idle"` must use the lowercase values.
- Attribute `cooldown_remaining` was removed – use the **Cooldown end** sensor / `cooldown_end` attribute.
- Entities are attached to the device of the original plug (and inherit its area) instead of a separate "Plug Protection" device. Entity names are translated ("Protected switch" / "Chráněný vypínač", …).
- Minimum Home Assistant version is 2026.3.0.
- Integration type is `helper`.
