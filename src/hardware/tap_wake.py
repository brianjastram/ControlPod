"""
Tap-to-wake controller using LIS3DH/LIS3DHTR over I2C.
"""

from __future__ import annotations

import logging
import subprocess
import time
from typing import Optional

try:
    import smbus  # type: ignore
except Exception:  # pragma: no cover - optional runtime dependency
    try:
        import smbus2 as smbus  # type: ignore
    except Exception:
        smbus = None

log = logging.getLogger(__name__)


# LIS3DH registers
CTRL_REG1 = 0x20
CTRL_REG4 = 0x23
CLICK_CFG = 0x38
CLICK_SRC = 0x39
CLICK_THS = 0x3A
TIME_LIMIT = 0x3B
TIME_LATENCY = 0x3C
TIME_WINDOW = 0x3D

# CLICK_SRC bit for double click
CLICK_SRC_DCLICK = 0x20
CLICK_SRC_SCLICK = 0x10

# CLICK_CFG bit mapping (per LIS3DH datasheet)
CLICK_CFG_XS = 0x01
CLICK_CFG_XD = 0x02
CLICK_CFG_YS = 0x04
CLICK_CFG_YD = 0x08
CLICK_CFG_ZS = 0x10
CLICK_CFG_ZD = 0x20
CLICK_CFG_ALL_SINGLE = CLICK_CFG_XS | CLICK_CFG_YS | CLICK_CFG_ZS
CLICK_CFG_ALL_DOUBLE = CLICK_CFG_XD | CLICK_CFG_YD | CLICK_CFG_ZD


class NullTapWake:
    def setup(self) -> bool:
        return False

    def poll(self, now: Optional[float] = None) -> None:
        return

    def close(self) -> None:
        return


class TapWakeController:
    def __init__(
        self,
        i2c_bus: int,
        i2c_addr: int,
        on_seconds: float,
        start_off: bool,
        display_id: Optional[int],
        toggle_on_tap: bool,
        single_wake: bool,
        click_threshold: int,
        time_limit: int,
        time_latency: int,
        time_window: int,
    ) -> None:
        self.i2c_bus = i2c_bus
        self.i2c_addr = i2c_addr
        self.on_seconds = max(1.0, float(on_seconds))
        self.start_off = bool(start_off)
        self.display_id = display_id if display_id is not None and display_id >= 0 else None
        self.toggle_on_tap = bool(toggle_on_tap)
        self.single_wake = bool(single_wake)
        self.click_threshold = int(click_threshold) & 0x7F
        self.time_limit = int(time_limit) & 0xFF
        self.time_latency = int(time_latency) & 0xFF
        self.time_window = int(time_window) & 0xFF

        self._bus = None
        self._display_on = False
        self._off_at = 0.0

    def setup(self) -> bool:
        if smbus is None:
            log.warning("[TAP] smbus not available; install python3-smbus or pip install smbus2.")
            return False
        try:
            self._bus = smbus.SMBus(self.i2c_bus)
            # 100 Hz, enable X/Y/Z
            self._bus.write_byte_data(self.i2c_addr, CTRL_REG1, 0x57)
            # High-resolution + BDU, ±2g
            self._bus.write_byte_data(self.i2c_addr, CTRL_REG4, 0x88)
            # Enable double-click on X/Y/Z; optionally enable single-click too.
            click_cfg = CLICK_CFG_ALL_DOUBLE
            if self.single_wake:
                click_cfg |= CLICK_CFG_ALL_SINGLE
            self._bus.write_byte_data(self.i2c_addr, CLICK_CFG, click_cfg)
            # Latch click (bit 7) + threshold
            self._bus.write_byte_data(
                self.i2c_addr, CLICK_THS, 0x80 | self.click_threshold
            )
            # Tap timing windowing (tune per enclosure)
            self._bus.write_byte_data(self.i2c_addr, TIME_LIMIT, self.time_limit)
            self._bus.write_byte_data(self.i2c_addr, TIME_LATENCY, self.time_latency)
            self._bus.write_byte_data(self.i2c_addr, TIME_WINDOW, self.time_window)
            # Clear any pending click
            self._bus.read_byte_data(self.i2c_addr, CLICK_SRC)
        except Exception as e:
            log.error(f"[TAP] LIS3DH init failed: {e}")
            self._bus = None
            return False

        if self.start_off:
            self._set_display_power(False)
        log.info(
            "[TAP] LIS3DH ready (addr=0x%02X bus=%s threshold=0x%02X).",
            self.i2c_addr,
            self.i2c_bus,
            self.click_threshold,
        )
        return True

    def _set_display_power(self, on: bool) -> None:
        cmd = ["vcgencmd", "display_power", "1" if on else "0"]
        if self.display_id is not None:
            cmd.append(str(self.display_id))
        try:
            subprocess.run(cmd, check=False, capture_output=True, text=True)
        except Exception as e:
            log.error(f"[TAP] display_power command failed: {e}")
            return

        self._display_on = on
        if on:
            self._off_at = time.time() + self.on_seconds
        else:
            self._off_at = 0.0

    def poll(self, now: Optional[float] = None) -> None:
        if self._bus is None:
            return
        now = time.time() if now is None else now
        try:
            src = self._bus.read_byte_data(self.i2c_addr, CLICK_SRC)
        except Exception as e:
            log.error(f"[TAP] CLICK_SRC read failed: {e}")
            return

        if src & CLICK_SRC_DCLICK:
            if self.toggle_on_tap and self._display_on:
                self._set_display_power(False)
                log.info("[TAP] Double-tap detected: display OFF (toggle).")
            else:
                self._set_display_power(True)
                log.info("[TAP] Double-tap detected: display ON for %.0fs.", self.on_seconds)
            return

        if self.single_wake and (src & CLICK_SRC_SCLICK):
            self._set_display_power(True)
            log.info("[TAP] Single-tap detected: display ON for %.0fs.", self.on_seconds)

        if self._display_on and self._off_at and now >= self._off_at:
            self._set_display_power(False)
            log.info("[TAP] Display timer expired: display OFF.")

    def close(self) -> None:
        if self._bus is not None:
            try:
                self._bus.close()
            except Exception:
                pass
        self._bus = None


def build_tap_wake(
    enabled: bool,
    i2c_bus: int,
    i2c_addr: int,
    on_seconds: float,
    start_off: bool,
    display_id: Optional[int],
    toggle_on_tap: bool,
    single_wake: bool,
    click_threshold: int,
    time_limit: int,
    time_latency: int,
    time_window: int,
):
    if not enabled:
        return NullTapWake()

    controller = TapWakeController(
        i2c_bus=i2c_bus,
        i2c_addr=i2c_addr,
        on_seconds=on_seconds,
        start_off=start_off,
        display_id=display_id,
        toggle_on_tap=toggle_on_tap,
        single_wake=single_wake,
        click_threshold=click_threshold,
        time_limit=time_limit,
        time_latency=time_latency,
        time_window=time_window,
    )
    if not controller.setup():
        return NullTapWake()
    return controller
