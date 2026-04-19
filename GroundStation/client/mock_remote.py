"""
Mock DJI Remote Emulator
Emulates the WildBridge Android app behavior over TCP and HTTP so that
`aegis_client.py` can be tested locally without physical DJI hardware.
"""

import argparse
import asyncio
import json
import socket
import threading
import time
import math
from contextlib import asynccontextmanager

import cv2
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse

# Global hardware lock so client reconnects don't crash Windows camera drivers
global_cap_obj = None
global_cap_lock = threading.Lock()

def get_global_cap():
    global global_cap_obj
    with global_cap_lock:
        if global_cap_obj is None:
            global_cap_obj = cv2.VideoCapture(0)
        return global_cap_obj

# ── Global State ────────────────────────────────────────────────────────

class MockState:
    def __init__(self, lat: float, lng: float, alt: float):
        self.lat = lat
        self.lng = lng
        self.alt = alt
        self.home_lat = lat
        self.home_lng = lng
        self.battery = 100
        self.target_waypoints = []
        self.is_flying = False
        
        self.lock = threading.Lock()

    def get_telemetry_dict(self):
        with self.lock:
            return {
                "location": {
                    "latitude": self.lat,
                    "longitude": self.lng,
                    "altitude": self.alt
                },
                "batteryLevel": self.battery,
                "satelliteCount": 12, # Emulate GPS lock
                "homeLocation": {
                    "latitude": self.home_lat,
                    "longitude": self.home_lng
                },
                "flightMode": "MOCK_FLIGHT" if self.is_flying else "IDLE"
            }
            
    def set_waypoints(self, waypoints):
        with self.lock:
            self.target_waypoints = waypoints
            if waypoints:
                self.is_flying = True

# Parse args before initializing state
parser = argparse.ArgumentParser(description="DJI Mock Remote")
parser.add_argument("--lat", type=float, default=46.0569, help="Initial mock latitude")
parser.add_argument("--lng", type=float, default=14.5058, help="Initial mock longitude")
parser.add_argument("--port-http", type=int, default=8080)
parser.add_argument("--port-tcp", type=int, default=8081)
args = parser.parse_args()

STATE = MockState(lat=args.lat, lng=args.lng, alt=0.0)

# ── Flight Interpolation ────────────────────────────────────────────────

def flight_controller_loop():
    """Background thread that smoothly moves the mock GPS coordinate towards the active waypoint."""
    SPEED = 0.00005 # Degrees per tick (approx 5m)
    
    while True:
        time.sleep(0.5)
        
        with STATE.lock:
            if not STATE.is_flying or not STATE.target_waypoints:
                STATE.is_flying = False
                continue
                
            # Grab current target
            target = STATE.target_waypoints[0]
            t_lat = target['lat']
            t_lng = target['lng']
            
            d_lat = t_lat - STATE.lat
            d_lng = t_lng - STATE.lng
            dist = math.hypot(d_lat, d_lng)
            
            if dist < SPEED:
                # Reached waypoint
                STATE.lat = t_lat
                STATE.lng = t_lng
                STATE.target_waypoints.pop(0)
            else:
                # Move towards waypoint
                STATE.lat += (d_lat / dist) * SPEED
                STATE.lng += (d_lng / dist) * SPEED
                
            # Deplete battery slowly for realism
            if STATE.battery > 5:
                STATE.battery -= 0.01

# ── TCP Telemetry Server (Port 8081) ────────────────────────────────────

def tcp_server_loop():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("0.0.0.0", args.port_tcp))
    sock.listen(5)
    print(f"[TCP] Telemetry server listening on 0.0.0.0:{args.port_tcp}")
    
    while True:
        client, addr = sock.accept()
        print(f"[TCP] Client connected: {addr}")
        def handle_client(c):
            try:
                while True:
                    telemetry = STATE.get_telemetry_dict()
                    payload = json.dumps(telemetry) + "\n"
                    c.sendall(payload.encode('utf-8'))
                    time.sleep(0.5)
            except (ConnectionResetError, BrokenPipeError):
                pass
            finally:
                c.close()
                print(f"[TCP] Client disconnected: {addr}")
                
        threading.Thread(target=handle_client, args=(client,), daemon=True).start()

# ── FastAPI Command Server (Port 8080) ──────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background threads on boot
    threading.Thread(target=tcp_server_loop, daemon=True).start()
    threading.Thread(target=flight_controller_loop, daemon=True).start()
    yield

app = FastAPI(lifespan=lifespan)

@app.post("/send/navigateTrajectory")
async def nav_traj(request: Request):
    """Intercepts djiInterface waypoint string and updates target_waypoints"""
    body_bytes = await request.body()
    try:
        body = body_bytes.decode('utf-8')
        segments = body.split(';')
        
        waypoints = []
        for segment in segments:
            parts = segment.split(',')
            if len(parts) >= 2:
                waypoints.append({
                    "lat": float(parts[0]), 
                    "lng": float(parts[1])
                })
                
        print(f"[HTTP] Received Trajectory with {len(waypoints)} waypoints.")
        STATE.set_waypoints(waypoints)
        return Response(content="SUCCESS")
    except Exception as e:
        print(f"[HTTP] Error parsing trajectory: {e}")
        return Response(content="ERROR", status_code=400)


@app.post("/send/enableVirtualStick")
async def enable_vs():
    return Response(content="SUCCESS")

@app.get("/video")
async def mjpeg_webcam():
    """Streams local webcam via OpenCV as MJPEG"""
    def gen():
        cap = get_global_cap()
        
        # Test if camera opened
        if not cap.isOpened():
             # If camera failed, fallback to a dummy image generator so the client doesn't crash
             while True:
                 import numpy as np
                 img = np.zeros((480, 640, 3), dtype=np.uint8)
                 cv2.putText(img, "Mock Camera Failed", (50, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 2)
                 _, buffer = cv2.imencode('.jpg', img)
                 yield (b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n")
                 time.sleep(1.0)
             return

        try:
            while True:
                with global_cap_lock:
                    ret, frame = cap.read()
                if not ret:
                    time.sleep(0.1)
                    continue
                # Compress slightly for network speed
                _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 65])
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n")
                time.sleep(0.1) # Max ~10FPS to save bandwidth
        except Exception:
            pass # Client disconnected, generator terminates safely

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")


if __name__ == "__main__":
    print(f"Booting Mock DJI Remote at {args.lat}, {args.lng}")
    uvicorn.run(app, host="0.0.0.0", port=args.port_http, log_level="warning")
