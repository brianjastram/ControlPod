"""
Display helpers for ControlPod (HDMI/console output).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


def _ft_to_in(value: float) -> float:
    return value * 12.0


@dataclass
class DisplayStatus:
    site_name: str
    depth_ft: float
    pump_on: bool
    alarm_on: bool
    stop_ft: float
    start_ft: float
    hi_alarm_ft: float
    override: bool


class NullDisplay:
    def update(self, status: DisplayStatus) -> None:
        return

    def close(self) -> None:
        return


class ConsoleDisplay:
    def __init__(self, tty: str = "/dev/tty1") -> None:
        self.tty = tty
        self._fp: Optional[object] = None
        try:
            self._fp = open(self.tty, "w", buffering=1)
        except Exception as e:
            log.error(f"[DISPLAY] Failed to open {self.tty}: {e}")

    def _write(self, text: str) -> None:
        if not self._fp:
            return
        try:
            self._fp.write(text)
            self._fp.flush()
        except Exception as e:
            log.error(f"[DISPLAY] Write failed: {e}")

    def update(self, status: DisplayStatus) -> None:
        depth_in = _ft_to_in(status.depth_ft)
        start_in = _ft_to_in(status.start_ft)
        stop_in = _ft_to_in(status.stop_ft)
        hi_alarm_in = _ft_to_in(status.hi_alarm_ft)

        lines = [
            f"Site: {status.site_name}",
            f"Depth: {depth_in:.1f} in",
            f"Pump: {'ON' if status.pump_on else 'OFF'}",
            f"Alarm: {'ON' if status.alarm_on else 'OFF'}",
            f"Stop: {stop_in:.1f} in",
            f"Start: {start_in:.1f} in",
            f"Hi alarm: {hi_alarm_in:.1f} in",
            f"Override: {'ON' if status.override else 'OFF'}",
        ]

        # Clear screen and home cursor.
        payload = "\x1b[2J\x1b[H" + "\n".join(lines) + "\n"
        self._write(payload)

    def close(self) -> None:
        if self._fp:
            try:
                self._fp.close()
            except Exception:
                pass
            self._fp = None


def build_display(driver: str, tty: Optional[str] = None):
    if not driver or driver == "none":
        return NullDisplay()
    if driver == "console":
        return ConsoleDisplay(tty=tty or "/dev/tty1")
    raise ValueError(f"Unknown display driver: {driver}")
