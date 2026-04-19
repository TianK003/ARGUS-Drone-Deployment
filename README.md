<div align="center">
  <img src="WildBridge_icon.png" alt="WildBridge App Icon" width="300" height="300">
</div>

> **WildBridge: Ground Station Interface for Lightweight Multi-Drone Control and Telemetry on DJI Platforms**  
> Part of the [WildDrone Project](https://wilddrone.eu) - European Union's Horizon Europe Research Program

## Overview

WildBridge is an open-source Android application that extends DJI's Mobile SDK V5 to provide accessible telemetry, video streaming, and low-level control for scientific research applications. Running directly on the DJI remote controller, it exposes network interfaces (HTTP and RTSP) over a local area network, enabling seamless integration with ground stations and external research tools.

 
![WildBridge Diagram](https://github.com/WildDrone/WildBridge/blob/main/WildBridgeDiagram.png "WildBridge System Architecture")


## Research and Citation

This work is part of the WildDrone project, funded by the European Union's Horizon Europe Research Program (Grant Agreement No. 101071224). The WildDrone project has also received funding in part from the EPSRC-funded Autonomous Drones for Nature Conservation Missions grant (EP/X029077/1).

**Academic Papers**:
```bibtex
@inproceedings{Rolland2025WildBridge,
  author    = {Edouard Rolland and Kilian Meier and Murat Bronz and Aditya Shrikhande and Tom Richardson and Ulrik Pagh Schultz Lundquist and Anders Christensen},
  title     = {WildBridge: Ground Station Interface for Lightweight Multi-Drone Control and Telemetry on DJI Platforms},
  booktitle = {Proceedings of the 13th International Conference on Robot Intelligence Technology and Applications (RiTA 2025)},
  year      = {2025},
  month = {December},
  publisher = {Springer},
  address   = {London, United Kingdom},
  note      = {In press},
  url       = {https://portal.findresearcher.sdu.dk/en/publications/wildbridge-ground-station-interface-for-lightweight-multi-drone-c},
}
```

### Key Features

- **Real-time AI Vision (SAM 3.1)**: Centralized `VisionDaemon` runs SAM 3.1 round-robin over every connected drone's live frame against a natural-language prompt, stores the last 50 annotated hit-frames, and surfaces every detection (drone, prompt, GPS, SAM-overlaid frame) to the UI via WebSocket fan-out.
- **Detection Dashboard**: Clickable live detection list with per-detection fullscreen lightbox, auto-pinning of every hit on the Leaflet map with hover-preview of the frame, a full-screen expanded detections panel, and transient toast notifications.
- **Edge-Driven Architecture**: Drones join the hub natively via WebSockets and push their own telemetry and video; no manual pre-registration, no server-side RTSP pull.
- **Server-Side Path Allocation**: Dynamic zigzag/sweep sector assignment across the swarm, recomputed whenever a drone joins or leaves to preserve non-overlapping coverage.
- **Real-time Telemetry**: 20 Hz edge-side sampling, 1 Hz dashboard fan-out via `/ws/drones`.
- **Live Swarm Video**: Every connected drone renders as an MJPEG tile; any tile opens full-screen in the same lightbox used for detection frames.
- **Multi-drone Coordination**: Tested concurrent fleets with sub-100 ms command latency inside the edge stack.
- **Cross-platform Integration**: Compatible with standard DJI RC platforms, a Python mock RC (`mock_remote.py`), and the direct-HTTP Python / ROS 2 clients under `GroundStation/`.

## Supported Hardware

### DJI Drones (Mobile SDK V5 Compatible)
- **DJI Mini 3/Mini 3 Pro**
- **DJI Mini 4 Pro**
- **DJI Mavic 3 Enterprise Series**
- **DJI Matrice 30 Series (M30/M30T)**
- **DJI Matrice 300 RTK**
- **DJI Matrice 350 RTK**
- Full list [here](https://developer.dji.com/doc/mobile-sdk-tutorial/en/)

### Remote Controllers
- **DJI RC Pro** - Primary supported controller
- **DJI RC Plus** - Enterprise compatibility
- **DJI RC-N3** - Standard controller (tested with smartphones)

## Performance Characteristics

Based on controlled experiments with consumer-grade hardware:

### Telemetry Performance
- **Latency**: <113ms mean, <290ms 90th percentile (up to 10 drones at 32Hz)
- **Scalability**: Tested up to 10 concurrent drones

### Video Streaming Performance
- **Latency**: 1.4-1.6s (1-4 drones), 1.8-1.9s (5-6 drones)
- **Scalability Limit**: 6 concurrent video streams before degradation
- **Format**: Standard Definition via RTSP
- **Compatibility**: FFmpeg, OpenCV, VLC

## Quick Start

### Prerequisites

1. **Hardware Setup**
   - DJI drone and compatible remote controller
   - Local Wi-Fi network (5GHz recommended)
   - Ground station computer

2. **Software Installation**



#### First, you need to install the WildBridge App on your controller: Step-by-Step Android Installation 

1. **Enable Developer Mode and USB Debugging on your Android Device**
   - Put your Android device in developer mode.
   - Enable USB debugging in developer options.

2. **Install Android Studio**
   - Download and install Android Studio Koala 2024.1.1:
     [Download Android Studio Koala 2024.1.1](https://redirector.gvt1.com/edgedl/android/studio/ide-zips/2024.1.2.13/android-studio-2024.1.2.13-linux.tar.gz)

3. **Clone the WildBridge Repository**
   - Open a terminal and run:
     ```bash
     git clone https://github.com/WildDrone/WildBridge.git
     ```

4. **Open the Project in Android Studio**
   - In Android Studio, select "Open" and choose:
     ```
     WildBridge/WildBridgeApp/android-sdk-v5-as
     ```

5. **Become a DJI developer and get an API key**
   - Register as a DJI developer and get an API key: [https://developer.dji.com/](https://developer.dji.com/)
   - Past your API key in:
     ```
     WildBridge/WildBridgeApp/android-sdk-v5-as/local.properties 
     ```
     ```
     AIRCRAFT_API_KEY="App key"
     ```

5. **Build and Deploy the App**
   - Build the app in Android Studio. Install any prompted dependencies.
   - Deploy the app to your controller.

6. **Start the Server on the Drone Controller**
   - In WildBridge, click "Testing Tools".
   - Open the "Virtual Stick" page.
   - The server is now running. You can send commands, view RTSP videofeed, and retrieve telemetry.

Refer to the code snippets in the Quick Start section for examples of sending commands and retrieving telemetry.


3. **Python GS Dependencies**
   ```bash
   pip install -r GroundStation/Python/requirements.txt
   ```

4. **ROS GS Dependencies**
   ```bash
   pip install -r GroundStation/ROS/requirements.txt
   ```

### Basic Usage

#### 1. Remote Controller Setup
- Connect RC to local Wi-Fi network
- Note the RC's IP address from network settings
- Install and launch WildBridge app
- Navigate to "Testing Tools" -> "Virtual Stick"
- When using control commands, press "Enable Virtual Stick"

#### 2. Ground Station Connection

**Telemetry Access via TCP Socket** (Python):
```python
import socket
import json

rc_ip = "192.168.1.100"  # Your RC IP
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect((rc_ip, 8081))

buffer = ""
while True:
    data = sock.recv(4096).decode('utf-8')
    buffer += data
    while '\n' in buffer:
        line, buffer = buffer.split('\n', 1)
        if line.strip():
            telemetry = json.loads(line)
            print(f"Battery: {telemetry['batteryLevel']}%")
            print(f"Location: {telemetry['location']}")
```

**Video Streaming** (OpenCV):
```python
import cv2

rc_ip = "192.168.1.100"  # Your RC IP
rtsp_url = f"rtsp://aaa:aaa@{rc_ip}:8554/streaming/live/1"
cap = cv2.VideoCapture(rtsp_url)
ret, frame = cap.read()
```

**Control Commands** (HTTP POST):
```python
import requests

rc_ip = "192.168.1.100"  # Your RC IP
# Takeoff
requests.post(f"http://{rc_ip}:8080/send/takeoff")

# Navigate to waypoint with PID control
data = "49.306254,4.593728,20,90"  # lat,lon,alt,yaw
requests.post(f"http://{rc_ip}:8080/send/gotoWPwithPID", data=data)

# DJI Native waypoint mission
waypoints = "49.306,4.593,20; 49.307,4.594,25; 49.308,4.595,20"
requests.post(f"http://{rc_ip}:8080/send/navigateTrajectoryDJINative", data=waypoints)
```

## Web Ground Station (ARGUS Hub)

The **ARGUS Hub** (`GroundStation/WebServer/`) is a unified FastAPI-based command-and-control center for operating drone swarms. It replaces manual fleet management with an **Edge-Driven** paradigm where drones discover and join the Hub automatically.

### Central Pillars
1. **The Modern Dashboard (`/`)**: 
   - A glassmorphic monitoring interface with a live Leaflet map and dynamic video grid.
   - **Real-time Pathing**: The Hub automatically assigns non-overlapping zigzag/sweep patterns to every drone that joins.
   - **Detections Tray**: AI-detected objects appear instantly as notifications with time-stamps and drone IDs.
2. **SAM 3.1 AI Vision (`VisionDaemon`)**:
   - The hub runs a background inference loop that multiplexes incoming video frames through the SAM 3.1 model.
   - Operators can dispatch a "Master Prompt" (e.g., "blue truck" or "person in red jacket") to the entire swarm via the dashboard.
3. **Edge Connectivity**: 
   - Drones connect via `ws://{HUB_IP}:8000/ws/swarm/{uuid}`.
   - Binary video frames are pushed via POST to the Hub's ingest endpoint, while telemetry flows over the persistent socket.

### System Architecture

```mermaid
graph TD
    subgraph Swarm Hub [ARGUS Hub :8000]
        RD[Registry]
        VD[VisionDaemon + SAM 3.1]
        RS[Route Server]
    end

    subgraph Edge Client [Drone / Phone]
        WB[WildBridge App]
        MC[Edge Client / mock_remote]
    end

    Dashboard[Browser Dashboard]

    MC -- "Telemetry + Join (WS)" --> RD
    MC -- "Binary Video (POST)" --> VD
    VD -- "AI Alerts (Memory Queue)" --> RD
    RD -- "State + Alerts (WS)" --> Dashboard
    RS -- "Path Updates (WS)" --> MC
```

### Installation & Startup

#### 1. Setup Environment
```bash
cd GroundStation/WebServer
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # Windows PowerShell (bash: source .venv/bin/activate)
pip install -r requirements.txt
```
*Note: a CUDA GPU is strongly recommended for SAM 3.1. `--cpu` works for dev but runs seconds per frame.*

#### 2. Run the Hub
```bash
python -m app
```
*Flags:*
- `--host HOST` / `--port PORT` — bind address (default `127.0.0.1:8000`).
- `--test` — small 5×5 m patrol paths at 10 m altitude for flight simulations.
- `--cpu` — force SAM onto CPU instead of CUDA GPU 0.

The hub is entirely in-memory; there's no registry file and drones don't need pre-registering. Any running edge client will auto-join.

#### 3. Simulated Multi-Drone Testing
The architecture is edge-driven — drones *push* telemetry and video to the hub — so each simulated drone needs three processes. For one drone:

```bash
# Terminal 1 — the hub
python -m app

# Terminal 2 — fake a DJI RC locally on ports 8082/8083
python client/mock_remote.py --port-http 8082 --port-tcp 8083 --lat 46.0569 --lng 14.5058

# Terminal 3 — the edge agent that bridges the fake RC ↔ hub
python client/aegis_client.py --ip 127.0.0.1 --port-http 8082 --port-tcp 8083
```

For a second simulated drone, run a second `mock_remote.py` on different ports (e.g. `--port-http 8084 --port-tcp 8085 --lat ...`) and a second `aegis_client.py` pointed at it. Each mock grabs the local webcam for video; pass `--image-folder <dir>` on subsequent mocks to sidestep the camera-device lock.

### Dashboard Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Single-page swarm dashboard (map, live camera tiles, detection panel, lightbox, toasts) |
| GET | `/api/health` | Hub liveness + active-drone count |
| GET | `/api/drones` | All drone telemetry snapshots |
| POST | `/api/prompt` | `{prompt}` — set the master SAM 3.1 tracking prompt |
| GET | `/api/detections` | All detection metadata (append-only history, cap 1000) |
| GET | `/api/detections/{id}/image.jpg` | SAM-overlaid JPEG for the detection; 404 once evicted (latest 50 retained) |
| WS | `/ws/drones` | 1 Hz fan-out of telemetry snapshots + new-detection alerts to the dashboard |
| WS | `/ws/swarm/{uuid}` | Edge-client bidirectional channel: join, telemetry, path updates |
| POST | `/api/swarm/{uuid}/video` | Edge-client raw JPEG ingest |
| GET | `/api/swarm/{uuid}/video.mjpg` | Dashboard-facing MJPEG re-stream for tile grid + fullscreen lightbox |

---

### Safety & Overrides
- **Controller Dominance**: Physical RC inputs always override Virtual Stick commands sent by the Hub.
- **RTH Priority**: The Hub is designed to maintain paths relative to the **original ascent point** to ensure drones stay within reliable radio range of their respective operators.
- **Deadman Switch**: The Hub automatically sends hover/neutral commands if an edge connection is lost during flight.


### RTSP smoke test (without the webapp)

`GroundStation/WebServer/tools/check_video.py` verifies the video path end-to-end — opens RTSP, prints reported resolution/FPS, measures actual received FPS, and saves the first decoded frame to `first_frame.png`:

```bash
pip install opencv-python   # if not already installed in the venv
python tools/check_video.py 192.168.1.137
```

### Safety and operational notes

- **Always click "Enable Virtual Stick" first.** The RC ignores `/send/stick` until virtual-stick mode is active.
- **The DISABLE / HARD STOP button** triggers `/send/abortMission` — it's the in-UI kill switch.
- **Deadman:** if the WebSocket closes or falls silent for 500 ms while sticks are non-zero, the backend automatically forwards a zeroed stick command.
- **The physical RC always overrides the webapp** — grab the physical sticks or the RTH button on the RC if anything feels wrong.
- **No auth.** The RC's own HTTP server has no auth either — run on a trusted LAN only.
- **Don't let the phone app background** while flying. Ports 8080 / 8081 / 8554 only exist while the Virtual Stick page is foregrounded. Disable battery-save for the app and keep the screen awake.

## API Reference

### Telemetry Stream (TCP Socket - Port 8081)

Connect to the TCP socket on port 8081 to receive continuous JSON telemetry at 20Hz.

**Telemetry Fields:**
| Field | Description |
|-------|-------------|
| `speed` | Aircraft velocity (x, y, z) |
| `heading` | Compass heading in degrees |
| `attitude` | Pitch, roll, yaw values |
| `location` | GPS coordinates and altitude |
| `gimbalAttitude` | Gimbal orientation |
| `batteryLevel` | Battery percentage |
| `satelliteCount` | GPS satellite count |
| `homeLocation` | Home point coordinates |
| `distanceToHome` | Distance to home in meters |
| `waypointReached` | Waypoint status flag |
| `isRecording` | Camera recording status |
| `flightMode` | Current flight mode (GPS, MANUAL, GO_HOME, etc.) |
| `remainingFlightTime` | Estimated flight time remaining |
| `batteryNeededToGoHome` | Battery % needed for RTH |
| `batteryNeededToLand` | Battery % needed to land |
| `timeNeededToGoHome` | Time to return home (seconds) |
| `maxRadiusCanFlyAndGoHome` | Max flyable radius (meters) |

### Control Endpoints (HTTP POST - Port 8080)

| Endpoint | Description | Parameters |
|----------|-------------|------------|
| `/send/takeoff` | Initiate takeoff | None |
| `/send/land` | Initiate landing | None |
| `/send/RTH` | Return to home | None |
| `/send/gotoWP` | Navigate to waypoint | `lat,lon,alt` |
| `/send/gotoWPwithPID` | Navigate with PID control | `lat,lon,alt,yaw` |
| `/send/gotoYaw` | Rotate to heading | `yaw_angle` |
| `/send/gotoAltitude` | Change altitude | `altitude` |
| `/send/navigateTrajectory` | Follow trajectory (Virtual Stick) | `lat,lon,alt;...;lat,lon,alt,yaw` |
| `/send/navigateTrajectoryDJINative` | DJI native waypoint mission | `lat,lon,alt;lat,lon,alt;...` |
| `/send/abort/DJIMission` | Stop DJI native mission | None |
| `/send/abortMission` | Stop and disable Virtual Stick | None |
| `/send/enableVirtualStick` | Enable Virtual Stick mode | None |
| `/send/stick` | Virtual stick input | `leftX,leftY,rightX,rightY` |
| `/send/camera/zoom` | Camera zoom control | `zoom_ratio` |
| `/send/camera/startRecording` | Start video recording | None |
| `/send/camera/stopRecording` | Stop video recording | None |
| `/send/gimbal/pitch` | Gimbal pitch control | `roll,pitch,yaw` |
| `/send/gimbal/yaw` | Gimbal yaw control | `roll,pitch,yaw` |

### Status Endpoints (HTTP GET - Port 8080)

| Endpoint | Description |
|----------|-------------|
| `/status/waypointReached` | Check if waypoint reached |
| `/status/intermediaryWaypointReached` | Check intermediary waypoint |
| `/status/yawReached` | Check if target yaw reached |
| `/status/altitudeReached` | Check if target altitude reached |
| `/status/camera/isRecording` | Check recording status |

### Legacy Telemetry Endpoints (HTTP GET - Port 8080)

These endpoints are available for backward compatibility. For continuous telemetry, use the TCP socket on port 8081.

| Endpoint | Description |
|----------|-------------|
| `/` | Connection test |
| `/aircraft/allStates` | Complete telemetry package (JSON) |
| `/aircraft/speed` | Aircraft velocity |
| `/aircraft/heading` | Compass heading |
| `/aircraft/attitude` | Pitch, roll, yaw |
| `/aircraft/location` | GPS coordinates and altitude |
| `/aircraft/gimbalAttitude` | Gimbal orientation |
| `/home/location` | Home point coordinates |

### Video Streaming
- **RTSP URL**: `rtsp://aaa:aaa@{RC_IP}:8554/streaming/live/1`
- **Format**: H.264, Standard Definition
- **Latency**: 1.4-1.9 seconds (depending on network)

## Project Structure

```
WildBridge/
├── GroundStation/                      # Ground Control System (GS)
│   ├── Python/                         # Python GS
│   │   └── djiInterface.py             # Full DJI communication API
│   └── ROS/                            # ROS 2 integration
│       ├── dji_controller/             # Main drone control package
│       ├── drone_videofeed/            # RTSP video streaming package
│       └── wildview_bringup/           # Launch configuration
└── WildBridgeApp/                      # Android application
    ├── android-sdk-v5-as/              # Main app project
    ├── android-sdk-v5-sample/          # Sample implementations
    └── android-sdk-v5-uxsdk/           # UI components
```

### ROS 2 Integration

WildBridge includes a complete ROS 2 implementation developed using **ROS Humble**, demonstrating how WildBridge HTTP requests can be seamlessly integrated into robotics applications.

#### Features
- **Multi-drone Support**: Simultaneous control of multiple DJI drones
- **Real-time Telemetry**: Publishing drone states as ROS topics
- **RTSP Video Streaming**: Live video feed integration with ROS Image messages
- **Command Interface**: ROS service calls for drone control
- **Dynamic Discovery**: Automatic drone detection via MAC address lookup

#### Package Structure
```
GroundStation/ROS/
├── dji_controller/          # Main drone control package
│   ├── controller.py        # ROS node for drone commands and telemetry
│   └── dji_interface.py     # HTTP interface wrapper
├── drone_videofeed/         # RTSP video streaming package
│   └── rtsp.py             # Video feed ROS node
└── wildview_bringup/        # Launch configuration
    └── swarm_connection.launch.py  # Multi-drone launch file
```

#### ROS Topics

**Published Topics** (per drone):
- `/drone_N/speed` - Current velocity magnitude
- `/drone_N/location` - GPS coordinates (NavSatFix)
- `/drone_N/attitude` - Pitch, roll, yaw
- `/drone_N/battery_level` - Battery percentage
- `/drone_N/video_frames` - Live camera feed (Image)

**Subscribed Topics** (commands):
- `/drone_N/command/takeoff` - Takeoff command
- `/drone_N/command/goto_waypoint` - Navigate to coordinates
- `/drone_N/command/gimbal_pitch` - Gimbal control

#### Usage Example
```bash
# Launch multi-drone system
ros2 launch wildview_bringup swarm_connection.launch.py

# Send takeoff command
ros2 topic pub /drone_1/command/takeoff std_msgs/Empty

# Navigate to waypoint [lat, lon, alt, yaw]
ros2 topic pub /drone_1/command/goto_waypoint std_msgs/Float64MultiArray "{data: [49.306254, 4.593728, 20.0, 90.0]}"

# Monitor telemetry
ros2 topic echo /drone_1/location
```

This ROS2 implementation showcases how WildBridge's HTTP API can be wrapped for integration with existing robotics frameworks, enabling seamless multi-drone coordination in research applications.

## Scientific Applications

WildBridge has been validated in multiple research domains:

- **Wildlife Conservation**: Real-time animal detection and geolocation
- **Wildfire Detection**: Early fire detection and mapping
- **Atmospheric Research**: Wind field profiling and measurement
- **Multi-drone Coordination**: Swarm-based data collection
- **Conservation Monitoring**: Long-term ecosystem studies

## Limitations and Considerations

### Technical Limitations
- **Video Scalability**: Maximum 6 concurrent video streams
- **Telemetry Rate**: Optimal performance up to 32Hz request rate
- **Synchronization**: Video and telemetry streams are not synchronized
- **SDK Dependency**: Relies on DJI Mobile SDK V5 evolution

### Operational Considerations
- **Setup Time**: Multi-drone configurations require network setup
- **Environmental Factors**: Performance affected by Wi-Fi interference
- **Data Synchronization**: Post-mission data alignment requires planning

## Troubleshooting

### Common Issues

**Connection Problems**:
- Verify RC IP address in network settings
- Ensure WildBridge app is running (Virtual Stick page open)
- For telemetry: connect to TCP port 8081
- For commands: use HTTP POST to port 8080

**Video Stream Issues**:
- Test RTSP URL in VLC: `rtsp://aaa:aaa@{RC_IP}:8554/streaming/live/1` (Open Network Protocol, Ctrl+N)
- Check network bandwidth for multiple streams
- Verify firewall settings on ground station

**Waypoint Navigation Issues**:
- If you send a drone to a waypoint but it does not move, ensure that Virtual Stick is enabled. You can enable Virtual Stick in the DJI App or send a command to enable it. Once enabled, the drone should be able to move to the waypoint.

### Debug Commands
```bash
# Test connectivity
ping {RC_IP}

# Test video stream
vlc rtsp://aaa:aaa@{RC_IP}:8554/streaming/live/1

# Monitor telemetry (TCP stream)
nc {RC_IP} 8081

# Check waypoint status
curl http://{RC_IP}:8080/status/waypointReached

# Send takeoff command
curl -X POST http://{RC_IP}:8080/send/takeoff
```

## License

This project is licensed under the MIT License - see the [LICENSE.txt](LICENSE.txt) file for details.

## Contributing

Contributions are welcome! Please reach out!

1. **Bug Reports**: Use GitHub issues with reproduction steps
2. **Feature Requests**: Describe use case and scientific application

For questions or collaboration inquiries, please contact the WildDrone consortium at [https://wilddrone.eu](https://wilddrone.eu).
