# FILE: control.py

import logging
import os

import RPi.GPIO as GPIO
from src.usb_settings import log_override_change
from src.config import (ALARM_GPIO_PIN, LOCAL_ROOT_DIR)

log = logging.getLogger(__name__)

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(ALARM_GPIO_PIN, GPIO.OUT)

# Persistent override flag file (real path on the Pi)
# Result: /home/pi/ControlPod/resources/override_flag.txt
OVERRIDE_FILE = os.path.join(LOCAL_ROOT_DIR, "ControlPod", "resources", "override_flag.txt")

# Ensure the directory exists so we can write the flag file
os.makedirs(os.path.dirname(OVERRIDE_FILE), exist_ok=True)

# ---------------------------------------------------------------------------
# OVERRIDE FLAG (persistent)
# ---------------------------------------------------------------------------
override_flag = False

# ---------------------------------------------------------------------------
# PUMP STATE (in-memory only, replaces unreliable relay-read)
# ---------------------------------------------------------------------------
pump_on_state = False

_alarm_state = False


def set_pump_state(state: bool):
    """
    Update the pump's state internally.
    The relay hardware cannot report its own state,
    so we must track it in software.
    """
    global pump_on_state
    pump_on_state = state


def get_pump_state() -> bool:
    """
    Return the last known pump state (True=ON, False=OFF).
    """
    return pump_on_state

# ---------------------------------------------------------------------------
# OVERRIDE LOGIC
# ---------------------------------------------------------------------------

def toggle_override(state: bool):
    """
    Enable/disable override AND persist to disk.
    """
    global override_flag
    override_flag = state
    try:
        with open(OVERRIDE_FILE, "w") as f:
            f.write("1" if state else "0")
        log_override_change(state, source="downlink")
        log.info(f"[CONTROL] Override {'ON' if state else 'OFF'} via toggle_override()")
    except Exception as e:
        log.error(f"[CONTROL] Failed to toggle override: {e}")


def is_override_active() -> bool:
    """
    Override flag (file-backed so main loop sees updates).
    """
    try:
        with open(OVERRIDE_FILE, "r") as f:
            return f.read().strip() == "1"
    except FileNotFoundError:
        return override_flag
    except Exception as e:
        log.error(f"[CONTROL] Failed to read override flag: {e}")
        return override_flag


def set_override_flag(state: bool):
    """
    Runtime override change (logged, not persisted).
    """
    global override_flag
    if override_flag == state:
        return
    override_flag = state
    try:
        log_override_change(state, source="runtime")
    except Exception as e:
        log.error(f"Failed to log override change: {e}")

# ---------------------------------------------------------------------------
# ALARM LIGHT
# ---------------------------------------------------------------------------

def set_alarm_light(state: bool) -> None:
    global _alarm_state

    if state == _alarm_state:
        return

    _alarm_state = state

    try:
        GPIO.output(ALARM_GPIO_PIN, GPIO.HIGH if state else GPIO.LOW)
        log.info(f"[ALARM] Alarm {'ON' if state else 'OFF'} (GPIO17)")
    except Exception as e:
        log.error(f"Failed to set alarm light: {e}")

# ---------------------------------------------------------------------------
# ALARM HELPERS
# ---------------------------------------------------------------------------

def check_hi_alarm(depth, hi_alarm_setpoint):
    triggered = depth > hi_alarm_setpoint
    log.debug(f"[ALARM EVAL] Depth={depth}, HI_ALARM={hi_alarm_setpoint}, Triggered={triggered}")
    return triggered
