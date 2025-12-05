import serial
import time
from typing import List, Optional, Union


class RAK3172Communicator:
    def __init__(self, port: str, baudrate: int = 115200, timeout: int = 1) -> None:
        """
        Simple UART wrapper for the RAK3172.

        - connect() / disconnect()
        - send_command("AT+...") -> List[str] of response lines
        - send_data(payload) -> sends AT+SEND=1:<hex>, returns full response as a single string
        - check_downlink() -> last RX_1 hex payload (if any), else None
        """
        self.last_downlink: Optional[str] = None
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser: Optional[serial.Serial] = None

    # ------------------------------------------------------------------
    # Basic serial lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the serial connection to the RAK3172."""
        self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
        print(f"Connected to {self.port} at {self.baudrate} baud.")

    def disconnect(self) -> None:
        """Close the serial connection to the RAK3172."""
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("Serial connection closed.")

    @property
    def serial_port(self) -> serial.Serial:
        """
        Expose the underlying serial port for advanced reads
        (used by reconnect_rak() to watch join events).
        """
        if not self.ser:
            raise ValueError("Serial port not initialized. Call connect() first.")
        return self.ser

    # ------------------------------------------------------------------
    # AT helpers
    # ------------------------------------------------------------------

    def send_command(self, command: str) -> List[str]:
        """
        Send a raw AT command and return the response lines.

        Example:
            send_command("AT+NJS?")
        """
        if not self.ser or not self.ser.is_open:
            raise ConnectionError("Serial connection is not open.")

        # Ensure proper line ending and encode
        self.ser.write((command + "\r\n").encode("utf-8"))
        # Give module time to respond
        time.sleep(0.5)

        raw = self.ser.read_all().decode("utf-8", errors="ignore").strip()
        if not raw:
            return []
        return raw.splitlines()

    # ------------------------------------------------------------------
    # Uplink + downlink
    # ------------------------------------------------------------------

    def _normalize_hex_payload(self, payload: Union[str, bytes, bytearray]) -> str:
        """
        Accept:
          - bytes / bytearray: treat as raw payload bytes and hex-encode.
          - str: treat as hex string (optional '0x' prefix, spaces allowed).

        Returns an uppercase hex string suitable for AT+SEND.
        """
        if isinstance(payload, (bytes, bytearray)):
            return payload.hex().upper()

        if isinstance(payload, str):
            # Strip common noise like "0x" prefix and spaces / newlines.
            cleaned = payload.strip().replace(" ", "").replace("\n", "")
            if cleaned.startswith("0x") or cleaned.startswith("0X"):
                cleaned = cleaned[2:]
            return cleaned.upper()

        raise TypeError(
            f"Unsupported payload type {type(payload)}; "
            f"use str (hex) or bytes."
        )

    def send_data(self, payload: Union[str, bytes, bytearray]) -> str:
        """
        Send uplink data using AT+SEND and capture any downlink RX_1 payload.

        `payload` can be:
          - bytes / bytearray: raw packed payload (e.g., struct.pack(...))
          - str: hex string (e.g., '01020304')

        Returns:
          Entire AT response as a single string (lines joined with '\n').

        Side effect:
          If a '+EVT:RX_1' line with hex is seen, it is stored in self.last_downlink.
        """
        if not self.ser or not self.ser.is_open:
            raise ConnectionError("Serial connection is not open.")

        hex_payload = self._normalize_hex_payload(payload)
        at_command = f"AT+SEND=1:{hex_payload}"

        response_lines = self.send_command(at_command)

        # Scan from bottom up for a downlink event
        for line in reversed(response_lines):
            if "+EVT:RX_1" in line and ":" in line:
                parts = line.strip().split(":")
                # Take the last colon-separated field as candidate hex
                candidate = parts[-1].strip()
                if candidate and all(c in "0123456789abcdefABCDEF" for c in candidate):
                    self.last_downlink = candidate.upper()
                    break

        return "\n".join(response_lines)

    def check_downlink(self) -> Optional[str]:
        """
        Return the last received downlink hex payload (if any), and clear it.

        Used by main.py to poll for new downlink commands.
        """
        if self.last_downlink:
            dl = self.last_downlink
            self.last_downlink = None
            return dl
        return None
