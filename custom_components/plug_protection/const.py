"""Constants for the Plug Protection integration."""

from homeassistant.const import Platform

DOMAIN = "plug_protection"

# ── Config keys ──────────────────────────────────────────────
CONF_PLUG_ENTITY = "plug_entity"
CONF_POWER_SENSOR = "power_sensor"
# Entity registry IDs (UUIDs) – survive entity_id renames
CONF_PLUG_REGISTRY_ID = "plug_registry_id"
CONF_POWER_REGISTRY_ID = "power_registry_id"
CONF_POWER_THRESHOLD = "power_threshold"
CONF_COOLDOWN_SECONDS = "cooldown_seconds"
CONF_ENABLE_NOTIFICATION = "enable_notification"
CONF_RAISE_ON_BLOCK = "raise_on_block"
CONF_HIDE_ORIGINAL = "hide_original"

# ── Defaults ─────────────────────────────────────────────────
DEFAULT_POWER_THRESHOLD = 10  # Watts
DEFAULT_COOLDOWN_SECONDS = 300  # 5 minutes
DEFAULT_ENABLE_NOTIFICATION = True
DEFAULT_RAISE_ON_BLOCK = False
DEFAULT_HIDE_ORIGINAL = True  # for new entries; existing entries keep "off"

# ── Services ─────────────────────────────────────────────────
SERVICE_FORCE_OFF = "force_off"
SERVICE_RESET_COOLDOWN = "reset_cooldown"

# ── Events ───────────────────────────────────────────────────
EVENT_BLOCKED = "plug_protection_blocked"

# ── Attributes ───────────────────────────────────────────────
ATTR_PROTECTED = "protected"
ATTR_ENABLED = "protection_enabled"
ATTR_CURRENT_POWER = "current_power"
ATTR_POWER_THRESHOLD = "power_threshold"
ATTR_COOLDOWN_TOTAL = "cooldown_total"
ATTR_COOLDOWN_END = "cooldown_end"
ATTR_PROTECTION_STATE = "protection_state"
ATTR_ORIGINAL_ENTITY = "original_entity"
ATTR_POWER_SENSOR = "power_sensor"
ATTR_LAST_BLOCK_TIME = "last_block_time"

# ── Protection states ────────────────────────────────────────
STATE_ACTIVE = "active"
STATE_COOLDOWN = "cooldown"
STATE_IDLE = "idle"
STATE_DISABLED = "disabled"  # protection switched off by the user
PROTECTION_STATES = [STATE_ACTIVE, STATE_COOLDOWN, STATE_IDLE, STATE_DISABLED]

# ── Revert (blocked turn-off) behaviour ──────────────────────
REVERT_ATTEMPTS = 3
REVERT_WAIT_SECONDS = 5.0  # how long to wait for the plug to report "on"
REVERT_POLL_SECONDS = 0.5
REVERT_RETRY_DELAY = 1.0  # seconds, multiplied by the attempt number

# ── Storage ──────────────────────────────────────────────────
STORAGE_VERSION = 1
STORAGE_SAVE_DELAY = 1  # seconds

# ── Platforms ────────────────────────────────────────────────
PLATFORMS = [Platform.SWITCH, Platform.SENSOR]

# ── Notification texts (HA has no translation category for them) ──
NOTIFICATION_TITLE = "🛡️ Plug Protection"
NOTIFICATION_TEXTS = {
    "en": {
        "blocked": (
            "Turn-off of **{name}** was blocked!\n\n"
            "Current power: {power} (threshold: {threshold} W)\n\n"
            "Protection state: {state}"
        ),
        "revert_failed": (
            "**{name}** was turned off while protected and Plug Protection "
            "could not turn it back on. Please check the plug!"
        ),
    },
    "cs": {
        "blocked": (
            "Vypnutí zásuvky **{name}** bylo zablokováno!\n\n"
            "Aktuální příkon: {power} (práh: {threshold} W)\n\n"
            "Stav ochrany: {state}"
        ),
        "revert_failed": (
            "Zásuvka **{name}** byla vypnuta, i když byla chráněná, a "
            "Plug Protection ji nedokázala znovu zapnout. Zkontrolujte ji!"
        ),
    },
}
