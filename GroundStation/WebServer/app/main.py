"""FastAPI app factory for the ARGUS Hub (Edge-Driven Paradigm)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .registry import DroneRegistry
from .routes import router
from .vision import VisionDaemon

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

def create_app(registry: DroneRegistry, device: str = "0") -> FastAPI:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        daemon = VisionDaemon(registry, device=device)
        daemon.start()
        app.state.vision_daemon = daemon
        try:
            yield
        finally:
            daemon.stop()
            registry.shutdown()

    app = FastAPI(
        title="ARGUS Hub (Passive Endpoint)",
        version="0.4.0",
        description="Edge-Driven Data Centralized Storage & UI",
        lifespan=lifespan,
    )
    
    app.state.registry = registry

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(STATIC_DIR / "dashboard.html")

    return app
