# FILE: telemetry.py

import logging

from src.model.depth_telemetry import DepthTelemetry
from src.config import RESISTOR_OHMS, MAX_DEPTH_FT, DEPTH_SCALING_FACTOR

log = logging.getLogger(__name__)


def read_depth(chan):
    """
    Read ADS1115 channel and convert to:
      - depth in ft
      - loop current in mA
      - shunt voltage in V

    `chan` is an adafruit_ads1x15.analog_in.AnalogIn instance,
    created in main.py as AnalogIn(ads, 0).
    """

    # --- SIM OVERRIDE (temporary test) ---
    # return 0.8, 10.0, 1.0   # depth > HI_ALARM
    # -------------------------------------
    
    if chan is None:
        raise RuntimeError("ADS1115 channel not initialized; cannot read depth.")

    # Read shunt voltage from ADS1115
    try:
        voltage = float(chan.voltage)  # ensure it's a plain float
    except Exception as e:
        log.error(f"[DEPTH] Failed to read ADC: {e}")
        raise

    # Convert voltage across shunt to loop current
    mA = (voltage / RESISTOR_OHMS) * 1000.0  # V/R → A → mA

    # Clamp to a sane range (0–25 mA)
    mA_clamped = max(0.0, min(mA, 25.0))

    # Map 4–20 mA → 0–MAX_DEPTH_FT
    if mA_clamped <= 4.0:
        depth = 0.0
    elif mA_clamped >= 20.0:
        depth = MAX_DEPTH_FT
    else:
        depth = ((mA_clamped - 4.0) / 16.0) * MAX_DEPTH_FT

    # Apply your calibration factor
    depth *= DEPTH_SCALING_FACTOR

    log.debug(
        f"[DEPTH] V={voltage:.4f} V, I={mA_clamped:.3f} mA, depth={depth:.2f} ft"
    )

    return DepthTelemetry(depth, mA_clamped, voltage)
