# Project: Aegis Swarm Middleware - Architecture & Specifications 

**Objective:** Create a distributed drone orchestration platform that leverages third-party hardware (DJI) to form a unified, autonomous surveillance swarm powered by **Meta SAM 3**.

---

## 1. System Architecture & Data Flow (Edge-Driven Paradigm)

The system operates across two main environments: **The Edge (Client)** and **The Hub (Central Server)**. Unlike traditional master-slave architectures, the Server is **passive**. It does not dictate which clients can join or manage RC IPs directly. Instead, all connection logic originates from the Edge Client.

### A. The Edge Client (Drone Proxy)
* **What it is:** A standalone Python script (e.g. `aegis_client.py`) running on a local computer connected to a DJI Controller via USB.
* **Responsibilities:**
  * **Joining:** On startup, it grabs the DJI controller's GPS coordinate and independently sends a `POST` request to the Hub to join the swarm.
  * **Video:** Extracts H.264/H.265 live video and continuously `POST`s (or WebSockets) frames to the Hub.
  * **Telemetry:** Continuously `POST`s live telemetry (GPS, battery) bounding data to the Hub.
  * **Mission Execution:** Receives its localized patrol path upon joining, and natively pushes it to the DJI controller to execute. On termination, the edge client fires a Return-To-Home sequence and leaves the swarm API.

### B. The Hub (Central Server)
* **Orchestration & Pathing:** 
  * Exposes simple REST API endpoints (`/api/swarm/...`) for drones to self-register.
  * When a drone joins with its starting GPS coordinate, the server calculates an optimal, non-overlapping patrol path radiating out from that point, and returns it in the HTTP response.
* **The Intelligence Loop (SAM Inference):**
  * The server runs a continuous **Round-Robin Processing Loop**. 
  * It maintains a single memory buffer storing the *latest received frame* from each connected drone. 
  * The loop cycles through these buffers, feeding them into SAM 3 to check against the active text prompt.

---

## 2. The Admin Dashboard (UI/UX Design)

The dashboard is strictly a **visualization layer**. It cannot force drones to connect or dictate IP addresses. It natively streams everything the Server is receiving.

### Single Unified View
* **The Tactical Map:** A live map (Leaflet or Mapbox) plotting:
  * The Center of Operations (extracted from the first drone's join coordinate).
  * The live, moving markers for every drone (updated dynamically via the Server relaying the telemetry POSTs).
  * The mathematically assigned target paths for situational awareness.
* **Global Prompt Command:** A simple input bar where the Admin types the target object (e.g., "red hatchback").
* **Alert Pins:** When SAM detects a target on a specific drone's frame, the geospatial coordinate of that detection is permanently pinned on the Tactical Map.

---

## 3. Required Tech Stack & Tools

To accomplish this seamlessly driven by the Edge Client, the framework requires:

### Client-Side Engine
* **Python (`aegis_client.py`):** Handling multithreaded push loops.
* **DJI SDK / PyDJI (`djiInterface.py`):** Reading states and controlling trajectories natively via HTTP/TCP on the remote.

### Hub Server & Intelligence
* **FastAPI:** To provide the lightning-fast, asynchronous REST API infrastructure required to process hundreds of tiny telemetry `POST` requests per minute.
* **Meta SAM 3 / Falcon-Perception:** Visual detection engine.
* **In-Memory Cache (e.g., Redis or Global Dictionary):** Crucial for preventing massive memory-leaks. The server must discard frames aggressively and only keep the absolute newest JPEG posted by an Edge Client for the Round-Robin loop.

---

## 4. Technical Blueprint for API Architecture

For the AI Agents developing the final Server codebase, you must implement these specific endpoints to support the Edge-driven `aegis_client.py`:

*   **`POST /api/swarm/join`**: 
    *   **Accepts:** `{ "id": "drone-x", "homeLocation": {"latitude": ..., "longitude": ...} }`
    *   **Returns:** JSON array with the dynamically generated `waypoints` and `finalYaw` for the pathing.
*   **`POST /api/swarm/{uuid}/telemetry`**: 
    *   **Accepts:** Full JSON telemetry snapshot directly from the drone's sensors. The server updates the UI immediately.
*   **`POST /api/swarm/{uuid}/video`**: 
    *   **Accepts:** A raw `image/jpeg` byte payload representing the absolute latest frame. *(Note: To be upgraded to WebSockets or WebRTC natively once stability is verified).*
*   **`DELETE /api/swarm/{uuid}/leave`**: 
    *   Deregisters the drone from the swarm, freeing up memory limits and removing it from the Dashboard.
