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

import os
import sys
import time
import json
import struct
import logging
from datetime import datetime

import serial
import busio
import board
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
import RPi.GPIO as GPIO

from config import (
    DEVICE_NAME,
    MAX_RETRIES,
    INTERVAL_MINUTES,
    READ_INTERVAL_SECONDS,
)

from telemetry import read_depth
from usb_settings import sync_usb_to_local, load_setpoints
from downlink import process_downlink_command
from control import is_override_active
import control
from rak3172_comm import RAK3172Communicator

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

LOG_DIR = "/home/pi/logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "main.py.log")

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setLevel(logging.INFO)
stream_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

file_handler = logging.FileHandler(LOG_FILE)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))

logging.basicConfig(
    level=logging.INFO,
    handlers=[stream_handler, file_handler],
)

# ---------------------------------------------------------------------------
# Hardware constants
# ---------------------------------------------------------------------------

# We now talk directly to the Numato relay on /dev/ttyACM0 everywhere.
RELAY_DEV = "/dev/ttyACM0"

ALARM_GPIO_PIN = 17           # Panel alarm LED

# ---------------------------------------------------------------------------
# Relay helpers
# ---------------------------------------------------------------------------

def send_relay_command(command: str) -> None:
    """
    Send a Numato-style relay command using /dev/ttyACM0.

    Examples:
        relay on 0
        relay off 0
        relay read 0
    """
    try:
        cmd = (command + "\r").encode()
        with serial.Serial(RELAY_DEV, 9600, timeout=1) as ser:
            ser.write(cmd)
        logging.info(f"[RELAY] Sent '{command}' to {RELAY_DEV}")
    except Exception as e:
        logging.error(f"[RELAY] Serial error on {RELAY_DEV}: {e}")


def turn_pump_on() -> None:
    send_relay_command("relay on 0")
    logging.info("[PUMP] Pump turned ON")


def turn_pump_off() -> None:
    send_relay_command("relay off 0")
    logging.info("[PUMP] Pump turned OFF")


def is_pump_on() -> bool:
    """
    Try to query relay state. Returns True if the relay reports ON, else False.

    Note: Numato's response format can be odd; this is best-effort and
    not relied on for normal runtime control (we track state in software).
    """
    try:
        with serial.Serial(RELAY_DEV, 9600, timeout=1) as ser:
            ser.write(b"relay read 0\r")
            response = ser.readline().decode(errors="ignore").strip().lower()
        logging.info(f"[RELAY] State response: '{response}'")
        return "on" in response
    except Exception as e:
        logging.error(f"[RELAY] State-check error: {e}")
        return False


def set_alarm_light_hw(state: bool) -> None:
    """
    Drive the panel alarm LED on GPIO17 only.
    """
    try:
        GPIO.output(ALARM_GPIO_PIN, GPIO.HIGH if state else GPIO.LOW)
        logging.info(f"[ALARM] Alarm {'ON' if state else 'OFF'}")
    except Exception as e:
        logging.error(f"[ALARM] Failed to set alarm state: {e}")

# ---------------------------------------------------------------------------
# RAK helpers
# ---------------------------------------------------------------------------

def reconnect_rak():
    """
    Connect to the RAK3172 on /dev/rak and try to ensure it is joined.

    Uses:
      - AT+NWM=1   (LoRaWAN mode)
      - AT+NJM=1   (OTAA)
      - AT+NJS?    (check join status)
      - AT+JOIN=1:1:10:5 (force OTAA join with retry window)
    """
    port = "/dev/rak"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            rak = RAK3172Communicator(port)
            rak.connect()
            logging.info(f"[RAK] Connected to RAK3172 on {port}")

            # Make sure we are in LoRaWAN + OTAA mode
            try:
                rak.send_command("AT+NWM=1")
                rak.send_command("AT+NJM=1")
            except Exception as e:
                logging.warning(f"[RAK] NWM/NJM setup warning: {e}")

            # Check join status
            joined = False
            try:
                status = rak.send_command("AT+NJS?")
                logging.info("[RAK] NJS? -> " + " | ".join(status))
                if any("+NJS:" in line and "1" in line for line in status):
                    joined = True
                    logging.info("[RAK] Already joined (NJS=1).")
            except Exception as e:
                logging.warning(f"[RAK] NJS? query failed: {e}")

            if not joined:
                logging.info("[RAK] Not joined, sending AT+JOIN=1:1:10:5 ...")
                join_lines = rak.send_command("AT+JOIN=1:1:10:5")
                logging.info("[RAK] JOIN immediate response: " + " | ".join(join_lines))

                # Watch the UART for join events for up to 30 seconds
                for _ in range(30):
                    time.sleep(1)
                    buf = rak.serial_port.read_all().decode(errors="ignore")
                    if not buf:
                        continue
                    buf_upper = buf.upper()
                    logging.info(f"[RAK] Join event RX: {buf.strip()}")
                    if "JOINED" in buf_upper or "NETWORK JOINED" in buf_upper:
                        joined = True
                        logging.info("[RAK] Join success detected from UART.")
                        break

                if not joined:
                    # Final status check
                    try:
                        status2 = rak.send_command("AT+NJS?")
                        logging.info("[RAK] NJS? (post-join) -> " + " | ".join(status2))
                        if any("+NJS:" in line and "1" in line for line in status2):
                            joined = True
                            logging.info("[RAK] Join confirmed via NJS=1.")
                        else:
                            logging.warning("[RAK] Still not joined after join window.")
                    except Exception as e:
                        logging.warning(f"[RAK] NJS? post-join failed: {e}")

            if not joined:
                logging.warning(
                    "[RAK] Proceeding, but module reports NOT JOINED; "
                    "uplinks will return AT_NO_NETWORK_JOINED until join completes."
                )

            return rak

        except Exception as e:
            logging.error(f"[RAK] Connect error ({attempt}/{MAX_RETRIES}): {e}")
            time.sleep(2)

    logging.error("[RAK] Max retries reached. Could not connect to RAK3172.")
    return None


def send_data_to_chirpstack(rak, telemetry, site_id=0x8B):
    """
    14-byte uplink matching the current ChirpStack codec:

      [0] protocol_version (1)
      [1] flags:
          bit0 = hi_alarm
          bit1 = lo_alarm
          bit2 = override
          bit3 = pump_on
      [2..3] depth_ft * 100
      [4..5] mA * 1000
      [6..7] volts * 1000
      [8..9] start_ft * 100
      [10..11] stop_ft * 100
      [12..13] site_id (uint16)
    """
    if rak is None:
        logging.debug("[SEND] No RAK instance – skipping uplink.")
        return False

    try:
        # Values from your telemetry dict
        depth_ft   = float(telemetry.get("depth_ft", 0.0))
        mA         = float(telemetry.get("mA", 0.0))
        voltage    = float(telemetry.get("voltage", 0.0))
        start_ft   = float(telemetry.get("start", 0.0))
        stop_ft    = float(telemetry.get("stop", 0.0))

        hi_alarm   = bool(telemetry.get("hi_alarm"))
        lo_alarm   = bool(telemetry.get("lo_alarm"))
        override   = bool(telemetry.get("override"))
        pump_on    = bool(telemetry.get("pump_on"))

        def clamp_u16(x: float) -> int:
            x_int = int(round(x))
            if x_int < 0:
                x_int = 0
            if x_int > 0xFFFF:
                x_int = 0xFFFF
            return x_int

        # Scale to fixed-point integers
        depth_x100  = clamp_u16(max(depth_ft, 0.0) * 100.0)
        current_uA  = clamp_u16(max(mA,       0.0) * 1000.0)
        voltage_mV  = clamp_u16(max(voltage,  0.0) * 1000.0)
        start_x100  = clamp_u16(max(start_ft, 0.0) * 100.0)
        stop_x100   = clamp_u16(max(stop_ft,  0.0) * 100.0)

        # Flags byte
        flags = 0
        if hi_alarm:
            flags |= 0x01
        if lo_alarm:
            flags |= 0x02
        if override:
            flags |= 0x04
        if pump_on:
            flags |= 0x08

        # Build payload
        payload = bytearray(14)
        payload[0] = 1           # protocol version
        payload[1] = flags

        payload[2] = (depth_x100 >> 8) & 0xFF
        payload[3] = depth_x100 & 0xFF

        payload[4] = (current_uA >> 8) & 0xFF
        payload[5] = current_uA & 0xFF

        payload[6] = (voltage_mV >> 8) & 0xFF
        payload[7] = voltage_mV & 0xFF

        payload[8]  = (start_x100 >> 8) & 0xFF
        payload[9]  = start_x100 & 0xFF

        payload[10] = (stop_x100 >> 8) & 0xFF
        payload[11] = stop_x100 & 0xFF

        payload[12] = (site_id >> 8) & 0xFF
        payload[13] = site_id & 0xFF

        logging.info(
            "[SEND] Packed uplink len=%d "
            "depth_ft=%.3f (x100=%d) mA=%.3f (uA=%d) "
            "volts=%.3f (mV=%d) start_ft=%.3f (x100=%d) "
            "stop_ft=%.3f (x100=%d) flags=0x%02X site_id=0x%02X",
            len(payload),
            depth_ft, depth_x100,
            mA, current_uA,
            voltage, voltage_mV,
            start_ft, start_x100,
            stop_ft, stop_x100,
            flags, site_id,
        )

        resp = rak.send_data(payload)

        if resp != "OK":
            logging.warning("[SEND] RAK returned error; resp=%r", resp)
            return False

        logging.info("[SEND] Uplink OK.")
        return True

    except Exception as e:
        logging.exception("[SEND] Failed to send uplink via RAK: %s", e)
        return False


# ---------------------------------------------------------------------------
# Global RAK instance + Dummy for bench
# ---------------------------------------------------------------------------

rak = reconnect_rak()
if rak is None:
    class DummyRAK:
        def __init__(self):
            self._downlink = None

        def send_data(self, payload):
            logging.info(f"[SIM] uplink sent (simulated)")
            return "SIM_OK"

        def check_downlink(self):
            if self._downlink:
                dl = self._downlink
                self._downlink = None
                return dl
            return None

        def inject(self, hex_payload: str):
            logging.info(f"[SIM] Injected downlink payload: {hex_payload}")
            self._downlink = hex_payload

    rak = DummyRAK()


def inject_downlink(hex_payload: str):
    """
    Bench helper: inject a hex payload as if it arrived from RAK.

    Example:
        inject_downlink("53455453544152543D302E3535")  # SETSTART=0.55
        inject_downlink("30")                          # override OFF (ASCII '0')
        inject_downlink("31")                          # override ON  (ASCII '1')
    """
    global rak
    try:
        rak.inject(hex_payload)
    except Exception:
        logging.error("inject_downlink() called but DummyRAK is not active.")
# ---------------------------------------------------------------------------
# Uplink Payload Builder
# ---------------------------------------------------------------------------

def build_uplink_payload(depth_ft, ma, volts, alarm_on, pump_on, site_id, timestamp=None):
    """
    Pack a 14-byte payload matching the ChirpStack binary codec:

    Byte 0 : protocol_version (uint8)
    Byte 1 : flags (bit 0 = alarm_on, bit 1 = pump_on)
    2-3    : depth_raw  (uint16, depth_ft * 100)
    4-5    : mA_raw     (uint16, mA * 1000)
    6-7    : volts_raw  (uint16, volts * 1000)
    8-11   : timestamp  (uint32, UNIX seconds)
    12-13  : site_id    (uint16)
    """
    protocol_version = 1

    flags = 0
    if alarm_on:
        flags |= 0x01
    if pump_on:
        flags |= 0x02

    depth_raw = max(0, int(round(depth_ft * 100.0)))
    ma_raw    = max(0, int(round(ma * 1000.0)))
    volts_raw = max(0, int(round(volts * 1000.0)))

    if timestamp is None:
        timestamp = int(time.time())

    ts_raw   = timestamp & 0xFFFFFFFF
    site_raw = site_id & 0xFFFF

    # > = big-endian; B B H H H I H = 1b,1b,2b,2b,2b,4b,2b = 14 bytes
    return struct.pack(">BBHHHIH",
                       protocol_version,
                       flags,
                       depth_raw,
                       ma_raw,
                       volts_raw,
                       ts_raw,
                       site_raw)

# ---------------------------------------------------------------------------
# MAIN CONTROL LOOP
# ---------------------------------------------------------------------------

def main() -> None:
    global rak
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
        chan = AnalogIn(ads, 0)  # single-ended channel 0
        logging.info("ADS1115 detected on I2C bus.")
    except Exception as e:
        ads = None
        chan = None
        logging.error(f"[SIM] No ADS1115 detected ({e}); using simulated depth readings.")

    # ----------------- Pump + alarms state -----------------
    pump_is_on = False
    alarm_hi_on = False
    alarm_lo_on = False

    # ----------------- USB setpoints sync -----------------
    try:
        synced = sync_usb_to_local()
        if synced:
            logging.info("[MAIN] USB setpoints updated → local cache refreshed.")
        else:
            logging.info("[MAIN] USB setpoints already current.")
    except Exception as e:
        logging.error(f"[MAIN] USB sync failed: {e}")

    try:
        current_setpoints = load_setpoints()
    except Exception as e:
        logging.error(f"[MAIN] Failed to load setpoints, using defaults: {e}")
        current_setpoints = {
            "START_PUMP_AT": 0.9,
            "STOP_PUMP_AT": 0.8,
            "HI_ALARM": 9.5,
            "LO_ALARM": 0.2,
            "SITE_NAME": "B2",
        }

    # --------- DETERMINISTIC STARTUP PUMP STATE ----------
    logging.info("[PUMP] Startup: forcing pump OFF for known safe state.")
    try:
        send_relay_command("relay off 0")
    except Exception as e:
        logging.error(f"[PUMP] Startup: failed to force OFF: {e}")

    pump_is_on = False
    logging.info("[PUMP] Startup: pump_is_on set to False (deterministic).")

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
            # read_depth is expected to return (depth_ft, mA, voltage)
            depth, mA, voltage = read_depth(chan)
            logging.info(
                f"[MEASURE] depth={depth:.2f} ft  mA={mA:.3f}  V={voltage:.3f}"
            )
        except Exception as e:
            logging.error(f"[MAIN] Error reading depth: {e}")
            # Always assign something so the rest of the loop can continue
            depth, mA, voltage = 0.0, 0.0, 0.0

        # -------- APPLY ZERO OFFSET --------
        try:
            zero_offset = current_setpoints.get("ZERO_OFFSET", 0.0)
            depth_raw = depth
            depth = max(0.0, depth_raw - zero_offset)
            # Correct zero adjustment: depth = raw + offset
            adjusted = depth_raw + zero_offset
            logging.info(
            f"[ZERO] Applied zero_offset={zero_offset:.3f} → adjusted_depth={adjusted:.3f} (raw={depth_raw:.3f})"
            )
            depth = adjusted

        except Exception as e:
            logging.error(f"[ZERO] Failed to apply zero offset: {e}")

        # ---------- Downlink ----------
        try:
            dl = rak.check_downlink() 
            if dl:
                logging.info(f"[DOWNLINK] Received raw: {dl}")
                process_downlink_command(dl)
                # Reload setpoints after any downlink
                try:
                    current_setpoints = load_setpoints()
                    logging.info(f"[SETPOINTS] Reloaded after downlink: {current_setpoints}")
                except Exception as e:
                    logging.error(f"[SETPOINTS] Failed to reload after downlink: {e}")
        except Exception as e:
            logging.error(f"[MAIN] Downlink check error: {e}")

        # ---------- Setpoints ----------
        start_depth = current_setpoints.get("START_PUMP_AT", 0.9)
        stop_depth  = current_setpoints.get("STOP_PUMP_AT", 0.8)
        hi_alarm    = current_setpoints.get("HI_ALARM", 9.5)
        lo_alarm    = current_setpoints.get("LO_ALARM", 0.2)
        site_name   = current_setpoints.get("SITE_NAME", "B2")

        # -----------------------------------------------------------------------
        # PUMP CONTROL (override first)
        # -----------------------------------------------------------------------
        override = is_override_active()

        if override:
            logging.info("[OVERRIDE] ACTIVE → Pump forced OFF.")
            if pump_is_on:
                turn_pump_off()
            pump_is_on = False
        else:
            # Normal automatic pump logic
            if pump_is_on and depth <= stop_depth:
                logging.info(
                    f"[PUMP] depth={depth:.2f} <= STOP_PUMP_AT={stop_depth:.2f} → OFF"
                )
                turn_pump_off()
                pump_is_on = False
            elif (not pump_is_on) and depth >= start_depth:
                logging.info(
                    f"[PUMP] depth={depth:.2f} >= START_PUMP_AT={start_depth:.2f} → ON"
                )
                turn_pump_on()
                pump_is_on = True

        # ----------------------------------------------------------
        # ALARMS
        # ----------------------------------------------------------
        hi_alarm_tripped = depth > hi_alarm
        lo_alarm_tripped = depth < lo_alarm

        if hi_alarm_tripped or lo_alarm_tripped:
            set_alarm_light_hw(True)
        else:
            set_alarm_light_hw(False)

        alarm_hi_on = hi_alarm_tripped
        alarm_lo_on = lo_alarm_tripped

        # ---------- Telemetry send ----------
        if time.time() - last_send_time >= INTERVAL_MINUTES * 60:
            telemetry = {
                "device": DEVICE_NAME,
                "ts": datetime.utcnow().isoformat(),
                "depth_ft": depth,
                "mA": mA,
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
                ok = send_data_to_chirpstack(rak, telemetry)
                if not ok:
                    logging.warning("[MAIN] Send failed; attempting RAK reconnect.")
                    rak2 = reconnect_rak()
                    if rak2 is not None:
                        rak = rak2
            except Exception as e:
                logging.error(f"[MAIN] Telemetry send error: {e}")

            last_send_time = time.time()

        time.sleep(READ_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
