"""FastAPI app factory for the ARGUS Hub (multi-drone ground station)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .registry import DroneRegistry
from .routes import router

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app(
    registry: DroneRegistry,
    defaults: dict | None = None,
    plans_dir: Path | None = None,
) -> FastAPI:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            registry.shutdown()

    app = FastAPI(
        title="ARGUS Hub",
        version="0.3.0",
        description=(
            "Multi-drone ground station. Serves a Leaflet swarm dashboard plus "
            "per-drone virtual-stick control and MJPEG video, all bridged to the "
            "WildBridge Android app's HTTP/TCP/RTSP contract."
        ),
        lifespan=lifespan,
    )
    app.state.registry = registry
    app.state.defaults = defaults or {}
    app.state.plans_dir = plans_dir or (STATIC_DIR.parent / "plans")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(STATIC_DIR / "dashboard.html")

    @app.get("/drone/{drone_id}", include_in_schema=False)
    def drone_control(drone_id: str, request: Request):
        if request.app.state.registry.get(drone_id) is None:
            raise HTTPException(status_code=404, detail=f"unknown drone: {drone_id}")
        # Inject DRONE_ID into the single-drone UI without a template engine.
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        injected = (
            f"<script>window.DRONE_ID = {drone_id!r};</script>"
        )
        html = html.replace("</head>", injected + "\n</head>", 1)
        return HTMLResponse(html)

    @app.get("/video", include_in_schema=False)
    def video_standalone():
        # Kept for backwards compatibility; user is expected to pass ?drone=ID.
        return FileResponse(STATIC_DIR / "video.html")

    return app
