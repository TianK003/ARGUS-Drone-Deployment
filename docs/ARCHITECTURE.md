# ARGUS Architecture

**Objective:** a distributed drone orchestration platform that uses DJI
hardware to form an autonomous surveillance swarm — initially piloted by a web
operator, with an intended endgame of centralized Meta SAM 3 detection across
all streams.

This document describes both the **current implementation** (multi-drone
ARGUS Hub web app on top of the WildBridge Android bridge) and the **roadmap**
toward the full swarm vision originally drafted under the "Aegis Swarm"
working name.

---

## Current implementation

```
┌──────────────┐         ┌───────────────────────────────┐         ┌─────────────────────┐
│   Browser    │  HTTP   │    ARGUS Hub (FastAPI :8000)  │  HTTP   │ WildBridge app on   │
│ Leaflet map +│◄──────► │                               │◄──────► │ DJI RC / Android    │
│ joystick UI  │  WS     │  registry + per-drone routes  │  TCP    │ (HTTP 8080 /        │
│              │         │  Live/Plan dashboard          │  RTSP   │  TCP 8081 /         │
└──────────────┘         └───────────────────────────────┘         │  RTSP 8554)         │
                                    │    ▲                          └─────────────────────┘
                                    │    │
                                    ▼    │
                         drones.json (persisted registry)
```

### Layers

- **WildBridge Android app** (`WildBridgeApp/`) — runs on the DJI RC Pro /
  RC Plus / RC-N3 or on an Android phone plugged into an RC-N1/N3. While its
  Virtual Stick page is foregrounded it exposes HTTP 8080 (commands), TCP 8081
  (telemetry JSON lines), RTSP 8554 (H.264 video). This is the single source
  of truth for the wire contract.

- **Python client** (`GroundStation/Python/djiInterface.py`) — canonical
  wrapper around the WildBridge protocol. One `DJIInterface(rc_ip)` per RC.

- **ARGUS Hub** (`GroundStation/WebServer/`) — FastAPI app on `:8000`:
  - `app/registry.py` — in-memory drone registry with JSON persistence
    (`drones.json`).
  - `app/routes.py` — per-drone HTTP and WebSocket routes namespaced under
    `/api/drones/{id}/...` and `/ws/drones/{id}/stick`, plus `/ws/drones`
    for 1 Hz telemetry fan-out consumed by the dashboard.
  - `app/main.py` — app factory, mounts `/static`, serves dashboard at `/`
    and injects `window.DRONE_ID` into `/drone/{id}`.
  - `app/drone_client.py` — `LiveDroneClient` / `MockDroneClient`.
  - `app/video.py` — `LiveVideoBroadcaster` (RTSP → OpenCV → JPEG with
    exponential backoff reconnect) and `MockVideoBroadcaster`.

- **ROS 2 wrapper** (`GroundStation/ROS/`) — parallel ground station for
  researchers who want topics/services instead of HTTP. Shares the underlying
  `djiInterface.py`. Not needed by the webapp.

### Web UI

- `/` — **Leaflet dashboard**, two modes:
  - **Live mode** (default) — renders a marker per connected drone from
    `GET /api/drones` + `/ws/drones`. Each row shows battery/online status
    and a `Control ↗` link that opens the single-drone UI. Includes a
    `+ Register drone` dialog that POSTs to `/api/drones`.
  - **Planning mode** — restores the Boustrophedon (lawnmower) patrol-path
    planner: click to place drones, drag to relocate, adjust reach and
    stripe spacing, then `Save plan` to persist the computed paths as JSON
    under `plans/`.
- `/drone/{id}` — single-drone control UI (joysticks + takeoff/land/RTH +
  MJPEG video), unchanged from the upstream fork other than the per-drone URL
  namespacing.
- `/video?drone={id}` — full-screen MJPEG viewer, for pinning on a second
  monitor.

### Network contract

| Port | Direction | Payload |
|------|-----------|---------|
| 8000 | browser ↔ Hub | HTTP/WS — dashboard, control, video re-stream |
| 8080 | Hub → RC | HTTP — commands (plain CSV bodies, not JSON) |
| 8081 | Hub ← RC | TCP — newline-delimited JSON telemetry |
| 8554 | Hub ← RC | RTSP H.264 live video |

Endpoint bodies are **plain CSV strings**, e.g. `/send/stick` takes
`"leftX,leftY,rightX,rightY"`. See `README.md §"API Reference"` and
`GroundStation/Python/djiInterface.py` for the full table.

---

## Roadmap — full swarm vision

The original architecture doc (written under the "Aegis Swarm" name)
envisioned three capabilities beyond what's implemented today. They are
sequenced here in the order they unlock the most value:

### 1. Boustrophedon pathing engine (planning → execution)

Today the planner is **client-side only** — the dashboard computes paths in
the browser and persists them via `POST /api/plans`. Next step: add a
server-side executor that takes a saved plan and streams waypoints to each
drone via `POST /send/navigateTrajectory` on the WildBridge contract.

- **Join protocol**: when a drone is registered, the server knows its home
  GPS and reach; the planner recalculates the grid so the new drone gets a
  non-overlapping sector.
- **Leave protocol (failsafe)**: if a drone disconnects or drops below a
  battery threshold, the Hub issues `POST /send/RTH` and recomputes the
  remaining drones' sectors to cover the gap.

### 2. Meta SAM 3 detection loop

Reference implementation lives in `GroundStation/WebServer/tools/sam3_webcam.py`
(standalone SAM 3 / Falcon Perception inference on a webcam, copied in from
the teammates' `sam` prototype branch). To integrate:

- Add a `GroundStation/WebServer/app/vision.py` that owns a single GPU worker.
- Implement a **Round-Robin Processing Loop**: cycle through every registered
  drone's `video.get_latest_jpeg()`, run SAM 3 against the active text prompt,
  forward hits to an `alerts` store.
- Admin UI: add a `Prompt` text field + `Alerts` feed to the dashboard's left
  panel; pin detection GPS on the map.

Rationale for centralization (vs. edge inference): the ARGUS Hub is expected
to run on a single GPU host; drones and the Android bridge cannot spare the
compute. The round-robin keeps VRAM usage bounded regardless of fleet size.

### 3. WebRTC / GStreamer video transport

Current video uses RTSP → OpenCV → MJPEG multipart. Good enough for latency
checks and the SAM frame loop, but it's ~1–3 s end-to-end, which is too slow
for first-person piloting. Target: sub-500 ms via `aiortc` WebRTC or a
GStreamer `rtspsrc ! rtph264depay ! webrtcbin` chain. The existing
`LiveVideoBroadcaster` abstraction is a drop-in swap point — consumers only
call `get_latest_jpeg()`, so a WebRTC variant that publishes H.264 directly
can be added without churning the dashboard.

### 4. Supporting infrastructure

The original doc called out:

- **WebSockets** (done) for telemetry & path commands without HTTP polling.
- **Redis / ZeroMQ** for the SAM round-robin buffer. Only needed when SAM
  lands; today every drone's "latest JPEG" lives in a thread-safe slot inside
  `LiveVideoBroadcaster` and that is sufficient for a single process.
- **FastAPI** (done) for async.
- **Leaflet.js** (done) for the tactical map.

---

## Notes on the Android app

The Android tree in `WildBridgeApp/` is **deliberately untouched** by the
ARGUS integration work. Three parallel module trees (`android-sdk-v5-as/`,
`android-sdk-v5-sample/`, `android-sdk-v5-uxsdk/`) contain near-duplicate
code; `android-sdk-v5-as/` is the deploy target per `CLAUDE.md`. Any fix to
the HTTP/TCP/RTSP contract must land on the RC side; ARGUS Hub is only a
consumer.
