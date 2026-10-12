"""Constants for the SR655 Fan Control integration."""

from datetime import timedelta

DOMAIN = "sr655_fan_control"

CONF_TOPIC_PREFIX = "topic_prefix"
CONF_PRESENCE_ENTITY = "presence_entity"
CONF_AWAY_DELAY = "away_delay"
CONF_HEARTBEAT = "heartbeat_interval"

# Topics are derived from one prefix and match the defaults of the NAS-side package.
DEFAULT_TOPIC_PREFIX = "homeassistant/sr655"
DEFAULT_AWAY_DELAY = 10  # minutes
DEFAULT_HEARTBEAT = 30  # seconds
# The controller falls back to its fallback profile after 120 s without a request,
# so the heartbeat must leave room for lost messages.
MIN_HEARTBEAT = 5
MAX_HEARTBEAT = 60

# Without telemetry for this long the NAS is treated as gone.
TELEMETRY_STALE = timedelta(seconds=120)

MODE_AUTO = "auto"
MODE_QUIET = "quiet"
MODE_NORMAL = "normal"
MODES = [MODE_AUTO, MODE_QUIET, MODE_NORMAL]
PROFILES = [MODE_QUIET, MODE_NORMAL]

# Entity states that mean "someone is home".
HOME_STATES = frozenset({"on", "home"})
PRESENCE_DOMAINS = ["binary_sensor", "person", "device_tracker", "group", "input_boolean"]

SENSOR_LABELS = {"cpu": "CPU", "hdd": "HDD", "nvme": "NVMe"}


def command_topic(prefix: str) -> str:
    return f"{prefix}/profile/set"


def state_topic(prefix: str) -> str:
    return f"{prefix}/profile"


def availability_topic(prefix: str) -> str:
    return f"{prefix}/availability"


def telemetry_topic(prefix: str) -> str:
    return f"{prefix}/telemetry"
