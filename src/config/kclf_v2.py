# KCLF v2 placeholder (RS485 / Waveshare AI485 etc.)
# Currently inherits v1 values; override hardware selectors as wiring matures.

from .kclf_v1 import *

MODE_NAME = "kclf_v2"

# Hardware selectors
# NOTE: switch back to "rs485" when the RS485 adapter is connected.
DEPTH_SENSOR_IMPL = "ads1115"
PUMP_DRIVER = "numato_serial"
ALARM_DRIVER = "gpio"
RADIO_DRIVER = "rak3172"

# RS485 / Waveshare AI485 settings
AI485_PORT = "/dev/ttyUSB1"     # Primary USB-to-RS485 adapter port
AI485_PORT_CANDIDATES = ["/dev/ttyUSB1", "/dev/ttyUSB2", "/dev/ttyUSB3"]
AI485_BAUD = 9600
AI485_DEVICE_ID = 1            # Modbus address
AI485_CHANNEL = 0              # 0-7 (registers 0x0000-0x0007 map to CH1-CH8)
AI485_RAW_MAX = 20000          # Raw output in microamps for 0-20 mA or 4-20 mA modes
AI485_MAX_MA = 20.0
AI485_MIN_MA = 4.0
AI485_DATA_TYPE = 0x0003       # 4-20 mA mode per datasheet
AI485_SET_MODE_ON_BOOT = True  # Write data type on startup

# Radio and pump port fallbacks (USB hub friendly)
SERIAL_PORT = "/dev/rak"
RAK_PORT_CANDIDATES = ["/dev/rak", "/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyAMA0"]
RELAY_PORT = "/dev/rakradio"
RELAY_DEV = "/dev/ttyACM0"
RELAY_PORT_CANDIDATES = ["/dev/ttyACM0", "/dev/ttyACM1", "/dev/ttyUSB2", "/dev/ttyUSB3"]

# USB / local paths (override if your mount point differs)
USB_MOUNT_PATH = "/media/usb"
LOCAL_SETPOINTS_FILE = "/home/pi/setpoints.json"
USB_SETPOINTS_FILE = "/media/usb/setpoints.json"

__all__ = [name for name in globals().keys() if name.isupper() or name.endswith("_IMPL")]
