"""
Passive HTTP & WebSocket routes for the Edge-Driven ARGUS Hub.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from .registry import DroneRegistry

log = logging.getLogger(__name__)

router = APIRouter()

TELEMETRY_FANOUT_INTERVAL = 1.0  # seconds

# ── Pydantic models ──────────────────────────────────────────────────

class LocationModel(BaseModel):
    latitude: float
    longitude: float

class JoinRequest(BaseModel):
    id: str
    homeLocation: LocationModel

# ── Helpers ──────────────────────────────────────────────────────────

def _registry(request: Request) -> DroneRegistry:
    return request.app.state.registry

def generate_square_patrol_path(home: LocationModel) -> list:
    """Generate a simple square 50-meter radius patrol around home for demonstration."""
    lat, lng = home.latitude, home.longitude
    # Roughly 50 meters in degrees
    d_lat = 0.00045 
    d_lng = 0.00065
    alt = 30 # 30m altitude
    return [
        {"lat": lat + d_lat, "lon": lng + d_lng, "alt": alt},
        {"lat": lat + d_lat, "lon": lng - d_lng, "alt": alt},
        {"lat": lat - d_lat, "lon": lng - d_lng, "alt": alt},
        {"lat": lat - d_lat, "lon": lng + d_lng, "alt": alt},
        {"lat": lat + d_lat, "lon": lng + d_lng, "alt": alt}
    ]

# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/api/health")
def health(request: Request):
    return {"ok": True, "active_drones": len(_registry(request).list())}

@router.get("/api/drones")
def list_drones(request: Request):
    """Retrieve all drone state for the dashboard."""
    return {"drones": _registry(request).list()}

@router.post("/api/swarm/join", status_code=201)
def swarm_join(payload: JoinRequest, request: Request):
    """The Edge Client hits this endpoint upon achieving GPS lock."""
    reg = _registry(request)
    
    # Simple dynamic KOORDINATE path assignment
    waypoints = generate_square_patrol_path(payload.homeLocation)
    final_yaw = 0
    
    drone_data = {
        "homeLocation": payload.homeLocation.model_dump(),
        "path": waypoints,
        "finalYaw": final_yaw
    }
    reg.add_or_update(payload.id, drone_data)
    
    log.info(f"Assigned patrol path to {payload.id} with {len(waypoints)} waypoints.")
    
    return {
        "status": "joined",
        "path": waypoints,
        "finalYaw": final_yaw
    }

@router.post("/api/swarm/{uuid}/telemetry")
async def swarm_telemetry(uuid: str, request: Request):
    """Edge client posts live JSON telemetry here natively."""
    try:
        telemetry_data = await request.json()
        _registry(request).update_telemetry(uuid, telemetry_data)
    except Exception as e:
        log.warning(f"Telemetry parse error from {uuid}: {e}")
        return Response(status_code=400)
    return Response(status_code=204)

@router.post("/api/swarm/{uuid}/video")
async def swarm_video(uuid: str, request: Request):
    """Edge client posts absolute newest JPEG bytes here natively."""
    body = await request.body()
    if not body:
        return Response(status_code=400, content="Empty body")
    
    _registry(request).update_video(uuid, body)
    return Response(status_code=204)

@router.delete("/api/swarm/{uuid}/leave")
def swarm_leave(uuid: str, request: Request):
    """Edge client deregisters from the swarm."""
    if not _registry(request).remove(uuid):
        raise HTTPException(status_code=404, detail="Unknown drone")
    return {"status": "left"}

# ── Dashboard WebSocket ──────────────────────────────────────────────

@router.websocket("/ws/drones")
async def ws_drones(ws: WebSocket):
    """1 Hz fan-out of telemetry snapshots to the UI."""
    await ws.accept()
    reg: DroneRegistry = ws.app.state.registry

    try:
        while True:
            snapshots = reg.list()
            await ws.send_json({"ts": time.time(), "drones": snapshots})
            await asyncio.sleep(TELEMETRY_FANOUT_INTERVAL)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("ws_drones error: %s", exc)


# ── MJPEG Video Streamer for UI ──────────────────────────────────────

MJPEG_BOUNDARY = "frame"

@router.get("/api/swarm/{uuid}/video.mjpg")
async def get_video_stream(uuid: str, request: Request):
    """Dashboard UI consumes this multipart stream to show the latest frame."""
    reg = _registry(request)

    async def gen():
        boundary = f"--{MJPEG_BOUNDARY}".encode()
        last_frame_ref = None
        
        while True:
            if await request.is_disconnected():
                return
                
            entry = reg.get(uuid)
            if not entry:
                await asyncio.sleep(1.0)
                continue
                
            current_frame = entry.get("latest_frame")
            if not current_frame or current_frame is last_frame_ref:
                await asyncio.sleep(0.05)
                continue
                
            last_frame_ref = current_frame
            yield boundary + b"\r\n"
            yield b"Content-Type: image/jpeg\r\n"
            yield f"Content-Length: {len(current_frame)}\r\n\r\n".encode()
            yield current_frame
            yield b"\r\n"

    return StreamingResponse(
        gen(),
        media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
