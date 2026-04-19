# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

WildBridge (a.k.a. ARGUS-Drone-Deployment) is a DJI ground-station system. The **Android app** in `WildBridgeApp/` is deployed onto a DJI RC controller and exposes network services for control, telemetry, and video.

This project implements the **ARGUS Hub** (`GroundStation/WebServer/`) — a modernized, multi-drone swarm management system. It features an **Edge-Driven** architecture where drones join automatically via WebSockets, centralized **SAM 3.1 AI Vision** for multi-plexed objective tracking, and a premium glassmorphic dashboard with server-side algorithmic path allocation.

Upstream paper: Rolland et al., *WildBridge* (RiTA 2025). EU Horizon Europe funded (WildDrone project).

## Repo layout

- `WildBridgeApp/` — Android app (Kotlin + DJI Mobile SDK V5). Contains **three parallel module trees with near-duplicate code**:
  - `android-sdk-v5-as/` — the project the README tells you to open in Android Studio and deploy.
  - `android-sdk-v5-sample/` — sample implementations, has its own `VirtualStickFragment.kt` and `DroneController.kt`.
  - `android-sdk-v5-uxsdk/` — reusable UI library.
  - Before editing any Kotlin, confirm which tree is live. Upstream appears to author changes in both `android-sdk-v5-as` and `android-sdk-v5-sample/src/main/java/dji/sampleV5/aircraft/`.
- `GroundStation/Python/djiInterface.py` — **canonical HTTP + TCP client**. Wraps every command and telemetry field the RC exposes. Reuse it; do not reimplement the protocol.
- `GroundStation/ROS/` — ROS 2 Humble wrapper that publishes telemetry as topics and exposes commands as services.
- `GroundStation/WebServer/` — **ARGUS Hub**. Edge-driven FastAPI hub + dashboard. All state is in-memory; nothing is persisted.
  - `app/vision.py`: `VisionDaemon` — a single background thread holding **SAM 3.1** in VRAM; round-robin inference over each connected drone's latest frame against the current master prompt. On a hit it calls `Results.plot()`, encodes the annotated JPEG, and posts a detection via `registry.record_detection(...)`.
  - `app/registry.py`: `DroneRegistry`. Thread-safe drone state + per-tick alert queue + append-only detection metadata (cap 1000) + FIFO detection-image store (cap 50).
  - `app/routes.py`: all HTTP + WebSocket routes. Dashboard-facing (`/ws/drones`, `/api/drones`, `/api/detections`, `/api/detections/{id}/image.jpg`, `/api/prompt`, `/api/swarm/{id}/video.mjpg`) and edge-client-facing (`/ws/swarm/{id}`, `POST /api/swarm/{id}/video`).
  - `app/pathing.py`: server-side zigzag/sweep allocator; assigns non-overlapping sectors to drones as they join.
  - `app/main.py`: FastAPI factory; `lifespan` starts the `VisionDaemon`.
  - `app/__main__.py`: argparse + uvicorn.
  - `static/dashboard.html`: single-file dashboard (HTML + CSS + JS inline). Renders the Leaflet map, connected drones, the Detections section (compact list + ⛶-expanded full-panel view replacing the map), a shared fullscreen lightbox (detection frames + live MJPEG), and detection toasts.
- `GroundStation/client/` — edge agents that run alongside a DJI RC (or a simulated one):
  - `aegis_client.py` — talks to the RC over the WildBridge HTTP/TCP contract AND to the hub over `/ws/swarm/{id}` (telemetry/paths) and `POST /api/swarm/{id}/video` (frames).
  - `mock_remote.py` — fakes a DJI RC on localhost (HTTP on `--port-http`, TCP on `--port-tcp`); uses the local webcam for video unless `--image-folder` is supplied.
- `docs/` — `ARCHITECTURE.md` (system + swarm roadmap) and `FILE_MAP.md` (one-line file catalogue).

## The network contract (load-bearing)

The single source of truth for how any client talks to the drone is the HTTP/TCP/RTSP protocol served by the Android app — **not** Kotlin internals. Any new ground-station code must match this contract; always cross-check:

- `README.md` §"API Reference" for the endpoint table.
- `GroundStation/Python/djiInterface.py` for the wire-format each endpoint expects (plain `text/plain` bodies like `"lat,lon,alt,yaw,speed"`, not JSON).

## Virtual-stick semantics

- `POST /send/stick` body is the string `"<leftX>,<leftY>,<rightX>,<rightY>"`, each float in `[-1, 1]`.
- Axes: left stick X = **yaw**, left stick Y = **throttle**; right stick X = **roll**, right stick Y = **pitch**.
- `djiInterface.requestSendStick()` saturates values to **±0.3** by default. That is a deliberate safety cap, not a bug — treat it as a configurable limit when building on top.
- **You must `POST /send/enableVirtualStick` before `/send/stick` has any effect.** `/send/navigateTrajectory` enables virtual stick implicitly; `/send/stick` does not. This is documented in README §Troubleshooting but routinely catches new users.
- `POST /send/abortMission` disables virtual stick and stops the current mission — use it as a hard-stop.

## Build & run

### Android app (deploys to the DJI RC or an Android phone plugged into an RC-N1/N3)
Open `WildBridgeApp/android-sdk-v5-as/` in **Android Studio Koala 2024.1.1**, put your DJI developer API key in `local.properties` as `AIRCRAFT_API_KEY=<key>` **without surrounding quotes** (`build.gradle` reads `.properties`-style and embeds the value verbatim into the manifest; quotes become part of the key and DJI registration fails), build, and deploy via USB to the controller or phone. No standard CLI build — DJI SDK's Maven repo and API-key handling expect the IDE. Before the first build the user must generate the keystore referenced by `gradle.properties` (`msdkkeystore.jks` with password `123456`, alias `msdkkeystore`).

### Python ground station
```bash
pip install -r GroundStation/Python/requirements.txt
python GroundStation/Python/djiInterface.py <RC_IP>   # dumps live telemetry
```

### Web backend — ARGUS Hub (this fork)
```bash
cd GroundStation/WebServer
python -m venv .venv && source .venv/bin/activate   # PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python -m app                                         # Live: edge drones join via WebSocket
python -m app --test                                  # Dev: 5x5m tiny grids + 10m altitude for flight sims
python -m app --cpu                                   # Force SAM onto CPU instead of CUDA GPU 0
```

CLI flags: `--host` (default `127.0.0.1`), `--port` (default `8000`), `--test`, `--cpu`. No `--mock`, no `--no-vision`, no drones.json. The hub is entirely in-memory.

### Simulated multi-drone setup (three processes per drone)
The hub only speaks the edge-driven contract — drones push their own video/telemetry in. There is no server-side mock; you run an edge stack per simulated drone:
```bash
# Terminal 1 — the hub
python -m app

# Terminal 2 — fake a DJI RC at 127.0.0.1:8082/8083
python client/mock_remote.py --port-http 8082 --port-tcp 8083 --lat 46.0569 --lng 14.5058

# Terminal 3 — the edge agent that bridges the fake RC ↔ hub
python client/aegis_client.py --ip 127.0.0.1 --port-http 8082 --port-tcp 8083
```
For a second simulated drone: a second `mock_remote.py` on different ports (e.g. 8084/8085) + a second `aegis_client.py`. The mocks grab the local webcam for video; use `--image-folder` on subsequent mocks to avoid a camera-device lock conflict. `aegis_client.py` depends on `websocket-client` (NOT `websocket` — the two PyPI packages collide in the `websocket` namespace and only `websocket-client` provides `WebSocketApp`).

Architecture in one diagram:
```
browser ──HTTP/WS──► ARGUS Hub (:8000)
                         │  ▲
                         │  │ /ws/drones  (1 Hz telemetry + alerts)
                         │  │ /api/detections[/{id}/image.jpg]
                         ▼  │
                     Registry + VisionDaemon (SAM 3.1, VRAM-resident)
                         ▲  ▲
                         │  │ /ws/swarm/{id}          (join + telemetry + path updates)
                         │  │ POST /api/swarm/{id}/video  (JPEG frames)
                         └──┴──────────── edge client (aegis_client.py)
                                          └── HTTP/TCP/RTSP ──► DJI RC (WildBridge app) or mock_remote.py
```

### Dashboard surface (`static/dashboard.html`)
Single-file HTML. Talks to `/api/drones`, `/api/detections`, `/ws/drones`. Features:
- **Search Target** panel → `POST /api/prompt`, sets the master SAM prompt.
- **Detections** section — compact list populated off `/ws/drones` alert fan-out AND a 5s polling fallback against `/api/detections` (WS alerts are the primary path; the poll is defensive). Click a row → fullscreen lightbox of the SAM-overlaid frame. ⛶ opens the expanded panel that replaces `#map` in the grid; the panel is a `grid-auto-rows: max-content` card grid with per-detection "Pin to map" checkbox.
- **Auto-pinning**: every new detection automatically drops a marker on the map at the drone's GPS at detection time, with a hover-only Leaflet tooltip showing a thumbnail of the frame (leaflet lazy-renders tooltips, so thumbnails only fetch on hover).
- **Live camera tiles** — ⛶ opens the drone's `/api/swarm/{id}/video.mjpg` in the same lightbox (MJPEG renders through a plain `<img>`; closing the lightbox nulls the src to actually terminate the stream).
- **Toasts** — bottom-right, 2 s, fire on *live* detections only; `bootstrapDetections()` passes `silent: true` so page reloads / polling don't spam.

### Integrated features
- **Server-side path executor** — zigzag allocation in `app/pathing.py`.
- **SAM 3.1 detection loop** — `app/vision.py`; produces detection metadata + annotated JPEGs stored in the registry.
- **WebRTC / GStreamer video transport** — *roadmap*: replace the current MJPEG re-stream for sub-200 ms latency.

### ROS 2 ground station
```bash
ros2 launch wildview_bringup swarm_connection.launch.py
```

## Simulators

The DJI Mobile SDK provides a built-in aircraft simulator (`SimulatorVM.kt` on the Android side). For ground-station-only simulation the right primitive is `GroundStation/client/mock_remote.py` (fakes the RC's HTTP/TCP/RTSP surface locally) paired with `aegis_client.py`. There is no longer a hub-side `--mock` flag; the hub sees a mock and a real RC identically.

## Gotchas that burn time

- The RC and the ground station must be on the **same LAN subnet**; upstream recommends 5 GHz Wi-Fi. No NAT.
- The server threads in the Android app only start when the **"Virtual Stick" page** of the WildBridge app is open on the RC. A backgrounded app means no port 8080.
- Parallel `WildBridgeApp/*` module trees: editing `VirtualStickFragment.kt` or `DroneController.kt` in the wrong tree means your changes never run. Deploy-path is `android-sdk-v5-as/`.
- `djiInterface.py` imports `cv2` at module scope but does not actually use it in the DJIInterface class for control/telemetry. The web backend reuses `DJIInterface` and depends on real opencv for the video feed — see `app/drone_client.py` for the "install real cv2 if present, else stub it" pattern. Any *other* consumer that doesn't want opencv must replicate that pattern, otherwise `DJIInterface` import fails with `ModuleNotFoundError: cv2`.
- Endpoint bodies are **plain CSV strings, not JSON** — a common mistake when writing new clients.
- Waypoint commands use **absolute altitude in meters**, WGS84 decimal lat/lon, yaw in compass degrees.
- The WildBridge phone/RC app's HTTP, TCP and RTSP servers only run while the **"Virtual Stick"** page is foregrounded. Any feature in the web backend (video feed included) dies silently if the page backgrounds or the screen locks. For a phone, disable battery-save for the app and turn on "Stay awake while charging" in Developer Options.
- The hub doesn't pull video from RTSP itself; `aegis_client.py` does that and POSTs JPEGs to `/api/swarm/{id}/video`. A drone's live tile going blank usually means either the RC app isn't foregrounded (so the aegis client's source is dry) or the aegis client process died. Check its stdout before debugging the hub.
- The per-drone video routes are namespaced under `/api/swarm/{id}/...` (edge-driven). Any pre-edge fork that used `/api/drones/{id}/video.mjpg` or global `/api/stick`, `/ws/stick`, `/api/video.mjpg` is **gone** — no direct migration path; the hub no longer proxies control-plane commands at all, virtual-stick piloting happens inside `aegis_client.py` against the RC directly.
- Detection state is in-memory: metadata cap is 1000 entries, JPEG cap is 50 (FIFO eviction, `has_image` flips to false once a frame is evicted). Restarting the hub clears everything.
- The webapp's RC-side package name is pinned: `com.dji.sampleV5.aircraft`. That string must match exactly in the DJI developer portal App registration. The keystore (`msdkkeystore.jks`) is NOT in the repo — users generate it themselves with the passwords in `gradle.properties` (`123456` / alias `msdkkeystore`).

## Where NOT to put new code

- Do not add server / webapp code inside `WildBridgeApp/`. That tree is the Android app only.
- Ground-station code — any Python/Node/Go/ROS wrapper — belongs under `GroundStation/`.
