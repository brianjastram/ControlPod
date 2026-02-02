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

Set CONTROL_POD_MODE (kclf_v1, kclf_v2) to pick hardware config.
"""

import time
import logging
import signal
import shlex
import subprocess
from pathlib import Path
from datetime import datetime, timezone

from src import config
from src import shared_state
from src import logger
from src.usb_settings import sync_usb_to_local, load_setpoints
from src.downlink import process_downlink_command
from src.control import is_override_active
from src.hardware import depth_sensor as depth_hw
from src.hardware import pump_control
from src.hardware import radio_rak as rak_service
from src.hardware import display as display_hw
from src.model.rak_dummy import DummyRAK

logger.setupLogging()
log = logging.getLogger(__name__)

# Runtime markers (tmpfs) for crash diagnostics.
HEARTBEAT_PATH = Path("/run/controlpod.heartbeat")
LAST_SEND_PATH = Path("/run/controlpod.last_send")
SHUTDOWN_PATH = Path("/run/controlpod.shutdown")
LOW_BATTERY_PATH = Path(getattr(config, "LOW_BATTERY_PATH", "/run/controlpod.low_battery"))
LOW_BATTERY_SHUTDOWN_CMD = getattr(config, "LOW_BATTERY_SHUTDOWN_CMD", "")

_stop_requested = False
_shutdown_reason = "unknown"
_low_battery_seen = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_marker(path: Path, content: str) -> None:
    try:
        path.write_text(content + "\n", encoding="utf-8")
    except Exception as e:
        log.debug(f"[MARKER] Failed to write {path}: {e}")


def _request_shutdown(reason: str) -> None:
    global _stop_requested, _shutdown_reason
    _stop_requested = True
    _shutdown_reason = reason
    _write_marker(SHUTDOWN_PATH, f"{_now_iso()} | {reason}")
    log.warning(f"[MAIN] Shutdown requested: {reason}")


def _handle_sigterm(signum, frame) -> None:
    _request_shutdown(f"signal:{signum}")


def _install_signal_handlers() -> None:
    try:
        signal.signal(signal.SIGTERM, _handle_sigterm)
        signal.signal(signal.SIGINT, _handle_sigterm)
    except Exception as e:
        log.warning(f"[MAIN] Signal handler setup failed: {e}")


def _low_battery_triggered() -> bool:
    if not LOW_BATTERY_PATH.exists():
        return False
    try:
        content = LOW_BATTERY_PATH.read_text(encoding="utf-8").strip().lower()
    except Exception as e:
        log.warning(f"[MAIN] Low battery flag read failed: {e}")
        return False
    if not content:
        return True
    return content in ("1", "true", "yes", "low", "critical")


def _maybe_shutdown_system(reason: str) -> None:
    if not LOW_BATTERY_SHUTDOWN_CMD:
        return
    try:
        args = shlex.split(LOW_BATTERY_SHUTDOWN_CMD)
        subprocess.run(args, check=False)
        log.warning(f"[MAIN] Low-battery shutdown command invoked: {LOW_BATTERY_SHUTDOWN_CMD}")
    except Exception as e:
        log.error(f"[MAIN] Failed to run shutdown command: {e}")

# ---------------------------------------------------------------------------
# Hardware instances (set in main)
# ---------------------------------------------------------------------------

depth_sensor = None
pump = None
rak = None
display = None

# ---------------------------------------------------------------------------
# MAIN CONTROL LOOP
# ---------------------------------------------------------------------------

def main() -> None:
    global rak, depth_sensor, pump, display, _low_battery_seen
    _install_signal_handlers()
    print(f"Starting ControlPod ({config.MODE}) ...")
    _write_marker(HEARTBEAT_PATH, f"{_now_iso()} | boot")

    depth_sensor = depth_hw.build_depth_sensor(config.DEPTH_SENSOR_IMPL)
    pump = pump_control.build_pump_controller(
        config.PUMP_DRIVER,
        config.RELAY_DEV,
        config.ALARM_GPIO_PIN,
        relay_candidates=getattr(config, "RELAY_PORT_CANDIDATES", None),
        alarm_driver=getattr(config, "ALARM_DRIVER", "gpio"),
        alarm_relay_dev=getattr(config, "ALARM_RELAY_DEV", None),
        alarm_relay_channel=int(getattr(config, "ALARM_RELAY_CHANNEL", 0)),
        alarm_candidates=getattr(config, "ALARM_RELAY_PORT_CANDIDATES", None),
    )

    allow_dummy_rak = bool(getattr(config, "ALLOW_DUMMY_RAK", False))
    if config.RADIO_DRIVER != "rak3172":
        if allow_dummy_rak:
            log.warning(
                f"[RADIO] Driver '{config.RADIO_DRIVER}' not implemented; using DummyRAK."
            )
            rak = DummyRAK()
        else:
            log.error(
                f"[RADIO] Driver '{config.RADIO_DRIVER}' not implemented and "
                "ALLOW_DUMMY_RAK is false; exiting."
            )
            _request_shutdown("radio_driver_not_supported")
            return
    else:
        rak = rak_service.connect()
        if rak is None:
            if allow_dummy_rak:
                log.warning("[RADIO] RAK connect failed; using DummyRAK (allowed).")
                rak = DummyRAK()
            else:
                log.error(
                    "[RADIO] RAK connect failed and ALLOW_DUMMY_RAK is false; exiting."
                )
                _request_shutdown("rak_connect_failed")
                return

    display = display_hw.build_display(
        getattr(config, "DISPLAY_DRIVER", "none"),
        tty=getattr(config, "DISPLAY_TTY", "/dev/tty1"),
        timezone_name=getattr(config, "DISPLAY_TIMEZONE", "UTC"),
        font=getattr(config, "DISPLAY_FONT", None),
        fb_path=getattr(config, "DISPLAY_FB", "/dev/fb0"),
        font_path=getattr(config, "DISPLAY_FONT_PATH", None),
        font_size=int(getattr(config, "DISPLAY_FONT_SIZE", 36)),
        foreground=getattr(config, "DISPLAY_FOREGROUND", "#FFFFFF"),
        background=getattr(config, "DISPLAY_BACKGROUND", "#000000"),
        padding=int(getattr(config, "DISPLAY_PADDING", 10)),
        line_spacing=int(getattr(config, "DISPLAY_LINE_SPACING", 4)),
        pixel_order=getattr(config, "DISPLAY_FB_PIXEL_ORDER", "RGB"),
    )

    # ----------------- Depth sensor setup -----------------
    depth_ready = depth_sensor.setup()
    shared_state.depth_sensor = depth_sensor
    shared_state.analog_input_channel = getattr(depth_sensor, "chan", None)
    if not depth_ready:
        log.warning("[DEPTH] Depth sensor not initialized; readings will be zeroed.")

    # ----------------- Pump + alarms state -----------------
    pump_is_on = False
    alarm_hi_on = False
    alarm_lo_on = False

    # ----------------- Heartbeat State---------------------
    # heartbeat_state = False
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
            "START_PUMP_AT": config.PUMP_START_FEET,
            "STOP_PUMP_AT": config.PUMP_STOP_FEET,
            "HI_ALARM": config.HI_ALARM_FEET,
            "LO_ALARM": config.LO_ALARM_FEET,
            "SITE_NAME": config.SITE_NAME,
        }

    # --------- DETERMINISTIC STARTUP PUMP STATE ----------
    log.info("[PUMP] Startup: forcing pump OFF for known safe state.")
    try:
        pump.turn_off()
    except Exception as e:
        log.error(f"[PUMP] Startup: failed to force OFF: {e}")

    pump_is_on = False
    log.info("[PUMP] Startup: pump_is_on set to False (deterministic).")

    # --------- Telemetry timer ----------
    last_send_time = time.time()
    depth_warning_logged = False
    last_display_time = 0.0

    # =====================================================
    # MAIN LOOP
    # =====================================================
    try:
        while True:
            if _stop_requested:
                break
            if _low_battery_triggered():
                if not _low_battery_seen:
                    _low_battery_seen = True
                    log.error("[MAIN] Low battery detected; initiating graceful shutdown.")
                    try:
                        pump.turn_off()
                    except Exception as e:
                        log.error(f"[PUMP] Low-battery shutdown: failed to force OFF: {e}")
                    _request_shutdown("low_battery")
                    _maybe_shutdown_system("low_battery")
                break
            # ----------------------------------------------------------
            # MEASUREMENT
            # ----------------------------------------------------------
            try:
                if hasattr(depth_sensor, "initialized") and not getattr(depth_sensor, "initialized"):
                    if not depth_warning_logged:
                        log.warning("[MAIN] Depth sensor not initialized; using zeros until available.")
                        depth_warning_logged = True
                    raise RuntimeError("Depth sensor not initialized; skipping read.")

                measurement = depth_sensor.read()
                depth = measurement.depth          # feet
                mA = measurement.ma_clamped        # mA
                voltage = measurement.voltage      # volts

                log.info(
                    f"[MEASURE] depth={depth:.2f} ft  mA={mA:.3f}  V={voltage:.3f}"
                )
            except Exception as e:
                depth, mA, voltage = 0.0, 0.0, 0.0

            # -------- APPLY ZERO OFFSET --------
            try:
                zero_offset = current_setpoints.get("ZERO_OFFSET", 0.0)
                depth_raw = depth

                # Apply offset: user-defined shift in feet
                adjusted = depth_raw + zero_offset

                # Clamp so we never send negative depths into the unsigned field
                depth = max(0.0, adjusted)

                log.info(
                    f"[ZERO] Applied zero_offset={zero_offset:.3f} ??? "
                    f"adjusted_depth={depth:.3f} (raw={depth_raw:.3f})"
                )
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
            start_depth = current_setpoints.get("START_PUMP_AT", config.PUMP_START_FEET)
            stop_depth  = current_setpoints.get("STOP_PUMP_AT", config.PUMP_STOP_FEET)
            hi_alarm    = current_setpoints.get("HI_ALARM", config.HI_ALARM_FEET)
            lo_alarm    = current_setpoints.get("LO_ALARM", config.LO_ALARM_FEET)
            site_name   = current_setpoints.get("SITE_NAME", config.SITE_NAME)

            # -----------------------------------------------------------------------
            # PUMP CONTROL (override first)
            # -----------------------------------------------------------------------
            override = is_override_active()

            if override:
                log.info("[OVERRIDE] ACTIVE ??? Pump forced OFF.")
                if pump_is_on:
                    pump.turn_off()
                pump_is_on = False
            else:
                # Normal automatic pump logic
                if pump_is_on and depth <= stop_depth:
                    log.info(
                        f"[PUMP] depth={depth:.2f} <= STOP_PUMP_AT={stop_depth:.2f} ??? OFF"
                    )
                    pump.turn_off()
                    pump_is_on = False
                elif (not pump_is_on) and depth >= start_depth:
                    log.info(
                        f"[PUMP] depth={depth:.2f} >= START_PUMP_AT={start_depth:.2f} ??? ON"
                    )
                    pump.turn_on()
                    pump_is_on = True

            # ----------------------------------------------------------
            # ALARMS
            # ----------------------------------------------------------
            hi_alarm_tripped = depth > hi_alarm
            lo_alarm_tripped = depth < lo_alarm

            if hi_alarm_tripped or lo_alarm_tripped:
                pump.set_alarm_light(True)
            else:
                pump.set_alarm_light(False)

            alarm_hi_on = hi_alarm_tripped
            alarm_lo_on = lo_alarm_tripped

            # ---------- Display update ----------
            display_interval = float(getattr(config, "DISPLAY_UPDATE_SECONDS", 1))
            if display_interval <= 0:
                display_interval = 1
            if time.time() - last_display_time >= display_interval:
                try:
                    display.update(
                        display_hw.DisplayStatus(
                            site_name=site_name,
                            depth_ft=depth,
                            pump_on=pump_is_on,
                            alarm_on=alarm_hi_on or alarm_lo_on,
                            stop_ft=stop_depth,
                            start_ft=start_depth,
                            hi_alarm_ft=hi_alarm,
                            lo_alarm_ft=lo_alarm,
                            override=is_override_active(),
                        )
                    )
                except Exception as e:
                    log.error(f"[DISPLAY] Update failed: {e}")
                last_display_time = time.time()

            # ---------- Telemetry send ----------
            if time.time() - last_send_time >= config.INTERVAL_MINUTES * 60:
                telemetry = {
                    "device": config.DEVICE_NAME,
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
                    if ok:
                        _write_marker(LAST_SEND_PATH, f"{_now_iso()} | ok")
                    else:
                        log.warning("[MAIN] Send failed; attempting RAK reconnect.")
                        rak2 = rak_service.reconnect_rak(rak)
                        if rak2 is not None:
                            rak = rak2
                except Exception as e:
                    log.error(f"[MAIN] Telemetry send error: {e}")

                last_send_time = time.time()

            # ---------- Heartbeat blink ----------
            #heartbeat_state = not heartbeat_state
            #GPIO.output(HEARTBEAT_GPIO_PIN,
            #            GPIO.HIGH if heartbeat_state else GPIO.LOW)

            _write_marker(HEARTBEAT_PATH, f"{_now_iso()} | loop")
            try:
                time.sleep(config.READ_INTERVAL_SECONDS)
            except Exception:
                if _stop_requested:
                    break
                raise
    finally:
        _write_marker(SHUTDOWN_PATH, f"{_now_iso()} | exit:{_shutdown_reason}")
        log.warning(f"[MAIN] Exiting main loop: {_shutdown_reason}")


if __name__ == "__main__":
    main()
