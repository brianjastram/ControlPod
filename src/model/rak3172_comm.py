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
        self.last_response_lines: list[str] = []
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
        self.ser.reset_input_buffer()
        self.ser.write((command + "\r\n").encode("utf-8"))
        self.ser.flush()

        # Read for up to ~2 seconds, line by line
        lines: List[str] = []
        deadline = time.time() + 2.0
        while time.time() < deadline:
            line = self.ser.readline().decode("utf-8", errors="ignore").strip()
            if line:
                lines.append(line)
            else:
                # If we already have something and there's a short pause, break early
                if lines:
                    break
                time.sleep(0.05)

        return lines

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
        Send uplink data using AT+SEND and capture any RX_1 downlink.
        Treats immediate "OK" as a successful send (RAK3172 behavior).
        """
        if not self.ser or not self.ser.is_open:
            raise ConnectionError("Serial connection is not open.")

        hex_payload = self._normalize_hex_payload(payload)
        at_command = f"AT+SEND=1:{hex_payload}"

        # Send the command
        response_lines = self.send_command(at_command)
        self.last_response_lines = response_lines

        # Consider "OK" or "+EVT:TX_DONE" as success.
        # Always read for a short window to capture late TX_DONE even if OK was seen.
        def _check_lines(lines):
            for line in lines:
                if line.strip() == "OK":
                    return True
                if "+EVT:TX_DONE" in line:
                    return True
            return False

        success = _check_lines(response_lines)

        # Read for up to ~5s to catch late events
        deadline = time.time() + 5.0
        while time.time() < deadline:
            line = self.ser.readline().decode("utf-8", errors="ignore").strip()
            if line:
                response_lines.append(line)
                if _check_lines([line]):
                    success = True
            else:
                time.sleep(0.05)

        # Capture downlink if present
        for line in reversed(response_lines):
            if "+EVT:RX_1" in line and ":" in line:
                parts = line.strip().split(":")
                candidate = parts[-1].strip()
                if candidate and all(c in "0123456789abcdefABCDEF" for c in candidate):
                    self.last_downlink = candidate.upper()
                    break

        if not success:
            # Log what we saw for debugging upstream callers
            print(f"[RAK SEND DEBUG] No OK/TX_DONE. Response: {response_lines}")
            if response_lines:
                return "ERROR:" + "|".join(response_lines)
            return "ERROR"

        return "OK"

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
