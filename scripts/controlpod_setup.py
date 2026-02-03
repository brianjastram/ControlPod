#!/usr/bin/env python3
"""
Interactive per-device setup for ControlPod.

Writes /etc/controlpod.env and optionally:
  - sets hostname
  - programs RAK keys (via scripts/program_rak.py)
"""

import os
import sys
from pathlib import Path
import subprocess
from typing import Optional

ENV_PATH = Path("/etc/controlpod.env")
SCRIPT_DIR = Path(__file__).resolve().parent
RAK_SCRIPT = SCRIPT_DIR / "program_rak.py"


def _require_root() -> None:
    if os.name != "nt" and os.geteuid() != 0:
        print("Please run with sudo:")
        print("  sudo python /home/pi/ControlPod/scripts/controlpod_setup.py")
        sys.exit(1)


def _load_existing() -> dict:
    values = {}
    if not ENV_PATH.exists():
        return values
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _prompt(label: str, default: Optional[str] = None) -> Optional[str]:
    if default:
        raw = input(f"{label} [{default}]: ").strip()
        return default if raw == "" else raw
    raw = input(f"{label}: ").strip()
    return None if raw == "" else raw


def _prompt_yes_no(label: str, default: bool = False) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    raw = input(label + suffix + ": ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def _parse_site_id(raw: Optional[str]) -> Optional[int]:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        if value.lower().startswith("0x"):
            return int(value, 16)
        return int(value)
    except ValueError:
        return None


def _format_site_id(site_id: int) -> str:
    return f"0x{site_id:04X}"


def _write_env(values: dict) -> None:
    lines = ["# ControlPod per-device overrides"]
    for key in sorted(values.keys()):
        lines.append(f"{key}={values[key]}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {ENV_PATH}")


def main() -> None:
    _require_root()
    print("ControlPod per-device setup")
    print("---------------------------")

    existing = _load_existing()

    site_name = _prompt("SITE_NAME", existing.get("SITE_NAME"))
    site_id_raw = _prompt(
        "SITE_ID (hex like 0x008A or decimal)",
        existing.get("SITE_ID"),
    )
    site_id = _parse_site_id(site_id_raw)
    if site_id is None and site_id_raw:
        print("!! Invalid SITE_ID; leaving unchanged.")

    device_name = _prompt("DEVICE_NAME", existing.get("DEVICE_NAME"))
    display_tz = _prompt("DISPLAY_TIMEZONE", existing.get("DISPLAY_TIMEZONE"))

    values = {}
    if site_name:
        values["SITE_NAME"] = site_name
    if site_id is not None:
        values["SITE_ID"] = _format_site_id(site_id)
    if device_name:
        values["DEVICE_NAME"] = device_name
    if display_tz:
        values["DISPLAY_TIMEZONE"] = display_tz

    if values:
        _write_env(values)
    else:
        print("No values set; skipping /etc/controlpod.env update.")

    if _prompt_yes_no("Set hostname now?", False):
        current = subprocess.check_output(["hostname"]).decode().strip()
        new_name = _prompt("Hostname", current)
        if new_name and new_name != current:
            subprocess.run(["hostnamectl", "set-hostname", new_name], check=False)
            print(f"Hostname set to {new_name}")

    if _prompt_yes_no("Program RAK keys now?", False):
        if not RAK_SCRIPT.exists():
            print(f"!! Missing script: {RAK_SCRIPT}")
        else:
            subprocess.run([sys.executable, str(RAK_SCRIPT)], check=False)


if __name__ == "__main__":
    main()
