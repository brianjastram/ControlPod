"""
RAK3172 LoRaWAN radio helper (variant-aware).
"""

import logging
import time
from typing import Optional

from src import config
from src.config import MAX_RETRIES, SITE_ID
from src.model.rak3172_comm import RAK3172Communicator

log = logging.getLogger(__name__)

_NJS_CHECK_INTERVAL = 10
_njs_send_counter = 0


def _parse_njs_response(lines: list[str]) -> bool:
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if "get the join status" in s:
            continue
        if "NJS" in s and "1" in s:
            return True
        if s == "1":
            return True
    return False


def connect(port: Optional[str] = None) -> Optional[RAK3172Communicator]:
    primary = port or getattr(config, "SERIAL_PORT", "/dev/rak")
    candidates = getattr(config, "RAK_PORT_CANDIDATES", [])
    ports_to_try = [p for p in [primary, *candidates] if p]
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            port_try = ports_to_try[(attempt - 1) % len(ports_to_try)]
            rak = RAK3172Communicator(port_try)
            rak.connect()
            log.info(f"[RAK] Connected to RAK3172 on {port_try}")

            try:
                rak.send_command("AT+NWM=1")
                rak.send_command("AT+NJM=1")
            except Exception as e:
                log.warning(f"[RAK] NWM/NJM setup warning: {e}")

            joined = False
            try:
                status = rak.send_command("AT+NJS")
                log.info("[RAK] NJS check (connect) -> " + " | ".join(status))
                if _parse_njs_response(status):
                    joined = True
                    log.info("[RAK] Already joined (NJS=1).")
            except Exception as e:
                log.warning(f"[RAK] NJS query failed: {e}")

            if not joined:
                log.info("[RAK] Not joined, sending AT+JOIN=1:1:10:5 ...")
                join_lines = rak.send_command("AT+JOIN=1:1:10:5")
                log.info("[RAK] JOIN immediate response: " + " | ".join(join_lines))

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
    try:
        resp = rak.send_command("AT+NJS")
        log.info(f"[RAK] NJS check -> {' | '.join(resp)}")
        if _parse_njs_response(resp):
            return True
    except Exception as e:
        log.warning(f"[RAK] NJS check failed: {e}")

    log.warning("[RAK] Module reports NOT JOINED; attempting re-join...")

    for attempt in range(1, max_join_attempts + 1):
        try:
            resp = rak.send_command(join_cmd)
            log.info(f"[RAK] JOIN attempt {attempt}: immediate response: {' | '.join(resp)}")
        except Exception as e:
            log.error(f"[RAK] JOIN command failed on attempt {attempt}: {e}")
            continue

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
    global _njs_send_counter

    if rak is None:
        log.debug("[SEND] No RAK instance — skipping uplink.")
        return False

    is_real_rak = hasattr(rak, "send_command")

    if is_real_rak:
        _njs_send_counter += 1
        if _njs_send_counter >= _NJS_CHECK_INTERVAL:
            _njs_send_counter = 0
            if not ensure_joined(rak):
                log.warning("[SEND] RAK not joined; skipping uplink this interval.")
                return False

    try:
        depth_ft = float(telemetry.get("depth", 0.0))
        current_mA = float(telemetry.get("current_mA", 0.0))
        voltage_V = float(telemetry.get("voltage", 0.0))
        start_ft = float(telemetry.get("start", 0.0))
        stop_ft = float(telemetry.get("stop", 0.0))

        hi_alarm = bool(telemetry.get("hi_alarm", False))
        lo_alarm = bool(telemetry.get("lo_alarm", False))
        override = bool(telemetry.get("override", False))
        pump_on = bool(telemetry.get("pump_on", False))

        site_id = SITE_ID

        depth_x100 = int(round(depth_ft * 100.0))
        current_uA = int(round(current_mA * 1000.0))
        voltage_mV = int(round(voltage_V * 1000.0))
        start_x100 = int(round(start_ft * 100.0))
        stop_x100 = int(round(stop_ft * 100.0))

        flags = 0
        if hi_alarm:
            flags |= 0x01
        if lo_alarm:
            flags |= 0x02
        if override:
            flags |= 0x04
        if pump_on:
            flags |= 0x08

        payload = bytearray(14)
        payload[0] = 1
        payload[1] = flags
        payload[2] = (depth_x100 >> 8) & 0xFF
        payload[3] = depth_x100 & 0xFF
        payload[4] = (current_uA >> 8) & 0xFF
        payload[5] = current_uA & 0xFF
        payload[6] = (voltage_mV >> 8) & 0xFF
        payload[7] = voltage_mV & 0xFF
        payload[8] = (start_x100 >> 8) & 0xFF
        payload[9] = start_x100 & 0xFF
        payload[10] = (stop_x100 >> 8) & 0xFF
        payload[11] = stop_x100 & 0xFF
        payload[12] = (site_id >> 8) & 0xFF
        payload[13] = site_id & 0xFF

        log.info(
            "[SEND] Packed uplink len=%d depth_ft=%.3f (x100=%d) mA=%.3f (uA=%d) "
            "volts=%.3f (mV=%d) start_ft=%.3f (x100=%d) stop_ft=%.3f (x100=%d) "
            "flags=0x%02X site_id=0x%04X",
            len(payload),
            depth_ft, depth_x100,
            current_mA, current_uA,
            voltage_V, voltage_mV,
            start_ft, start_x100,
            stop_ft, stop_x100,
            flags, site_id,
        )

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


def reconnect_rak(rak: RAK3172Communicator) -> Optional[RAK3172Communicator]:
    global _njs_send_counter
    log.info("[RAK] Attempting RAK reconnect...")
    _njs_send_counter = 0
    return connect()


def build_radio(driver: str):
    if driver == "rak3172":
        return {
            "connect": connect,
            "ensure_joined": ensure_joined,
            "send_data": send_data_to_chirpstack,
            "reconnect": reconnect_rak,
        }
    raise ValueError(f"Unknown radio driver: {driver}")
