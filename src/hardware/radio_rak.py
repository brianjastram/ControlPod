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


def _interpret_njs(lines: list[str]) -> tuple[bool, bool]:
    """
    Returns (joined, not_joined) based on response lines.
    """
    joined = False
    not_joined = False
    for line in lines:
        s = line.strip().upper()
        if not s:
            continue
        if "AT_NO_NETWORK_JOINED" in s:
            not_joined = True
        if "NJS" in s:
            if "1" in s:
                joined = True
            elif "0" in s:
                not_joined = True
        elif s == "1":
            joined = True
        elif s == "0":
            not_joined = True
    return joined, not_joined


def _query_join_status(rak: RAK3172Communicator) -> list[str]:
    """
    Try multiple join-status commands (RUI3/RUI4 differences).
    Returns response lines (may be empty or include errors).
    """
    cmds = ["AT+NJS=?", "AT+NJS", "AT+NJS?"]
    for cmd in cmds:
        try:
            resp = rak.send_command(cmd)
            return resp
        except Exception as e:
            log.debug(f"[RAK] NJS query failed for {cmd}: {e}")
    return []


def _parse_setting(lines: list[str], key: str) -> Optional[int]:
    prefix = f"AT+{key}="
    for line in lines:
        s = line.strip().upper()
        if s.startswith(prefix):
            value = s[len(prefix):].strip()
            digits = ""
            for ch in value:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            if digits:
                return int(digits)
    return None


def _get_setting(rak: RAK3172Communicator, key: str) -> Optional[int]:
    cmds = [f"AT+{key}=?", f"AT+{key}?", f"AT+{key}"]
    for cmd in cmds:
        try:
            resp = rak.send_command(cmd)
        except Exception as e:
            log.debug(f"[RAK] {key} query failed for {cmd}: {e}")
            continue
        value = _parse_setting(resp, key)
        if value is not None:
            return value
    return None


def _ensure_radio_config(rak: RAK3172Communicator, *, force: bool = False) -> None:
    desired = [
        ("ADR", int(getattr(config, "LORA_ADR", 0))),
        ("DR", int(getattr(config, "LORA_DR", 3))),
        ("CFM", int(getattr(config, "LORA_CFM", 0))),
    ]

    if force:
        for key, value in desired:
            try:
                rak.send_command(f"AT+{key}={value}")
            except Exception as e:
                log.warning(f"[RAK] {key}={value} apply warning: {e}")
        log.debug(
            "[RAK] Forced ADR/DR/CFM -> ADR=%s DR=%s CFM=%s",
            desired[0][1],
            desired[1][1],
            desired[2][1],
        )
        return

    for key, desired_value in desired:
        current = _get_setting(rak, key)
        if current == desired_value:
            continue
        try:
            rak.send_command(f"AT+{key}={desired_value}")
            if current is None:
                log.info(f"[RAK] Set {key}={desired_value} (was unknown)")
            else:
                log.info(f"[RAK] Set {key}={desired_value} (was {current})")
        except Exception as e:
            log.warning(f"[RAK] {key}={desired_value} apply warning: {e}")


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

            # Configure ADR / DR / confirm mode to stable values
            try:
                _ensure_radio_config(rak, force=True)
            except Exception as e:
                log.warning(f"[RAK] ADR/DR/CFM setup warning: {e}")

            joined = False
            try:
                status = _query_join_status(rak)
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
    # 1) Query join status
    resp = _query_join_status(rak)
    log.info(f"[RAK] NJS check -> {' | '.join(resp)}")
    joined, not_joined = _interpret_njs(resp)
    if joined:
        return True
    if not_joined:
        log.warning(f"[RAK] Join check reported NOT JOINED: {' | '.join(resp)}")
    else:
        # Empty/ambiguous responses: assume still joined to avoid needless re-join
        if not resp:
            log.warning("[RAK] NJS check returned no data; assuming joined.")
        else:
            log.warning(f"[RAK] NJS ambiguous ({' | '.join(resp)}); assuming joined.")
        return True

    log.warning("[RAK] Module reports NOT JOINED; attempting re-join...")

    for attempt in range(1, max_join_attempts + 1):
        try:
            resp = rak.send_command(join_cmd)
            log.info(f"[RAK] JOIN attempt {attempt}: immediate response: {' | '.join(resp)}")
        except Exception as e:
            log.error(f"[RAK] JOIN command failed on attempt {attempt}: {e}")
            continue

        time.sleep(10)

        resp2 = _query_join_status(rak)
        log.info(f"[RAK] NJS after JOIN attempt {attempt} -> {' | '.join(resp2)}")
        if _parse_njs_response(resp2):
            log.info("[RAK] Re-join succeeded according to NJS query.")
            return True

    log.error("[RAK] Re-join failed after max attempts.")
    return False


def send_data_to_chirpstack(rak: RAK3172Communicator, telemetry: dict) -> bool:
    global _njs_send_counter

    if rak is None:
        log.debug("[SEND] No RAK instance; skipping uplink.")
        return False

    is_real_rak = hasattr(rak, "send_command")

    if is_real_rak:
        _njs_send_counter += 1
        if _njs_send_counter >= _NJS_CHECK_INTERVAL:
            _njs_send_counter = 0
            if not ensure_joined(rak):
                log.warning("[SEND] RAK not joined; skipping uplink this interval.")
                return False
        if getattr(config, "LORA_ENFORCE_EVERY_SEND", False):
            try:
                _ensure_radio_config(rak, force=True)
            except Exception as e:
                log.warning(f"[RAK] ADR/DR/CFM enforce warning: {e}")

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
        log.debug(f"[SEND] Payload hex ({len(payload_hex)} chars): {payload_hex}")

        # First attempt: legacy format (works on RUI_4.0.6)
        confirmed = bool(getattr(config, "LORA_CFM", 0))
        resp = rak.send_data(
            payload_hex,
            port=1,
            confirmed=confirmed,
            use_port_format=False,
        )
        resp_str = "" if resp is None else str(resp).strip()
        try:
            raw_lines = getattr(rak, "last_response_lines", [])
        except Exception:
            raw_lines = []

        extra = " | raw=" + (" || ".join(raw_lines) if raw_lines else "[]")
        log.info(f"[SEND] RAK: {resp_str or 'NO_RESP'}{extra}")

        # Evaluate the response (legacy format)
        has_tx_done = any("TX_DONE" in l.upper() for l in raw_lines)
        has_param_error = any("AT_PARAM_ERROR" in l.upper() for l in raw_lines) or (
            resp_str and "AT_PARAM_ERROR" in resp_str.upper()
        )
        no_network = resp_str and "AT_NO_NETWORK_JOINED" in resp_str

        if no_network:
            log.error("[SEND] RAK reports no network joined.")
            return False

        if has_tx_done:
            return True

        # No TX_DONE: treat any ERROR as failure
        for line in raw_lines:
            l = line.upper()
            if "ERROR" in l:
                log.error(f"[SEND] RAK reported error: {line}")
                return False

        if resp_str and resp_str.upper().startswith("OK"):
            return True
        return False

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
