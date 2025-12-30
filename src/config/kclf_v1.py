# KCLF v1 (current hardware: ADS1115 depth, Numato relay, RAK3172)

from .base import LOCAL_ROOT_DIR, LOG_DIR

# Mode metadata / selectors
MODE_NAME = "kclf_v1"
DEPTH_SENSOR_IMPL = "ads1115"
PUMP_DRIVER = "numato_serial"
ALARM_DRIVER = "gpio"
RADIO_DRIVER = "rak3172"

# Device identity
DEVICE_NAME = "kandiyohi_pi_rak"
SITE_NAME = "8B"
SITE_ID = 0x008B

# Timing
INTERVAL_MINUTES = 1.00
READ_INTERVAL_SECONDS = 1  # How often to check depth (seconds)
SEND_INTERVAL_MINUTES = INTERVAL_MINUTES

# Retry limits
MAX_RETRIES = 5

# Hardware configuration
SERIAL_PORT = "/dev/ttyUSB0"  # RAK3172 port (if different, override here)
RELAY_PORT = "/dev/rakradio"  # Legacy name; Numato relay on /dev/ttyACM0
RELAY_DEV = "/dev/ttyACM0"
ALARM_GPIO_PIN = 17  # Panel alarm LED
# HEARTBEAT_GPIO_PIN = 27

# Depth conversion
RESISTOR_OHMS = 250
MAX_DEPTH_FT = 11.5
DEPTH_SCALING_FACTOR = 1.0

# Defaults for setpoints
PUMP_START_FEET = 0.9
PUMP_STOP_FEET = 0.8
HI_ALARM_FEET = 9.5
LO_ALARM_FEET = 0.2

# Files / paths
SETPOINTS_FILE = "/home/pi/setpoints.json"

__all__ = [
    "MODE_NAME",
    "DEPTH_SENSOR_IMPL",
    "PUMP_DRIVER",
    "ALARM_DRIVER",
    "RADIO_DRIVER",
    "DEVICE_NAME",
    "SITE_NAME",
    "SITE_ID",
    "INTERVAL_MINUTES",
    "READ_INTERVAL_SECONDS",
    "SEND_INTERVAL_MINUTES",
    "MAX_RETRIES",
    "SERIAL_PORT",
    "RELAY_PORT",
    "RELAY_DEV",
    "ALARM_GPIO_PIN",
    "RESISTOR_OHMS",
    "MAX_DEPTH_FT",
    "DEPTH_SCALING_FACTOR",
    "PUMP_START_FEET",
    "PUMP_STOP_FEET",
    "HI_ALARM_FEET",
    "LO_ALARM_FEET",
    "SETPOINTS_FILE",
    "LOCAL_ROOT_DIR",
    "LOG_DIR",
]
