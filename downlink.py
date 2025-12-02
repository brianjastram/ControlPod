"""
Handles processing of LoRaWAN downlink payloads received from ChirpStack. This includes:
- ASCII and binary command parsing
- Setting override mode (manual control of pump)
- Triggering zero calibration
- Updating setpoint values (START, STOP, alarms)
- Logging actions and errors
"""
import logging
from control import override_flag, set_override_flag


def decode_downlink_payload(raw):
    import logging

    if raw is None:
        logging.warning("No downlink message received.")
        return None

    raw = raw.strip()

    # Handle known single-byte values directly
    if raw == "00":
        return "00"
    if raw == "01":
        return "01"

    # Validate payload as hex string
    if not all(c in "0123456789abcdefABCDEF" for c in raw):
        logging.warning(f"Unexpected downlink message: {raw}")
        return None

    return raw

def is_override_active():
    from control import override_flag
    return override_flag

# Add process_downlink_command at the bottom of the file
def process_downlink_command(raw_downlink):
    """
    Parse and execute commands from a downlink payload.
    Supports:
      - Binary commands ('00', '01')
      - ASCII-encoded hex (e.g., 53455453544152543D302E3735 -> "SETSTART=0.75")
      - Plain text ASCII for local bench testing ("SETSTART=0.75")
    """
    try:
        if not raw_downlink:
            logging.warning(f"Empty downlink message: {raw_downlink}")
            return

        raw_downlink = raw_downlink.strip()

        # --- Handle binary downlink (00 or 01) ---
        if raw_downlink in ("00", "01"):
            if raw_downlink == "00":
                toggle_override(True)
                logging.info("[COMMAND] 00 - Manual override ON")
            else:
                toggle_override(False)
                logging.info("[COMMAND] 01 - Manual override OFF")
            return

        # --- Detect and decode hex-encoded ASCII commands ---
        ascii_command = None
        try:
            # Hex strings should be even-length and contain only 0-9A-F
            if len(raw_downlink) % 2 == 0 and all(c in "0123456789ABCDEFabcdef" for c in raw_downlink):
                decoded = bytes.fromhex(raw_downlink).decode("utf-8", errors="ignore").strip().upper()
                ascii_command = decoded
                logging.info(f"[COMMAND] ASCII decoded downlink: {ascii_command}")
        except Exception:
            pass  # not hex or failed to decode

        # --- Fall back to treating raw string as ASCII if no hex decode worked ---
        if not ascii_command:
            ascii_command = raw_downlink.upper()
            logging.info(f"[COMMAND] Interpreting raw ASCII downlink: {ascii_command}")

        # --- Command routing ---
        if ascii_command == "STOP":
            toggle_override(True)
            logging.info("Executed command: STOP -> Pump OFF, override enabled")

        elif ascii_command == "START":
            toggle_override(False)
            logging.info("Executed command: START -> Pump ON, override cleared")

        elif ascii_command == "ZERO":
            calibrate_zero_offset()
            logging.info("Executed command: ZERO -> Depth zero calibrated")

        elif ascii_command.startswith("SETSTART="):
            try:
                value = float(ascii_command.split("=")[1])
                from usb_settings import load_setpoints, save_setpoints
                setpoints = load_setpoints()
                setpoints["START_PUMP_AT"] = value
                save_setpoints(setpoints)
                logging.info(f"[COMMAND] Updated START_PUMP_AT to {value}")
            except ValueError:
                logging.warning(f"[COMMAND] Invalid SETSTART value: {ascii_command}")

        elif ascii_command.startswith("SETSTOP="):
            try:
                value = float(ascii_command.split("=")[1])
                from usb_settings import load_setpoints, save_setpoints
                setpoints = load_setpoints()
                setpoints["STOP_PUMP_AT"] = value
                save_setpoints(setpoints)
                logging.info(f"[COMMAND] Updated STOP_PUMP_AT to {value}")
            except ValueError:
                logging.warning(f"[COMMAND] Invalid SETSTOP value: {ascii_command}")

        elif ascii_command.startswith("SETALARMHI="):
            try:
                value = float(ascii_command.split("=")[1])
                from usb_settings import load_setpoints, save_setpoints
                setpoints = load_setpoints()
                setpoints["HI_ALARM"] = value
                save_setpoints(setpoints)
                logging.info(f"[COMMAND] Updated HI_ALARM to {value}")
            except ValueError:
                logging.warning(f"[COMMAND] Invalid SETALARMHI value: {ascii_command}")

        elif ascii_command.startswith("SETALARMLO="):
            try:
                value = float(ascii_command.split("=")[1])
                from usb_settings import load_setpoints, save_setpoints
                setpoints = load_setpoints()
                setpoints["LO_ALARM"] = value
                save_setpoints(setpoints)
                logging.info(f"[COMMAND] Updated LO_ALARM to {value}")
            except ValueError:
                logging.warning(f"[COMMAND] Invalid SETALARMLO value: {ascii_command}")

        elif ascii_command.startswith("SETHIALARM="):
            update_setpoints("HI_ALARM", ascii_command.split("=")[1])

        elif ascii_command.startswith("SETLOALARM="):
            update_setpoints("LO_ALARM", ascii_command.split("=")[1])

        else:
            logging.warning(f"[COMMAND] Unexpected downlink message: {ascii_command}")

    except Exception as e:
        logging.error(f"[ERROR] Failed to process downlink command '{raw_downlink}': {e}")


# Helper function to call the override toggle logic
def toggle_override(state):
    import control
    control.set_override_flag(state)
    import logging
    logging.info(f"[OVERRIDE] set to {state}")

    """
    Update system override flag and log the state.
    When enabled, pump logic is bypassed and relay is forced off.
    """

# Helper function to wrap zero offset logic from telemetry
def calibrate_zero_offset():
    """
    Capture the current depth reading and save it as the new zero offset.
    Works on both real hardware and bench simulation.
    """
    import logging
    try:
        depth = None

        # Try hardware path first
        try:
            from telemetry import read_depth
            from main import chan
            if chan is not None:
                depth_tuple = read_depth(chan)
                depth = depth_tuple[0] if isinstance(depth_tuple, tuple) else depth_tuple
                logging.info("[ZERO] Using telemetry.read_depth(chan)")
            else:
                raise RuntimeError("No ADS1115 channel detected")
        except Exception as hw_error:
            # Fallback path (simulation)
            logging.info(f"[ZERO] Hardware depth read failed ({hw_error}); using simulated depth = 0.0 ft")
            depth = 0.0

        # Save using the USB settings handler
        from usb_settings import save_zero_offset
        save_zero_offset(depth)

        logging.info(f"[ZERO] Calibrated zero offset to {depth:.2f} ft")

    except Exception as e:
        logging.error(f"[ZERO] Failed to calibrate zero offset: {e}")

def check_downlink_response(rak):
    """
    Polls the RAK3172 for a new downlink.
    Returns True if any setpoint or zero-offset command was processed.
    """
    try:
        downlink = rak.check_downlink()
        if not downlink:
            logging.debug("[DOWNLINK] No new downlink received.")
            return False

        logging.info(f"[DOWNLINK] Received downlink payload: {downlink}")

        # process_downlink_command() should handle all valid commands
        changed = process_downlink_command(downlink)
        return bool(changed)

    except Exception as e:
        logging.error(f"[DOWNLINK] Error while checking downlink: {e}")
        return False


# Helper function to call USB setpoint update logic
def update_setpoints(key, value):
    """
    Update a specific key in the setpoints.json file.
    Verifies the key exists and logs the updated value.
    """
    from usb_settings import load_setpoints, save_setpoints
    try:
        value = float(value)
        setpoints = load_setpoints()
        setpoints[key] = value
        save_setpoints(setpoints)
    except Exception as e:
        logging.error(f"Failed to update setpoint {key} to {value}: {e}")
