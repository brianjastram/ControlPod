# FILE: config.py

DEVICE_NAME = "kandiyohi_pi_rak"
SERIAL_PORT = "/dev/ttyUSB0"  # Update if RAK3172 is on a different port

MAX_RETRIES = 5
INTERVAL_MINUTES = 1.00

# Timing settings
READ_INTERVAL_SECONDS = 1        # How often to check the depth (in seconds)
SEND_INTERVAL_MINUTES = INTERVAL_MINUTES  # Mirror existing setting for compatibility

# Hardware configuration
RELAY_PORT = "/dev/rakradio"      # USB relay control port
RESISTOR_OHMS = 250              # Resistor value in ohms for mA conversion
MAX_DEPTH_FT = 11.5              # Max measurable depth (based on sensor)

DEPTH_SCALING_FACTOR = 1.0 # Reset for recalibration with sensor in air

# Path to setpoints JSON file
SETPOINTS_FILE = "/home/pi/setpoints.json"

LOCAL_ROOT_DIR = "/home/pi"

LOG_DIR = LOCAL_ROOT_DIR + "/logs"

ALARM_GPIO_PIN = 17           # Panel alarm LED
# HEARTBEAT_GPIO_PIN = 27       # Heartbeat LED

# We now talk directly to the Numato pump starter relay on /dev/ttyACM0 everywhere.
RELAY_DEV = "/dev/ttyACM0"

# Default setpoint values
PUMP_START_FEET = 0.9
PUMP_STOP_FEET = 0.8
HI_ALARM_FEET = 9.5
LO_ALARM_FEET = 0.2
SITE_NAME = "8B"
SITE_ID = 0x008B