#!/usr/bin/env python3
"""
Control Pod main control program for KCLF, Phase 8B.
Brian Jastram, Hydrometrix for Eric Xanderson, Kandiyohi Co. Land Fill

Features:

- Uses ADS1115 on channel 0 for depth (telemetry.read_depth(chan))
- Uses Numato USB relay on /dev/ttyACM0 for pump control
- Uses /dev/rak for the RAK3172 LoRaWAN radio (via rak3172_comm.RAK3172Communicator)
- Syncs setpoints from the USB key on startup
- Applies downlink commands (override, zero, setpoints)
- Sends JSON telemetry payloads to ChirpStack at INTERVAL_MINUTES
"""

import time
import logging
from datetime import datetime, timezone

from src import shared_state
from src import logger
from src.config import (
    DEVICE_NAME,
    INTERVAL_MINUTES,
    READ_INTERVAL_SECONDS,
    ALARM_GPIO_PIN,
    PUMP_START_FEET,
    PUMP_STOP_FEET,
    HI_ALARM_FEET,
    LO_ALARM_FEET,
    SITE_NAME,
)
from src.telemetry import read_depth
from src.usb_settings import sync_usb_to_local, load_setpoints
from src.downlink import process_downlink_command
from src.control import is_override_active
from src import rak as rak_service
from src import relay
from src.model.rak_dummy import DummyRAK

import busio
import board
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
import RPi.GPIO as GPIO

analog_input_channel = None
logger.setupLogging()
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global RAK instance + Dummy for bench
# ---------------------------------------------------------------------------

rak = rak_service.connect()
if rak is None:
    rak = DummyRAK()

# ---------------------------------------------------------------------------
# MAIN CONTROL LOOP
# ---------------------------------------------------------------------------

def main() -> None:
    global rak, analog_input_channel
    print("Starting MCTL3 with RAK3172...")

    # ----------------- GPIO -----------------
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(ALARM_GPIO_PIN, GPIO.OUT)
    GPIO.output(ALARM_GPIO_PIN, GPIO.LOW)

    # ----------------- ADS1115 -----------------
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        ads = ADS.ADS1115(i2c)
        analog_input_channel = AnalogIn(ads, 0)  # single-ended channel 0
        shared_state.analog_input_channel = AnalogIn(ads, 0)  # single-ended channel 0
        log.info("ADS1115 detected on I2C bus.")
    except Exception as e:
        ads = None
        shared_state.analog_input_channel = None
        log.error(f"[SIM] No ADS1115 detected ({e}); using simulated depth readings.")

    # ----------------- Pump + alarms state -----------------
    pump_is_on = False
    alarm_hi_on = False
    alarm_lo_on = False

    # ----------------- USB setpoints sync -----------------
    try:
        if sync_usb_to_local():
            log.info("[MAIN] USB setpoints updated → local cache refreshed.")
        else:
            log.info("[MAIN] USB setpoints already current.")
    except Exception as e:
        log.error(f"[MAIN] USB sync failed: {e}")

    try:
        current_setpoints = load_setpoints()
    except Exception as e:
        log.error(f"[MAIN] Failed to load setpoints, using defaults: {e}")
        current_setpoints = {
            "START_PUMP_AT": PUMP_START_FEET,
            "STOP_PUMP_AT": PUMP_STOP_FEET,
            "HI_ALARM": HI_ALARM_FEET,
            "LO_ALARM": LO_ALARM_FEET,
            "SITE_NAME": SITE_NAME,
        }

    # --------- DETERMINISTIC STARTUP PUMP STATE ----------
    log.info("[PUMP] Startup: forcing pump OFF for known safe state.")
    try:
        relay.send_relay_command("relay off 0")
    except Exception as e:
        log.error(f"[PUMP] Startup: failed to force OFF: {e}")

    pump_is_on = False
    log.info("[PUMP] Startup: pump_is_on set to False (deterministic).")

    # --------- Telemetry timer ----------
    last_send_time = time.time()

    # =====================================================
    # MAIN LOOP
    # =====================================================
    while True:
        # ----------------------------------------------------------
        # MEASUREMENT
        # ----------------------------------------------------------
        try:
            measurement = read_depth(analog_input_channel)
            # Adjust attribute names if they differ in DepthTelemetry
            depth = measurement.depth_ft
            mA = measurement.current_mA
            voltage = measurement.voltage

            log.info(
                f"[MEASURE] depth={depth:.2f} ft  mA={mA:.3f}  V={voltage:.3f}"
            )
        except Exception as e:
            log.error(f"[MAIN] Error reading depth: {e}")
            depth, mA, voltage = 0.0, 0.0, 0.0


        # -------- APPLY ZERO OFFSET --------
        try:
            zero_offset = current_setpoints.get("ZERO_OFFSET", 0.0)
            depth_raw = depth
            depth = max(0.0, depth_raw - zero_offset)
            # Correct zero adjustment: depth = raw + offset
            adjusted = depth_raw + zero_offset
            log.info(
            f"[ZERO] Applied zero_offset={zero_offset:.3f} → adjusted_depth={adjusted:.3f} (raw={depth_raw:.3f})"
            )
            depth = adjusted

        except Exception as e:
            log.error(f"[ZERO] Failed to apply zero offset: {e}")

        # ---------- Downlink ----------
        try:
            downlink_command = rak.check_downlink()
            if downlink_command:
                log.info(f"[DOWNLINK] Received raw: {downlink_command}")
                process_downlink_command(downlink_command)
                # Reload setpoints after any downlink
                try:
                    current_setpoints = load_setpoints()
                    log.info(f"[SETPOINTS] Reloaded after downlink: {current_setpoints}")
                except Exception as e:
                    log.error(f"[SETPOINTS] Failed to reload after downlink: {e}")
        except Exception as e:
            log.error(f"[MAIN] Downlink check error: {e}")

        # ---------- Setpoints ----------
        start_depth = current_setpoints.get("START_PUMP_AT", PUMP_START_FEET)
        stop_depth  = current_setpoints.get("STOP_PUMP_AT", PUMP_STOP_FEET)
        hi_alarm    = current_setpoints.get("HI_ALARM", HI_ALARM_FEET)
        lo_alarm    = current_setpoints.get("LO_ALARM", LO_ALARM_FEET)
        site_name   = current_setpoints.get("SITE_NAME", SITE_NAME)

        # -----------------------------------------------------------------------
        # PUMP CONTROL (override first)
        # -----------------------------------------------------------------------
        override = is_override_active()

        if override:
            log.info("[OVERRIDE] ACTIVE → Pump forced OFF.")
            if pump_is_on:
                relay.turn_pump_off()
            pump_is_on = False
        else:
            # Normal automatic pump logic
            if pump_is_on and depth <= stop_depth:
                log.info(
                    f"[PUMP] depth={depth:.2f} <= STOP_PUMP_AT={stop_depth:.2f} → OFF"
                )
                relay.turn_pump_off()
                pump_is_on = False
            elif (not pump_is_on) and depth >= start_depth:
                log.info(
                    f"[PUMP] depth={depth:.2f} >= START_PUMP_AT={start_depth:.2f} → ON"
                )
                relay.turn_pump_on()
                pump_is_on = True

        # ----------------------------------------------------------
        # ALARMS
        # ----------------------------------------------------------
        hi_alarm_tripped = depth > hi_alarm
        lo_alarm_tripped = depth < lo_alarm

        if hi_alarm_tripped or lo_alarm_tripped:
            relay.set_alarm_light_hw(True)
        else:
            relay.set_alarm_light_hw(False)

        alarm_hi_on = hi_alarm_tripped
        alarm_lo_on = lo_alarm_tripped

        # ---------- Telemetry send ----------
        if time.time() - last_send_time >= INTERVAL_MINUTES * 60:
            telemetry = {
                "device": DEVICE_NAME,
                "ts": datetime.now(timezone.utc).isoformat(),
                "depth": depth,
                "current_mA": mA,
                "voltage": voltage,
                "start": start_depth,
                "stop": stop_depth,
                "pump_on": pump_is_on,
                "override": is_override_active(),
                "hi_alarm": alarm_hi_on,
                "lo_alarm": alarm_lo_on,
                "site_name": site_name,
            }

            try:
                ok = rak_service.send_data_to_chirpstack(rak, telemetry)
                if not ok:
                    log.warning("[MAIN] Send failed; attempting RAK reconnect.")
                    rak2 = rak_service.reconnect_rak(rak)
                    if rak2 is not None:
                        rak = rak2
            except Exception as e:
                log.error(f"[MAIN] Telemetry send error: {e}")

            last_send_time = time.time()

        time.sleep(READ_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
