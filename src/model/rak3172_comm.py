import serial
import time

class RAK3172Communicator:
    def __init__(self, port, baudrate=115200, timeout=1):
        """
        Initialize the RAK3172 communicator.
        :param port: Serial port to which the RAK3172 is connected (e.g., "/dev/ttyUSB0").
        :param baudrate: Communication speed (default is 115200).
        :param timeout: Timeout for serial communication (default is 1 second).
        """
        self.last_downlink = None
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None

    def connect(self):
        """Open the serial connection to the RAK3172."""
        self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
        print(f"Connected to {self.port} at {self.baudrate} baud.")

    def send_command(self, command):
        """
        Send a raw AT command and return the response.
        :param command: AT command string.
        :return: List of response lines.
        """
        if not self.ser or not self.ser.is_open:
            raise ConnectionError("Serial connection is not open.")

        self.ser.write((command + "\r\n").encode())
        time.sleep(0.5)
        response = self.ser.read_all().decode('utf-8', errors='ignore').strip()
        return response.splitlines()

    def send_data(self, hex_payload):
        """
        Send uplink data using AT+SEND command and return the response including possible downlink.
        :param hex_payload: Hex-encoded string of payload data.
        :return: Joined response string from module.
        """
        at_command = f"AT+SEND=1:{hex_payload}"
        if not self.ser or not self.ser.is_open:
            raise ConnectionError("Serial connection is not open.")

        response_lines = self.send_command(at_command)
        for line in reversed(response_lines):
            if "+EVT:RX_1" in line and ":" in line:
                parts = line.strip().split(":")
                if len(parts) >= 5:
                    possible_hex = parts[-1].strip()
                    if all(c in "0123456789abcdefABCDEF" for c in possible_hex):
                        self.last_downlink = possible_hex
                        break
        return "\n".join(response_lines)

    def check_downlink(self):
        """
        Return the last received downlink payload stored from send_data.
        :return: Hex string of downlink payload or None if nothing received.
        """
        return self.last_downlink

    def disconnect(self):
        """Close the serial connection to the RAK3172."""
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("Serial connection closed.")

    @property
    def serial_port(self):
        if not self.ser:
            raise ValueError("Serial port not initialized. Call connect() first.")
        return self.ser
