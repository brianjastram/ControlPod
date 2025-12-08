import logging
import serial
import RPi.GPIO as GPIO
from src.config import MAX_RETRIES
from src.model.rak3172_comm import RAK3172Communicator
from src.config import RELAY_DEV, ALARM_GPIO_PIN
import time
import json

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# RAK helpers
# ---------------------------------------------------------------------------

def connect():
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
                status = rak.send_command("AT+NJS?")
                log.info("[RAK] NJS? -> " + " | ".join(status))
                if any("+NJS:" in line and "1" in line for line in status):
                    joined = True
                    log.info("[RAK] Already joined (NJS=1).")
            except Exception as e:
                log.warning(f"[RAK] NJS? query failed: {e}")

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
                        status2 = rak.send_command("AT+NJS?")
                        log.info("[RAK] NJS? (post-join) -> " + " | ".join(status2))
                        if any("+NJS:" in line and "1" in line for line in status2):
                            joined = True
                            log.info("[RAK] Join confirmed via NJS=1.")
                        else:
                            log.warning("[RAK] Still not joined after join window.")
                    except Exception as e:
                        log.warning(f"[RAK] NJS? post-join failed: {e}")

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


def send_data_to_chirpstack(rak: RAK3172Communicator, telemetry: dict) -> bool:
    """
    Encode telemetry as JSON, hex-encode, and send via RAK.

    Returns True if the send looked OK, False if the module reported
    AT_NO_NETWORK_JOINED or another obvious error.
    """
    try:
        payload_hex = json.dumps(telemetry).encode("utf-8").hex()

        # ---- CLEAN SEND LOGGING ----
        log.info(f"[SEND] uplink sent (bytes={len(payload_hex)})")

        resp = rak.send_data(payload_hex)  # returns string from rak3172_comm
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
    
    log.info("[RAK] Attempting RAK reconnect...")
    return connect()