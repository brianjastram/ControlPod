# Kandiyohi Co. Land Fill Control Pod

Control Pod main control program for KCLF, Phase 8B.

### Authored by:
Brian Jastram, **Hydrometrix** for Eric Xanderson, **Kandiyohi Co. Land Fill**

### Features:

- Uses ADS1115 on channel `0` for depth (telemetry.read_depth(chan))
- Uses Numato USB relay on `/dev/ttyACM0` for pump control
- Uses `/dev/rak` for the RAK3172 LoRaWAN radio (via `rak3172_comm.RAK3172Communicator`)
- Syncs setpoints from the USB key on startup
- Applies downlink commands (override, zero, setpoints)
- Sends JSON telemetry payloads to ChirpStack at `INTERVAL_MINUTES`