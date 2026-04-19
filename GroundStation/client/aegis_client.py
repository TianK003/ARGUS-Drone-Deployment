import sys
import os
import time
import json
import uuid
import threading
import requests
import cv2
import math
import websocket

# Ensure we can import the DJIInterface from the GroundStation module
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.append(os.path.join(project_root, "GroundStation", "Python"))

try:
    from djiInterface import DJIInterface
except ImportError:
    print("Error: Could not import DJIInterface. Please ensure it exists in GroundStation/Python/")
import argparse

# Global Configuration
SERVER_URL = "http://127.0.0.1:8000"
WS_URL = SERVER_URL.replace("http://", "ws://").replace("https://", "wss://")
IP_RC = "10.102.252.30"
PORT_HTTP = 8080
PORT_TCP = 8081
WS_URL = SERVER_URL.replace("http://", "ws://").replace("https://", "wss://")
IP_RC = "10.102.252.30"
DRONE_ID = f"drone-{str(uuid.uuid4())[:8]}"

# State flags
is_running = True
has_started_mission = False

# Dynamic state variables controlled by Hub
current_trajectory = []
final_yaw = 0
target_altitude = 200.0
path_ready_event = threading.Event()
ws_app: websocket.WebSocketApp = None
dji: DJIInterface = None

def push_telemetry_loop():
    """Continuously push telemetry data to the central server via WebSocket."""
    global is_running, ws_app
    while is_running:
        if ws_app and ws_app.sock and ws_app.sock.connected:
            telemetry = dji.getTelemetry()
            if telemetry:
                try:
                    payload = {"action": "telemetry", "data": telemetry}
                    ws_app.send(json.dumps(payload))
                except Exception:
                    pass
        time.sleep(1.0) # 1Hz update rate

def push_video_loop():
    """Continuously fetch RTSP frames and POST them to the server."""
    global is_running, has_started_mission
    
    # Wait until mission starts to save bandwidth
    while is_running and not has_started_mission:
        time.sleep(0.5)
        
    if not is_running: return
        
    video_source = dji.getVideoSource()
    if not video_source:
        print("Warning: No video source available.")
        return
        
    cap = cv2.VideoCapture(video_source)
    url = f"{SERVER_URL}/api/swarm/{DRONE_ID}/video"
    
    fail_count = 0
    while is_running:
        ret, frame = cap.read()
        if not ret:
            fail_count += 1
            if fail_count > 10:
                print("[Video Thread] Stream lost. Reconnecting to video source...")
                cap.release()
                time.sleep(1)
                cap = cv2.VideoCapture(video_source)
                fail_count = 0
            else:
                time.sleep(0.1)
            continue
            
        fail_count = 0
        _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
        
        try:
            # Video intentionally stays on HTTP POST to avoid clogging the text-based WS socket
            requests.post(url, data=buffer.tobytes(), headers={'Content-Type': 'image/jpeg'}, timeout=1)
        except requests.RequestException:
            pass
            
    cap.release()

def on_ws_message(ws, message):
    global current_trajectory, final_yaw, target_altitude
    data = json.loads(message)
    
    if data.get("action") == "path_update":
        path = data.get("waypoints", [])
        final_yaw = data.get("finalYaw", 0)
        target_altitude = float(data.get("targetAltitude", 200.0))
        
        print(f"\n[Hub] Received dynamic path update with {len(path)} waypoints (Alt: {target_altitude}m).")
        
        new_traj = [(p["lat"], p.get("lon", p.get("lng")), target_altitude) for p in path]
        current_trajectory = new_traj
        
        if not has_started_mission:
            path_ready_event.set()
        elif current_trajectory:
            # Dynamically divert the drone mid-flight
            print(">> Replanning active flight path...")
            try:
                dji.requestSendNavigateTrajectory(current_trajectory, final_yaw)
            except Exception as e:
                print(f"Failed to redirect drone: {e}")

def on_ws_error(ws, error):
    pass

def on_ws_close(ws, close_status_code, close_msg):
    print("\n[WS] Disconnected from Hub.")

def on_ws_open(ws):
    print("[WS] Connected to Hub. Sending location...")
    # Send Join Request
    home_location = dji.getTelemetry().get("location")
    if not home_location or not (home_location.get("latitude") or home_location.get("lat")):
        home_location = {"latitude": 46.0569, "longitude": 14.5058, "altitude": 0}
        
    join_msg = {
        "action": "join",
        "homeLocation": home_location
    }
    ws.send(json.dumps(join_msg))

def start_websocket():
    global ws_app
    ws_app = websocket.WebSocketApp(
        f"{WS_URL}/ws/swarm/{DRONE_ID}",
        on_open=on_ws_open,
        on_message=on_ws_message,
        on_error=on_ws_error,
        on_close=on_ws_close
    )
    ws_app.run_forever()

def main():
    global is_running, has_started_mission, dji, current_trajectory
    
    print(f"[{DRONE_ID}] Initializing connection to DJI Remote at {IP_RC}:{PORT_HTTP}...")
    dji = DJIInterface(IP_RC, port_http=PORT_HTTP, port_tcp=PORT_TCP)
    dji.startTelemetryStream()
    
    print("Waiting for GPS lock...")
    # Wait until we get a valid GPS fix
    for _ in range(30):
        telemetry = dji.getTelemetry()
        if telemetry and "location" in telemetry and telemetry["location"]:
            loc = telemetry["location"]
            if isinstance(loc, dict) and (loc.get("latitude") or loc.get("lat")):
                 break
        time.sleep(1)
        
    print("Starting WebSocket Client...")
    threading.Thread(target=start_websocket, daemon=True).start()
    
    # Block until the server gives us a path
    print("Waiting for Hub to assign patrol region...")
    if not path_ready_event.wait(timeout=10.0):
        print("Failed to receive initial assigned path from server. Exiting.")
        is_running = False
        dji.stopTelemetryStream()
        sys.exit(1)

    input(">>> Setup Complete. Press ENTER to start mission and follow path... <<<")
    has_started_mission = True
    
    # Start the telemetry background thread
    threading.Thread(target=push_telemetry_loop, daemon=True).start()
    threading.Thread(target=push_video_loop, daemon=True).start()
    
    print("Mission Started. Pushing dual streams...")
    
    try:
        print(f"Taking off and ascending to {target_altitude}m...")
        try:
            dji.requestSendTakeOff()
            time.sleep(3)
            dji.requestSendGotoAltitude(target_altitude)
            time.sleep(2)
        except Exception as e:
            print(f"Failed to execute takeoff: {e}")

        if current_trajectory:
            print("Sending initial trajectory to Drone...")
            try:
                dji.requestSendNavigateTrajectory(current_trajectory, final_yaw)
            except Exception as e:
                print(f"Failed to send trajectory: {e}")
                
            def get_distance(lat1, lon1, lat2, lon2):
                R = 6371e3
                d_lat = math.radians(lat2 - lat1)
                d_lon = math.radians(lon2 - lon1)
                a = math.sin(d_lat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon/2)**2
                return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

            while True:
                time.sleep(2)
                
                bat = dji.getBatteryLevel()
                if 0 < bat < 20: 
                    print(f"CRITICAL: Battery low ({bat}%). Aborting patrol.")
                    break
                    
                loc = dji.getLocation()
                if loc and loc.get("latitude") and loc.get("longitude") and current_trajectory:
                    lat = loc["latitude"]
                    lon = loc["longitude"]
                    
                    target_lat = current_trajectory[-1][0]
                    target_lon = current_trajectory[-1][1]
                    
                    dist = get_distance(lat, lon, target_lat, target_lon)
                    if dist < 0.5:
                        print(f"Reached end of path segment (Dist: {dist:.1f}m). Reversing...")
                        current_trajectory = current_trajectory[::-1]
                        time.sleep(2)
                        try:
                            dji.requestSendNavigateTrajectory(current_trajectory, final_yaw)
                        except Exception as e:
                            print(f"Failed to send reversed trajectory: {e}")
                            break
        else:
            print("Warning: Received empty path from server. Holding position.")
            while True:
                time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nShutdown signal received (Ctrl+C). Executing safe termination...")
    finally:
        is_running = False
        print("Sending Return To Home command...")
        try:
            dji.requestSendRTH()
        except Exception:
            pass
            
        if ws_app:
            ws_app.close()
            
        dji.stopTelemetryStream()
        print("Shutdown complete. Goodbye.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Aegis Client Edge Node")
    parser.add_argument("--ip", type=str, default="127.0.0.1", help="DJI Remote / Mock IP")
    parser.add_argument("--server", type=str, default="http://127.0.0.1:8000", help="Central Hub Server URL")
    parser.add_argument("--port-http", type=int, default=8080, help="Mock Remote HTTP Port")
    parser.add_argument("--port-tcp", type=int, default=8081, help="Mock Remote TCP Port")
    
    # Still allow simple positional args for backwards compat if needed, but favor flags
    args, unknown = parser.parse_known_args()
    
    IP_RC = args.ip
    SERVER_URL = args.server
    PORT_HTTP = args.port_http
    PORT_TCP = args.port_tcp
    
    # Handle old manual passing format if users just do `client.py 127.0.0.1 http://localhost:8000`
    if unknown and len(unknown) >= 1 and not unknown[0].startswith("--"):
        IP_RC = unknown[0]
        if len(unknown) >= 2 and not unknown[1].startswith("--"):
            SERVER_URL = unknown[1]

    WS_URL = SERVER_URL.replace("http://", "ws://").replace("https://", "wss://")
    main()
