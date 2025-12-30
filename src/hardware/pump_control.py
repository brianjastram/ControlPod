"""
Pump/relay and alarm light hardware helpers.
"""

import logging
import serial
import RPi.GPIO as GPIO

log = logging.getLogger(__name__)


class PumpController:
    def turn_on(self) -> None:
        raise NotImplementedError

    def turn_off(self) -> None:
        raise NotImplementedError

    def is_on(self) -> bool:
        raise NotImplementedError

    def set_alarm_light(self, state: bool) -> None:
        raise NotImplementedError


class NumatoPumpController(PumpController):
    def __init__(self, relay_dev: str, alarm_gpio_pin: int):
        self.relay_dev = relay_dev
        self.alarm_gpio_pin = alarm_gpio_pin

        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.alarm_gpio_pin, GPIO.OUT)
        GPIO.output(self.alarm_gpio_pin, GPIO.LOW)

    def _send_relay_command(self, command: str) -> None:
        try:
            cmd = (command + "\r").encode()
            with serial.Serial(self.relay_dev, 9600, timeout=1) as ser:
                ser.write(cmd)
            log.info(f"[RELAY] Sent '{command}' to {self.relay_dev}")
        except Exception as e:
            log.error(f"[RELAY] Serial error on {self.relay_dev}: {e}")

    def turn_on(self) -> None:
        self._send_relay_command("relay on 0")
        log.info("[PUMP] Pump turned ON")

    def turn_off(self) -> None:
        self._send_relay_command("relay off 0")
        log.info("[PUMP] Pump turned OFF")

    def is_on(self) -> bool:
        try:
            with serial.Serial(self.relay_dev, 9600, timeout=1) as ser:
                ser.write(b"relay read 0\r")
                response = ser.readline().decode(errors="ignore").strip().lower()
            log.info(f"[RELAY] State response: '{response}'")
            return "on" in response
        except Exception as e:
            log.error(f"[RELAY] State-check error: {e}")
            return False

    def set_alarm_light(self, state: bool) -> None:
        try:
            GPIO.output(self.alarm_gpio_pin, GPIO.HIGH if state else GPIO.LOW)
            log.info(f"[ALARM] Alarm {'ON' if state else 'OFF'} (GPIO{self.alarm_gpio_pin})")
        except Exception as e:
            log.error(f"[ALARM] Failed to set alarm state: {e}")


def build_pump_controller(driver: str, relay_dev: str, alarm_gpio_pin: int) -> PumpController:
    if driver == "numato_serial":
        return NumatoPumpController(relay_dev, alarm_gpio_pin)
    raise ValueError(f"Unknown pump driver: {driver}")
