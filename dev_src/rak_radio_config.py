#!/usr/bin/env python3
"""
Helper to set RAK3172 radio parameters (ADR/DR/CFM) over AT commands.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.model.rak3172_comm import RAK3172Communicator


def send(rak, cmd: str) -> None:
    print(f">> {cmd}")
    resp_lines = rak.send_command(cmd)
    for line in resp_lines:
        print(f"<< {line}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure RAK3172 ADR/DR/CFM")
    parser.add_argument("--port", default="/dev/rak", help="RAK serial port (default: /dev/rak)")
    parser.add_argument("--adr", type=int, default=0, help="ADR setting (0=off, 1=on)")
    parser.add_argument("--dr", type=int, default=3, help="Data rate (e.g., 3 for US915 DR3)")
    parser.add_argument("--cfm", type=int, default=0, help="Confirm mode (0=unconfirmed, 1=confirmed)")
    args = parser.parse_args()

    rak = RAK3172Communicator(args.port)
    rak.connect()

    send(rak, "AT")
    send(rak, f"AT+ADR={args.adr}")
    send(rak, f"AT+DR={args.dr}")
    send(rak, f"AT+CFM={args.cfm}")

    # Query back current values
    send(rak, "AT+ADR=?")
    send(rak, "AT+DR=?")
    send(rak, "AT+CFM=?")

    rak.disconnect()


if __name__ == "__main__":
    main()
