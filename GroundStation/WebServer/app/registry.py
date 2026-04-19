"""
Simple In-Memory Drone Registry for passive Server Paradigm.
"""

from __future__ import annotations

import logging
import threading
import random
from typing import Dict, Optional, List

log = logging.getLogger(__name__)

# vibrant colors
PALETTE = ['#00E676', '#58a6ff', '#f778ba', '#d29922', '#a371f7', '#ff7b72', '#39c5cf', '#e3b341', '#bc8cff', '#FF4081']

class DroneRegistry:
    def __init__(self):
        self._lock = threading.RLock()
        self._drones: Dict[str, dict] = {}
        self._alerts: List[dict] = []

    def push_alert(self, alert: dict):
        with self._lock:
            self._alerts.append(alert)

    def pop_alerts(self) -> List[dict]:
        with self._lock:
            if not self._alerts:
                return []
            res = self._alerts[:]
            self._alerts.clear()
            return res

    def add_or_update(self, drone_id: str, data: dict) -> dict:
        with self._lock:
            if drone_id not in self._drones:
                assigned_color = random.choice(PALETTE)
                self._drones[drone_id] = {
                    "id": drone_id,
                    "color": assigned_color,
                    "homeLocation": data.get("homeLocation", {}),
                    "telemetry": {},
                    "latest_frame": None,
                    "path": data.get("path", []),
                    "finalYaw": data.get("finalYaw", 0)
                }
                log.info(f"Registry: Registered new drone {drone_id}")
            else:
                self._drones[drone_id].update(data)
        return self._drones[drone_id]

    def update_telemetry(self, drone_id: str, telemetry: dict):
        with self._lock:
            if drone_id in self._drones:
                self._drones[drone_id]["telemetry"] = telemetry

    def update_video(self, drone_id: str, frame_bytes: bytes):
        with self._lock:
            if drone_id in self._drones:
                self._drones[drone_id]["latest_frame"] = frame_bytes

    def remove(self, drone_id: str) -> bool:
        with self._lock:
            if drone_id in self._drones:
                del self._drones[drone_id]
                log.info(f"Registry: Removed drone {drone_id}")
                return True
            return False

    def get(self, drone_id: str) -> Optional[dict]:
        with self._lock:
            return self._drones.get(drone_id)

    def list(self) -> List[dict]:
        with self._lock:
            # Strip out latest_frame bytes when listing as JSON
            res = []
            for d in self._drones.values():
                copy = d.copy()
                copy.pop("latest_frame", None)
                # flatten telemetry location for map
                loc = copy.get("telemetry", {}).get("location", {})
                copy["lat"] = loc.get("latitude", loc.get("lat", copy.get("homeLocation", {}).get("latitude", 0)))
                copy["lng"] = loc.get("longitude", loc.get("lon", copy.get("homeLocation", {}).get("longitude", 0)))
                res.append(copy)
            return res
    
    def shutdown(self):
        with self._lock:
            self._drones.clear()
