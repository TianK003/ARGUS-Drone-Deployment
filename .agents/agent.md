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
- `GroundStation/WebServer/` — **ARGUS Hub**. The centralized backend and frontend.
  - `app/vision.py`: **VisionDaemon** multiplexes video feeds across all drones using **SAM 3.1** on the GPU.
  - `app/registry.py`: Manages the dynamic drone state and AI detection alert queues.
  - `app/routes.py`: High-performance FastAPI routes for dashboard telemetry (1Hz fan-out), Edge client joining (WebSocket), and binary video ingest (POST).
  - `app/pathing.py`: Server-side **zigzag/sweep path generator**; automatically allocates sectors to drones as they join to ensure swarm-wide coverage without overlaps.
  - `static/dashboard.html`: The modern glassmorphic UI hub.
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

python -m app                                         # Live: Edge drones join via WebSocket
python -m app --test                                  # Dev: Use 5x5m tiny grids for flight sims
python -m app --no-vision                             # Disable SAM 3.1 inference
```

### Multi-Drone Mock Testing
Launch the Hub, then run multiple edge clients:
```powershell
python -m client.mock_remote --id alpha --cam-folder ./mock/A/
python -m client.mock_remote --id beta  --cam-folder ./mock/B/
```
Serves on `http://localhost:8000`. The landing page is the **Modern Dashboard** (`/`). 
- **Swarm Connection**: Drones appear automatically when their edge client joins.
- **AI Detections**: AI object hits from SAM 3.1 show up in the live notification tray via the `/ws/drones` broadcast.
- **Direct Control**: `/drone/{id}` remains for manual cockpit overrides.

Architecture in one diagram:
```
dashboard dashboard ──HTTP/WS──► ARGUS Hub (:8000) ──WS Path Update─► Edge Client (mc)
                                                  ──POST Master Prompt─► VisionDaemon (SAM 3.1)
Edge Client (mc)   ──WS/JSON─► ARGUS Hub (Registry) ──WS Status Update─► Dashboard
                   ──POST IMG─► ARGUS Hub (Vision)  
```

Core Python modules under `app/`:
- `registry.py` — `DroneRegistry`: thread-safe add/remove/list + JSON persistence, owns one `LiveDroneClient` + `LiveVideoBroadcaster` per drone.
- `routes.py` — per-drone routes namespaced under `/api/drones/{id}/...` (virtual-stick enable/disable, `/takeoff`, `/land`, `/rth`, `/stick`, `/video/status|snapshot.jpg|video.mjpg`). Stick WebSocket is `/ws/drones/{id}/stick` with the same 500 ms deadman + 20 Hz forward cap as before. `/ws/drones` fan-outs `{id → snapshot}` for the dashboard.
- `drone_client.py` — `LiveDroneClient` wraps `djiInterface.DJIInterface`; `MockDroneClient` is a stdout stub.
- `video.py` — `LiveVideoBroadcaster` (RTSP → OpenCV → JPEG with exponential-backoff reconnect) and `MockVideoBroadcaster`.
- `main.py` — FastAPI factory. `/drone/{id}` injects `<script>window.DRONE_ID = "..."</script>` into `index.html` so the client JS knows which drone it's controlling.
- `__main__.py` — argparse.

Helper scripts: `tools/check_video.py` (RTSP smoke test), `tools/sam3_webcam.py` (reference SAM 3 / Falcon inference on a webcam, not wired into the server — see roadmap below).

### Integrated Features
- **Server-side path executor** — Algorithmic sector allocation is LIVE in `app/pathing.py`.
- **Meta SAM 3 detection loop** — Centralized inference is LIVE in `app/vision.py`.
- **WebRTC / GStreamer video transport** — *Roadmap*: Replacement for current MJPEG to get sub-200ms latency.

### ROS 2 ground station
```bash
ros2 launch wildview_bringup swarm_connection.launch.py
```

## Simulators

The DJI Mobile SDK provides a built-in aircraft simulator (`SimulatorVM.kt` on the Android side). There is no separate simulator for ground-station code. The web backend's `--mock` flag stubs out HTTP calls so the UI can be developed without any drone or RC — it does **not** drive the DJI simulator.

## Gotchas that burn time

- The RC and the ground station must be on the **same LAN subnet**; upstream recommends 5 GHz Wi-Fi. No NAT.
- The server threads in the Android app only start when the **"Virtual Stick" page** of the WildBridge app is open on the RC. A backgrounded app means no port 8080.
- Parallel `WildBridgeApp/*` module trees: editing `VirtualStickFragment.kt` or `DroneController.kt` in the wrong tree means your changes never run. Deploy-path is `android-sdk-v5-as/`.
- `djiInterface.py` imports `cv2` at module scope but does not actually use it in the DJIInterface class for control/telemetry. The web backend reuses `DJIInterface` and depends on real opencv for the video feed — see `app/drone_client.py` for the "install real cv2 if present, else stub it" pattern. Any *other* consumer that doesn't want opencv must replicate that pattern, otherwise `DJIInterface` import fails with `ModuleNotFoundError: cv2`.
- Endpoint bodies are **plain CSV strings, not JSON** — a common mistake when writing new clients.
- Waypoint commands use **absolute altitude in meters**, WGS84 decimal lat/lon, yaw in compass degrees.
- The WildBridge phone/RC app's HTTP, TCP and RTSP servers only run while the **"Virtual Stick"** page is foregrounded. Any feature in the web backend (video feed included) dies silently if the page backgrounds or the screen locks. For a phone, disable battery-save for the app and turn on "Stay awake while charging" in Developer Options.
- The web backend's `LiveVideoBroadcaster` auto-reconnects with exponential backoff (1s → 10s). A `connected: false` in `GET /api/drones/{id}/video/status` usually means the app isn't foregrounded — not a backend bug.
- All control/video routes are now namespaced per drone (`/api/drones/{id}/...`). The old global `/api/stick`, `/ws/stick`, `/api/video.mjpg` paths from the pre-merge fork are **gone**. If you're porting code from before the ARGUS merge, it needs an id; if there was only one drone, add it to `drones.json` and hit its id.
- The webapp's RC-side package name is pinned: `com.dji.sampleV5.aircraft`. That string must match exactly in the DJI developer portal App registration. The keystore (`msdkkeystore.jks`) is NOT in the repo — users generate it themselves with the passwords in `gradle.properties` (`123456` / alias `msdkkeystore`).

## Where NOT to put new code

- Do not add server / webapp code inside `WildBridgeApp/`. That tree is the Android app only.
- Ground-station code — any Python/Node/Go/ROS wrapper — belongs under `GroundStation/`.
