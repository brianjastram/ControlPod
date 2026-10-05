# ControlPod v1.5 and industrial v2 development seed

Intake date: 2026-10-05. Status: planning backlog; implementation and hardware
acceptance remain open. The user's handoff is the design seed, not a claim that
the proposed hardware, deployment, or integration is already validated.

## Direction

| Track | Intended outcome | Starting point |
| --- | --- | --- |
| v1.5 | Harden the existing Pi, USB devices, and software; support a small monitoring-only pilot without waiting for v2. | Current ControlPod hardware abstractions and reliability work. |
| Industrial v2 | Keep the Pi as the edge computer; move critical field I/O toward isolated RS-485/Modbus and evaluate a separate UART LoRaWAN interface. | A deliberate hardware/interface design and bench proof. |
| Shared edge/NDB | Preserve asset identity, measurement meaning, units, original sample time, and quality across either hardware generation. | Backbone's existing neutral observation schema and versioned transport adapters. |

A potential DEM-CON pilot is a use case from the handoff, not a confirmed
booking, installation scope, or permission to operate equipment.

## Source and branch baseline

- [Original handoff](planning/sources/controlpod-v1.5-v2-handoff-2026-10-05.txt),
  retained byte-for-byte from the supplied attachment. SHA-256:
  `e39168e4ddb15d10d30bd93f146a24c1f7eb07deb05608bc3b1a19c1309539dd`.
- Source review: local `feature/RS485_module-screen-accel` at
  `6aaecad178022b236f2f92abf674f588b61a7e52`. The checkout was clean at intake;
  remote-tracking refs were not refreshed.
- `v1.0.0-kclf-phase8b` at `0e155140c5e018d42e0e5b5163295b17d8086c29`
  is a historical comparison anchor. Neither it nor the current branch proves
  what a field Pi currently runs.
- [Eric's separate archive review](../../ControlPodV2/REVIEW.md) and
  [archive provenance](../../ControlPodV2/SOURCE_ARCHIVE.json) remain separate.
  Local review branch `review/local` is at `a444595`; imported baseline is
  `bb4dd5f7a5a4961945e7943973b4acfea8cbe185`. Upstream URL and revision are
  unknown. Its service/radio design is useful reference material, not an
  established ancestor or a drop-in replacement.
- The current `kclf_v2` configuration and Eric's repository name do not mean
  either implements the industrial v2 concept in this handoff. Current
  `kclf_v2` still selects USB-connected sensor, relay, and radio paths.

The only branch created for this intake is `docs/v1.5-v2-development-seed`.
The branch names below are proposed work packages. This intake changes docs
only; it does not change runtime code, dependencies, hardware, or deployment.

## Risks and gates before control development

These findings concern inspected source. USB contention, electrical supply
problems, and garbled serial traffic remain hypotheses for the Kandiyohi
incident until the actual image, installed units, kernel, wiring, and logs
are examined.

| Risk | Source evidence / uncertainty | Required gate |
| --- | --- | --- |
| OFF can come too late | `src/main.py:184-211` can exit on radio failure before the startup OFF at `293-301`; USB sync/load also precede OFF. STOP persists/audits before the loop actuates. | Attempt the agreed safe output before optional I/O and persistence; prove sequencing with faults. |
| Invalid depth can become control input | `src/main.py:332-359` substitutes zero on read failure and then adds the offset. A positive offset could cross a start threshold. | Carry validity and age explicitly; invalid/stale data cannot authorize automatic ON. |
| Command intention can look confirmed | `src/hardware/pump_control.py:72-89` suppresses write failures; main updates its Boolean state after the attempt. Readback failure also returns false. | Separate requested output, relay readback, and physical pump feedback; preserve UNKNOWN on missing evidence. |
| Port enumeration can select another device | `src/config/kclf_v2.py:48-77` has useful by-id paths, but sensor/radio fallback lists overlap. Sensor setup can write before validating a response. | Verify identity and unique ownership before sending configuration/control bytes. |
| Restart is insufficient for every failure | Watchdog/restart exists, but a stuck USB/kernel path, latched relay, or Pi power loss may defeat software cleanup. | Independently verify de-energized wiring, interlocks, module defaults, and recovery behavior on a safe bench. |
| History and delivery are uncertain | Main samples for transmission without a durable outbox; radio success is weaker than confirmed NDB ingestion. | Agree loss window, storage budget, timestamp/clock policy, replay, and delivery acknowledgement semantics. |

Before an actuating bench or field test, identify the exact target hardware and
configuration, record rollback/recovery steps, and independently establish a
safe maintenance state. Do not use non-target equipment or unique field SD/USB
evidence for destructive recovery experiments.

Define the site's response to sensor loss, relay loss, network loss, service
restart, and power loss. Network loss does not automatically imply the same
policy as invalid sensor data: local automatic operation may remain appropriate
under an agreed site policy. A delayed LoRaWAN downlink cannot replace a local
emergency stop or independent safety interlock.

## Existing foundations to retain

- Hardware factories and an active RS-485 depth implementation already exist
  in `src/hardware/depth_sensor.py`, including CRC/header checks. The separate
  `src/hardware/waveshare_ai485.py` is a placeholder, not the active driver.
- By-id device paths, serial read/write timeouts, and radio join/recovery logic
  are already present. Extend their coverage instead of treating them as new.
- `controlpod.service` uses `Type=notify`, `WatchdogSec=90`, restart supervision,
  and a startup timeout. Main emits watchdog pings and runtime markers. These
  are source features, not verified guarantees about the installed field unit.
- The `ALLOW_DUMMY_RAK` bench fallback is explicit and defaults off.
- Keep display/tap features outside safety-critical deadlines.
- The active RAK uplink is a packed 14-byte payload despite README/main header
  wording about JSON. Document actual codec behavior in the transport work.

## v1.5 backlog

All checkboxes are future work. P0 gates apply before enabling actuation.

### P0: control and measurement safety

- [ ] **V15-01 — `fix/v15-safe-control-ordering`**: move the initial safe-output
  attempt ahead of radio, sensor configuration, display, and removable storage;
  make STOP actuation precede audit/export; cover controlled exit and exception
  paths. Audit import-time GPIO effects in `src/control.py` as well as main.
  Acceptance: fake blocked USB/radio, radio-init failure, exceptions, and
  SIGTERM show correct order and truthful failure state. Missing hardware stays
  UNKNOWN/faulted. SIGKILL and whole-Pi faults require the hardware gate above.
- [ ] **V15-02 — `fix/v15-measurement-quality`**: add acquisition time, validity,
  age, and error/quality to measurements. Keep invalid readings out of control
  decisions and calibration; add bounded sensor rediscovery. Acceptance: CRC
  error, timeout, initial absence, reconnect, stale sample, NaN/Inf, and sensor
  under/over-range remain visible faults, including with a positive offset.
  Invalid samples never cause automatic ON or a successful ZERO result.
  Verify the ZERO calibration sign against the additive offset in main: a valid
  reference must yield approximately zero adjusted depth on the next sample
  and after restart. Specify manual offset behavior separately.
- [ ] **V15-03 — `fix/v15-local-settings-authority`**: runtime uses validated
  local last-known-good settings. Use atomic replacement and schema/range/
  cross-field checks; return persistence errors honestly. USB becomes explicit
  import/export in a separate worker with mount/identity checks. Acceptance:
  absent, read-only, corrupt, stalled, or interrupted USB cannot stall safety
  decisions or replace valid settings with partial data/defaults silently.
  Reject invalid thresholds, non-finite values, and incomplete imports.
- [ ] **V15-04 — `fix/v15-serial-identity`**: make device roles explicit through
  by-id or verified udev mappings. Remove uncontrolled production enumeration
  fallbacks; reject ambiguous or conflicting roles. Validate the expected
  protocol before declaring readiness; avoid speculative startup writes.
  Acceptance: reordered enumeration, duplicate/missing adapters, and a wrong
  device on an available port produce no misdirected configuration/control.
- [ ] **V15-05 — `feat/v15-relay-results-and-channels`**: return bounded command
  outcomes and ON/OFF/UNKNOWN readback. Add explicit pump/alarm channel mapping
  and capability checks for a candidate four-channel Numato board. Current pump
  commands hardcode channel 0. One owner handles all channels on one physical
  board; validate channel collisions. Acceptance: missing port, timeout,
  malformed readback, and write failure cannot become confirmed OFF/ON.
  Relay state is labeled separately from motor/current/flow feedback.

### P1: fault isolation, radio, and monitoring

- [ ] **V15-06 — `refactor/v15-device-workers`**: define measurement/output/
  health interfaces, then isolate serial work behind one owner per physical
  device. Add bounded IPC, backoff, explicit close, freshness checks, and
  supervision. Start incrementally with the radio and optional USB worker;
  retain local safety authority. Acceptance: a hung/restarting radio, exporter,
  or display cannot freeze sampling or local control. Worker restarts create
  neither duplicate port owners nor stale command replay. Set deadlines against
  startup/watchdog budgets; do not remove existing supervision prematurely.
- [ ] **V15-07 — `fix/v15-radio-events-and-delivery`**: distinguish serial-open,
  joined, AT-accepted, RF-transmitted, and backend-received states. Replace
  silence-as-success handling (`OK_NO_RESP`); preserve asynchronous downlinks
  while sending AT commands. Acceptance: recorded serial streams exercise
  bursts, duplicate events, late replies, lost join, repeated TX failure, and
  reconnect. Diagnostics report the evidence level actually established.
- [ ] **V15-08 — `feat/v15-monitoring-profile`**: make an explicit read-only
  profile for a possible pilot. Remove actuator capability from its startup,
  imports, and downlink path; disable unneeded Modbus configuration writes.
  Acceptance: fake hardware records no relay opens/writes, GPIO output setup,
  or control-capable handlers. Invalid identity/profile fails closed. Sensor
  faults and network outages remain observable and samples continue buffering.
  Pilot scope, asset, signal, cadence, retention, and dashboard are agreed
  separately. Shared telemetry/outbox gates below still apply.
- [ ] **V15-09 — `test/v15-usb-recovery-acceptance`**: inventory the actual hub,
  supply, devices, cable lengths/quality, and mount/kernel/service settings.
  Measure power/undervoltage and enumeration/reconnect behavior rather than
  assuming software causes the failure. Acceptance on an isolated bench:
  simultaneous USB load, unplug/replug, stalled storage, radio loss, and power
  interruption preserve the agreed output policy and telemetry history.
  Define sampling latency, recovery deadlines, loss window, and soak duration
  first; save measured results and rollback instructions for the selected image.

## Shared edge/NDB work

Authority is the sibling Backbone implementation, reviewed at local HEAD
`aa3aca9b52fad3b69aed5fada7ed9c99b24bc9c2`. Backbone had unrelated local edits;
this intake does not modify them. Edge work belongs here; backend schema,
ingest, seeds, and dashboard changes belong in Backbone. Shared product
standards belong in the Hydrometrix hub.

Useful current contracts:

- [Domain](../../Backbone/docs/domain.md): series/site metadata owns parameter,
  unit, and source mapping; observations use `ts`, `value`, `quality`, `source`,
  and `ingest_ts`. API observations default quality to `raw`; quality is a
  string, not an established universal enum.
- [API schemas](../../Backbone/backend/app/api/schemas.py): use existing
  code/UUID ingest shapes and device/site mappings. Never infer asset identity
  solely from a display name or a cloned site number.
- [Ingest router](../../Backbone/backend/app/api/routers/ingest.py):
  `POST /api/v1/ingest/telemetry` supports several existing formats. Choose one
  documented adapter path and prove its mapping; do not invent a competing
  neutral schema or silently adopt Mayfly wire-format assumptions.
- [Observation upsert](../../Backbone/backend/app/services/ingest.py):
  `(series_id, ts)` conflict updates the existing row. This avoids duplicate
  keyed rows but permits replacement; it is not immutable/exactly-once history.
- [ChirpStack connector](../../Backbone/backend/app/services/chirpstack_mqtt_connector.py)
  decodes legacy binary values and uses uplink receive time. Preserving original
  sample times or decoding Eric's CBOR arrays requires explicit compatibility
  work. Integration is not established merely by sending a packet.
- Existing command acknowledgements distinguish backend acceptance, device
  execution, and confirmed state. Current request types are audio cue and GPS
  refresh only; the API does **not** already expose pump ON/OFF.

- [ ] **SH-01 — `feat/ndb-observation-adapter`**: record an explicit mapping
  from ControlPod device/site/asset to existing series, parameter, and unit;
  carry acquisition time in aware UTC and agreed quality/freshness. Preserve
  raw diagnostics where useful. Define missing-value and unsynchronized-clock
  behavior without presenting invalid zero as a valid measurement. Acceptance:
  versioned fixtures from either ControlPod track yield the same neutral series
  meaning as the established Mayfly/NDB conventions, and a Grafana query can
  consume them without depending on the board or radio model. Verify in an
  isolated test site, including tenant/device mapping and legacy codec fixtures.
- [ ] **SH-02 — `feat/edge-telemetry-outbox`**: persist timestamped samples in a
  bounded local store, separate from telemetry delivery and command queues.
  Choose storage/quota/wear policy, capture durable enqueue before sending,
  retain original sample identity/time across restart, and define when a sample
  is considered delivered for each transport. LoRaWAN radio/MAC acknowledgement
  is not proof of NDB ingest; an end-to-end receipt protocol or explicit weaker
  guarantee is needed. Acceptance: outage/replay, crash during enqueue/ack,
  disk-full, retention overflow, duplicates, and backlog prioritization are
  tested. Replay creates no extra keyed observations and never replays control
  commands. Define timestamp resolution to avoid same-series sample collisions.
- [ ] **SH-03 — `feat/control-command-contract`**: separately design a pump
  command extension with Backbone, preserving existing audio/GPS behavior.
  Specify command ID, device/output, authorized operations, deadline/expiry,
  validation, duplicate ledger, rejection/failure reasons, acknowledgements,
  and requested/received/validated/executed/confirmed stages. Keep telemetry
  read access separate from command authority. Current START means resume
  automatic operation; do not silently redefine it as force ON. Acceptance:
  stale, wrong-target, malformed, unauthorized, duplicate, and post-reboot
  commands do not actuate; physical confirmation stays unknown without feedback.
  This work is not required to launch a read-only pilot.

## Industrial v2 backlog

The Pi remains. The isolated RS-485 interface, modules, and UART radio are
candidate design choices; exact parts and electrical compatibility are open.

- [ ] **V2-01 — `design/v2-io-and-pin-budget`**: inventory installed/candidate
  hardware and produce a reviewed wiring/power/interface plan. Resolve whether
  the RS-485 interface uses UART, SPI, or another interface so it does not
  compete with the radio. Check GPIO ownership, console UART, voltage levels,
  power budget, isolation boundary, grounding, termination/bias, protection,
  enclosure/connectors, relay ratings, and safe power-up defaults against
  selected vendor documents. Acceptance: a named parts list, pin map, power
  budget, and safe-output/interlock design before connecting critical I/O.
- [ ] **V2-02 — `feat/v2-modbus-io`**: reuse reviewed Modbus framing where
  appropriate; add a single bus owner/scheduler with explicit address/register/
  scaling maps for sensors and relay/I/O modules. Use bounded deadlines,
  invalid/stale status, output readback, and device-loss policy. Acceptance:
  recorded protocol fixtures cover CRC/header/exception/timeout/address errors;
  safe-bench tests cover contention, module loss, restart, and de-energized
  outputs. No generic register scan or unreviewed configuration writes.
- [ ] **V2-03 — `feat/v2-uart-radio`**: define a transport-neutral radio contract
  and adapt the selected LA66 or RAK device to the verified direct interface.
  Eric's factory/drivers are reference material; USB implementations do not
  prove UART pin, voltage, firmware, or provisioning compatibility. Acceptance:
  verify credential retention, startup/join behavior, uplink/downlink parsing,
  reconnect, and power cycles on an isolated authorized bench. Use SH-01/02;
  retain an explicit versioned payload/decoder migration for any CBOR change.
- [ ] **V2-04 — `test/v2-acceptance-matrix`**: record reproducible end-to-end
  acceptance with both monitoring and control profiles. Cover simultaneous
  sensor/radio/relay faults, stale worker state, power loss, offline replay,
  storage exhaustion, watchdog restart, and physical output feedback. Choose
  site-specific response deadlines and soak duration before running the test;
  archive measured results and rollback steps. No production-readiness claim
  without evidence from the selected hardware and deployment profile.

## Branch and execution strategy

1. Retain `master`, `dev`, `Improvements`, the current feature branch, and
   historical tags. This seed does not merge or overwrite them.
2. When implementation starts, create proposed `dev/v1.5` from the reviewed
   seed/base lineage; use the small `fix/v15-*` and `feat/v15-*` packages above.
   Review the substantial existing feature-to-master differences before any
   production merge. A branch name is not a release designation.
3. Start with V15-01/02/03/04/05. Build SH-01/02 and V15-08 for a read-only
   pilot; add the worker/radio hardening needed by the chosen delivery path
   and verify it through V15-09.
   Use software fakes first, then an isolated bench, then a scoped field pilot.
4. Research V2-01 in parallel. Create proposed `dev/v2-industrial` only when
   implementation begins; share reviewed measurement/outbox/control contracts
   through normal merges or selected commits. Avoid copying all v1.5 hardware
   assumptions into v2 or mixing Eric's archive history into this repository.
5. Maintain separate software checks, electrical/bench evidence, and field
   acceptance. Define rates, deadlines, loss windows, and rollback with the
   actual site. Push, merge, install, provisioning, and deployment are separate
   actions from this planning intake.

First implementation seed: **safe control ordering plus explicit invalid/
unknown state**. First product seed: **a verifiably read-only monitoring
profile with neutral telemetry and bounded offline history**. Neither requires
waiting for an industrial v2 hardware redesign.
