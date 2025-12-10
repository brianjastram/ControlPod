import logging
import serial
import RPi.GPIO as GPIO
from src.config import MAX_RETRIES, SITE_ID
from src.model.rak3172_comm import RAK3172Communicator
from src.config import RELAY_DEV, ALARM_GPIO_PIN
import time
import json

log = logging.getLogger(__name__)

# How often to check join status (in number of sends)
_NJS_CHECK_INTERVAL = 10
_njs_send_counter = 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_njs_response(lines: list[str]) -> bool:
    """
    Best-effort parser for AT+NJS responses.

    Different firmwares may return:
      - "0" or "1"
      - "+NJS:0" / "+NJS:1"
      - "AT+NJS=0" / "AT+NJS=1"

    We treat anything containing '1' (and not obviously just help text)
    as "joined".
    """
    for line in lines:
        s = line.strip()
        if not s:
            continue

        # Help text looks like: "AT+NJS,R: get the join status (0 = not joined, 1 = joined)"
        if "get the join status" in s:
            continue

        if "NJS" in s and "1" in s:
            return True
        if s == "1":
            return True

    return False


# ---------------------------------------------------------------------------
# RAK helpers
# ---------------------------------------------------------------------------

def connect() -> RAK3172Communicator | None:
    """
    Connect to the RAK3172 on /dev/rak and try to ensure it is joined.

    Uses:
      - AT+NWM=1   (LoRaWAN mode)
      - AT+NJM=1   (OTAA)
      - AT+NJS     (check join status)
      - AT+JOIN=1:1:10:5 (force OTAA join with retry window)
    """
    port = "/dev/rak"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            rak = RAK3172Communicator(port)
            rak.connect()
            log.info(f"[RAK] Connected to RAK3172 on {port}")

            # Make sure we are in LoRaWAN + OTAA mode
            try:
                rak.send_command("AT+NWM=1")
                rak.send_command("AT+NJM=1")
            except Exception as e:
                log.warning(f"[RAK] NWM/NJM setup warning: {e}")

            # Check join status
            joined = False
            try:
                status = rak.send_command("AT+NJS")
                log.info("[RAK] NJS check (connect) -> " + " | ".join(status))
                if _parse_njs_response(status):
                    joined = True
                    log.info("[RAK] Already joined (NJS=1).")
            except Exception as e:
                log.warning(f"[RAK] NJS query failed: {e}")

            # If not joined, attempt join
            if not joined:
                log.info("[RAK] Not joined, sending AT+JOIN=1:1:10:5 ...")
                join_lines = rak.send_command("AT+JOIN=1:1:10:5")
                log.info("[RAK] JOIN immediate response: " + " | ".join(join_lines))

                # Watch the UART for join events for up to 30 seconds
                for _ in range(30):
                    time.sleep(1)
                    buf = rak.serial_port.read_all().decode(errors="ignore")
                    if not buf:
                        continue
                    buf_upper = buf.upper()
                    log.info(f"[RAK] Join event RX: {buf.strip()}")
                    if "JOINED" in buf_upper or "NETWORK JOINED" in buf_upper:
                        joined = True
                        log.info("[RAK] Join success detected from UART.")
                        break

                if not joined:
                    # Final status check
                    try:
                        status2 = rak.send_command("AT+NJS")
                        log.info("[RAK] NJS (post-join) -> " + " | ".join(status2))
                        if _parse_njs_response(status2):
                            joined = True
                            log.info("[RAK] Join confirmed via NJS=1.")
                        else:
                            log.warning("[RAK] Still not joined after join window.")
                    except Exception as e:
                        log.warning(f"[RAK] NJS post-join query failed: {e}")

            if not joined:
                log.warning(
                    "[RAK] Proceeding, but module reports NOT JOINED; "
                    "uplinks will return AT_NO_NETWORK_JOINED until join completes."
                )

            return rak

        except Exception as e:
            log.error(f"[RAK] Connect error ({attempt}/{MAX_RETRIES}): {e}")
            time.sleep(2)

    log.error("[RAK] Max retries reached. Could not connect to RAK3172.")
    return None


def ensure_joined(
    rak: RAK3172Communicator,
    max_join_attempts: int = 2,
    join_cmd: str = "AT+JOIN=1:1:10:5",
) -> bool:
    """
    Light health check: verify the RAK reports 'joined', and if not,
    try to re-join automatically.

    Returns True if we are (or become) joined, False if we fail.
    """

    # 1) Query join status
    try:
        resp = rak.send_command("AT+NJS")
        log.info(f"[RAK] NJS check -> {' | '.join(resp)}")
        if _parse_njs_response(resp):
            return True
    except Exception as e:
        log.warning(f"[RAK] NJS check failed: {e}")
        # fall through and *attempt* a join anyway

    log.warning("[RAK] Module reports NOT JOINED; attempting re-join...")

    # 2) Attempt re-join a few times
    for attempt in range(1, max_join_attempts + 1):
        try:
            resp = rak.send_command(join_cmd)
            log.info(f"[RAK] JOIN attempt {attempt}: immediate response: {' | '.join(resp)}")
        except Exception as e:
            log.error(f"[RAK] JOIN command failed on attempt {attempt}: {e}")
            continue

        # Allow time for join exchange and EVTs
        time.sleep(10)

        try:
            resp2 = rak.send_command("AT+NJS")
            log.info(f"[RAK] NJS after JOIN attempt {attempt} -> {' | '.join(resp2)}")
            if _parse_njs_response(resp2):
                log.info("[RAK] Re-join succeeded according to AT+NJS.")
                return True
        except Exception as e:
            log.warning(f"[RAK] NJS re-check failed after JOIN attempt {attempt}: {e}")

    log.error("[RAK] Re-join failed after max attempts.")
    return False


def send_data_to_chirpstack(rak: RAK3172Communicator, telemetry: dict) -> bool:
    """
    Build the 14-byte binary payload compatible with the legacy codec and send it.

    Layout (same as legacy ControlPod main):

        byte 0 : protocol version (1)
        byte 1 : flags (bitfield)
        bytes 2-3  : depth_x100 (uint16 big-endian)        depth [ft] * 100
        bytes 4-5  : current_uA (uint16 big-endian)        current [mA] * 1000
        bytes 6-7  : voltage_mV (uint16 big-endian)        voltage [V] * 1000
        bytes 8-9  : start_x100 (uint16 big-endian)        start [ft] * 100
        bytes 10-11: stop_x100 (uint16 big-endian)         stop [ft] * 100
        bytes 12-13: site_id (uint16 big-endian)           fixed site ID
    """
    global _njs_send_counter

    if rak is None:
        log.debug("[SEND] No RAK instance – skipping uplink.")
        return False

    # -------- Light join health check --------
    _njs_send_counter += 1
    if _njs_send_counter >= _NJS_CHECK_INTERVAL:
        _njs_send_counter = 0
        if not ensure_joined(rak):
            log.warning("[SEND] RAK not joined; skipping uplink this interval.")
            return False

    try:
        # Extract and normalize fields from the telemetry dict
        depth_ft   = float(telemetry.get("depth", 0.0))
        current_mA = float(telemetry.get("current_mA", 0.0))
        voltage_V  = float(telemetry.get("voltage", 0.0))
        start_ft   = float(telemetry.get("start", 0.0))
        stop_ft    = float(telemetry.get("stop", 0.0))

        hi_alarm   = bool(telemetry.get("hi_alarm", False))
        lo_alarm   = bool(telemetry.get("lo_alarm", False))
        override   = bool(telemetry.get("override", False))
        pump_on    = bool(telemetry.get("pump_on", False))

        site_id = SITE_ID

        # Scale to integers (match legacy behavior)
        depth_x100   = int(round(depth_ft * 100.0))
        current_uA   = int(round(current_mA * 1000.0))
        voltage_mV   = int(round(voltage_V * 1000.0))
        start_x100   = int(round(start_ft * 100.0))
        stop_x100    = int(round(stop_ft * 100.0))

        # Flags bitfield (same as legacy main)
        flags = 0
        if hi_alarm:
            flags |= 0x01
        if lo_alarm:
            flags |= 0x02
        if override:
            flags |= 0x04
        if pump_on:
            flags |= 0x08

        # Build 14-byte payload
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

        # Log the packed frame for debugging
        log.info(
            "[SEND] Packed uplink len=%d "
            "depth_ft=%.3f (x100=%d) mA=%.3f (uA=%d) "
            "volts=%.3f (mV=%d) start_ft=%.3f (x100=%d) "
            "stop_ft=%.3f (x100=%d) flags=0x%02X site_id=0x%04X",
            len(payload),
            depth_ft, depth_x100,
            current_mA, current_uA,
            voltage_V, voltage_mV,
            start_ft, start_x100,
            stop_ft, stop_x100,
            flags, site_id,
        )

        # Hex-encode for AT+SEND (same as legacy rak3172_comm usage)
        payload_hex = payload.hex()

        resp = rak.send_data(payload_hex)
        if resp is None or str(resp).strip() == "":
            log.debug("[SEND] RAK: no response")
            return False

        resp_str = str(resp).strip()
        log.info(f"[SEND] RAK: {resp_str}")

        if "AT_NO_NETWORK_JOINED" in resp_str:
            log.error("[SEND] RAK reports no network joined.")
            return False

        return True

    except Exception as e:
        log.error(f"[SEND] Exception while sending uplink: {e}")
        return False


def reconnect_rak(rak: RAK3172Communicator) -> RAK3172Communicator | None:
    """
    Simple reconnect helper used by main.py.
    Currently just calls connect() again and returns the new object (or None).
    """
    global _njs_send_counter

    log.info("[RAK] Attempting RAK reconnect...")
    _njs_send_counter = 0
    return connect()
