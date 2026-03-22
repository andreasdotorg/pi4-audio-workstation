# RT Services Architecture

**Status:** Approved (Architect + AE unified design, AD challenged, owner Q6
overrule). Design questions Q1-Q8 CLOSED.
**Date:** 2026-03-22
**Decisions:** F-064 root cause analysis, Q1-Q8 design discussion
**Relates to:** [rt-audio-stack.md](rt-audio-stack.md) (PW config),
[rt-signal-generator.md](rt-signal-generator.md) (signal-gen design),
[measurement-daemon.md](measurement-daemon.md) (measurement workflow),
[web-ui.md](web-ui.md) (web architecture),
[safety.md](../operations/safety.md) (operational safety)

---

## 1. Overview

The Pi 4B audio workstation uses four RT Rust services for real-time audio
data acquisition and generation. These services share a `audio-common` Cargo
workspace crate and communicate with the web UI and GraphManager via TCP/WebSocket.

The Python web UI (FastAPI) is the **control plane** — it orchestrates
measurement workflows, serves the dashboard, and provides the user interface.
The Rust services are the **data plane** — they handle real-time audio I/O
with deterministic latency guarantees that Python cannot provide.

### Architecture Diagram

```
Browser (laptop/tablet)
    |
    | HTTPS + WSS
    |
    v
Caddy reverse proxy (:8080)           <-- TLS termination, WS upgrade, auth
    |         |         |         |
    |         |         |         |
    v         v         v         v
 Web-UI   level-     pcm-      signal-    audio-
 (Python) bridge     bridge    gen        recorder
 :8000    :9100      :9200+    :4001      TBD
    |
    | localhost TCP
    |
    v
GraphManager (:4002)                   <-- link topology, mode transitions,
    |                                      tap lifecycle management
    v
PipeWire audio graph (SCHED_FIFO 88)
```

**Why this architecture exists (F-064 root cause):** The original design had
the Python web UI relay all audio data — PCM levels, spectrum, and DSP health
— through asyncio coroutines. Under real load (11 WebSocket connections +
collector loops), the single-threaded asyncio event loop saturated, causing
the web UI to become intermittently unreachable. F-063 (thread pool) and F-064
(collector timeouts) were partial fixes. The real fix is eliminating the Python
relay: browsers connect directly to Rust RT services via WebSocket, with Caddy
handling TLS termination and path routing.

---

## 2. Service Catalog

| Service | Binary | Port | Lifecycle | Tier | Purpose |
|---------|--------|------|-----------|------|---------|
| level-bridge | `pi4audio-level-bridge` | :9100 | systemd (always-on) | Data-plane | Pre/post convolver levels, WS JSON 10Hz |
| pcm-bridge | `pi4audio-pcm-bridge` | :9200+ | GM-managed (on-demand) | Data-plane | Spectrum taps, WS binary PCM |
| signal-gen | `pi4audio-signal-gen` | :4001 | GM-managed (on-demand) | Safety-critical | Measurement audio generation |
| audio-recorder | `pi4audio-audio-recorder` | TBD | GM-managed (on-demand) | Data-plane | Capture/recording for measurement + diagnostics |

### level-bridge

Always-on systemd user service. Maintains two PipeWire streams (convolver
input and output) and publishes pre/post-convolver level data as JSON over
WebSocket at 10 Hz. Replaces the Python `LevelsCollector` that polled
pcm-bridge over TCP.

- **PW streams:** 2 (convolver capture side + convolver playback side)
- **Protocol:** WebSocket JSON, 10 Hz update rate
- **Node property:** `node.passive = true` (never drives the graph)
- **Shared code:** `audio-common::LevelTracker`

### pcm-bridge

On-demand spectrum taps managed by GraphManager. Each instance attaches to a
specific point in the PipeWire graph and streams raw PCM data over WebSocket.
GM allocates ports starting at :9200 and monitors health.

- **Protocol:** WebSocket binary PCM (all channels interleaved)
- **Channel selection:** Browser JS selects which channels to display
- **Lifecycle:** GM creates/destroys instances via `start_tap`/`stop_tap` RPC
- **Node property:** `node.passive = true`
- **Shared code:** `audio-common::RingBuffer`, `audio-common::spa_format`

### signal-gen

RT-safe measurement audio generator. Hard-capped at -20 dBFS (immutable
`--max-level-dbfs` CLI argument, SEC-D037-04). Controlled via TCP JSON-RPC.
Python proxy stays in the loop for D-009 safety enforcement — the web UI
validates gain parameters before forwarding to signal-gen.

- **Protocol:** TCP JSON-RPC (newline-delimited)
- **Safety:** Hard output level cap, independent of any software configuration
- **Design doc:** [rt-signal-generator.md](rt-signal-generator.md)

### audio-recorder

Capture and recording service for measurement and diagnostics. Records raw
audio from specified PipeWire graph points. Deconvolution (performed
post-capture in Python) inherently finds time offsets, so sample-accurate
synchronization with signal-gen is not required.

- **Protocol:** TBD (likely TCP JSON-RPC matching signal-gen pattern)
- **Lifecycle:** GM-managed, on-demand
- **Shared code:** `audio-common` workspace crate
- **Origin:** Q6 owner overrule — separated from signal-gen because
  independent use cases exist (record without signal-gen, generate without
  recording) and process separation is cleaner

---

## 3. Security Tiers

**Hard constraint (Q8):** Safety-critical and data-plane services must NEVER
share a binary. This is a security boundary, not a performance optimization.

| Tier | Services | Rationale |
|------|----------|-----------|
| **Safety-critical** | GraphManager (watchdog), signal-gen (D-009 hard cap) | A bug or crash in data-plane code must not affect safety mechanisms. GM's watchdog mutes the system within 21ms on anomaly. Signal-gen's -20 dBFS cap protects speakers from measurement damage. |
| **Data-plane** | level-bridge, pcm-bridge, audio-recorder | Read-only taps and recording. A crash here loses monitoring data but cannot damage hardware. Same-tier merges permitted if warranted but not needed today. |

**Cross-tier consolidation is PROHIBITED.** If a future developer proposes
merging signal-gen into pcm-bridge "for efficiency," the answer is no. The
tier boundary is absolute.

---

## 4. Shared Infrastructure

### `audio-common` Cargo Workspace Crate

All four RT services share a workspace crate providing:

| Component | Purpose | Used by |
|-----------|---------|---------|
| `LevelTracker` | Lock-free atomic peak/RMS tracking | level-bridge, pcm-bridge |
| `RingBuffer` | Lock-free SPSC ring buffer for audio data | pcm-bridge, audio-recorder |
| `spa_format` | SPA format negotiation helpers | all services |

### WebSocket Library

`tungstenite` (synchronous WebSocket) for pcm-bridge and level-bridge. No
async runtime, no tokio. Rationale: RT audio services must not contend with
an async executor for CPU time. Each service runs a simple `loop { read_pw();
send_ws(); }` cycle synchronized to PipeWire graph wakeups.

### PipeWire Tap Properties

All taps use `node.passive = true` — they attach to the graph as passive
observers and never become graph drivers. This ensures:
- Taps cannot affect the audio processing deadline
- Removing a tap does not disrupt the audio pipeline
- Multiple taps can coexist without scheduling interference

---

## 5. Design Decisions (Q1-Q8)

| Question | Decision | Rationale |
|----------|----------|-----------|
| **Q1:** Single pcm-bridge or multi-instance? | Multi-instance (one per tap point) | Topology-unaware — each instance is a simple PW stream. GM manages which tap points exist. |
| **Q2:** Per-channel spectrum selection? | Browser JS selects channels | pcm-bridge sends all channels interleaved. Channel filtering in JS avoids RT service complexity. |
| **Q3:** Multiplexed or separate WS endpoints? | Separate WS per service | Simpler implementation, independent lifecycle, easier debugging. No multiplexing overhead. |
| **Q4:** Reverse proxy choice? | Caddy | Auto TLS (ACME/self-signed), simple WebSocket config, solves F-037 auth gap. Lighter than nginx for this use case. |
| **Q5:** Tap lifecycle management? | GM manages on-demand taps | `start_tap`/`stop_tap`/`list_taps` RPC. GM allocates ports, monitors health, kills on disconnect. |
| **Q6:** Separate audio-recorder? | **Yes (owner overrule)** | Independent use cases (record without signal-gen, generate without recording). Process separation preferred. Deconvolution handles timing. |
| **Q7:** Who owns measurement orchestration? | Web-UI Python | No RT-critical steps outside signal-gen. Python orchestrates the workflow (session management, file I/O, analysis). |
| **Q8:** Consolidate binaries? | **No — hard security constraint** | Safety-critical tier (GM, signal-gen) must never share binary with data-plane tier. See Section 3. |

---

## 6. Lifecycle Management

### Always-On Services (systemd)

**level-bridge** runs as a systemd user service, started at boot:

```ini
[Unit]
Description=pi4audio Level Bridge (pre/post convolver levels)
After=pipewire.service

[Service]
ExecStart=/usr/local/bin/pi4audio-level-bridge --listen 127.0.0.1:9100
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
```

### On-Demand Services (GM-managed)

**pcm-bridge**, **signal-gen**, and **audio-recorder** are started and stopped
by GraphManager based on operational need:

- **Measurement session:** GM starts signal-gen + audio-recorder, tears down
  when session ends
- **Spectrum viewing:** GM starts pcm-bridge tap at requested graph point,
  tears down when browser disconnects
- **Port allocation:** GM assigns ports from :9200+ for pcm-bridge instances,
  tracks active taps

GraphManager RPC for tap management:

```
start_tap(point: "convolver:out", channels: 4) -> { port: 9201, id: "tap-1" }
stop_tap(id: "tap-1") -> { ok: true }
list_taps() -> [{ id: "tap-1", point: "convolver:out", port: 9201 }]
```

---

## 7. Reverse Proxy (Caddy)

RT services bind to loopback only (127.0.0.1). Caddy terminates TLS and
handles WebSocket upgrades on port 8080 (the only externally-accessible port).

```
# Caddy config sketch
mugge:8080 {
    # Web UI (Python FastAPI)
    reverse_proxy /api/* localhost:8000
    reverse_proxy /ws/*  localhost:8000

    # RT services (direct browser -> Rust)
    reverse_proxy /rt/levels  localhost:9100
    reverse_proxy /rt/pcm/*   localhost:9200

    # Static files
    root * /opt/pi4audio/static
    file_server

    # TLS (self-signed for local network)
    tls internal
}
```

**Security benefits:**
- Solves F-037 (web UI currently has no authentication)
- Single TLS termination point — RT services don't need TLS libraries
- Caddy supports HTTP basic auth, client certificates, or IP allowlists
- All external traffic authenticated and encrypted

---

## 8. Implementation Phasing

| Phase | Priority | Scope | Estimated Effort | Depends On |
|-------|----------|-------|-----------------|------------|
| **2a** | HIGH | Replace `pipewire_collector` subprocess calls with GM RPC. Directly fixes F-061/F-063/F-064 collector blocking. | 1-2 days | -- |
| **2b** | HIGH | Add `tungstenite` WebSocket to pcm-bridge + `audio-common` shared crate | 2-3 days | 2a |
| **3** | MEDIUM | Caddy reverse proxy. Remove Python PCM relay. Browser connects directly to RT services. | 1 day | 2b |
| **4** | MEDIUM | GM on-demand tap management (`start_tap`/`stop_tap`/`list_taps` RPC) | 3-5 days | 3 |
| **5** | LOW | Measurement session integration (audio-recorder service) | 2-3 days | 4 |

**Phase 2a is the immediate priority** — it eliminates the asyncio event loop
saturation that causes F-064. The remaining phases are architectural
improvements that can proceed incrementally.

---

## 9. Relationship to Other Documents

| Document | Relationship |
|----------|-------------|
| [rt-audio-stack.md](rt-audio-stack.md) | PipeWire configuration, filter-chain convolver, gain architecture. RT services attach to this audio graph. |
| [rt-signal-generator.md](rt-signal-generator.md) | Detailed design of signal-gen (D-037). Covers safety caps, RPC protocol, PW stream management. |
| [measurement-daemon.md](measurement-daemon.md) | Measurement workflow architecture (D-036). Web-UI Python orchestrates measurement sessions using signal-gen + audio-recorder. |
| [web-ui.md](web-ui.md) | Web UI architecture. FilterChainCollector and LevelsCollector will be replaced by direct browser-to-RT-service WebSocket connections (Phase 3). |
| [safety.md](../operations/safety.md) | Operational safety constraints. Signal-gen's -20 dBFS cap (D-009), GM watchdog mute (<21ms), gain staging limits. |
| `docs/project/status.md` | F-064 entry contains the full Q1-Q8 discussion transcript and design rationale. |
