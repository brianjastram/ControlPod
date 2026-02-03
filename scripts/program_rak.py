#!/usr/bin/env python3
"""
Interactive RAK3172 provisioning (DevEUI / AppEUI / AppKey).
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.model.rak3172_comm import RAK3172Communicator  # noqa: E402


HEX_CHARS = set("0123456789ABCDEF")


def _prompt(label, default=None):
    if default:
        raw = input(f"{label} [{default}]: ").strip()
        return default if raw == "" else raw
    raw = input(f"{label}: ").strip()
    return "" if raw == "" else raw


def _prompt_yes_no(label, default=False):
    suffix = " [Y/n]" if default else " [y/N]"
    raw = input(label + suffix + ": ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def _prompt_hex(label, length, default=""):
    while True:
        raw = _prompt(label, default)
        if raw == "":
            return ""
        value = raw.replace(" ", "").upper()
        if len(value) != length:
            print(f"!! Expected {length} hex chars.")
            continue
        if any(ch not in HEX_CHARS for ch in value):
            print("!! Non-hex characters detected.")
            continue
        return value


def _has_error(lines):
    for line in lines:
        upper = line.upper()
        if "ERROR" in upper or "AT_PARAM_ERROR" in upper:
            return True
    return False


def _send(rak, cmd, fatal=False):
    print(f">> {cmd}")
    lines = rak.send_command(cmd)
    for line in lines:
        print(f"<< {line}")
    if _has_error(lines):
        msg = f"Command failed: {cmd}"
        if fatal:
            raise RuntimeError(msg)
        print(f"!! {msg}")
    print()
    return lines


def main():
    print("RAK3172 provisioning")
    print("--------------------")
    port = _prompt("RAK port", "/dev/rak") or "/dev/rak"
    deveui = _prompt_hex("DevEUI (16 hex)", 16)
    appeui = _prompt_hex("AppEUI (16 hex)", 16)
    appkey = _prompt_hex("AppKey (32 hex)", 32)
    band = _prompt("Band (optional)", "")
    dr = _prompt("DR", "3")
    adr = _prompt("ADR (0/1)", "0")
    cfm = _prompt("CFM (0/1)", "0")
    lorawan_class = (_prompt("Class (A/B/C)", "A") or "A").upper()
    mask = _prompt("Channel mask (optional, e.g. 0001)", "")

    rak = RAK3172Communicator(port=port)
    rak.connect()

    _send(rak, "AT", fatal=True)
    _send(rak, "AT+NWM=1", fatal=True)
    _send(rak, "AT+NJM=1", fatal=True)

    if deveui:
        _send(rak, f"AT+DEVEUI={deveui}", fatal=True)
    if appeui:
        _send(rak, f"AT+APPEUI={appeui}", fatal=True)
    if appkey:
        _send(rak, f"AT+APPKEY={appkey}", fatal=True)

    if lorawan_class:
        _send(rak, f"AT+CLASS={lorawan_class}", fatal=False)
    if band:
        _send(rak, f"AT+BAND={band}", fatal=False)
    if mask:
        _send(rak, f"AT+MASK={mask}", fatal=False)
    if adr:
        _send(rak, f"AT+ADR={adr}", fatal=False)
    if dr:
        _send(rak, f"AT+DR={dr}", fatal=False)
    if cfm:
        _send(rak, f"AT+CFM={cfm}", fatal=False)

    if _prompt_yes_no("Restart module now (ATZ)?", False):
        _send(rak, "ATZ", fatal=False)

    print("Done.")


if __name__ == "__main__":
    main()
