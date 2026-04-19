import sys
import os
import time
import json
import uuid
import threading
import requests
import cv2
import math

# Ensure we can import the DJIInterface from the GroundStation module
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.append(os.path.join(project_root, "GroundStation", "Python"))

try:
    from djiInterface import DJIInterface
except ImportError:
    print("Error: Could not import DJIInterface. Please ensure it exists in GroundStation/Python/")
    sys.exit(1)

# Global Configuration
SERVER_URL = "http://127.0.0.1:8000"
IP_RC = "10.102.252.30"
DRONE_ID = f"drone-{str(uuid.uuid4())[:8]}"

# State flags
is_running = True
has_started_mission = False

def push_telemetry_loop(dji):
    """Continuously push telemetry data to the central server."""
    global is_running
    url = f"{SERVER_URL}/api/swarm/{DRONE_ID}/telemetry"
    while is_running:
        telemetry = dji.getTelemetry()
        if telemetry:
            try:
                # We POST the entire telemetry blob or whatever subset the server needs
                requests.post(url, json=telemetry, timeout=2)
            except requests.RequestException:
                pass # Ignore connection drops on telemetry
        time.sleep(1.0) # 1Hz update rate

def push_video_loop(dji):
    """Continuously fetch RTSP frames and POST them to the server."""
    global is_running, has_started_mission
    
    # Wait until mission starts to save bandwidth, or start immediately if preferred
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
            
        # Encode frame as JPEG
        _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
        
        try:
            # Pushing individual frames via POST for simplicity
            requests.post(url, data=buffer.tobytes(), headers={'Content-Type': 'image/jpeg'}, timeout=1)
        except requests.RequestException:
            pass # Ignore dropped frames
            
    cap.release()

def main():
    global is_running, has_started_mission
    
    print(f"[{DRONE_ID}] Initializing connection to DJI Remote at {IP_RC}...")
    dji = DJIInterface(IP_RC)
    dji.startTelemetryStream()
    
    print("Waiting for GPS lock...")
    home_location = None
    # Wait until we get a valid GPS fix
    for _ in range(30):
        telemetry = dji.getTelemetry()
        if telemetry and "location" in telemetry and telemetry["location"]:
            loc = telemetry["location"]
            # Just verify it's not empty dictionary
            if isinstance(loc, dict) and (loc.get("latitude") or loc.get("lat")):
                 home_location = loc
                 break
        time.sleep(1)
        
    if not home_location:
         # Mocking location for development if real drone is not connected
         print("Warning: Could not get GPS lock. Using mock location for testing.")
         home_location = {"latitude": 46.0569, "longitude": 14.5058, "altitude": 0}
         
    print(f"GPS Lock acquired: {home_location}")
    print(f"Registering with Central Server: {SERVER_URL}...")
    
    # Send Join Request
    try:
        response = requests.post(
            f"{SERVER_URL}/api/swarm/join", 
            json={
                "id": DRONE_ID, 
                "homeLocation": home_location
            },
            timeout=5
        )
        response.raise_for_status()
        data = response.json()
        path = data.get("path", [])
        final_yaw = data.get("finalYaw", 0)
        target_altitude = float(data.get("targetAltitude", 200.0))
        print(f"Successfully joined swarm. Received path with {len(path)} waypoints (Alt: {target_altitude}m).")
    except Exception as e:
        print(f"Failed to join swarm on server: {e}")
        print("Cannot continue without assigned path. Exiting.")
        dji.stopTelemetryStream()
        sys.exit(1)

    # Convert path to tuples for the DJI Interface (lat, lon, alt)
    # Assuming the server returns [{"lat": x, "lon": y, "alt": z}, ...]
    try:
        # Force the patrol altitude to whatever the server commanded
        waypoints = [(p["lat"], p.get("lon", p.get("lng")), target_altitude) for p in path]
    except KeyError as e:
        print(f"Invalid path format received from server. Missing key: {e}")
        dji.stopTelemetryStream()
        sys.exit(1)

    input(">>> Setup Complete. Press ENTER to start mission and follow path... <<<")
    has_started_mission = True
    
    # Start the daemon threads for pushing data
    threading.Thread(target=push_telemetry_loop, args=(dji,), daemon=True).start()
    threading.Thread(target=push_video_loop, args=(dji,), daemon=True).start()
    
    print("Mission Started. Pushing telemetry and video...")
    
    try:
        print(f"Taking off and ascending to {target_altitude}m...")
        try:
            dji.requestSendTakeOff()
            time.sleep(3) # Initial delay for takeoff buffer
            dji.requestSendGotoAltitude(target_altitude)
            time.sleep(2) # Brief spacing before trajectory command
        except Exception as e:
            print(f"Failed to execute initial takeoff and ascend: {e}")

        if waypoints:
            print("Sending patrol trajectory to Drone...")
            try:
                dji.requestSendNavigateTrajectory(waypoints, final_yaw)
            except Exception as e:
                print(f"Failed to send trajectory to drone native API: {e}")
                
            current_trajectory = waypoints
            
            # Active Patrol Loop
            def get_distance(lat1, lon1, lat2, lon2):
                R = 6371e3
                d_lat = math.radians(lat2 - lat1)
                d_lon = math.radians(lon2 - lon1)
                a = math.sin(d_lat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon/2)**2
                return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

            while True:
                time.sleep(2)
                
                # Safety Battery Check
                bat = dji.getBatteryLevel()
                if 0 < bat < 20: 
                    print(f"CRITICAL: Battery low ({bat}%). Aborting patrol sequence.")
                    break # Break loop to trigger finally RTH block
                    
                # Waypoint End Detection
                loc = dji.getLocation()
                if loc and loc.get("latitude") and loc.get("longitude"):
                    lat = loc["latitude"]
                    lon = loc["longitude"]
                    
                    target_lat = current_trajectory[-1][0]
                    target_lon = current_trajectory[-1][1]
                    
                    dist = get_distance(lat, lon, target_lat, target_lon)
                    if dist < 0.5:
                        print(f"Reached end of path segment (Dist: {dist:.1f}m). Reversing...")
                        current_trajectory = current_trajectory[::-1]
                        time.sleep(2) # Brief hover before turning
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
            
        print("Disconnecting from Central Server...")
        try:
            requests.delete(f"{SERVER_URL}/api/swarm/{DRONE_ID}/leave", timeout=3)
        except Exception:
            pass
            
        dji.stopTelemetryStream()
        print("Shutdown complete. Goodbye.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        IP_RC = sys.argv[1]
    if len(sys.argv) > 2:
        SERVER_URL = sys.argv[2]
        
    main()
