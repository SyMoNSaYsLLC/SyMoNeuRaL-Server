"""cryptominer: routes that were declared on `app` in server.py.

Paths here are absolute, so this router is mounted WITHOUT a prefix.
Globals come off `core.context.ctx`; importing server would be a cycle.
"""
from __future__ import annotations

from fastapi import (Depends, FastAPI, HTTPException, Request, Response, WebSocket,
                     WebSocketDisconnect, status as http)
import cryptominer  # noqa: E402  -- the GPU miner. A DIFFERENT surface from asicminer:
import streamer  # noqa: E402  -- the IPTV surface AND the Guide that filters
from streamer import guide  # noqa: E402  -- the library half: matching, clustering,
import studio  # noqa: E402  -- the local agent and the

from fastapi import APIRouter

from core.context import ctx

router = APIRouter()


@router.get("/api/gpuminer/status", tags=["gpuminer"],
         summary="What the GPU miner is doing, and what it is reporting")
async def gpuminer_status(request: Request) -> dict:
    st = cryptominer.status()
    state, detail = cryptominer.unit_state(st)
    # `hashrate_mh_s` is whatever the miner binary itself printed, or null. It is never
    # derived from the card's specification: a projected hashrate shown where a measured
    # one belongs is exactly the claim this site exists to refuse.
    return {**st, "unit_state": state, "detail": detail}
@router.post("/api/gpuminer/control", tags=["gpuminer"],
          summary="Start or stop the miner. Starting takes the GPU from every other surface.")
async def gpuminer_control(request: Request, body: ctx.MinerBody) -> dict:
    if body.action == "status":
        return cryptominer.status()
    if body.action == "stop":
        return cryptominer.stop()
    return await cryptominer.start()
