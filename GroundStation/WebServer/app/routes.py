"""
Passive HTTP & WebSocket routes for the Edge-Driven ARGUS Hub.
"""

from __future__ import annotations

import asyncio
import logging
import time
import math
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from .registry import DroneRegistry
from .pathing import compute_paths
from .gemini import describe_detection

log = logging.getLogger(__name__)

router = APIRouter()

TELEMETRY_FANOUT_INTERVAL = 1.0  # seconds

# The only control-loop knob we can actually reach from Python without rebuilding the
# Android app. It rides the wire in the field the Kotlin parser calls "finalYaw" — but
# that value is positionally bound to DroneController.navigateTrajectory's lookaheadDistance
# arg. Must be non-zero: with 0, pure pursuit degenerates to aim-at-own-projection and the
# drone oscillates perpendicular to the segment.
DEFAULT_LOOKAHEAD_M = 5.5

# ── Pydantic models ──────────────────────────────────────────────────

class LocationModel(BaseModel):
    latitude: float
    longitude: float

class JoinRequest(BaseModel):
    id: str
    homeLocation: LocationModel

class PromptRequest(BaseModel):
    prompt: str

# ── Helpers ──────────────────────────────────────────────────────────

def _registry(request: Request) -> DroneRegistry:
    return request.app.state.registry

def generate_square_patrol_path(home: LocationModel, test_mode: bool) -> tuple[list, float]:
    """Generate a patrol square. 5x5m if test_mode, else larger 50m mock path until real koordinate integration."""
    lat, lng = home.latitude, home.longitude
    
    if test_mode:
        # approx 5x5m box (0.000045 degrees is roughly 5 meters at equator)
        d_lat = 0.0000225 
        d_lng = 0.0000225 / math.cos(math.radians(lat)) if lat else 0.0000225
        alt = 10.0
    else:
        # 50m radius default
        d_lat = 0.00045 
        d_lng = 0.00065
        alt = 30.0
        
    waypoints = [
        {"lat": lat + d_lat, "lon": lng + d_lng, "alt": alt},
        {"lat": lat + d_lat, "lon": lng - d_lng, "alt": alt},
        {"lat": lat - d_lat, "lon": lng - d_lng, "alt": alt},
        {"lat": lat - d_lat, "lon": lng + d_lng, "alt": alt},
        {"lat": lat + d_lat, "lon": lng + d_lng, "alt": alt}
    ]
    return waypoints, alt

# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/api/health")
def health(request: Request):
    return {"ok": True, "active_drones": len(_registry(request).list())}

@router.get("/api/drones")
def list_drones(request: Request):
    """Retrieve all drone state for the dashboard."""
    return {"drones": _registry(request).list()}

@router.post("/api/prompt", status_code=200)
def set_master_prompt(payload: PromptRequest, request: Request):
    """Updates the centralized SAM tracking prompt across the entire swarm."""
    daemon = getattr(request.app.state, "vision_daemon", None)
    if daemon:
        daemon.set_prompt(payload.prompt)
    return {"status": "ok"}

@router.get("/api/detections")
def list_detections(request: Request):
    """Full detection history (metadata only). Image bodies at /api/detections/{id}/image.jpg."""
    return {"detections": _registry(request).list_detections()}

@router.get("/api/detections/{det_id}/image.jpg")
def get_detection_image(det_id: str, request: Request):
    """Annotated JPEG for a detection. 404 once evicted (latest 50 are retained)."""
    img = _registry(request).get_detection_image(det_id)
    if img is None:
        raise HTTPException(status_code=404, detail="image evicted or unknown detection")
    return Response(content=img, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000, immutable"})

@router.get("/api/detections/{det_id}/raw_image.jpg")
def get_detection_raw_image(det_id: str, request: Request):
    """Un-annotated (pre-SAM-overlay) JPEG. Same FIFO cap as the annotated variant.
    Fed to Gemini for description so the model doesn't see SAM's colored mask."""
    img = _registry(request).get_raw_detection_image(det_id)
    if img is None:
        raise HTTPException(status_code=404, detail="raw image evicted or unknown detection")
    return Response(content=img, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000, immutable"})

@router.post("/api/detections/{det_id}/describe")
def describe_detection_endpoint(det_id: str, request: Request):
    """Return a Gemini-generated short description of the detection subject plus a
    confidence 0-100. Cached per detection id — subsequent calls don't hit Gemini."""
    reg = _registry(request)

    cached = reg.get_detection_description(det_id)
    if cached is not None:
        return {"description": cached["description"], "confidence": cached["confidence"], "cached": True}

    raw = reg.get_raw_detection_image(det_id)
    if raw is None:
        raise HTTPException(status_code=404, detail="raw image evicted or unknown detection")

    # Find the SAM prompt this detection was triggered by.
    sam_prompt = ""
    for det in reg.list_detections():
        if det["id"] == det_id:
            sam_prompt = det.get("prompt", "") or ""
            break

    description, confidence = describe_detection(raw, sam_prompt)
    reg.set_detection_description(det_id, description, confidence)
    return {"description": description, "confidence": confidence, "cached": False}

swarm_sockets: Dict[str, WebSocket] = {}
broadcast_lock = asyncio.Lock()
is_broadcast_queued = False

async def delayed_broadcast(app_state: Any, delay: float):
    """Wait for the swarm to stabilize before calculating paths."""
    global is_broadcast_queued
    await asyncio.sleep(delay)
    async with broadcast_lock:
        is_broadcast_queued = False
        broadcast_swarm_paths_now(app_state)

def broadcast_swarm_paths(app_state: Any):
    """Trailing-edge debounce for swarm pathing updates."""
    global is_broadcast_queued
    if not is_broadcast_queued:
        is_broadcast_queued = True
        asyncio.create_task(delayed_broadcast(app_state, 1.5))

def broadcast_swarm_paths_now(app_state: Any):
    reg = app_state.registry
    drones_list = reg.list()
    
    if not drones_list:
        return
        
    pathing_input = []
    for d in drones_list:
        home_loc = d.get("homeLocation", {})
        path_lat = home_loc.get("latitude", home_loc.get("lat", d.get("lat", 0)))
        path_lng = home_loc.get("longitude", home_loc.get("lon", d.get("lng", 0)))
        
        pathing_input.append({
            "id": d["id"],
            "lat": path_lat,
            "lng": path_lng,
            "reach": 100
        })

    result = compute_paths(pathing_input, stripe_spacing=10, sweep_dir='ew')
    paths = result["paths"]

    for drone_id, waypoints in paths.items():
        if drone_id not in swarm_sockets:
            continue

        fmt_waypoints = [{"lat": pt[0], "lon": pt[1], "alt": 30.0} for pt in waypoints]
        if not fmt_waypoints:
            continue
        
        # Only update and send if the path has actually changed to avoid redundant resets
        existing_drone = reg.get(drone_id) or {}
        if existing_drone.get("path") == fmt_waypoints:
            continue
            
        reg.add_or_update(drone_id, {"path": fmt_waypoints})

        asyncio.create_task(swarm_sockets[drone_id].send_json({
            "action": "path_update",
            "waypoints": fmt_waypoints,
            "targetAltitude": 30.0,
            "lookaheadDistance": DEFAULT_LOOKAHEAD_M,
        }))

@router.websocket("/ws/swarm/{uuid}")
async def ws_swarm(uuid: str, ws: WebSocket):
    await ws.accept()
    swarm_sockets[uuid] = ws
    reg = ws.app.state.registry
    test_mode = getattr(ws.app.state, "test_mode", False)
    
    try:
        while True:
            data = await ws.receive_json()
            action = data.get("action")
            
            if action == "join":
                home_dict = data.get("homeLocation", {})
                lat = home_dict.get("latitude", 0)
                lng = home_dict.get("longitude", 0)
                
                # Add to registry immediately
                reg.add_or_update(uuid, {
                    "homeLocation": home_dict,
                    "lat": lat,
                    "lng": lng
                })
                
                if test_mode:
                    # In test mode we just assign simple local boxes
                    home = LocationModel(**home_dict)
                    waypoints, target_alt = generate_square_patrol_path(home, True)
                    reg.add_or_update(uuid, {"path": waypoints})
                    await ws.send_json({
                        "action": "path_update",
                        "waypoints": waypoints,
                        "targetAltitude": target_alt,
                        "lookaheadDistance": DEFAULT_LOOKAHEAD_M,
                    })
                else:
                    # Trigger the massive algorithmic swarm allocation
                    broadcast_swarm_paths(ws.app.state)

            elif action == "mission_state":
                # Edge client announces takeoff/landing so we don't re-allocate mid-flight.
                reg.add_or_update(uuid, {"mission_active": bool(data.get("active", False))})

            elif action == "telemetry":
                tel = data.get("data", {})
                reg.update_telemetry(uuid, tel)
                
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning(f"Swarm WS error {uuid}: {e}")
    finally:
        if uuid in swarm_sockets:
            del swarm_sockets[uuid]
        reg.remove(uuid)
        if not test_mode:
            broadcast_swarm_paths(ws.app.state)

@router.post("/api/swarm/{uuid}/video")
async def swarm_video(uuid: str, request: Request):
    """Edge client posts absolute newest JPEG bytes here natively."""
    body = await request.body()
    if not body:
        return Response(status_code=400, content="Empty body")
    
    _registry(request).update_video(uuid, body)
    return Response(status_code=204)

# ── Dashboard WebSocket ──────────────────────────────────────────────

@router.websocket("/ws/drones")
async def ws_drones(ws: WebSocket):
    """1 Hz fan-out of telemetry snapshots to the UI."""
    await ws.accept()
    reg: DroneRegistry = ws.app.state.registry

    try:
        while True:
            snapshots = reg.list()
            await ws.send_json({"ts": time.time(), "drones": snapshots, "alerts": reg.pop_alerts()})
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
