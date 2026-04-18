"""Entrypoint: `python -m app [--mock | --rc-ip IP] [--host H] [--port P] [--max-stick F] [--no-video]`."""

from __future__ import annotations

import argparse
import sys

import uvicorn

from .drone_client import LiveDroneClient, MockDroneClient
from .main import create_app
from .video import LiveVideoBroadcaster, MockVideoBroadcaster


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="app",
        description="WildBridge web backend — bridges a browser to the DJI RC's HTTP API.",
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--rc-ip", metavar="IP",
                      help="IP of the DJI RC running the WildBridge app.")
    mode.add_argument("--mock", action="store_true",
                      help="Local-only; log commands to stdout instead of sending.")
    p.add_argument("--host", default="127.0.0.1",
                   help="Bind address (default: 127.0.0.1). Use 0.0.0.0 to expose on LAN.")
    p.add_argument("--port", type=int, default=8000, help="Port (default: 8000).")
    p.add_argument("--max-stick", type=float, default=0.3,
                   help="Saturation cap in [0, 1] for stick axes (default: 0.3).")
    p.add_argument("--no-video", action="store_true",
                   help="Disable the video broadcaster (skips RTSP connection and /api/video.mjpg).")
    return p.parse_args(argv)


def main():
    args = parse_args()
    if not 0.0 <= args.max_stick <= 1.0:
        print("error: --max-stick must be in [0, 1]", file=sys.stderr)
        sys.exit(2)

    if args.mock:
        drone = MockDroneClient(max_stick=args.max_stick)
        video = None if args.no_video else MockVideoBroadcaster()
    else:
        drone = LiveDroneClient(rc_ip=args.rc_ip, max_stick=args.max_stick)
        video = None if args.no_video else LiveVideoBroadcaster(
            f"rtsp://aaa:aaa@{args.rc_ip}:8554/streaming/live/1"
        )

    app = create_app(drone, video_broadcaster=video)
    video_note = "off" if video is None else video.mode
    print(
        f"Serving on http://{args.host}:{args.port}  "
        f"(mode={drone.mode}, rc_ip={drone.rc_ip}, max_stick={args.max_stick}, video={video_note})"
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
