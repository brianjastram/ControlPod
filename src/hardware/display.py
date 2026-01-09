"""
Display helpers for ControlPod (HDMI/console output).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
import os
from typing import Optional

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:  # pragma: no cover - best-effort timezone support
    ZoneInfo = None
try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover - optional dependency
    Image = None
    ImageDraw = None
    ImageFont = None

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
    lo_alarm_ft: float
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
        lo_alarm_in = _ft_to_in(status.lo_alarm_ft)

        now = datetime.now(self._tz) if self._tz else datetime.now()
        date_str = now.strftime("%Y-%m-%d").strip()
        time_str = now.strftime("%H:%M:%S %Z").strip()

        lines = [
            f"Site: {status.site_name}",
            "DateTime:",
            f"{date_str}",
            f"{time_str}",
            f"Depth: {depth_in:.1f} in",
            f"Pump: {'ON' if status.pump_on else 'OFF'}",
            f"Alarm: {'ON' if status.alarm_on else 'OFF'}",
            f"Start: {start_in:.1f} in",
            f"Stop: {stop_in:.1f} in",
            f"Hi Alm: {hi_alarm_in:.1f} in",
            f"Lo Alm: {lo_alarm_in:.1f} in",
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


class FramebufferDisplay:
    def __init__(
        self,
        fb_path: str = "/dev/fb0",
        timezone_name: str = "UTC",
        font_path: Optional[str] = None,
        font_size: int = 36,
        foreground: str = "#FFFFFF",
        background: str = "#000000",
        padding: int = 10,
        line_spacing: int = 4,
        pixel_order: str = "RGB",
    ) -> None:
        if Image is None:
            raise RuntimeError("Pillow not available for framebuffer display.")

        self.fb_path = fb_path
        self.timezone_name = timezone_name
        self.foreground = foreground
        self.background = background
        self.padding = padding
        self.line_spacing = line_spacing
        self.pixel_order = pixel_order.upper()
        self._tz = None
        self._fb = None
        self._size = (480, 320)
        self._bpp = 32
        self._stride = None
        self._pixel_mode = "BGRX"

        if ZoneInfo:
            try:
                self._tz = ZoneInfo(timezone_name)
            except Exception as e:
                log.warning(f"[DISPLAY] Failed to load timezone {timezone_name}: {e}")

        self._load_fb_info()
        self._open_fb()
        self._load_font(font_path, font_size)

    def _load_fb_info(self) -> None:
        try:
            with open("/sys/class/graphics/fb0/virtual_size", "r") as fp:
                width_s, height_s = fp.read().strip().split(",")
            with open("/sys/class/graphics/fb0/bits_per_pixel", "r") as fp:
                bpp_s = fp.read().strip()
            width = int(width_s)
            height = int(height_s)
            bpp = int(bpp_s)
            if width > 0 and height > 0:
                self._size = (width, height)
            if bpp in (16, 24, 32):
                self._bpp = bpp
        except Exception as e:
            log.warning(f"[DISPLAY] FB info read failed; using defaults: {e}")

        if self._bpp == 16:
            self._pixel_mode = "RGB"
        elif self._bpp == 24:
            self._pixel_mode = "BGR" if self.pixel_order == "BGR" else "RGB"
        else:
            self._pixel_mode = "BGRX" if self.pixel_order == "BGR" else "RGBX"

        bytes_per_pixel = max(1, self._bpp // 8)
        self._stride = self._size[0] * bytes_per_pixel
        for path in ("/sys/class/graphics/fb0/stride", "/sys/class/graphics/fb0/line_length"):
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r") as fp:
                    val = int(fp.read().strip())
                if val > 0:
                    self._stride = val
                break
            except Exception as e:
                log.warning(f"[DISPLAY] FB stride read failed: {e}")

    def _open_fb(self) -> None:
        try:
            self._fb = open(self.fb_path, "r+b", buffering=0)
        except Exception as e:
            raise RuntimeError(f"Failed to open {self.fb_path}: {e}") from e

    def _load_font(self, font_path: Optional[str], font_size: int) -> None:
        if font_path:
            try:
                self._font = ImageFont.truetype(font_path, font_size)
                return
            except Exception as e:
                log.warning(f"[DISPLAY] Font load failed ({font_path}): {e}")
        self._font = ImageFont.load_default()

    def _line_height(self) -> int:
        try:
            bbox = self._font.getbbox("Ag")
            return max(1, bbox[3] - bbox[1])
        except Exception:
            try:
                return self._font.getsize("Ag")[1]
            except Exception:
                return 12

    def _blit(self, image: "Image.Image") -> None:
        if not self._fb:
            return
        try:
            self._fb.seek(0)
            if self._bpp == 16:
                self._fb.write(self._pack_rgb565(image))
            else:
                raw = image.tobytes("raw", self._pixel_mode)
                if self._stride and self._stride != self._size[0] * (self._bpp // 8):
                    raw = self._pad_stride(raw, self._bpp // 8)
                self._fb.write(raw)
        except Exception as e:
            log.error(f"[DISPLAY] FB write failed: {e}")

    def _pack_rgb565(self, image: "Image.Image") -> bytes:
        width, height = self._size
        rgb = image.tobytes("raw", "RGB")
        out = bytearray(self._stride * height)
        out_idx = 0
        rgb_idx = 0
        pad = self._stride - (width * 2)
        swap = self.pixel_order == "BGR"

        for _ in range(height):
            for _ in range(width):
                r = rgb[rgb_idx]
                g = rgb[rgb_idx + 1]
                b = rgb[rgb_idx + 2]
                rgb_idx += 3
                if swap:
                    r, b = b, r
                value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                out[out_idx] = value & 0xFF
                out[out_idx + 1] = (value >> 8) & 0xFF
                out_idx += 2
            if pad > 0:
                out_idx += pad

        return bytes(out)

    def _pad_stride(self, raw: bytes, bytes_per_pixel: int) -> bytes:
        width, height = self._size
        row_len = width * bytes_per_pixel
        out = bytearray(self._stride * height)
        out_idx = 0
        raw_idx = 0
        pad = self._stride - row_len
        for _ in range(height):
            out[out_idx:out_idx + row_len] = raw[raw_idx:raw_idx + row_len]
            out_idx += row_len
            raw_idx += row_len
            if pad > 0:
                out_idx += pad
        return bytes(out)

    def update(self, status: DisplayStatus) -> None:
        depth_in = _ft_to_in(status.depth_ft)
        start_in = _ft_to_in(status.start_ft)
        stop_in = _ft_to_in(status.stop_ft)
        hi_alarm_in = _ft_to_in(status.hi_alarm_ft)
        lo_alarm_in = _ft_to_in(status.lo_alarm_ft)

        now = datetime.now(self._tz) if self._tz else datetime.now()
        date_str = now.strftime("%Y-%m-%d").strip()
        time_str = now.strftime("%H:%M:%S %Z").strip()

        lines = [
            f"Site: {status.site_name}",
            "DateTime:",
            f"{date_str}",
            f"{time_str}",
            f"Depth: {depth_in:.1f} in",
            f"Pump: {'ON' if status.pump_on else 'OFF'}",
            f"Alarm: {'ON' if status.alarm_on else 'OFF'}",
            f"Start: {start_in:.1f} in",
            f"Stop: {stop_in:.1f} in",
            f"Hi Alm: {hi_alarm_in:.1f} in",
            f"Lo Alm: {lo_alarm_in:.1f} in",
            f"Override: {'ON' if status.override else 'OFF'}",
        ]

        image = Image.new("RGB", self._size, self.background)
        draw = ImageDraw.Draw(image)
        y = self.padding
        line_height = self._line_height()
        for line in lines:
            draw.text((self.padding, y), line, font=self._font, fill=self.foreground)
            y += line_height + self.line_spacing
            if y >= self._size[1]:
                break

        self._blit(image)

    def close(self) -> None:
        if self._fb:
            try:
                self._fb.close()
            except Exception:
                pass
            self._fb = None


def build_display(
    driver: str,
    tty: Optional[str] = None,
    timezone_name: str = "UTC",
    font: Optional[str] = None,
    fb_path: Optional[str] = None,
    font_path: Optional[str] = None,
    font_size: int = 36,
    foreground: str = "#FFFFFF",
    background: str = "#000000",
    padding: int = 10,
    line_spacing: int = 4,
    pixel_order: str = "RGB",
):
    if not driver or driver == "none":
        return NullDisplay()
    if driver == "console":
        return ConsoleDisplay(
            tty=tty or "/dev/tty1",
            timezone_name=timezone_name,
            font=font,
        )
    if driver in ("framebuffer", "fb"):
        if Image is None:
            log.warning("[DISPLAY] Pillow not available; falling back to console display.")
            return ConsoleDisplay(
                tty=tty or "/dev/tty1",
                timezone_name=timezone_name,
                font=font,
            )
        return FramebufferDisplay(
            fb_path=fb_path or "/dev/fb0",
            timezone_name=timezone_name,
            font_path=font_path,
            font_size=font_size,
            foreground=foreground,
            background=background,
            padding=padding,
            line_spacing=line_spacing,
            pixel_order=pixel_order,
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
