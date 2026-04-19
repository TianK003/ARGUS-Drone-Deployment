# ARGUS Hub (WebServer)

A FastAPI server that sits between a browser and one-or-more WildBridge Android apps running on DJI RCs. Hosts a Leaflet multi-drone dashboard at `/` and a per-drone control + MJPEG video UI at `/drone/{id}`.

For the big picture (roadmap, full swarm vision) see `../../docs/ARCHITECTURE.md`.

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

Opens `http://localhost:8000`. Seeds a single mock drone (`mock-1`) at Ljubljana so the dashboard and single-drone UI have something to show. Every command is logged to stdout.

### Live mode (real RCs on the LAN)

Copy the example registry, edit it for your drones, then launch:

```bash
cp drones.example.json drones.json
python -m app
```

The RCs must be powered on, the WildBridge app must be running, and its **"Testing Tools → Virtual Stick"** page must be foregrounded (that's what starts the per-RC port-8080 server).

Add or remove drones at runtime via the dashboard's `+ Register drone` button — the registry is persisted back to `drones.json`.

### Flags

| Flag | Default | Meaning |
|---|---|---|
| `--mock` | off | Force all drones to mock mode; seed a Ljubljana mock drone if registry is empty. |
| `--drones-config PATH` | `./drones.json` | Registry file (JSON). Persisted on every add/remove. |
| `--host HOST` | `127.0.0.1` | Bind address. `0.0.0.0` to expose on LAN. |
| `--port PORT` | `8000` | Web-server port. |
| `--max-stick F` | `0.3` | Saturation cap for stick axes in `[0, 1]`. Matches the upstream safety cap. |
| `--no-video` | off | Disable video broadcasters for all drones (skips RTSP). |

## UI

- **`/`** — Leaflet dashboard. `Live` mode renders real connected drones (from `/api/drones` + `/ws/drones`). `Planning` mode is the Boustrophedon patrol-path planner — click to place drones, adjust reach/spacing, save plan to `plans/`.
- **`/drone/{id}`** — joysticks (yaw/throttle + roll/pitch), Takeoff / Land / RTH / Enable-VS / hard-stop, activity log, MJPEG video tab.
- **`/video?drone={id}`** — standalone full-screen MJPEG viewer.

## Endpoints

All control/video routes are namespaced per drone.

| Method | Path | Forwards to |
|---|---|---|
| GET | `/api/health` | — |
| GET | `/api/drones` | List + telemetry snapshot per drone |
| POST | `/api/drones` | Register; body `{id, rc_ip, label?, home_lat?, home_lng?, reach_m?, mock?, enable_video?}` |
| GET | `/api/drones/{id}` | Single snapshot |
| DELETE | `/api/drones/{id}` | Remove from registry (stops its video broadcaster) |
| POST | `/api/drones/{id}/virtual-stick/enable` | RC `/send/enableVirtualStick` |
| POST | `/api/drones/{id}/virtual-stick/disable` | RC `/send/abortMission` |
| POST | `/api/drones/{id}/stick` | `{leftX, leftY, rightX, rightY}` → RC `/send/stick` |
| POST | `/api/drones/{id}/takeoff` · `/land` · `/rth` | Matching RC command |
| WS | `/ws/drones/{id}/stick` | Stick stream — 20 Hz forward cap + 500 ms deadman |
| WS | `/ws/drones` | 1 Hz fan-out of telemetry snapshots for the dashboard |
| GET | `/api/drones/{id}/video/status` | `{connected, fps, width, height, last_frame_age_s, mode}` |
| GET | `/api/drones/{id}/video/snapshot.jpg` | Latest JPEG |
| GET | `/api/drones/{id}/video.mjpg` | `multipart/x-mixed-replace` MJPEG stream |
| POST | `/api/plans` | Persist a Boustrophedon plan JSON under `plans/` |

Interactive docs at `http://localhost:8000/docs`.

## Safety

- **Always click "Enable Virtual Stick" first** on the per-drone page. `/send/stick` is ignored by the drone until virtual-stick mode is active.
- **Big red DISABLE button** calls `/send/abortMission` — hard-stop.
- **Deadman**: if the stick WebSocket closes or goes silent for 500 ms while sticks are held, the backend forwards one zeroed stick command automatically.
- **No auth.** The RC's own HTTP server has no auth either. Only run on a trusted LAN.

## Tools

- `tools/check_video.py` — RTSP smoke test without the webapp.
- `tools/sam3_webcam.py` — reference SAM 3 / Falcon Perception inference on a webcam. Not wired into the server; slated for the Vision Engine step in `../../docs/ARCHITECTURE.md §"Roadmap"`.
