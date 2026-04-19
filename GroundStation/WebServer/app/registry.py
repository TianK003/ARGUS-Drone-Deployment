"""
Simple In-Memory Drone Registry for passive Server Paradigm.
"""

from __future__ import annotations

import logging
import threading
import random
import uuid
from collections import OrderedDict
from typing import Dict, Optional, List

log = logging.getLogger(__name__)

# vibrant colors
PALETTE = ['#00E676', '#58a6ff', '#f778ba', '#d29922', '#a371f7', '#ff7b72', '#39c5cf', '#e3b341', '#bc8cff', '#FF4081']

DETECTION_IMAGE_CAP = 50
DETECTION_META_CAP = 1000

class DroneRegistry:
    def __init__(self):
        self._lock = threading.RLock()
        self._drones: Dict[str, dict] = {}
        self._alerts: List[dict] = []
        self._detections: List[dict] = []
        self._detection_images: "OrderedDict[str, bytes]" = OrderedDict()

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

    def record_detection(
        self,
        drone_id: str,
        drone_label: str,
        prompt: str,
        ts_ms: int,
        lat: float,
        lng: float,
        jpeg_bytes: Optional[bytes],
    ) -> dict:
        det_id = f"det-{uuid.uuid4().hex[:8]}"
        payload = {
            "id": det_id,
            "droneId": drone_id,
            "droneLabel": drone_label,
            "prompt": prompt,
            "ts": ts_ms,
            "lat": lat,
            "lng": lng,
            "has_image": bool(jpeg_bytes),
        }
        with self._lock:
            self._detections.append(payload)

            if jpeg_bytes:
                self._detection_images[det_id] = jpeg_bytes
                while len(self._detection_images) > DETECTION_IMAGE_CAP:
                    evicted_id, _ = self._detection_images.popitem(last=False)
                    for entry in self._detections:
                        if entry["id"] == evicted_id:
                            entry["has_image"] = False
                            break

            # Defensive: cap total metadata to avoid OOM on runaway prompts.
            while len(self._detections) > DETECTION_META_CAP:
                old = self._detections.pop(0)
                self._detection_images.pop(old["id"], None)

            self._alerts.append(payload)
        return payload

    def list_detections(self) -> List[dict]:
        with self._lock:
            return [d.copy() for d in self._detections]

    def get_detection_image(self, det_id: str) -> Optional[bytes]:
        with self._lock:
            return self._detection_images.get(det_id)

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
