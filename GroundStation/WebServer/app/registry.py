"""
Drone registry for the ARGUS Hub.

Holds one `DroneEntry` per known RC. Each entry lazily constructs its own
`LiveDroneClient` / `LiveVideoBroadcaster` (or their mock counterparts) so
adding a drone at runtime doesn't force a restart.

Thread-safe: callers from request handlers and the WebSocket fan-out may
touch the registry concurrently.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .drone_client import LiveDroneClient, MockDroneClient
from .video import LiveVideoBroadcaster, MockVideoBroadcaster

log = logging.getLogger(__name__)


@dataclass
class DroneEntry:
    id: str
    label: str
    rc_ip: str
    home_lat: Optional[float] = None
    home_lng: Optional[float] = None
    reach_m: int = 800
    mock: bool = False
    max_stick: float = 0.3
    enable_video: bool = True
    client: object = field(default=None, init=False, repr=False)
    video: object = field(default=None, init=False, repr=False)
    added_at: float = field(default_factory=time.time)

    def ensure_started(self) -> None:
        """Build the drone client and video broadcaster on first access."""
        if self.client is None:
            if self.mock:
                self.client = MockDroneClient(max_stick=self.max_stick)
                # MockDroneClient doesn't carry its own rc_ip; stamp it so
                # /api/health can still identify which drone spoke.
                self.client.rc_ip = self.rc_ip or "mock"
            else:
                self.client = LiveDroneClient(rc_ip=self.rc_ip, max_stick=self.max_stick)
        if self.video is None and self.enable_video:
            if self.mock:
                self.video = MockVideoBroadcaster()
            else:
                self.video = LiveVideoBroadcaster(
                    f"rtsp://aaa:aaa@{self.rc_ip}:8554/streaming/live/1"
                )
            self.video.start()

    def stop(self) -> None:
        if self.video is not None:
            try:
                self.video.stop()
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("stopping video for drone %s failed: %s", self.id, exc)
        self.video = None
        self.client = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "rc_ip": self.rc_ip,
            "home_lat": self.home_lat,
            "home_lng": self.home_lng,
            "reach_m": self.reach_m,
            "mock": self.mock,
            "max_stick": self.max_stick,
            "enable_video": self.enable_video,
        }


class DroneRegistry:
    def __init__(self, config_path: Optional[Path] = None):
        self._lock = threading.RLock()
        self._drones: Dict[str, DroneEntry] = {}
        self._config_path = config_path

    # ── CRUD ──────────────────────────────────────────────────────────

    def add(self, entry: DroneEntry, persist: bool = True) -> DroneEntry:
        with self._lock:
            if entry.id in self._drones:
                raise ValueError(f"drone id already exists: {entry.id}")
            entry.ensure_started()
            self._drones[entry.id] = entry
        if persist:
            self._save()
        log.info("registry: added drone %s (rc=%s, mock=%s)", entry.id, entry.rc_ip, entry.mock)
        return entry

    def remove(self, drone_id: str, persist: bool = True) -> bool:
        with self._lock:
            entry = self._drones.pop(drone_id, None)
        if entry is None:
            return False
        entry.stop()
        if persist:
            self._save()
        log.info("registry: removed drone %s", drone_id)
        return True

    def get(self, drone_id: str) -> Optional[DroneEntry]:
        with self._lock:
            return self._drones.get(drone_id)

    def list(self) -> List[DroneEntry]:
        with self._lock:
            return list(self._drones.values())

    def shutdown(self) -> None:
        with self._lock:
            entries = list(self._drones.values())
            self._drones.clear()
        for entry in entries:
            entry.stop()

    # ── JSON persistence ─────────────────────────────────────────────

    def persist(self) -> None:
        """Write the current registry to disk (no-op if no config path was set)."""
        self._save()

    def _save(self) -> None:
        if self._config_path is None:
            return
        data = {"drones": [e.to_dict() for e in self.list()]}
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            with self._config_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError as exc:
            log.warning("registry: could not persist %s: %s", self._config_path, exc)

    @classmethod
    def from_config(cls, config_path: Optional[Path], defaults: Optional[dict] = None) -> "DroneRegistry":
        reg = cls(config_path=config_path)
        defaults = defaults or {}
        if config_path is None or not config_path.exists():
            return reg
        try:
            with config_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("registry: cannot read %s (%s) — starting empty", config_path, exc)
            return reg

        for raw in data.get("drones", []):
            try:
                entry = DroneEntry(
                    id=str(raw["id"]),
                    label=str(raw.get("label") or raw["id"]),
                    rc_ip=str(raw.get("rc_ip") or ""),
                    home_lat=raw.get("home_lat"),
                    home_lng=raw.get("home_lng"),
                    reach_m=int(raw.get("reach_m") or 800),
                    mock=bool(raw.get("mock", defaults.get("mock", False))),
                    max_stick=float(raw.get("max_stick") or defaults.get("max_stick", 0.3)),
                    enable_video=bool(raw.get("enable_video", defaults.get("enable_video", True))),
                )
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("registry: skipping malformed entry %r: %s", raw, exc)
                continue
            try:
                reg.add(entry, persist=False)
            except ValueError as exc:
                log.warning("registry: skipping %s: %s", entry.id, exc)

        return reg
