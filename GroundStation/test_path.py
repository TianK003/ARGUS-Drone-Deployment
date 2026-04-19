import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'WebServer'))
from app.pathing import compute_paths

drones = [
    {'id': '1', 'lat': 46.0569, 'lng': 14.5058, 'reach': 800},
    {'id': '2', 'lat': 46.0600, 'lng': 14.5100, 'reach': 800}
]
res = compute_paths(drones, stripe_spacing=40, sweep_dir='ew')
print(f"Paths generated: {len(res.get('paths', {}))}")
for k, v in res.get('paths', {}).items():
    print(f"Drone {k}: {len(v)} waypoints")
