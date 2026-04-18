# WildBridge Web Backend (Phase 1)

A FastAPI server that sits between a browser and the WildBridge Android app running on a DJI RC. Lets an operator fly the drone from a web page — the RC app stays the "middle man", its physical sticks are replaced by two on-screen joysticks.

Phase 1 scope: virtual-stick control + Takeoff / Land / RTH. No waypoint editor, telemetry dashboard, or video yet.

## Install

```bash
cd GroundStation/WebServer
pip install -r requirements.txt
```

Python 3.9+.

## Run

### Mock mode (no drone / no RC required)

```bash
python -m app --mock
```

Opens on `http://localhost:8000`. Every command is logged to stdout instead of being sent. Use this for UI work.

### Live mode (real RC on the LAN)

```bash
python -m app --rc-ip 192.168.1.100
```

The RC must be powered on, the WildBridge app must be running, and its **"Testing Tools → Virtual Stick"** page must be open (that's what starts the port-8080 server).

### Flags

| Flag | Default | Meaning |
|---|---|---|
| `--rc-ip IP` | — | RC controller IP on the LAN. Required unless `--mock`. |
| `--mock` | off | Don't touch the network; log commands to stdout. |
| `--host HOST` | `127.0.0.1` | Bind address. Use `0.0.0.0` to expose on LAN. |
| `--port PORT` | `8000` | Web-server port. |
| `--max-stick F` | `0.3` | Saturation cap for stick axes in `[0, 1]`. Matches the upstream safety cap. |

## Endpoints

| Method | Path | Body | Forwards to |
|---|---|---|---|
| GET | `/` | — | serves `static/index.html` |
| GET | `/api/health` | — | — |
| POST | `/api/virtual-stick/enable` | — | `/send/enableVirtualStick` |
| POST | `/api/virtual-stick/disable` | — | `/send/abortMission` |
| POST | `/api/stick` | `{leftX, leftY, rightX, rightY}` | `/send/stick` |
| POST | `/api/takeoff` | — | `/send/takeoff` |
| POST | `/api/land` | — | `/send/land` |
| POST | `/api/rth` | — | `/send/RTH` |
| WS | `/ws/stick` | `{leftX, leftY, rightX, rightY}` | debounced → `/send/stick` |

Interactive docs at `http://localhost:8000/docs`.

## Safety

- **Always click "Enable Virtual Stick" first.** `/send/stick` is ignored by the drone until virtual-stick mode is active.
- **Big red DISABLE button** calls `/send/abortMission` — use it as a hard-stop.
- **Deadman:** if the WebSocket closes or goes silent for 500 ms while sticks are held, the backend forwards a zeroed stick command automatically.
- **No auth.** The RC's own HTTP server has no auth either. Only run this on a trusted LAN.

## Phase 2+ roadmap (not built)

Waypoint editor on a map (`/send/navigateTrajectory`), live telemetry from TCP 8081, RTSP-to-browser video, multi-drone, mission save/load.
