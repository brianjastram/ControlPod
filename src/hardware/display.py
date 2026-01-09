"""
Display helpers for ControlPod (HDMI/console output).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:  # pragma: no cover - best-effort timezone support
    ZoneInfo = None

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
    def __init__(
        self,
        tty: str = "/dev/tty1",
        timezone_name: str = "UTC",
        font: Optional[str] = None,
    ) -> None:
        self.tty = tty
        self.timezone_name = timezone_name
        self._tz = None
        self._fp: Optional[object] = None
        if ZoneInfo:
            try:
                self._tz = ZoneInfo(timezone_name)
            except Exception as e:
                log.warning(f"[DISPLAY] Failed to load timezone {timezone_name}: {e}")

        if font:
            self._apply_font(font)

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

        now = datetime.now(self._tz) if self._tz else datetime.now()
        ts = now.strftime("%Y-%m-%d %H:%M:%S %Z").strip()

        lines = [
            f"Site: {status.site_name}",
            f"Time: {ts}",
            f"Depth: {depth_in:.1f} in",
            f"Pump: {'ON' if status.pump_on else 'OFF'}  Alarm: {'ON' if status.alarm_on else 'OFF'}",
            f"Start: {start_in:.1f} in  Stop: {stop_in:.1f} in",
            f"Hi alarm: {hi_alarm_in:.1f} in  Override: {'ON' if status.override else 'OFF'}",
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


def build_display(
    driver: str,
    tty: Optional[str] = None,
    timezone_name: str = "UTC",
    font: Optional[str] = None,
):
    if not driver or driver == "none":
        return NullDisplay()
    if driver == "console":
        return ConsoleDisplay(
            tty=tty or "/dev/tty1",
            timezone_name=timezone_name,
            font=font,
        )
    raise ValueError(f"Unknown display driver: {driver}")
    def _apply_font(self, font: str) -> None:
        try:
            import subprocess

            result = subprocess.run(
                ["setfont", font],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                err = result.stderr.strip() or result.stdout.strip()
                log.warning(f"[DISPLAY] setfont failed ({result.returncode}): {err}")
        except FileNotFoundError:
            log.warning("[DISPLAY] setfont not found; skipping font change.")
        except Exception as e:
            log.warning(f"[DISPLAY] setfont error: {e}")
