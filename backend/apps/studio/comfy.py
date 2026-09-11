"""The ComfyUI bridge: HTTP queueing, WebSocket monitoring, and the GPU lease around both.

Everything in this module was written against the local clone at `<root>/ComfyUI`, not against
documentation. The line numbers in the tables below are that source, and they are here so the
next person can check the claims rather than trust them.

## HTTP surface used (`ComfyUI/server.py`)

| Call | Line | Why |
|---|---|---|
| `POST /prompt` | 1072 | queue a graph; returns `prompt_id` |
| `GET /history/{prompt_id}` | 1059 | outputs after execution |
| `GET /view?filename&subfolder&type` | 516 | fetch a produced image |
| `GET /object_info` | 800 | the node catalogue the canvas and validator use |
| `GET /system_stats` | 686 | liveness probe |
| `POST /interrupt` | 1160 | cancel the running job |
| `POST /free` | 1192 | `{"unload_models":…, "free_memory":…}` -- how the card is given back |

`POST /prompt` replies `{"prompt_id", "number", "node_errors"}` on success and **400** with
`{"error", "node_errors"}` on a graph it will not run. Both shapes are surfaced verbatim;
`node_errors` is the single most useful thing to put in front of a user with a broken graph,
and summarising it would throw away the node id that is wrong.

## WebSocket protocol

`ws://<host>/ws?clientId=<uuid>`, every text frame `{"type": event, "data": data}`
(`server.py:1382`). The events this module relays, all read from source:

| Event | Source | Payload |
|---|---|---|
| `status` | server.py:1397 | queue depth |
| `execution_start` | execution.py:742 | `{prompt_id}` |
| `execution_cached` | execution.py:770 | `{nodes, prompt_id}` -- nodes skipped by the cache |
| `executing` | execution.py:496 | `{node, display_node, prompt_id}` |
| `progress` | main.py:460 | `{value, max, prompt_id, node}` |
| `executed` | execution.py:436/578 | `{node, display_node, output, prompt_id}` |
| `execution_error` | execution.py:536 | traceback and node id |
| `execution_success` | execution.py:824 | `{prompt_id}` |
| `execution_interrupted` | execution.py:699 | broadcast |

**The done sentinel is `executing` with `data["node"] is None`** (`main.py:394`), and that is
what `script_examples/websockets_api_example.py` breaks on. This module treats
`execution_success`, `execution_error`, `execution_interrupted` *and* that sentinel as
terminal, because relying on only one of them is how a monitor hangs forever on a graph that
errored.

Binary frames are latent previews. They are surfaced as preview events rather than dropped,
so the canvas can show a real in-progress image instead of a decorative spinner.

## Two ordering rules that are not optional

1. **Connect the socket before queueing.** ComfyUI starts executing the moment `/prompt`
   returns; a client that queues first and connects second races the first `executing` frame
   and loses it on a cached graph. Connect, *then* POST.
2. **Give the card back before releasing the lock.** See `lease()`.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
import urllib.parse
import uuid
from typing import AsyncIterator

from . import httpclient
import websockets

from . import workspace

__all__ = ["ComfyClient", "base_url", "ws_url", "TERMINAL", "lease", "GovernorError"]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8188

# Terminal in the sense of "stop waiting", not "succeeded". A monitor that only watches for
# execution_success hangs forever on a graph that raised.
TERMINAL = frozenset({"execution_success", "execution_error", "execution_interrupted"})

# Which process this waits on when it asks whether the card came back. A substring of the
# path ComfyUI actually runs from, passed to `gpu-governor.sh drain <substring>`, so the
# question is "has OUR server let go" and not "is the whole card empty" -- chat is often
# legitimately warm at ~8.1 GiB and the second question would answer no about a healthy box.
COMFY_PROC = "symoneural-ui/main.py"


def base_url() -> str:
    """Where ComfyUI is. Loopback by *default*, and the default is all it is.

    The reason for the default stands: the public surface is FastAPI's, and ComfyUI has no
    authentication of its own to put on an open port. But this reads the environment on every
    call and caches nothing, so the destination is chosen per request -- and `env_set` in
    `tools_impl/host.py:150` writes `os.environ` in this same process, which puts the address
    inside what an agent turn can change. Measured: `base_url()` gave `http://127.0.0.1:8188`,
    then `env_set("SYMONEURAL_COMFY_URL", "http://169.254.169.254:80")`, then `base_url()` gave
    `http://169.254.169.254:80` -- the link-local metadata address, fetched by the API process
    on behalf of whoever is driving the agent.

    No allow-list is implemented here as of 2026-08-20 -- a deliberate pre-launch state, not a
    cleared posture (request ledger R-98, held, awaiting re-scope). What keeps this shut is the
    gate in front of the agent, not this function, so do not read the first line as a bound on
    where requests go.
    """
    if (env := os.environ.get("SYMONEURAL_COMFY_URL")):
        return env.rstrip("/")
    host = os.environ.get("SYMONEURAL_COMFY_HOST", DEFAULT_HOST)
    port = os.environ.get("SYMONEURAL_COMFY_PORT", str(DEFAULT_PORT))
    return f"http://{host}:{port}"


def ws_url(client_id: str) -> str:
    scheme = "wss" if base_url().startswith("https") else "ws"
    netloc = base_url().split("://", 1)[1]
    return f"{scheme}://{netloc}/ws?clientId={urllib.parse.quote(client_id)}"


class GovernorError(RuntimeError):
    """The GPU lock could not be taken, or could not be given back cleanly."""


# ---- the governor lease ----------------------------------------------------
def _governor() -> str:
    root = workspace.ROOT
    if root is None:
        raise GovernorError("no project root; cannot find scripts/gpu-governor.sh")
    g = root / "scripts" / "gpu-governor.sh"
    if not g.is_file():
        raise GovernorError(f"governor not found at {g}")
    return str(g)


# `_drain_floor()` used to live here: it read `DRAIN_FLOOR_MIB` out of the shell script and
# this module ran its own poll of `nvidia-smi --query-gpu=memory.used` against it. Reading the
# number across was the right instinct and the wrong unit of sharing -- the *reading* is the
# part that was wrong, not the threshold, and copying the threshold copied the bug with it.
# `drain` counted the KDE desktop as a tenant (R-171), so this poll did too, and the same fix
# had to land in two places or `drained: false` would appear in a record on a card that had
# come back. The governor is now called instead, so there is one implementation and one floor.


async def _run(*argv: str, timeout: float = 330) -> tuple[int, str, str]:
    p = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(p.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            p.kill()
        raise GovernorError(f"{argv[1] if len(argv) > 1 else argv[0]} timed out after {timeout}s")
    return p.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


async def _vram_used_mib() -> int | None:
    try:
        rc, out, _ = await _run("nvidia-smi", "--query-gpu=memory.used",
                                "--format=csv,noheader,nounits", timeout=30)
    except (GovernorError, FileNotFoundError, OSError):
        return None
    if rc != 0:
        return None
    try:
        return int(out.strip().splitlines()[0].strip())
    except (ValueError, IndexError):
        return None


@contextlib.asynccontextmanager
async def lease(surface: str = "comfy", *, timeout: int = 300, free_after: bool = True):
    """Hold the GPU for one job and give it back -- never for a process lifetime.

    `.claude/CLAUDE.md`: *"Hold the lock for a job, never for a process lifetime."* ComfyUI is
    a long-lived server that keeps weights resident, which is exactly the shape the governor
    exists to prevent: with FLUX loaded there is not enough of a 15.9 GiB card left for chat
    or for training, and those surfaces would block on `acquire` until it timed out.

    The resolution is `POST /free` (`server.py:1192`), which is why this context manager, and
    not a plain `acquire`/`release` pair, is the only supported way to run a job here:

        acquire comfy -> run the job -> POST /free -> wait for the driver -> release comfy

    **`/free` sets a queue flag, it does not free synchronously.** So the wait below is a
    real one -- `gpu-governor.sh drain`, scoped to ComfyUI's own process, so there is one
    definition of "drained" in this repo and not a second copy here that has to be fixed
    twice. If the memory has not come back in time this yields `drained: False` in the record
    rather than pretending. The caller decides whether to escalate to stopping the process; this does not
    kill anything it did not start.
    """
    gov = _governor()
    rc, out, err = await _run("bash", gov, "acquire", surface, str(timeout),
                              timeout=timeout + 30)
    if rc != 0:
        raise GovernorError(f"could not acquire '{surface}': {(err or out).strip()[:400]}")

    record: dict = {"surface": surface, "acquired": True, "freed": None, "drained": None,
                    "vram_after_mib": None, "drain_wait_s": None}
    try:
        yield record
    finally:
        if free_after:
            try:
                async with httpclient.AsyncClient(timeout=30) as c:
                    r = await c.post(f"{base_url()}/free",
                                     json={"unload_models": True, "free_memory": True})
                record["freed"] = r.status_code == 200
            except httpclient.HTTPError as e:
                # ComfyUI being gone is a fine reason for /free to fail, and it means the
                # memory is already coming back. Record it; do not raise out of a finally.
                record["freed"] = False
                record["free_error"] = f"{type(e).__name__}: {e}"

            # The governor owns the definition of "drained". Its exit status is the verdict
            # and its own log line carries the reading it acted on; the figure recorded here
            # is the whole card, which is the honest thing to report to a caller and is NOT
            # what the verdict was reached on -- most of it is the KDE session.
            started = time.monotonic()
            try:
                rc, out, err = await _run("bash", _governor(), "drain", COMFY_PROC,
                                          timeout=90)
                record["drained"] = rc == 0
                if rc != 0:
                    record["drain_error"] = (err or out).strip()[-400:]
            except (GovernorError, OSError) as e:
                record["drained"] = False
                record["drain_error"] = f"{type(e).__name__}: {e}"
            record["drain_wait_s"] = round(time.monotonic() - started, 1)
            record["vram_after_mib"] = await _vram_used_mib()

        rc, out, err = await _run("bash", gov, "release", surface, timeout=90)
        record["released"] = rc == 0
        if rc != 0:
            record["release_error"] = (err or out).strip()[:400]


# ---- the client ------------------------------------------------------------
class ComfyClient:
    """One conversation with a ComfyUI server. Cheap to construct; holds no socket until asked."""

    def __init__(self, url: str | None = None, client_id: str | None = None,
                 timeout: float = 60.0) -> None:
        self.url = (url or base_url()).rstrip("/")
        # ComfyUI routes WS frames to the client_id that queued the prompt. Minting one per
        # client instance is what makes the monitor see only its own job's events.
        self.client_id = client_id or str(uuid.uuid4())
        self.timeout = timeout
        self._object_info: dict | None = None

    # -- liveness ------------------------------------------------------------
    async def alive(self) -> dict:
        """Is a server answering, and what is it. Never raises; absence is a reading."""
        try:
            async with httpclient.AsyncClient(timeout=5) as c:
                r = await c.get(f"{self.url}/system_stats")
                if r.status_code != 200:
                    return {"up": False, "url": self.url, "http_status": r.status_code}
                return {"up": True, "url": self.url, "system": r.json()}
        except httpclient.HTTPError as e:
            return {"up": False, "url": self.url, "detail": f"{type(e).__name__}: {e}"}

    # -- catalogue -----------------------------------------------------------
    async def object_info(self, refresh: bool = False) -> dict:
        """The full node catalogue. Cached per client: it is ~2 MB of JSON and it does not
        change while the server is up."""
        if self._object_info is not None and not refresh:
            return self._object_info
        async with httpclient.AsyncClient(timeout=120) as c:
            r = await c.get(f"{self.url}/object_info")
            r.raise_for_status()
            self._object_info = r.json()
        return self._object_info

    # -- queueing ------------------------------------------------------------
    async def queue(self, graph: dict, extra_data: dict | None = None,
                    front: bool = False) -> dict:
        """POST /prompt. Returns the server's own reply, including node_errors, unchanged.

        A 400 here is a graph the server refuses, and its `node_errors` names the node and the
        input that is wrong -- far more useful to a user than any summary this could write.
        """
        body: dict = {"prompt": graph, "client_id": self.client_id}
        if extra_data:
            body["extra_data"] = extra_data
        if front:
            body["front"] = True
        async with httpclient.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(f"{self.url}/prompt", json=body)
        if r.status_code == 200:
            return {"ok": True, **r.json()}
        try:
            payload = r.json()
        except ValueError:
            payload = {"error": r.text[:2000]}
        return {"ok": False, "http_status": r.status_code, **payload}

    async def interrupt(self) -> bool:
        async with httpclient.AsyncClient(timeout=30) as c:
            r = await c.post(f"{self.url}/interrupt")
        return r.status_code == 200

    # -- monitoring ----------------------------------------------------------
    @contextlib.asynccontextmanager
    async def socket(self):
        """Open the event socket. Use this *before* queueing -- see the module docstring."""
        async with websockets.connect(ws_url(self.client_id), max_size=None,
                                      open_timeout=15, ping_interval=20) as ws:
            yield ws

    async def watch(self, ws, prompt_id: str | None = None,
                    idle_timeout: float = 900) -> AsyncIterator[dict]:
        """Yield normalised events from an open socket until the job ends.

        Yielded shape is always `{"type": …, "data": {…}}` plus a synthesised
        `{"type": "preview", …}` for binary frames. Filtering on `prompt_id` is applied only
        to frames that carry one -- `status` does not, and dropping it would hide the queue
        depth the UI shows.
        """
        deadline = time.monotonic() + idle_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                yield {"type": "monitor_timeout",
                       "data": {"prompt_id": prompt_id, "after_s": idle_timeout}}
                return
            try:
                frame = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                yield {"type": "monitor_timeout",
                       "data": {"prompt_id": prompt_id, "after_s": idle_timeout}}
                return
            except websockets.exceptions.ConnectionClosed as e:
                yield {"type": "socket_closed", "data": {"code": e.code, "reason": str(e)}}
                return

            if isinstance(frame, (bytes, bytearray)):
                # Latent preview. The first 8 bytes are two big-endian uint32 headers
                # (event type, image format); the rest is the image. Surfaced rather than
                # dropped so the canvas can show the real in-progress render.
                #
                # The format word is carried through rather than discarded with the header: it
                # is 1 for JPEG and 2 for PNG, and a consumer handed only the payload has no
                # way to name the MIME type it is about to put in an `<img>`.
                fmt = int.from_bytes(bytes(frame[4:8]), "big") if len(frame) >= 8 else 0
                yield {"type": "preview",
                       "data": {"prompt_id": prompt_id, "bytes": max(0, len(frame) - 8),
                                "format": {1: "image/jpeg", 2: "image/png"}.get(fmt, "")},
                       "binary": bytes(frame[8:])}
                continue

            try:
                msg = json.loads(frame)
            except (ValueError, TypeError):
                continue
            etype = msg.get("type")
            data = msg.get("data") or {}

            got = data.get("prompt_id") if isinstance(data, dict) else None
            if prompt_id and got and got != prompt_id:
                continue

            yield {"type": etype, "data": data}

            if etype in TERMINAL:
                return
            # main.py:394 -- `executing` with a null node is the "queue is empty" sentinel.
            if etype == "executing" and isinstance(data, dict) and data.get("node") is None:
                return

    # -- results -------------------------------------------------------------
    async def history(self, prompt_id: str) -> dict:
        async with httpclient.AsyncClient(timeout=self.timeout) as c:
            r = await c.get(f"{self.url}/history/{prompt_id}")
            r.raise_for_status()
            doc = r.json()
        return doc.get(prompt_id, {}) if isinstance(doc, dict) else {}

    async def outputs(self, prompt_id: str) -> list[dict]:
        """Flatten a history entry into the image records the UI and the tools both want.

        Videos and audio use the same `{filename, subfolder, type}` shape under different
        keys, so anything shaped like a saved file is collected rather than just `images`.
        """
        hist = await self.history(prompt_id)
        found: list[dict] = []
        for node_id, node_out in (hist.get("outputs") or {}).items():
            if not isinstance(node_out, dict):
                continue
            for kind, items in node_out.items():
                if not isinstance(items, list):
                    continue
                for item in items:
                    if isinstance(item, dict) and "filename" in item:
                        found.append({"node": node_id, "kind": kind,
                                      "filename": item.get("filename"),
                                      "subfolder": item.get("subfolder", ""),
                                      "type": item.get("type", "output"),
                                      "url": self.view_url(item.get("filename", ""),
                                                           item.get("subfolder", ""),
                                                           item.get("type", "output"))})
        return found

    def view_url(self, filename: str, subfolder: str = "", type_: str = "output") -> str:
        q = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder,
                                    "type": type_})
        return f"{self.url}/view?{q}"

    async def view(self, filename: str, subfolder: str = "",
                   type_: str = "output") -> tuple[bytes, str]:
        """Fetch one produced file. Returns (bytes, content-type)."""
        async with httpclient.AsyncClient(timeout=self.timeout) as c:
            r = await c.get(f"{self.url}/view",
                            params={"filename": filename, "subfolder": subfolder,
                                    "type": type_})
            r.raise_for_status()
            return r.content, r.headers.get("content-type", "application/octet-stream")

    async def free(self, unload_models: bool = True, free_memory: bool = True) -> bool:
        async with httpclient.AsyncClient(timeout=30) as c:
            r = await c.post(f"{self.url}/free",
                             json={"unload_models": unload_models,
                                   "free_memory": free_memory})
        return r.status_code == 200
