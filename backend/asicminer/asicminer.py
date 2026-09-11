"""asicminer: routes that were declared on `app` in server.py.

Paths here are absolute, so this router is mounted WITHOUT a prefix.
Globals come off `core.context.ctx`; importing server would be a cycle.
"""
from __future__ import annotations

from fastapi import (Depends, FastAPI, HTTPException, Request, Response, WebSocket,
                     WebSocketDisconnect, status as http)
import asicminer  # noqa: E402
import streamer  # noqa: E402  -- the IPTV surface AND the Guide that filters
from streamer import guide  # noqa: E402  -- the library half: matching, clustering,
import studio  # noqa: E402  -- the local agent and the

from fastapi import APIRouter

from core.context import ctx

router = APIRouter()


@router.get("/api/asicminer/firmware", tags=["asicminer"],
         summary="Firmware packages actually present on this machine")
async def asic_firmware(request: Request) -> dict:
    # Read off disk rather than from a list in the page, so the model picker cannot claim
    # firmware that is not there, or miss firmware that is.
    return {"packages": asicminer.packages()}
@router.post("/api/asicminer/scan", tags=["asicminer"],
          summary="Discover rigs on a private network")
async def asic_scan(request: Request, body: ctx.ScanBody) -> dict:
    if not body.cidr.strip():
        raise HTTPException(400, "give a CIDR, e.g. 10.0.0.0/24")
    return await asicminer.discover(body.cidr.strip())
@router.post("/api/asicminer/emulator", tags=["asicminer"],
          summary="Start, stop or query the QEMU emulator")
async def asic_emulator(request: Request, body: ctx.EmuBody) -> dict:
    if body.action == "status":
        return asicminer.emulator_status()
    if body.action == "stop":
        return asicminer.emulator_stop()
    if not body.package:
        raise HTTPException(400, "no package id given")
    return asicminer.emulator_start(body.package)
