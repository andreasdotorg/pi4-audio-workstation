# PipeWire RT Promotion Model

## Topic: JACK client RT promotion — correct vs wrong approach (2026-03-27)

**Context:** F-033 investigation (JACK thread RT promotion for Mixxx/Reaper).
Worker-3 discovered the correct pattern through trial and error.

**Learning:** PipeWire's RT model promotes individual callback threads inside
client processes. The client process itself should NOT be globally RT.

**Wrong approach:** Setting `CPUSchedulingPolicy=fifo` on a JACK client service
(Mixxx, Reaper) or wrapping with `chrt -f 70 pw-jack mixxx`. This makes ALL
application threads FIFO (GUI, database, library scanner) — causes harmful
priority inversion.

**Correct approach:** Add these to the client's systemd service unit:
```ini
LimitRTPRIO=88
LimitMEMLOCK=infinity
```
This gives PipeWire *permission* to promote only the data/bridge thread to
FIFO via its RT module. The application's own threads remain SCHED_OTHER.

**Important distinction:**
- **PipeWire daemon** (`pipewire.service`): `CPUSchedulingPolicy=fifo` is
  correct because ALL PW daemon threads should be RT. This is the F-020
  workaround pattern.
- **JACK clients** (Mixxx, Reaper, signal-gen): Only resource limits
  (`LimitRTPRIO`, `LimitMEMLOCK`) are needed. PW promotes the specific
  callback threads itself.

**Model service:** `pi4audio-signal-gen.service` (lines 23-36) documents this
pattern correctly.

**Source:** worker-3, F-033 investigation.
**Tags:** pipewire, rt, fifo, jack, mixxx, reaper, signal-gen, systemd,
LimitRTPRIO, LimitMEMLOCK, priority-inversion, f-033, f-020
