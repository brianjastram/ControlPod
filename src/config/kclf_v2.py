# KCLF v2 placeholder (RS485 / Waveshare AI485 etc.)
# Currently inherits v1 values; override hardware selectors as wiring matures.

from .kclf_v1 import *

MODE_NAME = "kclf_v2"

# Hardware selectors
DEPTH_SENSOR_IMPL = "rs485"
PUMP_DRIVER = "numato_serial"
ALARM_DRIVER = "numato_serial"
RADIO_DRIVER = "rak3172"

# Display (HDMI console)
DISPLAY_DRIVER = "framebuffer"
DISPLAY_TTY = "/dev/tty1"
DISPLAY_UPDATE_SECONDS = 1
DISPLAY_TIMEZONE = "America/Chicago"
DISPLAY_FONT = "Lat15-TerminusBold24x12"
DISPLAY_FB = "/dev/fb0"
DISPLAY_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
DISPLAY_FONT_SIZE = 60
DISPLAY_FOREGROUND = "#FFFFFF"
DISPLAY_BACKGROUND = "#000000"
DISPLAY_PADDING = 6
DISPLAY_LINE_SPACING = 2
DISPLAY_FB_PIXEL_ORDER = "RGB"

# Tap-to-wake (LIS3DH/LIS3DHTR over I2C)
TAP_WAKE_ENABLED = True
TAP_WAKE_I2C_BUS = 1
TAP_WAKE_I2C_ADDR = 0x19
TAP_WAKE_ON_SECONDS = 300
TAP_WAKE_START_OFF = True
TAP_WAKE_DISPLAY_ID = None  # HDMI0=2, HDMI1=7, or None for default
TAP_WAKE_TOGGLE = True  # Double-tap while on turns display off
TAP_WAKE_SINGLE_WAKE = False  # Double-tap only

# More sensitive double-tap detection for enclosure mounting.
TAP_WAKE_CLICK_THRESHOLD = 0x06
TAP_WAKE_TIME_LIMIT = 0x10
TAP_WAKE_TIME_LATENCY = 0x10
TAP_WAKE_TIME_WINDOW = 0xA0
# RS485 / Waveshare AI485 settings
AI485_PORT = "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_BG01Q3R0-if00-port0"     # Primary USB-to-RS485 adapter port
AI485_PORT_CANDIDATES = [
    "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_BG01Q3R0-if00-port0",
    "/dev/ttyUSB1",
    "/dev/ttyUSB0",
    "/dev/ttyUSB2",
    "/dev/ttyUSB3",
]
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
RELAY_DEV = "/dev/serial/by-id/usb-Numato_Systems_Pvt._Ltd._Numato_Lab_1_Channel_USB_Powered_Relay_Module_NLRL260101R0557-if00"
RELAY_PORT_CANDIDATES = [
    "/dev/serial/by-id/usb-Numato_Systems_Pvt._Ltd._Numato_Lab_1_Channel_USB_Powered_Relay_Module_NLRL260101R0557-if00",
]
ALARM_RELAY_DEV = "/dev/serial/by-id/usb-Numato_Systems_Pvt._Ltd._Numato_Lab_1_Channel_USB_Powered_Relay_Module_NLRL260101R0556-if00"
ALARM_RELAY_CHANNEL = 0
ALARM_RELAY_PORT_CANDIDATES = [
    "/dev/serial/by-id/usb-Numato_Systems_Pvt._Ltd._Numato_Lab_1_Channel_USB_Powered_Relay_Module_NLRL260101R0556-if00",
]

# USB / local paths (override if your mount point differs)
USB_MOUNT_PATH = "/media/usb"
LOCAL_SETPOINTS_FILE = "/home/pi/setpoints.json"
USB_SETPOINTS_FILE = "/media/usb/setpoints.json"

__all__ = [name for name in globals().keys() if name.isupper() or name.endswith("_IMPL")]

SITE_NAME = "8A"

SITE_ID = 0x008A
