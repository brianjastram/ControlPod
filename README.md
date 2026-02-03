# Kandiyohi Co. Land Fill Control Pod

Control Pod main control program for KCLF, Phase 8B.

### Authored by:
Brian Jastram, **Hydrometrix** for Eric Xanderson, **Kandiyohi Co. Land Fill**

### Features:

- Uses ADS1115 on channel `0` for depth (`telemetry.read_depth(analog_input_channel)`)
- Uses Numato USB relay on `/dev/ttyACM0` for pump control
- Uses `/dev/rak` for the RAK3172 LoRaWAN radio (via `rak3172_comm.RAK3172Communicator`)
- Syncs setpoints from the USB key on startup
- Applies downlink commands (override, zero, setpoints)
- Sends JSON telemetry payloads to ChirpStack at `INTERVAL_MINUTES`

### Reliability / crash diagnostics

The app writes runtime markers to `/run` (tmpfs) for post-mortem debugging:

- `/run/controlpod.heartbeat` updated every loop
- `/run/controlpod.last_send` updated on successful uplink
- `/run/controlpod.shutdown` updated on clean shutdown or SIGTERM/SIGINT

Optional systemd health check (timer-based restart if heartbeat is stale):

```bash
sudo cp /home/pi/ControlPod/systemd/controlpod-healthcheck.service /etc/systemd/system/
sudo cp /home/pi/ControlPod/systemd/controlpod-healthcheck.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now controlpod-healthcheck.timer
```

Adjust the timeout with `MAX_AGE_SECONDS` in
`/home/pi/ControlPod/systemd/controlpod-healthcheck.service`.

### Low-battery graceful shutdown

If `/run/controlpod.low_battery` exists (or contains `1/true/yes/low/critical`),
the app will:

1) Force the pump OFF
2) Write shutdown markers
3) Exit the main loop gracefully

Optional: configure a shutdown command in `src/config/kclf_v1.py`:

```
LOW_BATTERY_SHUTDOWN_CMD = "sudo /sbin/shutdown -h now"
```

### Journald persistence and disk limits

Persistent journald uses disk space under `/var/log/journal` (not RAM).
To cap usage, set limits in `/etc/systemd/journald.conf`:

```
Storage=persistent
SystemMaxUse=100M
SystemMaxFileSize=10M
RuntimeMaxUse=20M
MaxRetentionSec=2week
```

Check current usage:

```bash
journalctl --disk-usage
```

### DummyRAK gating (bench testing)

By default, the service exits if the RAK radio cannot be opened. To allow
fallback to `DummyRAK` during bench testing, set an environment variable:

```
ALLOW_DUMMY_RAK=1
```

### Tap-to-wake display (LIS3DH/LIS3DHTR)

ControlPod can use a LIS3DH/LIS3DHTR accelerometer on I2C to wake the HDMI display
on double-tap and blank it after a timeout. Configure in `src/config/kclf_v1.py`
or `src/config/kclf_v2.py`:

```
TAP_WAKE_ENABLED = True
TAP_WAKE_I2C_BUS = 1
TAP_WAKE_I2C_ADDR = 0x19
TAP_WAKE_ON_SECONDS = 300
TAP_WAKE_START_OFF = True
TAP_WAKE_MODE = "blank"  # "blank" keeps HDMI on for fast wake; "power" saves power
TAP_WAKE_FORCE_POWER_ON = True
TAP_WAKE_TOGGLE = True
TAP_WAKE_SINGLE_WAKE = True
```

Install the SMBus bindings on Pi OS:

```bash
sudo apt-get install -y python3-smbus
```

If ControlPod runs inside a Python venv and cannot import `smbus`, install
`smbus2` into the venv:

```bash
/home/pi/ControlPod/env/bin/pip install smbus2
```
