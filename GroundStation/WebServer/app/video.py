"""
Video broadcaster: pulls RTSP, re-encodes to JPEG, holds the latest frame
in a shared slot. Consumers read the most recent frame at their own pace.

Two implementations share the same surface:
- LiveVideoBroadcaster: connects to the phone's RTSP server; reconnects on loss.
- MockVideoBroadcaster: generates a test pattern so the UI can be developed
  without a drone.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)

JPEG_QUALITY = 80


class _BaseBroadcaster:
    mode: str = "unknown"

    def __init__(self) -> None:
        self._latest_jpeg: Optional[bytes] = None
        self._latest_ts: float = 0.0
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._fps = 0.0
        self._resolution: Tuple[int, int] = (0, 0)
        self._connected = False

    # ── lifecycle ──
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name=f"video-{self.mode}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _run(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    # ── data ──
    def _publish(self, frame_bgr: np.ndarray) -> None:
        ok, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            return
        with self._lock:
            self._latest_jpeg = buf.tobytes()
            self._latest_ts = time.time()

    def get_latest_jpeg(self) -> Tuple[Optional[bytes], float]:
        with self._lock:
            return self._latest_jpeg, self._latest_ts

    def status(self) -> dict:
        age = (time.time() - self._latest_ts) if self._latest_jpeg else None
        return {
            "mode": self.mode,
            "connected": self._connected,
            "fps": round(self._fps, 1),
            "width": self._resolution[0],
            "height": self._resolution[1],
            "last_frame_age_s": round(age, 3) if age is not None else None,
        }


class LiveVideoBroadcaster(_BaseBroadcaster):
    """Reconnecting RTSP consumer. Backoff on failure."""

    mode = "live"

    def __init__(self, rtsp_url: str):
        super().__init__()
        self._url = rtsp_url

    def _run(self) -> None:
        backoff = 1.0
        while self._running:
            cap = None
            try:
                log.info("video: opening %s", self._url)
                cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
                if not cap.isOpened():
                    self._connected = False
                    log.warning("video: cv2.VideoCapture could not open stream; retrying in %.1fs", backoff)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 10.0)
                    continue

                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                self._resolution = (w, h)
                self._connected = True
                backoff = 1.0
                log.info("video: connected %dx%d", w, h)

                frames = 0
                t0 = time.time()
                while self._running:
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        log.warning("video: read() returned no frame; reconnecting")
                        break
                    self._publish(frame)
                    frames += 1
                    now = time.time()
                    if now - t0 >= 1.0:
                        self._fps = frames / (now - t0)
                        frames = 0
                        t0 = now
            except Exception as exc:
                log.warning("video: loop error: %s", exc)
            finally:
                if cap is not None:
                    cap.release()
                self._connected = False
                self._fps = 0.0


class MockVideoBroadcaster(_BaseBroadcaster):
    """Generates a test-pattern frame ~30 fps so the UI has something to show."""

    mode = "mock"

    def __init__(self, width: int = 640, height: int = 360):
        super().__init__()
        self._resolution = (width, height)

    def _run(self) -> None:
        self._connected = True
        w, h = self._resolution
        start = time.time()
        frames = 0
        t0 = start
        while self._running:
            elapsed = time.time() - start
            frame = np.zeros((h, w, 3), dtype=np.uint8)
            frame[:] = (18, 22, 28)  # bg

            # Moving circle (radians / sec)
            cx = int(w / 2 + (w * 0.35) * np.cos(elapsed * 1.5))
            cy = int(h / 2 + (h * 0.35) * np.sin(elapsed * 1.5))
            cv2.circle(frame, (cx, cy), 34, (255, 180, 62), -1)
            cv2.circle(frame, (cx, cy), 34, (255, 220, 150), 2)

            # Grid
            for x in range(0, w, 80):
                cv2.line(frame, (x, 0), (x, h), (40, 48, 58), 1)
            for y in range(0, h, 80):
                cv2.line(frame, (0, y), (w, y), (40, 48, 58), 1)

            # Labels
            cv2.putText(frame, "MOCK VIDEO  (no drone connected)", (16, 32),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (230, 230, 230), 2, cv2.LINE_AA)
            cv2.putText(frame, time.strftime("%H:%M:%S", time.localtime()),
                        (16, h - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1, cv2.LINE_AA)
            cv2.putText(frame, f"{int(1 / max(time.time() - t0, 1e-3))} Hz render" if frames else "",
                        (w - 200, h - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1, cv2.LINE_AA)

            self._publish(frame)
            frames += 1
            now = time.time()
            if now - t0 >= 1.0:
                self._fps = frames / (now - t0)
                frames = 0
                t0 = now

            time.sleep(1 / 30)
        self._connected = False
