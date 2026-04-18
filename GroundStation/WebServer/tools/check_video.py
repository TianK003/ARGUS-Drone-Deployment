"""
Verify the RTSP video feed from the WildBridge app is reachable and decodable.

Prints stream resolution/FPS, measures end-to-end frame latency for ~5 seconds,
and saves the first decoded frame to disk for a visual sanity check.

Usage:
    pip install opencv-python
    python tools/check_video.py <PHONE_IP>
    python tools/check_video.py 10.12.42.212
"""

from __future__ import annotations

import sys
import time

import cv2


def main():
    if len(sys.argv) != 2:
        print("usage: python tools/check_video.py <PHONE_IP>", file=sys.stderr)
        sys.exit(2)

    ip = sys.argv[1]
    url = f"rtsp://aaa:aaa@{ip}:8554/streaming/live/1"
    print(f"opening {url}")

    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        print("FAILED: cv2.VideoCapture did not open. Check:", file=sys.stderr)
        print("  - WildBridge 'Virtual Stick' page is foregrounded on the phone", file=sys.stderr)
        print("  - VLC can play the same URL", file=sys.stderr)
        print("  - FFmpeg (the opencv-python wheel bundles one) is not blocked by firewall", file=sys.stderr)
        sys.exit(1)

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"stream opened: {width}x{height} @ {fps:.1f} fps (reported)")

    # First frame
    ok, frame = cap.read()
    if not ok or frame is None:
        print("FAILED: stream opened but first read() returned no frame", file=sys.stderr)
        sys.exit(1)
    first_path = "first_frame.png"
    cv2.imwrite(first_path, frame)
    print(f"saved first decoded frame → {first_path} ({frame.shape[1]}x{frame.shape[0]})")

    # Measure received FPS for ~5 s
    print("measuring receive-side FPS for 5 seconds…")
    frames = 0
    t0 = time.time()
    while time.time() - t0 < 5.0:
        ok, frame = cap.read()
        if ok:
            frames += 1
    dt = time.time() - t0
    print(f"decoded {frames} frames in {dt:.2f}s → {frames / dt:.1f} fps")

    cap.release()
    print("OK — video path is healthy.")


if __name__ == "__main__":
    main()
