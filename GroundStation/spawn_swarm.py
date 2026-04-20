import argparse
import socket
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
FALLBACK_COUNT = 30  # used only when the image folder has no images
START_PORT = 8080

DEFAULT_OVERLAY_FOLDER = "overlays"
IMAGE_EXTS = (".png", ".jpg", ".jpeg")

def is_port_free(port: int) -> bool:
    """Try to bind; return True only if the port is genuinely free."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()

def kill_windows_port_owner(port: int) -> bool:
    """On Windows, find the PID listening on `port` via netstat and taskkill it.
    Returns True if something was killed. No-op on non-Windows."""
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, timeout=5
        ).stdout
    except Exception:
        return False
    needle = f":{port} "
    killed = False
    for line in out.splitlines():
        if needle in line and "LISTENING" in line:
            parts = line.split()
            pid = parts[-1]
            try:
                subprocess.run(["taskkill", "/F", "/PID", pid],
                               capture_output=True, timeout=5)
                killed = True
            except Exception:
                pass
    return killed

def get_random_location(clat, clng, radius):
    # Random angle and distance for uniform circle distribution
    angle = random.random() * 2 * math.pi
    dist = math.sqrt(random.random()) * radius
    
    # Approx offsets
    delta_lat = (dist * math.cos(angle)) / 111320.0
    delta_lng = (dist * math.sin(angle)) / (111320.0 * math.cos(math.radians(clat)))
    
    return clat + delta_lat, clng + delta_lng

def main():
    ap = argparse.ArgumentParser(description="Spawn a swarm of mock DJI drones")
    ap.add_argument("--image-overlay-folder", default=DEFAULT_OVERLAY_FOLDER,
                    help=f"Folder of images; one drone is spawned per image (default: {DEFAULT_OVERLAY_FOLDER})")
    ap.add_argument("--verbose", action="store_true",
                    help="Forward mock/aegis stdout+stderr to this terminal (debug drone dropouts)")
    ap.add_argument("--kill-stale", action="store_true",
                    help="If mock ports are held by zombie processes, kill them (Windows only, uses taskkill)")
    cli_args = ap.parse_args()

    sub_stdout = None if cli_args.verbose else subprocess.DEVNULL
    sub_stderr = None if cli_args.verbose else subprocess.DEVNULL
    # CREATE_NO_WINDOW hides the child console on Windows — with no console, inherited
    # stdout has nothing to draw on. Disable it in verbose so logs reach this terminal.
    creation_flags = 0 if cli_args.verbose else CREATE_NO_WINDOW

    processes = []

    # Use the venv python if available
    python_exe = os.path.join("WebServer", "venv", "Scripts", "python.exe")
    if not os.path.exists(python_exe):
        python_exe = "python" # Fallback

    # Gather overlay images — swarm size is determined by file count
    overlay_folder = cli_args.image_overlay_folder
    overlay_images = []
    if os.path.isdir(overlay_folder):
        overlay_images = sorted(
            os.path.join(overlay_folder, f)
            for f in os.listdir(overlay_folder)
            if f.lower().endswith(IMAGE_EXTS)
        )

    if overlay_images:
        count = len(overlay_images)
        print(f"Using {count} images from '{overlay_folder}/' — spawning {count} drones.")
    else:
        count = FALLBACK_COUNT
        print(f"No images in '{overlay_folder}/' — falling back to {count} drones on webcam/dummy feed.")

    # Pre-flight: make sure every port we're about to bind is actually free. A previous
    # spawn_swarm run that was Ctrl+C'd mid-flight often leaves mock processes orphaned,
    # and new aegis clients silently attach to those zombies (with drained batteries, etc).
    needed_ports = []
    for i in range(count):
        needed_ports.append(START_PORT + i * 10)      # http
        needed_ports.append(START_PORT + i * 10 + 1)  # tcp
    busy = [p for p in needed_ports if not is_port_free(p)]
    if busy:
        print(f"ERROR: the following ports are already in use: {busy}")
        if cli_args.kill_stale and os.name == "nt":
            print("--kill-stale set — killing whatever's holding them...")
            for p in busy:
                kill_windows_port_owner(p)
            time.sleep(1.0)
            still_busy = [p for p in busy if not is_port_free(p)]
            if still_busy:
                print(f"Still busy after kill: {still_busy}. Aborting.")
                sys.exit(1)
            print("Cleared.")
        else:
            print("These are most likely zombie mock_remote/aegis_client processes from a previous run.")
            print("Fix: re-run with --kill-stale (Windows), or open Task Manager and kill stray python.exe processes.")
            sys.exit(1)

    print(f"Spawning {count} mock drones around {CENTER_LAT}, {CENTER_LNG}...")

    for i in range(count):
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
        if overlay_images:
            remote_cmd += ["--static-image", os.path.abspath(overlay_images[i])]
        p_remote = subprocess.Popen(
            remote_cmd,
            stdout=sub_stdout,
            stderr=sub_stderr,
            creationflags=creation_flags
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
            stdout=sub_stdout,
            stderr=sub_stderr,
            creationflags=creation_flags
        )
        # Pipe the ENTER key to start the mission immediately
        try:
            p_client.stdin.write(b"\n")
            p_client.stdin.flush()
        except:
            pass
            
        processes.append(p_client)
        
        time.sleep(2.0)

    print(f"\nSuccessfully spawned {len(processes)} processes ({count} remotes + {count} clients).")
    print("Keep this script running to maintain the swarm. Press Ctrl+C to kill all drones.")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nKilling swarm...")
        # First a polite terminate, then wait, then hard kill any stragglers — otherwise
        # mock_remote's background threads (tcp_server_loop, uvicorn) can linger on Windows
        # and hold the ports, blocking the next run.
        for p in processes:
            try:
                p.terminate()
            except Exception:
                pass
        deadline = time.time() + 3.0
        for p in processes:
            remaining = max(0.0, deadline - time.time())
            try:
                p.wait(timeout=remaining)
            except Exception:
                pass
        for p in processes:
            if p.poll() is None:
                try:
                    p.kill()
                except Exception:
                    pass
        print("Done.")

if __name__ == "__main__":
    main()
