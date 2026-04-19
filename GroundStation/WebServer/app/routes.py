"""HTTP + WebSocket routes for the ARGUS Hub."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from .registry import DroneEntry, DroneRegistry

log = logging.getLogger(__name__)

router = APIRouter()

FORWARD_INTERVAL = 0.05   # seconds — 20 Hz cap for WS-driven stick forwarding
DEADMAN_TIMEOUT = 0.5     # seconds — stop drone if no WS input for this long
TELEMETRY_FANOUT_INTERVAL = 1.0  # seconds — per-drone snapshot rate on /ws/drones


# ── Pydantic models ──────────────────────────────────────────────────

class StickCommand(BaseModel):
    leftX: float = Field(0.0, ge=-1.0, le=1.0)
    leftY: float = Field(0.0, ge=-1.0, le=1.0)
    rightX: float = Field(0.0, ge=-1.0, le=1.0)
    rightY: float = Field(0.0, ge=-1.0, le=1.0)


class DroneCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    label: Optional[str] = None
    rc_ip: str = Field(..., min_length=1)
    home_lat: Optional[float] = None
    home_lng: Optional[float] = None
    # reach_m is optional at registration — the dashboard picks it via a
    # post-placement slider and can PATCH it any time afterwards.
    reach_m: Optional[int] = Field(None, ge=50)
    mock: bool = False
    enable_video: bool = True


class DroneUpdate(BaseModel):
    label: Optional[str] = None
    reach_m: Optional[int] = Field(None, ge=50, le=10000)
    home_lat: Optional[float] = None
    home_lng: Optional[float] = None


# ── Helpers ──────────────────────────────────────────────────────────

def _registry(request: Request) -> DroneRegistry:
    return request.app.state.registry


def _entry(request: Request, drone_id: str) -> DroneEntry:
    reg = _registry(request)
    entry = reg.get(drone_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown drone: {drone_id}")
    entry.ensure_started()
    return entry


def _telemetry_snapshot(entry: DroneEntry) -> dict:
    """Best-effort snapshot for dashboard display."""
    snap = {
        "id": entry.id,
        "label": entry.label,
        "rc_ip": entry.rc_ip,
        "mock": entry.mock,
        "home_lat": entry.home_lat,
        "home_lng": entry.home_lng,
        "reach_m": entry.reach_m,
    }
    client = getattr(entry, "client", None)
    video = getattr(entry, "video", None)

    # LiveDroneClient wraps a DJIInterface exposing lat/lon/battery/etc.
    dji = getattr(client, "_dji", None)
    if dji is not None:
        for method, key in (
            ("getLocation", "location"),
            ("getAttitude", "attitude"),
            ("getBatteryLevel", "battery"),
            ("getSpeed", "speed"),
            ("getHeading", "heading"),
        ):
            fn = getattr(dji, method, None)
            if not callable(fn):
                continue
            try:
                snap[key] = fn()
            except Exception:
                snap[key] = None

    # Normalize: if we have a location, also flatten into lat/lng for the map.
    loc = snap.get("location")
    if isinstance(loc, dict):
        snap["lat"] = loc.get("lat") or loc.get("latitude")
        snap["lng"] = loc.get("lng") or loc.get("lon") or loc.get("longitude")
    elif isinstance(loc, (list, tuple)) and len(loc) >= 2:
        snap["lat"], snap["lng"] = loc[0], loc[1]

    if snap.get("lat") is None and entry.home_lat is not None:
        snap["lat"] = entry.home_lat
        snap["lng"] = entry.home_lng

    if video is not None:
        try:
            vstat = video.status()
        except Exception:
            vstat = {"connected": False, "mode": "unknown"}
        snap["video"] = vstat
        snap["online"] = bool(vstat.get("connected")) or entry.mock
    else:
        snap["video"] = None
        snap["online"] = entry.mock

    return snap


# ── Health / registry CRUD ───────────────────────────────────────────

@router.get("/api/health")
def health(request: Request):
    reg = _registry(request)
    return {"ok": True, "drones": [e.id for e in reg.list()]}


@router.get("/api/drones")
def list_drones(request: Request):
    reg = _registry(request)
    return {"drones": [_telemetry_snapshot(e) for e in reg.list()]}


@router.post("/api/drones", status_code=201)
def add_drone(payload: DroneCreate, request: Request):
    reg = _registry(request)
    defaults = request.app.state.defaults
    entry = DroneEntry(
        id=payload.id,
        label=payload.label or payload.id,
        rc_ip=payload.rc_ip,
        home_lat=payload.home_lat,
        home_lng=payload.home_lng,
        reach_m=payload.reach_m if payload.reach_m is not None else 800,
        mock=payload.mock or bool(defaults.get("mock")),
        max_stick=float(defaults.get("max_stick", 0.1)),
        enable_video=payload.enable_video and not bool(defaults.get("no_video")),
    )
    try:
        reg.add(entry)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _telemetry_snapshot(entry)


@router.delete("/api/drones/{drone_id}", status_code=204)
def delete_drone(drone_id: str, request: Request):
    if not _registry(request).remove(drone_id):
        raise HTTPException(status_code=404, detail=f"unknown drone: {drone_id}")
    return Response(status_code=204)


@router.get("/api/drones/{drone_id}")
def get_drone(drone_id: str, request: Request):
    return _telemetry_snapshot(_entry(request, drone_id))


@router.patch("/api/drones/{drone_id}")
def update_drone(drone_id: str, payload: DroneUpdate, request: Request):
    reg = _registry(request)
    entry = reg.get(drone_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown drone: {drone_id}")
    if payload.label is not None:
        entry.label = payload.label
    if payload.reach_m is not None:
        entry.reach_m = payload.reach_m
    if payload.home_lat is not None:
        entry.home_lat = payload.home_lat
    if payload.home_lng is not None:
        entry.home_lng = payload.home_lng
    reg.persist()
    return _telemetry_snapshot(entry)


# ── Per-drone control ────────────────────────────────────────────────

@router.post("/api/drones/{drone_id}/virtual-stick/enable")
async def virtual_stick_enable(drone_id: str, request: Request):
    entry = _entry(request, drone_id)
    resp = await asyncio.to_thread(entry.client.enable_virtual_stick)
    return {"response": resp}


@router.post("/api/drones/{drone_id}/virtual-stick/disable")
async def virtual_stick_disable(drone_id: str, request: Request):
    entry = _entry(request, drone_id)
    resp = await asyncio.to_thread(entry.client.disable_virtual_stick)
    return {"response": resp}


@router.post("/api/drones/{drone_id}/stick")
async def send_stick(drone_id: str, cmd: StickCommand, request: Request):
    entry = _entry(request, drone_id)
    resp = await asyncio.to_thread(
        entry.client.send_stick, cmd.leftX, cmd.leftY, cmd.rightX, cmd.rightY
    )
    return {"response": resp}


@router.post("/api/drones/{drone_id}/takeoff")
async def takeoff(drone_id: str, request: Request):
    entry = _entry(request, drone_id)
    return {"response": await asyncio.to_thread(entry.client.takeoff)}


@router.post("/api/drones/{drone_id}/land")
async def land(drone_id: str, request: Request):
    entry = _entry(request, drone_id)
    return {"response": await asyncio.to_thread(entry.client.land)}


@router.post("/api/drones/{drone_id}/rth")
async def rth(drone_id: str, request: Request):
    entry = _entry(request, drone_id)
    return {"response": await asyncio.to_thread(entry.client.rth)}


class GimbalPitchCommand(BaseModel):
    pitch: float = Field(..., ge=-90.0, le=30.0)  # DJI gimbal joint range


@router.post("/api/drones/{drone_id}/gimbal/pitch")
async def gimbal_pitch(drone_id: str, cmd: GimbalPitchCommand, request: Request):
    entry = _entry(request, drone_id)
    resp = await asyncio.to_thread(entry.client.set_gimbal_pitch, cmd.pitch)
    return {"response": resp}


# ── Per-drone stick WebSocket ────────────────────────────────────────

@router.websocket("/ws/drones/{drone_id}/stick")
async def ws_stick(ws: WebSocket, drone_id: str):
    """
    Continuous stream of {leftX, leftY, rightX, rightY} → RC at ≤20 Hz.
    Deadman: 500 ms of silence zeros the sticks once; on disconnect we
    always send one zero-stick packet as a final safety stop.
    """
    reg: DroneRegistry = ws.app.state.registry
    entry = reg.get(drone_id)
    if entry is None:
        await ws.close(code=4404, reason=f"unknown drone: {drone_id}")
        return
    entry.ensure_started()
    client = entry.client

    await ws.accept()

    latest = {"leftX": 0.0, "leftY": 0.0, "rightX": 0.0, "rightY": 0.0}
    last_input_ts = time.time()
    last_sent_ts = 0.0
    stopped = True

    async def forwarder():
        nonlocal last_sent_ts, stopped
        while True:
            await asyncio.sleep(FORWARD_INTERVAL)
            now = time.time()

            if now - last_input_ts > DEADMAN_TIMEOUT:
                if not stopped:
                    await asyncio.to_thread(client.send_stick, 0.0, 0.0, 0.0, 0.0)
                    stopped = True
                continue

            if now - last_sent_ts < FORWARD_INTERVAL:
                continue

            all_zero = not any(latest.values())
            if all_zero and stopped:
                continue

            await asyncio.to_thread(
                client.send_stick,
                latest["leftX"], latest["leftY"],
                latest["rightX"], latest["rightY"],
            )
            last_sent_ts = now
            stopped = all_zero

    task = asyncio.create_task(forwarder())
    try:
        while True:
            msg = await ws.receive_json()
            try:
                latest["leftX"] = float(msg.get("leftX", 0.0))
                latest["leftY"] = float(msg.get("leftY", 0.0))
                latest["rightX"] = float(msg.get("rightX", 0.0))
                latest["rightY"] = float(msg.get("rightY", 0.0))
            except (TypeError, ValueError):
                continue
            last_input_ts = time.time()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("ws_stick[%s] error: %s", drone_id, exc)
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await asyncio.to_thread(client.send_stick, 0.0, 0.0, 0.0, 0.0)
        except Exception as exc:
            log.warning("ws_stick[%s] final safety-stop failed: %s", drone_id, exc)


# ── Dashboard telemetry fan-out ──────────────────────────────────────

@router.websocket("/ws/drones")
async def ws_drones(ws: WebSocket):
    """1 Hz fan-out of telemetry snapshots for the map dashboard."""
    await ws.accept()
    reg: DroneRegistry = ws.app.state.registry

    try:
        while True:
            snapshots = [_telemetry_snapshot(e) for e in reg.list()]
            await ws.send_json({"ts": time.time(), "drones": snapshots})
            await asyncio.sleep(TELEMETRY_FANOUT_INTERVAL)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("ws_drones error: %s", exc)


# ── Per-drone video ──────────────────────────────────────────────────

MJPEG_BOUNDARY = "frame"


def _video(entry: DroneEntry):
    v = getattr(entry, "video", None)
    if v is None:
        raise HTTPException(status_code=503, detail=f"video not enabled for {entry.id}")
    return v


@router.get("/api/drones/{drone_id}/video/status")
def video_status(drone_id: str, request: Request):
    return _video(_entry(request, drone_id)).status()


@router.get("/api/drones/{drone_id}/video/snapshot.jpg")
def video_snapshot(drone_id: str, request: Request):
    v = _video(_entry(request, drone_id))
    jpeg, ts = v.get_latest_jpeg()
    if jpeg is None:
        raise HTTPException(status_code=503, detail="no frame yet")
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store", "X-Frame-Timestamp": f"{ts:.3f}"},
    )


@router.get("/api/drones/{drone_id}/video.mjpg")
async def video_mjpeg(drone_id: str, request: Request):
    """Multipart MJPEG stream consumed by the browser <img>."""
    v = _video(_entry(request, drone_id))

    async def gen():
        last_ts = 0.0
        boundary = f"--{MJPEG_BOUNDARY}".encode()
        while True:
            if await request.is_disconnected():
                return
            jpeg, ts = v.get_latest_jpeg()
            if jpeg is None or ts == last_ts:
                await asyncio.sleep(0.02)
                continue
            last_ts = ts
            yield boundary + b"\r\n"
            yield b"Content-Type: image/jpeg\r\n"
            yield f"Content-Length: {len(jpeg)}\r\n\r\n".encode()
            yield jpeg
            yield b"\r\n"

    return StreamingResponse(
        gen(),
        media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


# ── Mission plans (stub persistence) ─────────────────────────────────

class PlanSave(BaseModel):
    name: Optional[str] = None
    drones: list = Field(default_factory=list)
    paths: dict = Field(default_factory=dict)
    params: dict = Field(default_factory=dict)


@router.post("/api/plans", status_code=201)
def save_plan(payload: PlanSave, request: Request):
    """Persist a planned mission (drone placements + Boustrophedon paths) as JSON."""
    from pathlib import Path
    import json

    plans_dir: Path = request.app.state.plans_dir
    plans_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = payload.name or f"plan-{stamp}"
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    path = plans_dir / f"{safe}.json"
    path.write_text(
        json.dumps(
            {"saved_at": time.time(), "name": name, **payload.model_dump()},
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"name": name, "path": str(path)}
