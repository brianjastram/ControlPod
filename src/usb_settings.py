import os
import json
import logging
from datetime import datetime
import time
import shutil
from config import LOG_DIR

log = logging.getLogger(__name__)

LOCAL_LOG_DIR = LOG_DIR

LOCAL_OVERRIDE_LOG = os.path.join(LOCAL_LOG_DIR, "override_log.txt")
LOCAL_SETTINGS_LOG = os.path.join(LOCAL_LOG_DIR, "settings_log.txt")

USB_MOUNT_PATH = "/media/usb"
SETPOINTS_FILE = os.path.join(USB_MOUNT_PATH, "setpoints.json")
SETTINGS_LOG_FILE = os.path.join(USB_MOUNT_PATH, "settings_log.txt")
COMMAND_FILE = os.path.join(USB_MOUNT_PATH, "command.txt")

OVERRIDE_LOG_FILE = os.path.join(USB_MOUNT_PATH, "override_log.txt")

def _log_to_targets(message: str, targets):
    for path in targets:
        try:
            parent = os.path.dirname(path)
            # only ensure local directory; USB root should already exist
            if parent and parent.startswith(LOCAL_LOG_DIR):
                os.makedirs(parent, exist_ok=True)
            with open(path, "a") as f:
                f.write(message + "\n")
                f.flush()
                os.fsync(f.fileno())   # force write to media
        except Exception as e:
            log.warning(f"[LOG WRITE FAILED] {path}: {e}")

def log_override_change(state: bool, source: str = "runtime"):
    """Log an override change to both local and USB logs."""
    log.info(f"[LOG] override_change -> state={state} source={source}")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp} - Override {'ON' if state else 'OFF'} (source={source})"
    _log_to_targets(line, [LOCAL_OVERRIDE_LOG, OVERRIDE_LOG_FILE])


def log_setting_change(key: str, old_value, new_value, source: str = "downlink"):
    """Log a single setting change to both local and USB logs."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp} - Setting '{key}': {old_value} -> {new_value} (source={source})"
    _log_to_targets(line, [LOCAL_SETTINGS_LOG, SETTINGS_LOG_FILE])


def load_zero_offset():
    """Read the current zero_offset_ft from setpoints.json."""
    try:
        if not os.path.exists(SETPOINTS_FILE):
            raise FileNotFoundError(f"{SETPOINTS_FILE} not found")
        with open(SETPOINTS_FILE, 'r') as f:
            setpoints = json.load(f)
            return setpoints.get("zero_offset_ft", 0.0)
    except Exception as e:
        log.error(f"Failed to load zero offset: {e}")
        return 0.0

def save_zero_offset(offset_ft):
    """Update the zero_offset_ft and ZERO_OFFSET values in setpoints.json."""
    try:
        setpoints = {}
        if os.path.exists(SETPOINTS_FILE):
            with open(SETPOINTS_FILE, 'r') as f:
                setpoints = json.load(f)

        if (setpoints.get("zero_offset_ft") != offset_ft or
            setpoints.get("ZERO_OFFSET") != offset_ft):
            setpoints["zero_offset_ft"] = offset_ft
            setpoints["ZERO_OFFSET"] = offset_ft
            save_setpoints(setpoints)
            log.info(f"[ZERO] Saved zero offset {offset_ft:.2f} ft to setpoints.json")
    except Exception as e:
        log.error(f"Failed to save zero offset: {e}")

def load_setpoints():
    """Load setpoints from the USB key."""
    if not os.path.exists(SETPOINTS_FILE):
        raise FileNotFoundError(f"Setpoints file not found at {SETPOINTS_FILE}")
    with open(SETPOINTS_FILE, 'r') as f:
        return json.load(f)



# Timestamp for last write to settings_log.txt
last_write_time = 0  # global timestamp

def save_setpoints(setpoints):
    """
    Save setpoints to the USB key, including ZERO_OFFSET.
    Only writes if there is a change to avoid excessive writes.
    """
    global last_write_time
    now = time.time()

    # Load the previous setpoints from the USB file
    try:
        with open(SETPOINTS_FILE, "r") as f:
            old_setpoints = json.load(f)
    except Exception:
        old_setpoints = {}

    # Ensure all expected keys are included in the new setpoints
    full_setpoints = {
    "START_PUMP_AT": setpoints.get("START_PUMP_AT", old_setpoints.get("START_PUMP_AT")),
    "STOP_PUMP_AT": setpoints.get("STOP_PUMP_AT", old_setpoints.get("STOP_PUMP_AT")),
    "HI_ALARM": setpoints.get("HI_ALARM", old_setpoints.get("HI_ALARM")),
    "LO_ALARM": setpoints.get("LO_ALARM", old_setpoints.get("LO_ALARM")),
    "ZERO_OFFSET": setpoints.get("ZERO_OFFSET", old_setpoints.get("ZERO_OFFSET")),
    "SITE_NAME": setpoints.get("SITE_NAME", old_setpoints.get("SITE_NAME", "B2")),
    }


    # Only proceed if there is a change
    if full_setpoints != old_setpoints:
        log.info("[USB] Setpoints changed. Updating...")

        if now - last_write_time > 10:
            _log_to_targets(
                f"{datetime.now().isoformat()} - Updated setpoints: {full_setpoints}",
                [LOCAL_SETTINGS_LOG, SETTINGS_LOG_FILE],
            )
            last_write_time = now

        try:
            # Write the updated setpoints to the USB drive
            with open(SETPOINTS_FILE, "w") as f:
                json.dump(full_setpoints, f, indent=2)

            # After writing to USB, mirror to the local copy
            try:
                shutil.copy2(SETPOINTS_FILE, LOCAL_SETPOINTS_FILE)
                log.info("[SYNC] Mirrored updated setpoints to local copy.")
            except Exception as e:
                log.error(f"[SYNC] Failed to copy setpoints to local: {e}")

        except Exception as e:
            log.error(f"Failed to update setpoints.json: {e}")

    else:
        log.debug("[USB] No change in setpoints.")



def update_setpoints_if_changed(current_setpoints):
    """
    Load setpoints from USB and update if different from current.
    Log changes and return updated setpoints if changed.
    """
    try:
        new_setpoints = load_setpoints()
        if new_setpoints != current_setpoints:
            print("[USB] Setpoints changed. Updating...")
            save_setpoints(new_setpoints)
            return new_setpoints
        else:
            print("[USB] No change in setpoints.")
    except Exception as e:
        print(f"[USB] Error updating setpoints: {e}")
    return current_setpoints

# --- Sync Logic Between USB and Local Files ---

LOCAL_SETPOINTS_FILE = "/home/pi/setpoints.json"

def sync_usb_to_local():
    """
    If the USB setpoints file exists and is newer than the local copy,
    copy it to /home/pi/setpoints.json so the control logic uses the latest settings.
    """
    try:
        if not os.path.exists(SETPOINTS_FILE):
            log.info("[SYNC] No USB setpoints file found; skipping sync.")
            return False

        usb_mtime = os.path.getmtime(SETPOINTS_FILE)
        local_mtime = os.path.getmtime(LOCAL_SETPOINTS_FILE) if os.path.exists(LOCAL_SETPOINTS_FILE) else 0

        if usb_mtime > local_mtime:
            shutil.copy2(SETPOINTS_FILE, LOCAL_SETPOINTS_FILE)
            log.info("[SYNC] Copied newer USB setpoints to local file.")
            return True
        else:
            log.debug("[SYNC] Local setpoints already up to date.")
    except Exception as e:
        log.error(f"[SYNC] Failed to sync USB→local: {e}")
    return False


def sync_local_to_usb():
    """
    If local setpoints file exists and is newer than USB, copy it to USB.
    This ensures consistency if local changes happen (optional).
    """
    try:
        if not os.path.exists(LOCAL_SETPOINTS_FILE):
            return False

        local_mtime = os.path.getmtime(LOCAL_SETPOINTS_FILE)
        usb_mtime = os.path.getmtime(SETPOINTS_FILE) if os.path.exists(SETPOINTS_FILE) else 0

        if local_mtime > usb_mtime:
            shutil.copy2(LOCAL_SETPOINTS_FILE, SETPOINTS_FILE)
            log.info("[SYNC] Copied newer local setpoints to USB.")
            return True
    except Exception as e:
        log.error(f"[SYNC] Failed to sync local→USB: {e}")
    return False


def write_command_from_downlink(hex_payload):
    """
    Decode hex payload and write it as a structured command to command.txt on the USB.
    Supports specific keywords like:
    - FORCE_PUMP_OFF
    - SET_PUMP_ON=0.2
    - SET_PUMP_OFF=0.1
    - SET_ALARM_ON=1.5
    - SET_ALARM_OFF=1.3
    - ZERO_LEVEL
    """
    try:
        command_str = bytes.fromhex(hex_payload).decode('utf-8').strip()
        print(f"[USB] Decoded downlink command: {command_str}")

        command_data = {}

        if command_str == "FORCE_PUMP_OFF" or command_str == "ZERO_LEVEL":
            command_data = {"command": command_str}
        elif "=" in command_str:
            key, value = command_str.split("=", 1)
            try:
                command_data = {"command": key, "value": float(value)}
            except ValueError:
                print(f"[USB] Invalid numeric value in command: {command_str}")
                return
        else:
            print(f"[USB] Unsupported command format: {command_str}")
            return

        command_data["timestamp"] = datetime.now().isoformat(timespec="seconds")
        with open(COMMAND_FILE, 'w') as f:
            json.dump(command_data, f)
            f.write('\n')

        print(f"[USB] Wrote command to {COMMAND_FILE}: {command_data}")
    except Exception as e:
        print(f"[USB] Failed to write command: {e}")


def handle_rak_downlink(hex_payload):
    """
    Process downlink payload received via RAK3172 and write it to USB.
    :param hex_payload: Hex string of the payload (e.g., "53544f50" for "STOP")
    """
    if not hex_payload:
        print("[RAK] No downlink payload received.")
        return

    print(f"[RAK] Handling downlink payload: {hex_payload}")
    write_command_from_downlink(hex_payload)