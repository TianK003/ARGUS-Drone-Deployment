"""HTTP + WebSocket routes for the web backend."""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

router = APIRouter()

FORWARD_INTERVAL = 0.05   # seconds — 20 Hz cap for WS-driven stick forwarding
DEADMAN_TIMEOUT = 0.5     # seconds — stop drone if no WS input for this long


class StickCommand(BaseModel):
    leftX: float = Field(0.0, ge=-1.0, le=1.0)
    leftY: float = Field(0.0, ge=-1.0, le=1.0)
    rightX: float = Field(0.0, ge=-1.0, le=1.0)
    rightY: float = Field(0.0, ge=-1.0, le=1.0)


def _client(request: Request):
    return request.app.state.drone_client


@router.get("/api/health")
def health(request: Request):
    c = _client(request)
    recent = [
        {"ts": e.ts, "action": e.action, "detail": e.detail, "response": e.response}
        for e in list(c.last_calls)[-10:]
    ]
    return {
        "ok": True,
        "mode": c.mode,
        "rc_ip": c.rc_ip,
        "max_stick": c.max_stick,
        "recent_calls": recent,
    }


@router.post("/api/virtual-stick/enable")
async def virtual_stick_enable(request: Request):
    resp = await asyncio.to_thread(_client(request).enable_virtual_stick)
    return {"response": resp}


@router.post("/api/virtual-stick/disable")
async def virtual_stick_disable(request: Request):
    resp = await asyncio.to_thread(_client(request).disable_virtual_stick)
    return {"response": resp}


@router.post("/api/stick")
async def stick(cmd: StickCommand, request: Request):
    resp = await asyncio.to_thread(
        _client(request).send_stick, cmd.leftX, cmd.leftY, cmd.rightX, cmd.rightY
    )
    return {"response": resp}


@router.post("/api/takeoff")
async def takeoff(request: Request):
    return {"response": await asyncio.to_thread(_client(request).takeoff)}


@router.post("/api/land")
async def land(request: Request):
    return {"response": await asyncio.to_thread(_client(request).land)}


@router.post("/api/rth")
async def rth(request: Request):
    return {"response": await asyncio.to_thread(_client(request).rth)}


@router.websocket("/ws/stick")
async def ws_stick(ws: WebSocket):
    """
    Accepts a stream of {leftX, leftY, rightX, rightY} JSON messages and forwards
    them to the RC at ≤20 Hz. Safety: if the socket closes or falls silent for
    500 ms while the sticks are non-zero, a zeroed stick command is sent once.
    """
    await ws.accept()
    client = ws.app.state.drone_client

    latest = {"leftX": 0.0, "leftY": 0.0, "rightX": 0.0, "rightY": 0.0}
    last_input_ts = time.time()
    last_sent_ts = 0.0
    stopped = True  # drone is currently in a "zero stick" state

    async def forwarder():
        nonlocal last_sent_ts, stopped
        while True:
            await asyncio.sleep(FORWARD_INTERVAL)
            now = time.time()

            # Deadman: no input for a while → make sure the drone is stopped.
            if now - last_input_ts > DEADMAN_TIMEOUT:
                if not stopped:
                    await asyncio.to_thread(client.send_stick, 0.0, 0.0, 0.0, 0.0)
                    stopped = True
                continue

            if now - last_sent_ts < FORWARD_INTERVAL:
                continue

            all_zero = not any(latest.values())
            if all_zero and stopped:
                continue  # don't spam zeros once the drone has already been stopped

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
        log.warning("ws_stick error: %s", exc)
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await asyncio.to_thread(client.send_stick, 0.0, 0.0, 0.0, 0.0)
        except Exception as exc:
            log.warning("final safety-stop failed: %s", exc)


# ── Video ────────────────────────────────────────────────────────────

MJPEG_BOUNDARY = "frame"


def _video(request: Request):
    v = request.app.state.video
    if v is None:
        raise HTTPException(status_code=503, detail="Video broadcaster not configured")
    return v


@router.get("/api/video/status")
def video_status(request: Request):
    return _video(request).status()


@router.get("/api/video/snapshot.jpg")
def video_snapshot(request: Request):
    jpeg, ts = _video(request).get_latest_jpeg()
    if jpeg is None:
        raise HTTPException(status_code=503, detail="No video frame available yet")
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store", "X-Frame-Timestamp": f"{ts:.3f}"},
    )


@router.get("/api/video.mjpg")
async def video_mjpeg(request: Request):
    """Multipart MJPEG stream; consumed by the browser with a plain <img src>."""
    v = _video(request)

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
