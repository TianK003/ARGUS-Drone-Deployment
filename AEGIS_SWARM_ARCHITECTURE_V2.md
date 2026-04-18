# Project: Aegis Swarm Middleware - Architecture & Specifications 

**Objective:** Create a distributed drone orchestration platform that leverages third-party hardware (DJI) to form a unified, autonomous surveillance swarm powered by **Meta SAM 3**.

---

## 1. The Prototyping Phase \& Knowledge Base

The final architecture builds upon three successful proof-of-concept branches:

1. **`sam` branch (Vision Engine):** Demonstrated real-time object segmentation and detection using Meta's SAM 3 model operating on a camera feed.
2. **`koordinate` branch (Orchestrator \& Dashboard):** Prototyped the swarm coordination algorithm, dynamic pathing assignment, and a live map-based tracker dashboard.
3. **`nace` branch (Streaming):** Validated the mechanism for capturing live video footage from the edge client and streaming it over the network to the central server.

---

## 2. System Architecture \& Data Flow

The system operates across two main environments: **The Edge (Client)** and **The Hub (Central Server)**.

### A. The Edge Client (Drone Proxy)
* **Hardware:** Local computer connected to a DJI Controller via USB.
* **Responsibilities:**
  * Extracts H.264/H.265 live video feed and streams it continuously to the server.
  * Transmits live telemetry data (GPS coordinates, battery status).
  * Receives pathing instructions (waypoints) from the central server and executes them autonomously.
* **Network Behavior:** No heavy processing is done here. It simply acts as a dumb pipe for I/O to bypass edge compute limits.

### B. The Hub (Central Server)
* **Orchestration \& Pathing:** 
  * Receives all incoming GPS connections.
  * Dynamically calculates and assigns patrol paths to each connected drone, ensuring non-overlapping optimal coverage (inspired by the `koordinate` prototype).
* **The Intelligence Loop (SAM Inference):**
  * The server runs a continuous **Round-Robin Processing Loop**. 
  * It cycles through all active drone streams, taking the *latest single frame* from Drone 1, feeding it into SAM 3 to check against the active text prompt, then moving to Drone 2, and so on.
  * This prevents the GPU from being overwhelmed by simultaneous video streams while maintaining near-real-time coverage across the swarm.

---

## 3. The Admin Dashboard (UI/UX Design)

The Control Center is a web-based dashboard strictly for the System Admin. The interface is highly optimized for situational awareness and is vertically split across the screen:

### Left Panel (Skinny - 30% Width)
Stacked vertically into three dedicated interaction modules:
1. **Prompt Command (Top):** An input field where the Admin enters the natural language descriptor for SAM 3 (e.g., "red hatchback" or "lost hiker").
2. **Alerts Feed (Middle):** A chronological feed of successful detections. When a drone detects the prompted object, a notification appears here with a snippet/timestamp. *Clicking expands this section to full screen.*
3. **Swarm Roster (Bottom):** A list of all actively connected drones, displaying health stats (Battery, Signal, Current Task). *Clicking expands this section to full screen.*

### Right Panel (Wide - 70% Width)
* **The Tactical Map:** A live, interactive geographical map displaying the positions of all drones, their assigned paths, and coverage areas (from the `koordinate` logic). 
* **Alert Pins:** When SAM detects a target, the GPS coordinate of that specific frame is permanently pinned on this map.

---

## 4. Required Tech Stack & Tools

To accomplish this effectively, particularly managing real-time video and orchestration, we need to utilize the following stack (including necessary tools required for production that weren't in the initial plan):

### Core Tools (Already Planned)
* **Python (Client/Server Backend):** For edge scripting, backend logic, and SAM 3 integration.
* **Meta SAM 3 (Segment Anything):** For zero-shot visual detection based on text prompts.
* **DJI SDK / PyDJI:** For interfacing and pulling data from the controller.

### Missing/Recommended Tools (Crucial for Networking & UI)
* **WebRTC or GStreamer (Video Transport):**
  * *Why:* Standard TCP/HTTP streaming (like typical Flask setups) introduces massive latency (2-5 seconds). For drone piloting and accurate SAM detection, we need sub-500ms latency. WebRTC (via `aiortc` in Python) is the gold standard here.
* **WebSockets / Socket.io:**
  * *Why:* For sending real-time telemetry (GPS) and receiving Koordinate pathing commands instantly without the overhead of HTTP polling. 
* **Redis / ZeroMQ (In-Memory Queue):**
  * *Why:* To handle the Round-Robin SAM architecture. Drones will write their "latest frame" into an ephemeral memory buffer, and the SAM loop will read the most recent frame directly from memory. This prevents memory leaks and backlog pileups.
* **Leaflet.js or Mapbox GL JS (Frontend Map):**
  * *Why:* High-performance mapping libraries that can easily draw custom polygons, live moving markers (drones), and dynamic paths without lagging the browser.
* **FastAPI (Python Web Framework):**
  * *Why:* Much faster and inherently asynchronous compared to Flask, making it ideal for juggling multiple WebSocket connections for the swarm simultaneously.

---

## 5. Complete Technical Implementation Specification

This section provides the blueprint for the AI agents driving the final implementation. The architecture utilizes Python and FastAPI on the Hub Server, with a Python-based client connecting to the DJI remote.

### A. Central Dispatch & Drone Lifecycle
*   **Connection Handshake:** The Client (connected to the DJI controller via USB) connects to the Hub Server via a FastAPI WebSocket. 
*   **Registration & Telemetry:** The server registers the new drone ID and begins listening for continuous state/telemetry updates. The Client starts the telemetry stream and posts to the server using `djiInterface.py`.
    ```python
    dji = DJIInterface(IP_RC)
    dji.startTelemetryStream()
    # The telemetry dictionary contains: speed, heading, attitude, location (GPS), batteryLevel, etc.
    telemetry = dji.getTelemetry() 
    ```
*   **Center of Operations:** Upon receiving the first telemetry packet with a valid GPS `location` (`getHomeLocation()`), the server records the controller's coordinates as the center of operation.
*   **Disconnection:** If the WebSocket closes or a heartbeat timeout occurs, the Hub deregisters the drone and immediately removes it from the Dashboard UI.

### B. Dynamic Pathing Engine (Koordinate Logic)
*   **Mathematical Routing:** Based on the Center of Operation and the total connected drones, the Server dynamically computes non-overlapping, localized patrol paths (arrays of lat/lon/alt waypoints) radiating outward.
*   **Execution Delivery:** The server issues these waypoints to the Client. The Client then uses the DJI Native HTTP POST command endpoints to push the trajectory to the drone.
    ```python
    # Example execution from Client to Drone
    dji.requestSendNavigateTrajectory(waypoints, finalYaw)
    # OR using native DJI speeds
    dji.requestSendNavigateTrajectoryDJINative(waypoints, speed=10.0)
    ```

### C. Edge Video Streaming
*   **Stream Source:** The Client extracts the live video feed directly from the DJI drone's RTSP endpoint.
    ```python
    videoSource = f"rtsp://aaa:aaa@{IP_RC}:8554/streaming/live/1"
    cap = cv2.VideoCapture(videoSource)
    ```
*   **Transport Mode:** Frames are read sequentially. They are encoded as JPEGs or via WebRTC strings, and pushed efficiently to the FastAPI server using WebSockets (as mocked in `web_server.py`). The Edge Client does *no* AI inference.

### D. SAM Detection Pipeline (Round-Robin)
*   **In-Memory Buffer:** The FastAPI server maintains a global dictionary thread-safe buffer (`latest_frames[drone_id]`) holding only the absolute latest frame from each active drone to prevent memory leaks and lag.
*   **Processing Loop:** A background thread iterates through `latest_frames`. It passes the frame to `SAM3SemanticPredictor` (or `Falcon-Perception`) along with the Admin's master prompt.
    ```python
    # Pseudocode for the Hub Server round-robin loop
    for drone_id, frame_bytes in latest_frames.items():
        frame = cv2.imdecode(np.frombuffer(frame_bytes, np.uint8), cv2.IMREAD_COLOR)
        # Pad/Resize for SAM 3 requirements
        h, w = frame.shape[:2]
        frame = cv2.resize(frame, ((w // 32) * 32, (h // 32) * 32))

        predictor.set_image(frame)
        results = predictor(text=[master_prompt])
        if results and object_detected(results):
            trigger_alert(drone_id, frame)
    ```
*   **Alert Generation:** When an object is detected, the server takes the drone's current `location` (lat, lon, altitude) from its telemetry state, computes the FOV geographic center based on gimbal pitch/yaw (`getGimbalAttitude()`), and fires an alert event.

### E. Admin Dashboard UI
*   **FastAPI Backend:** Uses `uvicorn` and FastAPI's `WebSocketEndpoint` to serve the UI and manage the asynchronous bi-directional communication.
*   **Multi-Pane Interface:** Displaying a frontend map (e.g., Leaflet.js or Mapbox GL JS) that plots:
    1. The Center of Operation.
    2. Active Drones (moving dynamically based on WebSocket telemetry broadcasts).
    3. Assigned polygon paths.
    4. SAM Alert Pins (permanent markers where a detection was confirmed).
*   **Dynamic Video Grid:** A visual grid displaying the continuous feed (or annotated inference feed) from all connected drones, dynamically rendering and removing HTML video/canvas tiles as drones connect/disconnect.
