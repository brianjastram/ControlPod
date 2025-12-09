from dataclasses import dataclass

@dataclass
class DepthTelemetry:
    depth: float
    ma_clamped: float
    voltage: float