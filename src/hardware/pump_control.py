"""
Pump/relay and alarm light hardware helpers.
"""

import logging
import os
from typing import Optional

import serial

try:
    import RPi.GPIO as GPIO
except Exception:  # pragma: no cover - optional on non-Pi systems
    GPIO = None

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
    def __init__(
        self,
        relay_dev: str,
        alarm_driver: str = "gpio",
        alarm_gpio_pin: Optional[int] = None,
        alarm_relay_dev: Optional[str] = None,
        alarm_relay_channel: int = 0,
        candidates=None,
        alarm_candidates=None,
    ):
        self.relay_dev = relay_dev
        self.relay_candidates = candidates or []
        self.alarm_driver = alarm_driver or "gpio"
        self.alarm_gpio_pin = alarm_gpio_pin
        self.alarm_relay_dev = alarm_relay_dev
        self.alarm_relay_channel = alarm_relay_channel
        if alarm_candidates is None:
            self.alarm_relay_candidates = list(self.relay_candidates)
        else:
            self.alarm_relay_candidates = list(alarm_candidates)

        if self.alarm_driver == "gpio":
            if GPIO is None:
                log.warning("[ALARM] GPIO library unavailable; alarm output disabled.")
            elif self.alarm_gpio_pin is None:
                log.warning("[ALARM] No ALARM_GPIO_PIN configured; alarm output disabled.")
            else:
                GPIO.setwarnings(False)
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(self.alarm_gpio_pin, GPIO.OUT)
                GPIO.output(self.alarm_gpio_pin, GPIO.LOW)

    def _send_relay_command(self, command: str) -> None:
        try:
            dev = self._resolve_device()
            if dev is None:
                log.warning(f"[RELAY] No relay device available; skipped '{command}'")
                return

            cmd = (command + "\r").encode()
            with serial.Serial(dev, 9600, timeout=1) as ser:
                ser.write(cmd)
            log.info(f"[RELAY] Sent '{command}' to {dev}")
        except Exception as e:
            log.error(f"[RELAY] Serial error on {dev or self.relay_dev}: {e}")

    def _resolve_device(self):
        if os.path.exists(self.relay_dev):
            return self.relay_dev
        for c in self.relay_candidates:
            if os.path.exists(c):
                self.relay_dev = c
                return c
        return None

    def _resolve_alarm_device(self):
        if self.alarm_relay_dev and os.path.exists(self.alarm_relay_dev):
            return self.alarm_relay_dev
        pump_dev = self._resolve_device()
        for c in self.alarm_relay_candidates:
            if not os.path.exists(c):
                continue
            if pump_dev and c == pump_dev:
                continue
            self.alarm_relay_dev = c
            return c
        return None

    def turn_on(self) -> None:
        self._send_relay_command("relay on 0")
        log.info("[PUMP] Pump turned ON")

    def turn_off(self) -> None:
        self._send_relay_command("relay off 0")
        log.info("[PUMP] Pump turned OFF")

    def is_on(self) -> bool:
        dev = self._resolve_device()
        if dev is None:
            log.warning("[RELAY] No relay device available for state check.")
            return False
        try:
            with serial.Serial(dev, 9600, timeout=1) as ser:
                ser.write(b"relay read 0\r")
                response = ser.readline().decode(errors="ignore").strip().lower()
            log.info(f"[RELAY] State response: '{response}'")
            return "on" in response
        except Exception as e:
            log.error(f"[RELAY] State-check error: {e}")
            return False

    def set_alarm_light(self, state: bool) -> None:
        if self.alarm_driver == "numato_serial":
            command = f"relay {'on' if state else 'off'} {self.alarm_relay_channel}"
            try:
                dev = self._resolve_alarm_device()
                if dev is None:
                    log.warning(f"[ALARM] No alarm relay device available; skipped '{command}'")
                    return
                cmd = (command + "\r").encode()
                with serial.Serial(dev, 9600, timeout=1) as ser:
                    ser.write(cmd)
                log.info(
                    f"[ALARM] Alarm {'ON' if state else 'OFF'} "
                    f"(relay {self.alarm_relay_channel} @ {dev})"
                )
            except Exception as e:
                log.error(f"[ALARM] Serial error on {dev or self.alarm_relay_dev}: {e}")
            return

        if self.alarm_driver == "gpio":
            if GPIO is None or self.alarm_gpio_pin is None:
                log.warning("[ALARM] GPIO alarm unavailable; skipped.")
                return
            try:
                GPIO.output(self.alarm_gpio_pin, GPIO.HIGH if state else GPIO.LOW)
                log.info(f"[ALARM] Alarm {'ON' if state else 'OFF'} (GPIO{self.alarm_gpio_pin})")
            except Exception as e:
                log.error(f"[ALARM] Failed to set alarm state: {e}")
            return

        log.warning(f"[ALARM] Unknown alarm driver '{self.alarm_driver}'; alarm output disabled.")


def build_pump_controller(
    driver: str,
    relay_dev: str,
    alarm_gpio_pin: Optional[int],
    relay_candidates=None,
    alarm_driver: str = "gpio",
    alarm_relay_dev: Optional[str] = None,
    alarm_relay_channel: int = 0,
    alarm_candidates=None,
) -> PumpController:
    if driver == "numato_serial":
        return NumatoPumpController(
            relay_dev,
            alarm_driver=alarm_driver,
            alarm_gpio_pin=alarm_gpio_pin,
            alarm_relay_dev=alarm_relay_dev,
            alarm_relay_channel=alarm_relay_channel,
            candidates=relay_candidates,
            alarm_candidates=alarm_candidates,
        )
    raise ValueError(f"Unknown pump driver: {driver}")
