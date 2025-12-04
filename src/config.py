# FILE: config.py

DEVICE_NAME = "kandiyohi_pi_rak"
SERIAL_PORT = "/dev/ttyUSB0"  # Update if RAK3172 is on a different port

MAX_RETRIES = 5
INTERVAL_MINUTES = 0.25

# Timing settings
READ_INTERVAL_SECONDS = 10        # How often to check the depth (in seconds)
SEND_INTERVAL_MINUTES = INTERVAL_MINUTES  # Mirror existing setting for compatibility

# Hardware configuration
RELAY_PORT = "/dev/rakradio"      # USB relay control port
RESISTOR_OHMS = 250              # Resistor value in ohms for mA conversion
MAX_DEPTH_FT = 10.0              # Max measurable depth (based on sensor)

DEPTH_SCALING_FACTOR = 1.064  # Reset for recalibration with sensor in air

# Path to setpoints JSON file
SETPOINTS_FILE = "/home/pi/setpoints.json"

LOCAL_ROOT_DIR = "/home/pi"

LOG_DIR = LOCAL_ROOT_DIR + "/logs"

ALARM_RELAY_PIN = 17 # TODO: IS THIS THE SAME AS THE GPIO PIN BELOW?
ALARM_GPIO_PIN = 17           # Panel alarm LED
# We now talk directly to the Numato relay on /dev/ttyACM0 everywhere.
RELAY_DEV = "/dev/ttyACM0"
