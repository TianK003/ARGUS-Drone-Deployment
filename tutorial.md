# ARGUS / WildBridge Quick Start Tutorial

This guide provides simple step-by-step instructions on how to run the ARGUS server, connect hardware drones, and run drone simulations.

## 1. How to Launch the Server (ARGUS Hub)
The central server coordinates the drones and provides the live web dashboard.

1. Open your terminal or PowerShell.
2. Navigate to the `WebServer` directory:
   ```bash
   cd GroundStation/WebServer
   ```
3. Activate the Python virtual environment and install dependencies (if not already done):
   ```bash
   # Windows PowerShell
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
4. Start the server:
   ```bash
   python -m app
   ```
5. Open your web browser and go to `http://127.0.0.1:8000` to view the Dashboard.

---

## 2. How to Connect a Client (Real DJI Drone)
To connect a real drone, you need the drone, the DJI Remote Controller, and your computer to all be on the same Wi-Fi network.

1. **On the Remote Controller:**
   - Connect to the Wi-Fi network.
   - Note the IP Address of the Controller (e.g., `192.168.1.100`).
   - Open the **WildBridge App**.
   - Navigate to **"Testing Tools" -> "Virtual Stick"**.
   - Click the **"Enable Virtual Stick"** button.
2. **On your Computer:**
   - Open a new terminal.
   - Use the `aegis_client.py` bridge script to connect the RC to the Hub. Replace `<RC_IP>` with the IP address from step 1:
   ```bash
   python GroundStation/client/aegis_client.py --ip <RC_IP> --port-http 8080 --port-tcp 8081
   ```

---

## 3. How to Create and Connect a Simulated Client
You can test the system without a physical drone by running a "mock" remote controller on your computer.

1. **Start the Mock RC** (Terminal 1):
   ```bash
   python GroundStation/client/mock_remote.py --port-http 8082 --port-tcp 8083
   ```
2. **Connect the Bridge Agent** (Terminal 2):
   ```bash
   python GroundStation/client/aegis_client.py --ip 127.0.0.1 --port-http 8082 --port-tcp 8083
   ```
*The simulated drone will immediately appear on the web dashboard at `http://127.0.0.1:8000`.*

---

## 4. How to Launch a Drone Swarm (Simulation)
The repository includes a script that spins up an entire fleet of simulated drones — one `mock_remote.py` + one `aegis_client.py` pair per drone — scattered randomly within a 250 m radius of a central point (currently FRI Ljubljana, `46.049564, 14.468333`).

1. Ensure the **ARGUS Hub** is running in one terminal (see step 1).
2. Open a new terminal from the root of the project.
3. Run the swarm script:
   ```bash
   python GroundStation/spawn_swarm.py
   ```
4. Watch the web dashboard! The Hub automatically detects the new drones and instantly assigns them non-overlapping zigzag patrol paths.
5. Press **Ctrl+C** in the swarm terminal to kill every drone. Leave the script running for as long as you want the swarm alive.

### How the swarm size is decided
There is no fixed drone count anymore — it comes from the **overlay image folder**, `GroundStation/overlays/` by default:

- **One drone per image.** Each drone gets its own image served as a static MJPEG feed (`--static-image`), so every drone shows a different picture on the dashboard. The repo currently ships 5 aerial images, so a plain run gives you 5 drones.
- **No images found?** The script falls back to **6** drones on the webcam/dummy feed.
- Use a different folder with `--image-overlay-folder <path>`.

If you ask for more drones than there are images with `--count`, the extras don't get an image: the *first* extra drone opens the local webcam, and every drone after that serves a black screen (`--black-screen`). Only one process can hold the camera, hence the split.

### Options
```bash
# Force a specific fleet size, ignoring the image count
python GroundStation/spawn_swarm.py --count 12

# Use a different image folder (one drone per image inside it)
python GroundStation/spawn_swarm.py --image-overlay-folder ../my_frames

# Show the mock/aegis logs in this terminal instead of hiding them
python GroundStation/spawn_swarm.py --verbose

# Ports still held by zombies from a previous run? Kill the owners (Windows only)
python GroundStation/spawn_swarm.py --kill-stale
```

| Flag | Default | What it does |
|---|---|---|
| `--image-overlay-folder` | `overlays` | Folder of `.png`/`.jpg`/`.jpeg` images; one drone spawned per image. |
| `--count` | *(from image count)* | Total drones to spawn. Overrides both the image count and the fallback. |
| `--verbose` | off | Forwards each child process's stdout/stderr to this terminal (child consoles become visible). Use this to debug drones dropping off the dashboard. |
| `--kill-stale` | off | On Windows, `taskkill`s whatever process is holding a port the swarm needs. |

### Ports
Drone *i* gets HTTP port `8080 + i*10` and TCP port `8080 + i*10 + 1` — so drone 0 is `8080/8081`, drone 1 is `8090/8091`, and so on.

The script **pre-flight checks every port before spawning anything** and aborts with an error list if any are busy. This is almost always leftover `mock_remote`/`aegis_client` processes from a run that was Ctrl+C'd mid-spawn. Fix it by re-running with `--kill-stale` (Windows), or kill the stray `python.exe` processes in Task Manager.
