"""The obs-websocket v5 bridge: this process is the client, and the password never leaves it.

    from live.lib import obs
    bridge = obs.Bridge()
    await bridge.start()          # returns immediately; connects in the background
    bridge.state()                # always a dict, never raises, never blocks

## Why FastAPI is the client and port 28001 is not proxied

Garrett asked, three times, for port 28001 to be reachable through the site without opening a
router port -- "you can port this where i would not need to open port 28001 on router
correct?". The answer is yes, and the shape that gets there is NOT a proxy.

obs-websocket v5 authenticates with a SHA256 challenge/response over the socket. A browser
speaking to it directly needs the password, so proxying 28001 out to 443 would hand the
stream-control credential to every visitor -- and that credential is not read-only: anyone
holding it can switch scenes, stop the recording and stop the stream. `scripts/symoneural-ui.sh`
already refuses the same trade for the node editor and says why in its header ("Binding
0.0.0.0 here would put an unauthenticated node editor with filesystem access on a box with a
public IP").

So the socket stays on loopback and this process connects to it. The password lives in
`symoneural-live.env`, mode 600, and what reaches a visitor is a dict of readings assembled
here. Nothing on 28001 is exposed, so nothing has to be forwarded.

Measured 2026-08-21: obs-websocket v5 has no bind-address setting, so OBS is listening on
`0.0.0.0:28001` and is reachable from the LAN today. That is not this module's problem to fix
-- it is a note for whoever wonders why the loopback rule is stated so heavily.

## RecordStateChanged, not StreamStateChanged

The HLS this site serves comes out of OBS's **Recording** output, because the Stream output is
his YouTube feed and taking it would stop him streaming to YouTube. The recording output fires
`RecordStateChanged`. Subscribe to the wrong one and the site reads offline while segments are
being written to disk, with nothing wrong in any log to find -- the same silent shape as the
`/studio/comfy` cookie-path drift, where every piece worked and the pairing did not.
`tests/test_live.py::TheRecordOutputIsWhatTheSiteWatchesTests` asserts the pairing, because
getting it right once is not the same as it staying right.

Both are tracked and reported; only the record one drives `live`.

## Never raises, never blocks a request

`state()` is read by a route. It returns whatever the background task last saw, including
"never connected" and "the password is wrong", each said in words. A bridge that is down must
degrade the page to a video with no telemetry, never to an error -- the video path in `hls.py`
holds no credential and does not import this module, so it keeps working regardless.

## Protocol note

obs-websocket 5.x, opcodes as published by the project: 0 Hello, 1 Identify, 2 Identified,
5 Event, 6 Request, 7 RequestResponse. There is no copy of that specification in
`external/`, so the shapes below are the wire's and are validated rather than assumed: an
unexpected Hello is reported as `detail` instead of being pattern-matched past. If OBS changes
its handshake this says so in words on the page.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import os
import time

# obs-websocket 5.x opcodes.
OP_HELLO = 0
OP_IDENTIFY = 1
OP_IDENTIFIED = 2
OP_EVENT = 5
OP_REQUEST = 6
OP_REQUEST_RESPONSE = 7

# EventSubscription bit for the Outputs group, which carries RecordStateChanged and
# StreamStateChanged; General (bit 0) carries ExitStarted. Scenes (bit 2) carries
# CurrentProgramSceneChanged. Only what is displayed is subscribed to: an unsubscribed event
# is one this process never has to hold, and the scene name is the most sensitive thing on
# this page -- see `SCENE_NAMES` in `routes.py`.
SUB_GENERAL = 1 << 0
SUB_SCENES = 1 << 2
SUB_OUTPUTS = 1 << 6
SUBSCRIPTIONS = SUB_GENERAL | SUB_SCENES | SUB_OUTPUTS

RPC_VERSION = 1

# How often GetStats is asked for. OBS renders at 60fps here; a reading a second is plenty for
# a dropped-frame counter and is two orders of magnitude below anything that would cost OBS
# something. Events are pushed, so this poll only covers the numbers that have no event.
POLL_S = 2.0

# Reconnect backoff. Starts fast because the common case is "OBS has not been started yet"
# and he will start it while looking at the page; caps low because this is loopback and a
# retry costs nothing.
BACKOFF_START_S = 1.0
BACKOFF_MAX_S = 15.0


def _auth_response(password: str, salt: str, challenge: str) -> str:
    """The v5 challenge/response.

    base64(sha256(base64(sha256(password + salt)) + challenge)). Written out rather than
    folded into one expression because getting the two rounds the wrong way round produces a
    perfectly well-formed string that OBS rejects with an unhelpful close code, and the next
    person needs to be able to read the steps.
    """
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def configured() -> tuple[bool, str]:
    """Is there a password to connect with, and if not, what should be said about it.

    A missing password is a normal state, not a fault: the video path needs no credential, so
    a fresh box serves the stream and reports the bridge as unconfigured. The env var is named
    in the message because "not configured" without the variable's name is a message that
    makes somebody grep.
    """
    if _env("SYMONEURAL_OBS_PASSWORD"):
        return True, ""
    return False, ("SYMONEURAL_OBS_PASSWORD is not set — scene, bitrate and dropped-frame "
                   "readings are unavailable. The video itself does not need it. "
                   "See backend/live/README.md.")


class Bridge:
    """One long-lived connection to OBS, and the last thing it said.

    Owned by `api.py`'s lifespan: started once at boot, stopped once at shutdown. It is not
    per-request and must never be constructed inside a route -- a connection per request would
    re-run the SHA256 handshake on every page load and OBS rate-limits nothing, so the failure
    would be silent and only visible as latency.
    """

    def __init__(self, host: str | None = None, port: int | None = None,
                 password: str | None = None) -> None:
        self.host = host or _env("SYMONEURAL_OBS_HOST", "127.0.0.1")
        self.port = port if port is not None else int(_env("SYMONEURAL_OBS_PORT", "28001"))
        self._password = password if password is not None else _env("SYMONEURAL_OBS_PASSWORD")
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._next_id = 0

        # Everything a reader may see. Seeded with the honest starting state rather than with
        # zeros: a dropped-frame count of 0 before anything has connected is a decorative
        # gauge, which this project bars outright.
        self._s: dict = {
            "connected": False,
            "detail": "not started",
            "obs_version": None,
            "recording": None,        # None = unknown, not False
            "streaming": None,
            "record_state": None,     # the last OBS_WEBSOCKET_OUTPUT_* string seen
            "stream_state": None,
            "scene": None,
            "fps": None,
            "cpu_percent": None,
            "render_skipped": None,
            "output_skipped": None,
            "connected_since": None,
            "last_reading": None,
        }

    # -- reading -----------------------------------------------------------------------

    def state(self) -> dict:
        """A copy of the last reading. Never raises, never blocks, never awaits."""
        return dict(self._s)

    # -- lifecycle ---------------------------------------------------------------------

    async def start(self) -> None:
        ok, why = configured()
        if not ok:
            self._s["detail"] = why
            return
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="obs-bridge")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._s["connected"] = False
        self._s["detail"] = "stopped"

    # -- the connection loop -----------------------------------------------------------

    async def _run(self) -> None:
        backoff = BACKOFF_START_S
        while not self._stop.is_set():
            try:
                await self._session()
                backoff = BACKOFF_START_S
            except asyncio.CancelledError:
                raise
            except Exception as exc:                          # noqa: BLE001
                # Deliberately broad. This task must outlive every failure mode of a socket
                # to a program the user starts and stops by hand: refused, reset, killed
                # mid-frame, replaced by a different OBS. The exception TYPE is reported --
                # `ConnectionRefusedError` tells an operator "OBS is not running" and a
                # message of "" tells them nothing.
                self._s["connected"] = False
                self._s["connected_since"] = None
                self._s["detail"] = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            if self._stop.is_set():
                break
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=backoff)
            backoff = min(backoff * 2, BACKOFF_MAX_S)

    async def _session(self) -> None:
        # Imported here rather than at module scope so that importing this module -- which
        # `apps/live/__init__.py` does, and every test collection therefore does -- cannot
        # fail on a box without the library. `python3-websockets` is a Debian package and is
        # present on the serving interpreter (checked 2026-08-21), but an import that only
        # matters when the bridge actually runs belongs where the bridge actually runs.
        import websockets

        url = f"ws://{self.host}:{self.port}"
        async with websockets.connect(url, open_timeout=5, ping_interval=20) as ws:
            hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if hello.get("op") != OP_HELLO:
                raise RuntimeError(f"expected Hello (op {OP_HELLO}), got op {hello.get('op')}")
            d = hello.get("d") or {}
            ident: dict = {"rpcVersion": RPC_VERSION, "eventSubscriptions": SUBSCRIPTIONS}
            auth = d.get("authentication")
            if auth:
                try:
                    ident["authentication"] = _auth_response(
                        self._password, auth["salt"], auth["challenge"])
                except KeyError as exc:
                    raise RuntimeError(
                        f"Hello asked for authentication but carried no {exc}") from None
            elif self._password:
                # Not an error. Worth saying, because "I set a password and it is being
                # ignored" is a real misconfiguration: OBS's Enable Authentication box is off.
                self._s["detail"] = ("OBS is not requiring authentication — the password in "
                                     "symoneural-live.env is unused. Tick Enable "
                                     "Authentication in OBS.")

            await ws.send(json.dumps({"op": OP_IDENTIFY, "d": ident}))
            got = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if got.get("op") != OP_IDENTIFIED:
                raise RuntimeError(
                    f"Identify rejected: op {got.get('op')} {json.dumps(got.get('d'))[:200]}")

            self._s["connected"] = True
            self._s["connected_since"] = time.time()
            self._s["obs_version"] = d.get("obsWebSocketVersion")
            if "not requiring authentication" not in (self._s.get("detail") or ""):
                self._s["detail"] = ""

            # The state OBS is already in. Without this, a page loaded while a recording is
            # already running reads "not recording" until the next state CHANGE -- which for
            # a stream that started an hour ago is never.
            await self._request(ws, "GetRecordStatus")
            await self._request(ws, "GetStreamStatus")
            await self._request(ws, "GetCurrentProgramScene")

            poller = asyncio.create_task(self._poll(ws))
            try:
                async for raw in ws:
                    self._ingest(json.loads(raw))
            finally:
                poller.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await poller
        self._s["connected"] = False
        self._s["connected_since"] = None
        self._s["detail"] = self._s["detail"] or "OBS closed the connection"

    async def _poll(self, ws) -> None:
        while True:
            await asyncio.sleep(POLL_S)
            await self._request(ws, "GetStats")

    async def _request(self, ws, request_type: str, data: dict | None = None) -> None:
        """Fire and forget: the reply arrives on the same socket and `_ingest` files it.

        No response correlation and no futures, on purpose. Every request this module makes is
        a poll whose answer updates a field; nothing here needs to await a specific reply, and
        a pending-futures table is a memory leak waiting for a socket that dies mid-request.
        """
        self._next_id += 1
        await ws.send(json.dumps({
            "op": OP_REQUEST,
            "d": {"requestType": request_type, "requestId": str(self._next_id),
                  "requestData": data or {}},
        }))

    # -- interpreting what arrives -----------------------------------------------------

    def _ingest(self, msg: dict) -> None:
        op = msg.get("op")
        d = msg.get("d") or {}
        if op == OP_EVENT:
            self._event(d.get("eventType", ""), d.get("eventData") or {})
        elif op == OP_REQUEST_RESPONSE:
            self._response(d.get("requestType", ""), d.get("responseData") or {})
        self._s["last_reading"] = time.time()

    def _event(self, kind: str, data: dict) -> None:
        # `RecordStateChanged` is the one that drives the site's LIVE lamp -- see the module
        # docstring. `StreamStateChanged` is tracked and displayed but drives nothing here,
        # because it is his YouTube feed and the site is not serving that.
        if kind == "RecordStateChanged":
            self._s["recording"] = bool(data.get("outputActive"))
            self._s["record_state"] = data.get("outputState")
        elif kind == "StreamStateChanged":
            self._s["streaming"] = bool(data.get("outputActive"))
            self._s["stream_state"] = data.get("outputState")
        elif kind == "CurrentProgramSceneChanged":
            self._s["scene"] = data.get("sceneName")
        elif kind == "ExitStarted":
            self._s["detail"] = "OBS is shutting down"

    def _response(self, kind: str, data: dict) -> None:
        if kind == "GetRecordStatus":
            self._s["recording"] = bool(data.get("outputActive"))
        elif kind == "GetStreamStatus":
            self._s["streaming"] = bool(data.get("outputActive"))
        elif kind == "GetCurrentProgramScene":
            # OBS 5.5 renamed this field and kept the old one; read either rather than pin a
            # version, since the value is the same string both times.
            self._s["scene"] = data.get("sceneName") or data.get("currentProgramSceneName")
        elif kind == "GetStats":
            self._s["fps"] = data.get("activeFps")
            self._s["cpu_percent"] = data.get("cpuUsage")
            self._s["render_skipped"] = data.get("renderSkippedFrames")
            self._s["output_skipped"] = data.get("outputSkippedFrames")
