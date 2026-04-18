# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

WildBridge (a.k.a. ARGUS-Drone-Deployment in this fork) is a DJI ground-station system. The **Android app** in `WildBridgeApp/` is deployed onto a DJI RC controller (RC Pro / RC Plus / RC-N3) and, while the "Virtual Stick" page is open, exposes three LAN-facing services that let ground-station code control the drone without touching physical sticks: **HTTP on 8080** (commands), **TCP on 8081** (20 Hz JSON telemetry), **RTSP on 8554** (video).

This fork adds a browser-facing webapp (`GroundStation/WebServer/`) so an operator can fly the drone from a web UI instead of the physical RC.

Upstream paper: Rolland et al., *WildBridge* (RiTA 2025). EU Horizon Europe funded (WildDrone project).

## Repo layout

- `WildBridgeApp/` — Android app (Kotlin + DJI Mobile SDK V5). Contains **three parallel module trees with near-duplicate code**:
  - `android-sdk-v5-as/` — the project the README tells you to open in Android Studio and deploy.
  - `android-sdk-v5-sample/` — sample implementations, has its own `VirtualStickFragment.kt` and `DroneController.kt`.
  - `android-sdk-v5-uxsdk/` — reusable UI library.
  - Before editing any Kotlin, confirm which tree is live. Upstream appears to author changes in both `android-sdk-v5-as` and `android-sdk-v5-sample/src/main/java/dji/sampleV5/aircraft/`.
- `GroundStation/Python/djiInterface.py` — **canonical HTTP + TCP client**. Wraps every command and telemetry field the RC exposes. Reuse it; do not reimplement the protocol.
- `GroundStation/ROS/` — ROS 2 Humble wrapper that publishes telemetry as topics and exposes commands as services.
- `GroundStation/WebServer/` — FastAPI + vanilla-JS webapp (added in this fork). Browser-facing: virtual-stick control over a WebSocket + live MJPEG video re-streamed from the RC's RTSP feed. See `GroundStation/WebServer/README.md`.

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

### Web backend (this fork)
```bash
cd GroundStation/WebServer
python -m venv .venv && source .venv/bin/activate   # PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app --mock                    # dev; generated test-pattern video
python -m app --rc-ip 192.168.1.100     # talk to a real RC (phone or RC Pro)
python -m app --rc-ip ... --no-video    # skip the RTSP broadcaster entirely
```
Serves on `http://localhost:8000` with two tabs: **Control** (on-screen joysticks, takeoff/land/RTH/disable) and **Video** (MJPEG re-stream). Standalone video page at `/video` for popping onto a second monitor.

Architecture in one diagram:
```
browser ──HTTP/WS──► FastAPI (:8000) ──HTTP──► RC/phone (:8080)  commands
                                    ──RTSP──► RC/phone (:8554)   video (decoded, re-encoded to MJPEG, fanned out)
```
Core Python modules under `app/`: `drone_client.py` (Live/Mock, wraps `djiInterface.DJIInterface`), `routes.py` (REST + `/ws/stick` with 500 ms deadman + 20 Hz forward cap, plus `/api/video.mjpg` multipart), `video.py` (Live/Mock broadcaster, OpenCV-driven background thread, single latest-frame slot), `main.py` (app factory + `lifespan` hook), `__main__.py` (argparse). Helper script: `tools/check_video.py` for an RTSP smoke test without the webapp.

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
- The web backend's `LiveVideoBroadcaster` auto-reconnects with exponential backoff (1s → 10s). A `connected: false` in `/api/video/status` usually means the app isn't foregrounded — not a backend bug.
- The webapp's RC-side package name is pinned: `com.dji.sampleV5.aircraft`. That string must match exactly in the DJI developer portal App registration. The keystore (`msdkkeystore.jks`) is NOT in the repo — users generate it themselves with the passwords in `gradle.properties` (`123456` / alias `msdkkeystore`).

## Where NOT to put new code

- Do not add server / webapp code inside `WildBridgeApp/`. That tree is the Android app only.
- Ground-station code — any Python/Node/Go/ROS wrapper — belongs under `GroundStation/`.
