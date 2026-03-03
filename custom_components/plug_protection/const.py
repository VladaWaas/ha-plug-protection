"""Constants for the Plug Protection integration."""

DOMAIN = "plug_protection"

# ── Config keys ──────────────────────────────────────────────
CONF_PLUG_ENTITY = "plug_entity"
CONF_POWER_SENSOR = "power_sensor"
CONF_POWER_THRESHOLD = "power_threshold"
CONF_COOLDOWN_SECONDS = "cooldown_seconds"
CONF_ENABLE_NOTIFICATION = "enable_notification"

# ── Defaults ─────────────────────────────────────────────────
DEFAULT_POWER_THRESHOLD = 10  # Watts
DEFAULT_COOLDOWN_SECONDS = 300  # 5 minutes
DEFAULT_ENABLE_NOTIFICATION = True

# ── Services ─────────────────────────────────────────────────
SERVICE_FORCE_OFF = "force_off"
SERVICE_RESET_COOLDOWN = "reset_cooldown"

# ── Attributes ───────────────────────────────────────────────
ATTR_PROTECTED = "protected"
ATTR_CURRENT_POWER = "current_power"
ATTR_POWER_THRESHOLD = "power_threshold"
ATTR_COOLDOWN_REMAINING = "cooldown_remaining"
ATTR_COOLDOWN_TOTAL = "cooldown_total"
ATTR_PROTECTION_STATE = "protection_state"
ATTR_ORIGINAL_ENTITY = "original_entity"
ATTR_LAST_BLOCK_TIME = "last_block_time"

# ── Protection states ────────────────────────────────────────
STATE_ACTIVE = "active"
STATE_COOLDOWN = "cooldown"
STATE_IDLE = "idle"

# ── Platforms ────────────────────────────────────────────────
PLATFORMS = ["switch", "sensor"]
