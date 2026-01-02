#!/usr/bin/env python3
"""
One-time / occasional setup for the RAK3172.

Edit the DEVEUI / APPEUI / APPKEY / BAND values before running.
Run only when /dev/rak is present.
"""

# --- ensure project root is on sys.path ---
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # /home/pi/ControlPod
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# ------------------------------------------

import time
from src.model.rak3172_comm import RAK3172Communicator

RAK_PORT = "/dev/rak"

DEVEUI = "AC1F09FFFE1D83AD"
APPEUI = "AC1F09FFF9153172"
APPKEY = "AC1F09FFFE1D83ADAC1F09FFF9153172"
LORAWAN_CLASS = "A"   # usually A
BAND = 5              # example: US915 often uses band index like 2; adjust as needed
DR = 3                # data rate you're already using in main.py (AT+DR=3)
ADR = 0               # keep ADR off to avoid DR drift / empty frames
CFM = 0               # unconfirmed uplinks
US915_BAND = 5


def _has_error(resp_lines: list[str]) -> bool:
    for line in resp_lines:
        upper = line.upper()
        if "ERROR" in upper or "AT_PARAM_ERROR" in upper:
            return True
    return False


def _parse_setting(lines: list[str], key: str):
    prefix = f"AT+{key}="
    for line in lines:
        s = line.strip().upper()
        if s.startswith(prefix):
            value = s[len(prefix):].strip()
            digits = ""
            for ch in value:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            if digits:
                return int(digits)
    return None


def send(rak, cmd, *, fatal: bool = False):
    print(f">> {cmd}")
    resp_lines = rak.send_command(cmd)
    for line in resp_lines:
        print(f"<< {line}")
    print()
    if _has_error(resp_lines):
        msg = f"Command failed: {cmd}"
        if fatal:
            raise RuntimeError(msg)
        print(f"!! {msg}")
    time.sleep(2.5)
    return resp_lines


def query_setting(rak, key: str):
    resp_lines = send(rak, f"AT+{key}=?", fatal=False)
    return _parse_setting(resp_lines, key)


def main():
    rak = RAK3172Communicator(port=RAK_PORT)
    rak.connect()

    # Basic sanity
    send(rak, "AT", fatal=True)
    # Optional: some firmwares support version / band queries; harmless if they error
    send(rak, "AT+NWM=?")   # query current network mode (LoRaWAN vs P2P)
    send(rak, "AT+NJM=?")   # query join mode (OTAA/ABP)

    # Put module into LoRaWAN OTAA mode
    send(rak, "AT+NWM=1", fatal=True)          # 1 = LoRaWAN
    send(rak, "AT+NJM=1", fatal=True)          # 1 = OTAA

    # Set IDs / keys (edit above constants before running)
    send(rak, f"AT+DEVEUI={DEVEUI}", fatal=True)
    send(rak, f"AT+APPEUI={APPEUI}", fatal=True)
    send(rak, f"AT+APPKEY={APPKEY}", fatal=True)

    # Set class and band / data rate
    send(rak, f"AT+CLASS={LORAWAN_CLASS}", fatal=True)
    send(rak, f"AT+BAND={BAND}", fatal=True)
    send(rak, f"AT+ADR={ADR}", fatal=True)
    send(rak, f"AT+DR={DR}", fatal=True)
    send(rak, f"AT+CFM={CFM}", fatal=True)

    # Force US915 sub-band 1 (channels 0-7)
    if BAND == US915_BAND:
        send(rak, "AT+MASK=0001", fatal=True)
    else:
        print("Skipping AT+MASK (non-US915 band).")

    # Save configuration to NVM
    # send(rak, "AT+SAVE") # Command not be supported on all firmware versions

    # Verify ADR/DR/CFM after setup
    adr_val = query_setting(rak, "ADR")
    dr_val = query_setting(rak, "DR")
    cfm_val = query_setting(rak, "CFM")
    print(f"Verify ADR -> {adr_val} (expected {ADR})")
    print(f"Verify DR  -> {dr_val} (expected {DR})")
    print(f"Verify CFM -> {cfm_val} (expected {CFM})")
    if adr_val != ADR or dr_val != DR or cfm_val != CFM:
        print("!! One or more settings did not stick; check module config.")

    # Optional: restart module to apply everything cleanly
    send(rak, "ATZ")

    print("RAK setup complete. Now you can let main.py run and call AT+JOIN at startup.")


if __name__ == "__main__":
    main()

