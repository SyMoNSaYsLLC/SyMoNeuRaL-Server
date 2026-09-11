"""Prove the obs-websocket handshake works, without anybody typing or reading the password.

    cd backend && python3 -m live.verify_bridge

This is the check that `tests/test_live.py` cannot make and `tests/live.mjs` must not make: a
real handshake against the real OBS on this box. It exists because the v5 auth is
`base64(sha256(base64(sha256(password + salt)) + challenge))`, and getting the two rounds the
wrong way round produces a perfectly well-formed 44-character string that OBS rejects with an
unhelpful close code. Nothing offline can tell the difference between that and a correct one.

## Why it reads OBS's own config file

The password never enters a terminal, a transcript, a shell history or an environment
variable. It is read out of

    ~/.var/app/com.obsproject.Studio/config/obs-studio/plugin_config/obs-websocket/config.json

which is where obs-websocket keeps it, used for one handshake, and never printed. What this
prints is a length, a version, and PASS or FAIL. That matters more here than it usually would:
this credential was already displayed once in a screenshot -- along with a QR code encoding the
same value -- and the rule that came out of it is that a credential which has been displayed is
spent. Re-displaying it to test it would be the same mistake with better intentions.

The path is Flatpak's. A non-Flatpak OBS keeps the same file under `~/.config/obs-studio/`,
and both are tried.

## What a failure means

    ConnectionRefusedError      OBS is not running, or its websocket server is switched off
                                (Tools -> WebSocket Server Settings -> Enable WebSocket server).
    1001 "Server stopping"      OBS was shutting down as this connected. Start it and re-run.
    op 5 with an auth message   the password in the config file is not the one OBS is using,
                                which happens if it was regenerated and not saved.
    identified, then nothing    not a failure. OBS idle sends no events; the GetStats reply
                                below is what proves the request path.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

from .obs import (OP_HELLO, OP_IDENTIFIED, OP_IDENTIFY, RPC_VERSION, SUBSCRIPTIONS,
                  _auth_response)

CONFIG_PATHS = (
    pathlib.Path.home() / ".var/app/com.obsproject.Studio/config/obs-studio"
                          "/plugin_config/obs-websocket/config.json",
    pathlib.Path.home() / ".config/obs-studio/plugin_config/obs-websocket/config.json",
)

PROBES = ("GetVersion", "GetRecordStatus", "GetStreamStatus", "GetStats")


def _config() -> dict:
    for p in CONFIG_PATHS:
        if p.is_file():
            print(f"config     {p}")
            return json.loads(p.read_text())
    raise SystemExit("no obs-websocket config.json found; is OBS installed?")


async def main() -> int:
    import websockets

    cfg = _config()
    port = int(cfg.get("server_port", 28001))
    password = cfg.get("server_password", "")            # read, never printed
    print(f"server     enabled={cfg.get('server_enabled')} "
          f"auth_required={cfg.get('auth_required')} port={port} "
          f"password_length={len(password)}")

    async with websockets.connect(f"ws://127.0.0.1:{port}", open_timeout=5) as ws:
        hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        if hello.get("op") != OP_HELLO:
            print(f"FAIL       expected Hello (op {OP_HELLO}), got op {hello.get('op')}")
            return 1
        d = hello["d"]
        print(f"hello      obs-websocket {d.get('obsWebSocketVersion')} "
              f"rpc {d.get('rpcVersion')} auth={'yes' if d.get('authentication') else 'no'}")

        ident: dict = {"rpcVersion": RPC_VERSION, "eventSubscriptions": SUBSCRIPTIONS}
        if d.get("authentication"):
            ident["authentication"] = _auth_response(
                password, d["authentication"]["salt"], d["authentication"]["challenge"])
        await ws.send(json.dumps({"op": OP_IDENTIFY, "d": ident}))

        got = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        if got.get("op") != OP_IDENTIFIED:
            print(f"FAIL       Identify rejected: {json.dumps(got)[:300]}")
            return 1
        print("PASS       identified — the challenge/response in obs.py is correct, "
              f"negotiated rpc {got['d'].get('negotiatedRpcVersion')}")

        for rt in PROBES:
            await ws.send(json.dumps({"op": 6, "d": {"requestType": rt, "requestId": rt,
                                                     "requestData": {}}}))
        seen = set()
        while len(seen) < len(PROBES):
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if msg.get("op") != 7:
                continue
            kind = msg["d"]["requestType"]
            rd = msg["d"].get("responseData") or {}
            seen.add(kind)
            if kind == "GetVersion":
                print(f"  obs      {rd.get('obsVersion')} on {rd.get('platformDescription')}")
            elif kind == "GetRecordStatus":
                print(f"  record   active={rd.get('outputActive')} "
                      f"timecode={rd.get('outputTimecode')}")
            elif kind == "GetStreamStatus":
                print(f"  stream   active={rd.get('outputActive')}")
            elif kind == "GetStats":
                print(f"  stats    fps={rd.get('activeFps')} cpu={rd.get('cpuUsage')} "
                      f"renderSkipped={rd.get('renderSkippedFrames')} "
                      f"outputSkipped={rd.get('outputSkippedFrames')}")
    print("PASS       every probe answered")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
