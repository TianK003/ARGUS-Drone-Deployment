"""FastAPI app factory for the WildBridge web backend."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .routes import router

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app(drone_client, video_broadcaster=None) -> FastAPI:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if video_broadcaster is not None:
            video_broadcaster.start()
        try:
            yield
        finally:
            if video_broadcaster is not None:
                video_broadcaster.stop()

    app = FastAPI(
        title="WildBridge Web Backend",
        version="0.2.0",
        description=(
            "Bridges a browser UI to the WildBridge Android app's HTTP API on the DJI RC. "
            "Virtual-stick control + live MJPEG video."
        ),
        lifespan=lifespan,
    )
    app.state.drone_client = drone_client
    app.state.video = video_broadcaster

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/video", include_in_schema=False)
    def video_standalone():
        return FileResponse(STATIC_DIR / "video.html")

    return app
