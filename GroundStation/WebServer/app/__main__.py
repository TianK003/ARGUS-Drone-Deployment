"""
Entrypoint for the ARGUS Hub.

Usage:
    python -m app [--mock] [--drones-config PATH]
                  [--host H] [--port P] [--max-stick F] [--no-video]

Drone registry is loaded from `drones.json` (override with --drones-config).
When `--mock` is set and the registry is empty, a single mock drone is seeded
so the UI is immediately usable.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

from .main import create_app
from .registry import DroneEntry, DroneRegistry


DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "drones.json"


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="app",
        description="ARGUS Hub — multi-drone web ground station.",
    )
    p.add_argument("--mock", action="store_true",
                   help="Seed a mock drone if registry is empty; force new drones to mock mode.")
    p.add_argument("--drones-config", metavar="PATH", default=str(DEFAULT_CONFIG),
                   help=f"Path to drones.json (default: {DEFAULT_CONFIG}).")
    p.add_argument("--host", default="127.0.0.1",
                   help="Bind address (default: 127.0.0.1). 0.0.0.0 to expose on LAN.")
    p.add_argument("--port", type=int, default=8000, help="Port (default: 8000).")
    p.add_argument("--max-stick", type=float, default=0.3,
                   help="Saturation cap in [0, 1] for stick axes (default: 0.3).")
    p.add_argument("--no-video", action="store_true",
                   help="Disable video broadcasters for all drones (skips RTSP).")
    return p.parse_args(argv)


def main():
    args = parse_args()
    if not 0.0 <= args.max_stick <= 1.0:
        print("error: --max-stick must be in [0, 1]", file=sys.stderr)
        sys.exit(2)

    config_path = Path(args.drones_config)
    defaults = {
        "mock": args.mock,
        "max_stick": args.max_stick,
        "no_video": args.no_video,
    }

    registry = DroneRegistry.from_config(config_path, defaults=defaults)

    # In mock mode, seed one entry so the dashboard isn't empty on first boot.
    if args.mock and not registry.list():
        registry.add(
            DroneEntry(
                id="mock-1",
                label="Mock Drone 1",
                rc_ip="mock",
                home_lat=46.0569,
                home_lng=14.5058,
                reach_m=800,
                mock=True,
                max_stick=args.max_stick,
                enable_video=not args.no_video,
            )
        )

    plans_dir = config_path.parent / "plans"
    app = create_app(registry, defaults=defaults, plans_dir=plans_dir)

    print(
        f"Serving ARGUS Hub on http://{args.host}:{args.port}  "
        f"(mock={args.mock}, drones={[e.id for e in registry.list()]}, "
        f"config={config_path})"
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
