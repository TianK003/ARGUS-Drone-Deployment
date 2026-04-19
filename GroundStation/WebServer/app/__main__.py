"""
Entrypoint for the Passive ARGUS Hub.
Usage: python -m app [--host H] [--port P]
"""

from __future__ import annotations

import argparse
import uvicorn
from pathlib import Path

from .main import create_app
from .registry import DroneRegistry

def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="app", description="ARGUS Hub — Passive Dashboard.")
    p.add_argument("--host", default="127.0.0.1", help="Bind address. 0.0.0.0 to expose on LAN.")
    p.add_argument("--port", type=int, default=8000, help="Port (default: 8000).")
    p.add_argument("--test", action="store_true", help="Launch in test mode (10m altitude, 5x5m square paths).")
    return p.parse_args(argv)

def main():
    args = parse_args()
    
    # Initialize empty memory-only registry
    registry = DroneRegistry()

    # Create the passive REST API
    app = create_app(registry)
    app.state.test_mode = args.test

    mode_str = "TEST MODE" if args.test else "PRODUCTION MODE"
    print(f"Serving Passive ARGUS Hub ({mode_str}) on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")

if __name__ == "__main__":
    main()
