"""
Drone client abstraction.

Two implementations share the same surface:
- LiveDroneClient forwards commands to the WildBridge HTTP server on the RC.
- MockDroneClient logs calls to stdout, no network I/O.
"""

from __future__ import annotations

import sys
import time
import types
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque

# djiInterface.py has an unused top-level `import cv2`. If opencv isn't
# installed, stub it so the webapp can still import the HTTP client.
# If opencv *is* installed (for the video feed), use the real thing.
try:
    import cv2  # noqa: F401
except ImportError:
    sys.modules["cv2"] = types.ModuleType("cv2")

_DJI_INTERFACE_DIR = Path(__file__).resolve().parent.parent.parent / "Python"
if str(_DJI_INTERFACE_DIR) not in sys.path:
    sys.path.insert(0, str(_DJI_INTERFACE_DIR))

from djiInterface import (  # noqa: E402
    DJIInterface,
    EP_ABORT_MISSION,
    EP_ENABLE_VIRTUAL_STICK,
    EP_GIMBAL_SET_PITCH,
    EP_LAND,
    EP_RTH,
    EP_STICK,
    EP_TAKEOFF,
)


@dataclass
class LogEntry:
    ts: float
    action: str
    detail: str = ""
    response: str = ""


def _clamp(x: float, s: float) -> float:
    if x > s:
        return s
    if x < -s:
        return -s
    return x


class LiveDroneClient:
    """Forwards commands to the WildBridge HTTP server on the RC (port 8080)."""

    mode = "live"

    def __init__(self, rc_ip: str, max_stick: float = 0.1):
        self.rc_ip = rc_ip
        self.max_stick = max_stick
        self._dji = DJIInterface(rc_ip)
        self.last_calls: Deque[LogEntry] = deque(maxlen=100)

    def _record(self, action: str, detail: str, response: str) -> str:
        self.last_calls.append(LogEntry(time.time(), action, detail, response))
        return response

    def enable_virtual_stick(self) -> str:
        return self._record("enable", "", self._dji.requestSend(EP_ENABLE_VIRTUAL_STICK, ""))

    def disable_virtual_stick(self) -> str:
        return self._record("disable", "", self._dji.requestSend(EP_ABORT_MISSION, ""))

    def send_stick(self, lx: float, ly: float, rx: float, ry: float) -> str:
        s = self.max_stick
        lx, ly, rx, ry = _clamp(lx, s), _clamp(ly, s), _clamp(rx, s), _clamp(ry, s)
        body = f"{lx:.4f},{ly:.4f},{rx:.4f},{ry:.4f}"
        return self._record("stick", body, self._dji.requestSend(EP_STICK, body))

    def takeoff(self) -> str:
        return self._record("takeoff", "", self._dji.requestSend(EP_TAKEOFF, ""))

    def land(self) -> str:
        return self._record("land", "", self._dji.requestSend(EP_LAND, ""))

    def rth(self) -> str:
        return self._record("rth", "", self._dji.requestSend(EP_RTH, ""))

    def set_gimbal_pitch(self, pitch_deg: float) -> str:
        body = f"0,{pitch_deg:.2f},0"
        return self._record("gimbal", body, self._dji.requestSend(EP_GIMBAL_SET_PITCH, body))


class MockDroneClient:
    """No-op drone client for local development. Logs every call to stdout."""

    mode = "mock"
    rc_ip = "mock"

    def __init__(self, max_stick: float = 0.1):
        self.max_stick = max_stick
        self.last_calls: Deque[LogEntry] = deque(maxlen=100)

    def _record(self, action: str, detail: str = "") -> str:
        entry = LogEntry(time.time(), action, detail, "OK")
        self.last_calls.append(entry)
        ts_str = time.strftime("%H:%M:%S", time.localtime(entry.ts))
        suffix = f" {detail}" if detail else ""
        print(f"[MOCK {ts_str}] {action}{suffix}", flush=True)
        return "OK"

    def enable_virtual_stick(self) -> str:
        return self._record("enable")

    def disable_virtual_stick(self) -> str:
        return self._record("disable")

    def send_stick(self, lx: float, ly: float, rx: float, ry: float) -> str:
        s = self.max_stick
        lx, ly, rx, ry = _clamp(lx, s), _clamp(ly, s), _clamp(rx, s), _clamp(ry, s)
        return self._record("stick", f"{lx:+.3f},{ly:+.3f},{rx:+.3f},{ry:+.3f}")

    def takeoff(self) -> str:
        return self._record("takeoff")

    def land(self) -> str:
        return self._record("land")

    def rth(self) -> str:
        return self._record("rth")

    def set_gimbal_pitch(self, pitch_deg: float) -> str:
        return self._record("gimbal", f"pitch={pitch_deg:+.1f}°")
