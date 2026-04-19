# ARGUS — File Map

A one-line-per-file catalogue of the moving parts. For the "why" behind a
given layer, see `docs/ARCHITECTURE.md`. For on-the-wire contracts, see
`README.md §"API Reference"` and `GroundStation/Python/djiInterface.py`.

## Top-level

| Path | Purpose |
|------|---------|
| `README.md` | User-facing README: install, API reference, gotchas. |
| `CLAUDE.md` | Project instructions for Claude Code sessions. |
| `docs/ARCHITECTURE.md` | System architecture + swarm roadmap (née AEGIS). |
| `docs/FILE_MAP.md` | This document. |
| `.gitignore`, `LICENSE` | Standard. |
| `WildBridgeDiagram.png`, `WildBridge_icon.png` | Upstream marketing assets. |

## `WildBridgeApp/` — Android app (do not touch)

The Kotlin tree deployed onto a DJI RC Pro / RC Plus / RC-N3 (or an Android
phone plugged into an RC-N1/N3). Only cited here for orientation.

| Subtree | Purpose |
|---------|---------|
| `android-sdk-v5-as/` | The module Android Studio builds and deploys. |
| `android-sdk-v5-sample/` | Upstream sample code, mirrors `-as/`. |
| `android-sdk-v5-uxsdk/` | Reusable UI library. |

Of particular note inside the app (but out of scope for this repo's edits):
`VirtualStickFragment.kt` and `DroneController.kt` expose the HTTP :8080 /
TCP :8081 / RTSP :8554 endpoints consumed by the ground station.

## `GroundStation/Python/` — canonical drone client

| File | Purpose |
|------|---------|
| `djiInterface.py` | `DJIInterface` class — wraps every WildBridge endpoint (HTTP commands, TCP telemetry, RTSP URL helper). Reuse it; do not reimplement the protocol. |
| `requirements.txt` | `requests` only. |

## `GroundStation/WebServer/` — ARGUS Hub (FastAPI)

| File | Purpose |
|------|---------|
| `app/__main__.py` | CLI: `python -m app [--mock] [--drones-config PATH] [--host H] [--port P] [--max-stick F] [--no-video]`. Loads registry, seeds a mock drone if `--mock` and registry is empty, launches uvicorn. |
| `app/main.py` | FastAPI app factory: `/`, `/drone/{id}`, `/video`, CORS, static mount, lifespan hook for registry shutdown. |
| `app/routes.py` | HTTP + WebSocket routes: `/api/drones` CRUD, `/api/drones/{id}/{takeoff,land,rth,stick,virtual-stick/*,video/*}`, `/ws/drones/{id}/stick` (20 Hz + 500 ms deadman), `/ws/drones` (1 Hz telemetry fan-out), `/api/plans` (persist Boustrophedon plan JSON). |
| `app/registry.py` | `DroneEntry` + `DroneRegistry`: thread-safe add/remove/list, JSON persistence to `drones.json`, lazy `LiveDroneClient` + `LiveVideoBroadcaster` per entry. |
| `app/drone_client.py` | `LiveDroneClient` (wraps `DJIInterface`) and `MockDroneClient` (stdout-only, for dev). Both expose `enable_virtual_stick`, `send_stick`, `takeoff`, `land`, `rth`, `last_calls`. |
| `app/video.py` | `LiveVideoBroadcaster` (RTSP → OpenCV → JPEG, reconnect with exponential backoff) and `MockVideoBroadcaster` (test-pattern at ~30 fps). |
| `static/dashboard.html` | Multi-drone Leaflet dashboard. Live mode renders markers from `/api/drones` + `/ws/drones`. Planning mode restores the Boustrophedon planner: click to add, drag, reach slider, stripe spacing, save plan via `POST /api/plans`. |
| `static/index.html` | Single-drone control UI: joysticks (left = yaw/throttle, right = roll/pitch), takeoff/land/RTH, hard-stop, activity log, embedded video tab. |
| `static/video.html` | Standalone full-screen MJPEG viewer. Requires `?drone=ID`. |
| `static/app.js` | Single-drone UI logic: joystick widgets, WebSocket reconnect, HTTP actions, video status polling. Reads `window.DRONE_ID` injected by the server. |
| `static/style.css` | Dark theme for the single-drone UI. |
| `tools/check_video.py` | RTSP smoke test without the webapp. |
| `tools/sam3_webcam.py` | Standalone SAM 3 / Falcon Perception inference on a webcam. Reference code for the future swarm vision loop (see `docs/ARCHITECTURE.md §"Roadmap"`). Not wired into the server. |
| `requirements.txt` | `fastapi`, `uvicorn[standard]`, `requests`, `opencv-python-headless`, `numpy`. |
| `drones.example.json` | Copy to `drones.json` to pre-populate the registry. |
| `README.md` | WebServer-specific quickstart. |

## `GroundStation/ROS/` — ROS 2 wrapper (out of scope for the webapp)

| Package | Purpose |
|---------|---------|
| `dji_controller/` | `DjiNode` — subscribes to `command/*` topics and publishes telemetry. One node per RC IP via namespace. |
| `drone_videofeed/` | `RtspNode` — publishes RTSP frames as `sensor_msgs/Image`. |
| `wildview_bringup/` | Launch files. `swarm_connection.launch.py` brings up three namespaced drones and the corresponding nodes; ARP-resolves drone 1 at runtime. |
