"""
Handles processing of LoRaWAN downlink payloads received from ChirpStack. This includes:
- ASCII and hex-encoded ASCII command parsing
- Setting override mode (manual control of pump)
- Triggering zero calibration
- Updating setpoint values (START, STOP, alarms, zero offset)
- Logging actions and errors
"""
import logging
from src.control import (
    toggle_override as control_toggle_override,
    is_override_active as control_is_override_active,
)
from src.telemetry import read_depth
from src.usb_settings import save_zero_offset, load_setpoints, save_setpoints
from src import shared_state

log = logging.getLogger(__name__)


def decode_downlink_payload(raw):
    """
    Normalize and sanity-check the raw downlink payload string.

    Expected usage with ChirpStack:
      - "HEX" encoding mode, where payload is hex-encoded ASCII, e.g.
        53455453544152543D302E3735 -> "SETSTART=0.75"

    This function just:
      - strips whitespace
      - verifies it looks like hex
      - returns the cleaned string (or None on obvious garbage)
    """
    if raw is None:
        log.warning("No downlink message received.")
        return None

    raw = raw.strip()

    if not raw:
        log.warning("Empty downlink payload.")
        return None

    # Validate payload as hex string
    if not all(c in "0123456789abcdefABCDEF" for c in raw):
        log.warning(f"Unexpected non-hex downlink message: {raw}")
        return None

    return raw


def is_override_active():
    # Use the control module's file-backed flag so main loop sees updates
    return control_is_override_active()


def _parse_ascii_from_hex_or_raw(downlink: str, original_raw: str) -> str:
    """
    Try to interpret the downlink as hex-encoded ASCII.
    If that fails, fall back to treating the raw string as ASCII.
    Returns an upper-cased ASCII command string.
    """
    ascii_command = None

    # Try hex -> ASCII first
    try:
        if len(downlink) % 2 == 0 and all(
            c in "0123456789ABCDEFabcdef" for c in original_raw
        ):
            decoded = bytes.fromhex(downlink).decode(
                "utf-8", errors="ignore"
            ).strip()
            if decoded:
                ascii_command = decoded.upper()
                log.info(f"[COMMAND] ASCII decoded downlink: {ascii_command}")
    except Exception:
        # Not valid hex or not valid UTF-8 – we'll fall back to raw
        pass

    if not ascii_command:
        ascii_command = downlink.upper()
        log.info(f"[COMMAND] Interpreting raw ASCII downlink: {ascii_command}")

    return ascii_command


def process_downlink_command(raw_downlink):
    """
    Parse and execute commands from a downlink payload.

    Supports (all via ASCII, typically hex-encoded from ChirpStack):

      - "STOP"
      - "START"
      - "ZERO"
      - "SETSTART=<float>"
      - "SETSTOP=<float>"
      - "SETALARMHI=<float>" / "SETHIALARM=<float>"
      - "SETALARMLO=<float>" / "SETLOALARM=<float>"
      - "SETOFFSET=<float>" / "SETZERO=<float>" / "SETZEROOFFSET=<float>"
      - "SETOVERRIDE=<0 or 1>"   (0 = override off, 1 = override on)

    Returns True if a valid command was recognized and acted upon, False otherwise.
    """

    if not raw_downlink:
        log.warning(f"Empty downlink message: {raw_downlink}")
        return False

    changed = False

    try:
        downlink = raw_downlink.strip()
        ascii_command = _parse_ascii_from_hex_or_raw(downlink, raw_downlink)

        # --- Simple keyword commands ---
        if ascii_command == "STOP":
            # STOP: enable override and (in control module) ensure pump is off
            toggle_override(True)
            log.info("Executed command: STOP -> Pump OFF, override enabled")
            return True

        if ascii_command == "START":
            # START: clear override and let normal logic control pump
            toggle_override(False)
            log.info("Executed command: START -> Pump ON (via normal logic), override cleared")
            return True

        if ascii_command == "ZERO":
            calibrate_zero_offset()
            log.info("Executed command: ZERO -> Depth zero calibrated")
            return True

        # --- Key=Value style commands ---
        parts = ascii_command.split("=")
        if len(parts) != 2:
            log.error(f"[COMMAND] Unexpected downlink message: {ascii_command}")
            return False

        command_name, command_value = parts[0].strip(), parts[1].strip()

        if command_name == "SETSTART":
            update_setpoints("START_PUMP_AT", command_value)
            changed = True

        elif command_name == "SETSTOP":
            update_setpoints("STOP_PUMP_AT", command_value)
            changed = True

        elif command_name in ("SETALARMHI", "SETHIALARM"):
            update_setpoints("HI_ALARM", command_value)
            changed = True

        elif command_name in ("SETALARMLO", "SETLOALARM"):
            update_setpoints("LO_ALARM", command_value)
            changed = True

        elif command_name in ("SETOFFSET", "SETZERO", "SETZEROOFFSET"):
            update_setpoints("ZERO_OFFSET", command_value)
            log.info(f"[COMMAND] Set zero offset to {command_value}")
            changed = True

        elif command_name == "SETOVERRIDE":
            # New: remote override via ASCII
            try:
                # Anything non-zero -> True, exactly 0 -> False
                val = float(command_value)
                state = (val != 0.0)
                toggle_override(state)
                log.info(f"[COMMAND] SETOVERRIDE={command_value} -> override set to {state}")
                changed = True
            except ValueError:
                log.warning(f"[COMMAND] Invalid SETOVERRIDE value: {command_value}")

        else:
            log.error(f"[COMMAND] Invalid downlink command: {ascii_command}")
            changed = False

    except Exception as e:
        log.error(f"[ERROR] Failed to process downlink command '{raw_downlink}': {e}")
        return False

    return changed


# Helper function to call the override toggle logic
def toggle_override(state):
    """
    Update system override flag and log the state.
    When enabled, pump logic is bypassed and relay is forced by manual control.
    """
    control_toggle_override(state)
    log.info(f"[OVERRIDE] set to {state}")


# Helper function to wrap zero offset logic from telemetry
def calibrate_zero_offset():
    """
    Capture the current depth reading and save it as the new zero offset.
    Works on both real hardware and bench simulation.
    """
    try:
        depth = None

        # Try hardware path first
        try:
            if shared_state.analog_input_channel is not None:
                depth_telemetry = read_depth(shared_state.analog_input_channel)
                depth = depth_telemetry.depth
                log.info("[ZERO] Using telemetry.read_depth(chan)")
            else:
                raise RuntimeError("No ADS1115 channel detected")
        except Exception as hw_error:
            # Fallback path (simulation)
            log.info(f"[ZERO] Hardware depth read failed ({hw_error}); using simulated depth = 0.0 ft")
            depth = 0.0

        # Save using the USB settings handler
        save_zero_offset(depth)

        log.info(f"[ZERO] Calibrated zero offset to {depth:.2f} ft")

    except Exception as e:
        log.error(f"[ZERO] Failed to calibrate zero offset: {e}")


def check_downlink_response(rak):
    """
    Polls the RAK3172 for a new downlink.
    Returns True if any setpoint / override / zero-offset command was processed.
    """
    try:
        downlink = rak.check_downlink()
        if not downlink:
            log.debug("[DOWNLINK] No new downlink received.")
            return False

        log.info(f"[DOWNLINK] Received downlink payload: {downlink}")

        changed = process_downlink_command(downlink)
        return bool(changed)

    except Exception as e:
        log.error(f"[DOWNLINK] Error while checking downlink: {e}")
        return False


def update_setpoints(key, value):
    """
    Update a specific key in the setpoints.json file.
    Verifies the key exists and logs the updated value.
    """
    try:
        value = float(value)
        setpoints = load_setpoints()
        setpoints[key] = value
        save_setpoints(setpoints)
        log.info(f"[SETPOINT] {key} updated to {value}")
    except ValueError:
        log.warning(f"[COMMAND] Invalid {key} value: {value}")
    except Exception as e:
        log.error(f"Failed to update setpoint {key} to {value}: {e}")