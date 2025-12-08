import logging
import serial           # if used there
import RPi.GPIO as GPIO
from src.config import RELAY_DEV, ALARM_GPIO_PIN

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Relay helpers
# ---------------------------------------------------------------------------

def send_relay_command(command: str) -> None:
    """
    Send a Numato-style relay command using /dev/ttyACM0.

    Examples:
        relay on 0
        relay off 0
        relay read 0
    """
    try:
        cmd = (command + "\r").encode()
        with serial.Serial(RELAY_DEV, 9600, timeout=1) as ser:
            ser.write(cmd)
        log.info(f"[RELAY] Sent '{command}' to {RELAY_DEV}")
    except Exception as e:
        log.error(f"[RELAY] Serial error on {RELAY_DEV}: {e}")


def turn_pump_on() -> None:
    send_relay_command("relay on 0")
    log.info("[PUMP] Pump turned ON")


def turn_pump_off() -> None:
    send_relay_command("relay off 0")
    log.info("[PUMP] Pump turned OFF")


def is_pump_on() -> bool:
    """
    Try to query relay state. Returns True if the relay reports ON, else False.

    Note: Numato's response format can be odd; this is best-effort and
    not relied on for normal runtime control (we track state in software).
    """
    try:
        with serial.Serial(RELAY_DEV, 9600, timeout=1) as ser:
            ser.write(b"relay read 0\r")
            response = ser.readline().decode(errors="ignore").strip().lower()
        log.info(f"[RELAY] State response: '{response}'")
        return "on" in response
    except Exception as e:
        log.error(f"[RELAY] State-check error: {e}")
        return False


def set_alarm_light_hw(state: bool) -> None:
    """
    Drive the panel alarm LED on GPIO17 only.
    """
    try:
        GPIO.output(ALARM_GPIO_PIN, GPIO.HIGH if state else GPIO.LOW)
        log.info(f"[ALARM] Alarm {'ON' if state else 'OFF'}")
    except Exception as e:
        log.error(f"[ALARM] Failed to set alarm state: {e}")
