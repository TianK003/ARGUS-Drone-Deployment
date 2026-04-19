import subprocess
import time
import random
import math
import os
import signal
import sys

# Windows flag to hide terminal windows
CREATE_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0

# Target Center
CENTER_LAT = 46.049564053030984
CENTER_LNG = 14.468332969551334
RADIUS_M = 500
COUNT = 30
START_PORT = 8080

def get_random_location(clat, clng, radius):
    # Random angle and distance for uniform circle distribution
    angle = random.random() * 2 * math.pi
    dist = math.sqrt(random.random()) * radius
    
    # Approx offsets
    delta_lat = (dist * math.cos(angle)) / 111320.0
    delta_lng = (dist * math.sin(angle)) / (111320.0 * math.cos(math.radians(clat)))
    
    return clat + delta_lat, clng + delta_lng

def main():
    processes = []
    
    print(f"Spawning {COUNT} mock drones around {CENTER_LAT}, {CENTER_LNG}...")
    
    # Use the venv python if available
    python_exe = os.path.join("WebServer", "venv", "Scripts", "python.exe")
    if not os.path.exists(python_exe):
        python_exe = "python" # Fallback

    for i in range(COUNT):
        p_http = START_PORT + (i * 10)
        p_tcp = p_http + 1
        lat, lng = get_random_location(CENTER_LAT, CENTER_LNG, RADIUS_M)
        
        print(f"Drone {i:02}: Port {p_http}/{p_tcp} at {lat:.5f}, {lng:.5f}")
        
        # 1. Spawn Mock Remote
        # We use subprocess.Popen to run in background
        remote_cmd = [
            python_exe, "-m", "client.mock_remote",
            "--port-http", str(p_http),
            "--port-tcp", str(p_tcp),
            "--lat", str(lat),
            "--lng", str(lng)
        ]
        p_remote = subprocess.Popen(
            remote_cmd, 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW
        )
        processes.append(p_remote)
        
        # Give remote a moment to bind ports
        time.sleep(0.5)
        
        # 2. Spawn Aegis Client
        client_cmd = [
            python_exe, "-m", "client.aegis_client",
            "--ip", "127.0.0.1",
            "--port-http", str(p_http),
            "--port-tcp", str(p_tcp)
        ]
        # We don't want 30 consoles popping up, so we'll just run them hidden or in this output
        # But wait, aegis_client has an input() prompt!
        # I'll pipe a newline to it immediately to bypass the 'Press ENTER' prompt.
        p_client = subprocess.Popen(
            client_cmd, 
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW
        )
        # Pipe the ENTER key to start the mission immediately
        try:
            p_client.stdin.write(b"\n")
            p_client.stdin.flush()
        except:
            pass
            
        processes.append(p_client)
        
        time.sleep(2.0)

    print(f"\nSuccessfully spawned {len(processes)} processes (30 remotes + 30 clients).")
    print("Keep this script running to maintain the swarm. Press Ctrl+C to kill all drones.")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nKilling swarm...")
        for p in processes:
            p.terminate()
        print("Done.")

if __name__ == "__main__":
    main()
