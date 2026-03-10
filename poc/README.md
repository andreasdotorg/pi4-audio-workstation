# Web UI PoC – Pi4 Audio Workstation

Proof-of-concept: browser-based spectrograph and level meters for the Pi4 audio workstation.

## Prerequisites

- Python 3.11+
- JACK server running (48 kHz, quantum 256)
- Loopback sink with 3 monitor ports
- CamillaDSP running with websocket server on 127.0.0.1:1234

## Setup

```bash
cd poc/
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> **Note:** The `camilladsp` (pycamilladsp) package is not published on PyPI.
> `requirements.txt` installs it directly from GitHub
> (`git+https://github.com/HEnquist/pycamilladsp.git`). You need `git`
> installed on the system for this to work.

## Run

```bash
uvicorn server:app --host 0.0.0.0 --port 8080
```

Open `http://<pi-ip>:8080` in Chrome or Firefox.

## Architecture

```
JACK (Loopback monitors)
  └─> server.py (JACK client "webui-poc", 3 input ports)
        ├─ /ws/pcm    → binary WebSocket (256-frame float32 chunks @ 48 kHz)
        └─ /ws/levels → JSON WebSocket (CamillaDSP RMS/peak, 10 Hz poll)

Browser (index.html)
  ├─ PCM WS → AudioWorklet → ChannelSplitter → 3x AnalyserNode → Canvas spectrograph
  └─ Levels WS → 16 bar meters (capture + playback)
```

## Pass/Fail Criteria

| # | Test | Pass | Fail |
|---|------|------|------|
| P1 | JACK client registers and connects | `jack_lsp` shows `webui-poc` with 3 connections | Fails to register |
| P2 | PCM streams for 5 min | < 1% frame drops | > 5% drops or disconnect |
| P3 | Spectrograph >= 25 fps for 5 min | FPS counter shows 25-30 | FPS < 20 or freeze |
| P4 | pycamilladsp levels returns valid data | 16 floats in [-96, 0] dB range | Exception or empty |
| P5 | Level meters update >= 8 Hz | Smooth movement | < 5 Hz or freeze |
| P6 | 0 CamillaDSP xruns during test | 0 xruns in 5 min | Any xrun |
| P7 | PoC CPU overhead < 3% | top shows < 3% additional | > 5% additional |
| P8 | JACK callback < 500 us | No xruns from PoC client | > 500 us or xruns |
