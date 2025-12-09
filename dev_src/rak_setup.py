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
BAND = 5             # example: US915 often uses band index like 2; adjust as needed
DR = 3                # data rate you're already using in main.py (AT+DR=3)

def send(rak, cmd):
    print(f">> {cmd}")
    resp_lines = rak.send_command(cmd)
    for line in resp_lines:
        print(f"<< {line}")
    print()
    time.sleep(0.3)


def main():
    rak = RAK3172Communicator(port=RAK_PORT)
    rak.connect()

    # Basic sanity
    send(rak, "AT")
    # Optional: some firmwares support version / band queries; harmless if they error
    send(rak, "AT+NWM=?")   # query current network mode (LoRaWAN vs P2P)
    send(rak, "AT+NJM=?")   # query join mode (OTAA/ABP)

    # Put module into LoRaWAN OTAA mode
    send(rak, "AT+NWM=1")          # 1 = LoRaWAN
    send(rak, "AT+NJM=1")          # 1 = OTAA

    # Set IDs / keys (edit above constants before running)
    send(rak, f"AT+DEVEUI={DEVEUI}")
    send(rak, f"AT+APPEUI={APPEUI}")
    send(rak, f"AT+APPKEY={APPKEY}")

    # Set class and band / data rate
    send(rak, f"AT+CLASS={LORAWAN_CLASS}")
    send(rak, f"AT+BAND={BAND}")
    send(rak, f"AT+DR={DR}")

    # Force US915 sub-band 2 (channels 8–15 + channel 65)
    send(rak, "AT+MASK=0002")

    # Save configuration to NVM
    send(rak, "AT+SAVE")

    # Optional: restart module to apply everything cleanly
    send(rak, "ATZ")

    print("RAK setup complete. Now you can let main.py run and call AT+JOIN at startup.")


if __name__ == "__main__":
    main()

