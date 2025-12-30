"""
Placeholder for Waveshare AI485 / RS485 depth interface.
Implement Modbus read to return a DepthTelemetry-like payload.
"""

class WaveshareAI485:
    def __init__(self, port: str = "/dev/ttyS0", baudrate: int = 9600):
        self.port = port
        self.baudrate = baudrate

    def setup(self):
        # TODO: initialize serial/Modbus connection
        return False

    def read(self):
        # TODO: implement depth read via RS485
        raise NotImplementedError("RS485 depth read not implemented yet.")
