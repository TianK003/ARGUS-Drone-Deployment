# ARGUS Hub (WebServer)

FastAPI server that pairs with **WildBridge** edge clients (one per drone) to form a multi-drone swarm dashboard. Runs an in-process **SAM 3.1** vision loop that continuously scans every connected drone's live video against a natural-language prompt and surfaces hits (with the SAM-overlaid frame) in the dashboard.

For the big picture and roadmap see `../../docs/ARCHITECTURE.md`.

## Install

```bash
cd GroundStation/WebServer
python -m venv .venv && source .venv/bin/activate   # PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Python 3.9+. A CUDA GPU is recommended for SAM 3.1; `--cpu` works for dev but runs seconds per frame.

## Run

```bash
python -m app                        # Live
python -m app --test                 # 5×5 m patrol paths at 10 m altitude (flight sims)
python -m app --cpu                  # Force SAM onto CPU instead of CUDA GPU 0
```

Visit `http://localhost:8000`.

The hub is entirely in-memory — nothing is persisted. Drones don't need to be pre-registered; they join automatically when an edge client connects.

### Flags

| Flag | Default | Meaning |
|---|---|---|
| `--host` | `127.0.0.1` | Bind address. `0.0.0.0` to expose on LAN. |
| `--port` | `8000` | Web-server port. |
| `--test` | off | Small 5×5 m patrol paths at 10 m altitude (for flight sims). |
| `--cpu` | off | Force SAM onto CPU instead of CUDA GPU 0. |

## Simulated multi-drone setup

The architecture is edge-driven — drones *push* video and telemetry to the hub — so a local simulation needs three processes per drone:

```bash
# Terminal 1 — the hub
python -m app

# Terminal 2 — fake a DJI RC at 127.0.0.1:8082/8083
python client/mock_remote.py --port-http 8082 --port-tcp 8083 --lat 46.0569 --lng 14.5058

# Terminal 3 — the edge agent that bridges the fake RC to the hub
python client/aegis_client.py --ip 127.0.0.1 --port-http 8082 --port-tcp 8083
```

For a second simulated drone, run a second mock on different ports (e.g. `--port-http 8084 --port-tcp 8085 --lat ...`) and a second `aegis_client.py` pointing at it. Each mock uses the local webcam for video; use `--image-folder <dir>` on subsequent mocks to avoid the camera-device lock conflict.

## Dashboard

One page at `/`:

- **Search Target** — enter a natural-language prompt and dispatch to the swarm. SAM 3.1 starts matching against every drone's next frame.
- **Detections** — live list of matched frames (drone + prompt). Click any row to see the SAM-overlaid frame full-screen. The ⛶ button opens the expanded detections panel in the map slot — scrollable card grid with per-detection *Pin to map* checkbox. New detections also trigger a 2-second toast bottom-right.
- **Drones** — auto-populated camera-tile grid, one tile per connected edge client. ⛶ on a tile opens that drone's live MJPEG full-screen in the same lightbox.
- **Map** — every connected drone renders as a marker with a coloured path line. Every detection auto-pins at the drone's GPS *at detection time* with a hover preview of the frame; the hub never moves those pins even if the drone does.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Dashboard (static HTML + JS) |
| GET | `/api/health` | `{ok, active_drones}` |
| GET | `/api/drones` | All drone telemetry snapshots |
| POST | `/api/prompt` | `{prompt}` — set the master SAM tracking prompt |
| GET | `/api/detections` | All detection metadata (append-only history, cap 1000) |
| GET | `/api/detections/{id}/image.jpg` | Annotated JPEG; 404 once evicted (latest 50 retained, FIFO) |
| WS | `/ws/drones` | 1 Hz fan-out of snapshots + new-detection alerts for the dashboard |
| WS | `/ws/swarm/{uuid}` | Edge-client bidirectional channel: join, telemetry, path updates |
| POST | `/api/swarm/{uuid}/video` | Edge-client raw JPEG ingest |
| GET | `/api/swarm/{uuid}/video.mjpg` | Dashboard-facing MJPEG re-stream for the tile grid and fullscreen lightbox |

Interactive docs at `/docs`.

## Modules

- `app/registry.py` — in-memory `DroneRegistry`: drone state, alert queue, detection metadata (cap 1000), detection JPEG store (FIFO cap 50).
- `app/routes.py` — all HTTP + WebSocket routes listed above.
- `app/vision.py` — `VisionDaemon`. Single background thread holding SAM 3.1 in VRAM, round-robin over every connected drone's latest frame, encodes an annotated JPEG via `Results.plot()`, calls `registry.record_detection(...)`.
- `app/pathing.py` — server-side zigzag/sweep allocator; assigns non-overlapping sectors to drones as they join (or a single 5×5 m box in `--test`).
- `app/main.py` — FastAPI factory. The lifespan starts the `VisionDaemon`.
- `app/__main__.py` — argparse + uvicorn.
- `static/dashboard.html` — single-file dashboard (CSS + JS inline). Talks to `/api/drones`, `/api/detections`, `/ws/drones`.

## Tools

- `tools/check_video.py` — RTSP smoke test without the webapp.
- `tools/sam3_webcam.py` — reference SAM 3 inference on a local webcam. Not part of the hub; handy for verifying the Ultralytics install works before running the daemon.

## Safety

- **No auth.** Run on a trusted LAN only.
- **The physical RC always overrides the hub.** If anything feels wrong, grab the sticks or press RTH on the RC.
- **Enable Virtual Stick first.** The RC ignores `/send/stick` until virtual-stick mode is active. `aegis_client.py` does this automatically when it takes off.
