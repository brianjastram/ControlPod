"""
Depth sensor implementations (ADS1115 and RS485 Waveshare AI485).
"""

import logging
import struct
import time
from typing import Optional

import serial

from src import config
from src.config import RESISTOR_OHMS, MAX_DEPTH_FT, DEPTH_SCALING_FACTOR
from src.model.depth_telemetry import DepthTelemetry

log = logging.getLogger(__name__)


class DepthSensor:
    def setup(self) -> bool:
        raise NotImplementedError

    def read(self) -> DepthTelemetry:
        raise NotImplementedError


class Ads1115DepthSensor(DepthSensor):
    def __init__(self, channel_index: int = 0):
        self.channel_index = channel_index
        self.chan = None

    def setup(self) -> bool:
        try:
            import busio
            import board
            import adafruit_ads1x15.ads1115 as ADS
            from adafruit_ads1x15.analog_in import AnalogIn

            i2c = busio.I2C(board.SCL, board.SDA)
            ads = ADS.ADS1115(i2c)
            self.chan = AnalogIn(ads, self.channel_index)
            log.info("ADS1115 detected on I2C bus.")
            return True
        except Exception as e:
            self.chan = None
            log.error(f"[SIM] No ADS1115 detected ({e}); using simulated depth readings.")
            return False

    def read(self) -> DepthTelemetry:
        if self.chan is None:
            raise RuntimeError("ADS1115 channel not initialized; cannot read depth.")

        try:
            voltage = float(self.chan.voltage)
        except Exception as e:
            log.error(f"[DEPTH] Failed to read ADC: {e}")
            raise

        mA = (voltage / RESISTOR_OHMS) * 1000.0
        return _convert_ma_to_depth(mA, voltage)


def _modbus_crc(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def _build_read_input_regs(slave_addr: int, start: int, count: int) -> bytes:
    payload = struct.pack(">B B H H", slave_addr, 0x04, start, count)
    crc = _modbus_crc(payload)
    return payload + struct.pack("<H", crc)


def _build_write_single_reg(slave_addr: int, reg: int, value: int) -> bytes:
    payload = struct.pack(">B B H H", slave_addr, 0x06, reg, value)
    crc = _modbus_crc(payload)
    return payload + struct.pack("<H", crc)


class Rs485DepthSensor(DepthSensor):
    """
    Waveshare AI485 via Modbus RTU (USB-to-RS485 adapter).
    """

    def __init__(self):
        self.port = getattr(config, "AI485_PORT", "/dev/ttyUSB1")
        self.port_candidates = getattr(
            config, "AI485_PORT_CANDIDATES", ["/dev/ttyUSB1", "/dev/ttyUSB0"]
        )
        self.baud = getattr(config, "AI485_BAUD", 9600)
        self.device_id = getattr(config, "AI485_DEVICE_ID", 1)
        self.channel = getattr(config, "AI485_CHANNEL", 0)
        self.raw_max = getattr(config, "AI485_RAW_MAX", 20000)
        self.max_ma = getattr(config, "AI485_MAX_MA", 20.0)
        self.min_ma = getattr(config, "AI485_MIN_MA", 4.0)
        self.data_type = getattr(config, "AI485_DATA_TYPE", 0x0003)
        self.set_mode_on_boot = getattr(config, "AI485_SET_MODE_ON_BOOT", False)
        self.initialized = False

    def setup(self) -> bool:
        ports_to_try = [p for p in [self.port, *self.port_candidates] if p]
        last_error = None

        for candidate in ports_to_try:
            try:
                with serial.Serial(candidate, self.baud, timeout=1) as ser:
                    ser.reset_input_buffer()
                    if self.set_mode_on_boot:
                        reg_addr = 0x1000 + self.channel  # 0x1000-0x1007 map to CH1-CH8
                        frame = _build_write_single_reg(self.device_id, reg_addr, self.data_type)
                        ser.write(frame)
                        ser.flush()
                        time.sleep(0.05)
                self.port = candidate
                self.initialized = True
                log.info(f"[DEPTH] RS485 ready on {self.port} (device {self.device_id})")
                return True
            except Exception as e:
                last_error = e
                continue

        self.initialized = False
        if last_error:
            log.error(f"[DEPTH] RS485 init failed on {ports_to_try}: {last_error}")
        else:
            log.error("[DEPTH] RS485 init failed: no candidate ports provided.")
        return False

    def _read_raw_channel(self) -> int:
        frame = _build_read_input_regs(self.device_id, self.channel, 1)
        with serial.Serial(self.port, self.baud, timeout=1) as ser:
            ser.write(frame)
            ser.flush()
            time.sleep(0.05)
            expected_len = 5 + 2  # addr + func + bytecount + data(2) + crc(2)
            resp = ser.read(expected_len)

        if len(resp) < expected_len:
            raise RuntimeError(f"Modbus response too short ({len(resp)} bytes)")

        data_no_crc = resp[:-2]
        resp_crc = struct.unpack("<H", resp[-2:])[0]
        calc_crc = _modbus_crc(data_no_crc)
        if resp_crc != calc_crc:
            raise RuntimeError(f"CRC mismatch (resp={resp_crc:04X} calc={calc_crc:04X})")

        addr, func, byte_count = resp[0], resp[1], resp[2]
        if addr != self.device_id or func != 0x04 or byte_count != 2:
            raise RuntimeError(f"Unexpected Modbus header addr={addr} func={func} bc={byte_count}")

        raw_val = struct.unpack(">H", resp[3:5])[0]
        return raw_val

    def read(self) -> DepthTelemetry:
        if not self.initialized:
            raise RuntimeError("RS485 depth sensor not initialized; call setup() first.")

        raw = self._read_raw_channel()
        raw = max(0, min(raw, self.raw_max))

        ma = (raw / self.raw_max) * self.max_ma
        return _convert_ma_to_depth(ma, voltage=None, min_ma=self.min_ma)


def _convert_ma_to_depth(ma: float, voltage: Optional[float], min_ma: float = 4.0) -> DepthTelemetry:
    mA_clamped = max(0.0, min(ma, 25.0))

    if mA_clamped <= min_ma:
        depth = 0.0
    elif mA_clamped >= 20.0:
        depth = MAX_DEPTH_FT
    else:
        depth = ((mA_clamped - min_ma) / (20.0 - min_ma)) * MAX_DEPTH_FT

    depth *= DEPTH_SCALING_FACTOR

    log.debug(
        f"[DEPTH] I={mA_clamped:.3f} mA, depth={depth:.2f} ft"
        + (f", V={voltage:.4f} V" if voltage is not None else "")
    )

    return DepthTelemetry(depth, mA_clamped, voltage if voltage is not None else 0.0)


def build_depth_sensor(impl: str) -> DepthSensor:
    if impl == "ads1115":
        return Ads1115DepthSensor()
    if impl == "rs485":
        return Rs485DepthSensor()
    raise ValueError(f"Unknown depth sensor impl: {impl}")
