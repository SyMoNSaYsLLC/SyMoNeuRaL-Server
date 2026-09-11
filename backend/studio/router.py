"""HTTP and WebSocket surface for SyMoNeuRaL Studio.

Two routers, because they live at two different places in the URL space and `api.py` mounts
`site/` at `/` last, so both must be declared above that mount:

    /api/studio/*      router      the agent, the tools, the queue, the state
    /studio/editor/*    ui_router   a same-origin reverse proxy in front of ComfyUI's own editor

## Why there is a reverse proxy here and not a hand-written canvas

The original plan was ~1000 lines of vanilla JS: an SVG wire layer over an absolutely
positioned node layer, snap-to-grid dragging, type-checked port wiring, a palette, and a
context menu that ranks compatible next nodes. All of that already exists, is better, and is
maintained by somebody else: `comfyui_frontend_package 1.49.6` ships in this ComfyUI install
and provides snap-to-grid, typed links, a searchable node palette, link-release node
suggestions -- the "Intelligent Block Helper" by another name -- per-node progress rings and
inline image results.

It is also designed to be hosted under a sub-path: its `api_base` is computed as
`location.pathname.split('/').slice(0, -1).join('/')`, and its asset references are relative.
Served at `/studio/editor/`, it addresses `/studio/editor/api/...` by itself, with no URL
rewriting anywhere in this file. That is a supported deployment mode, not a hack.

So what is written here is the part that is genuinely ours: the lease discipline, the agent,
the tool registry, and the chrome around the editor.

## The interception, and why it has to exist

A render started inside the embedded editor goes straight to ComfyUI and would never touch
`scripts/gpu-governor.sh` -- FLUX would take 7 GB of a 15.9 GiB card while `chat` or `train`
sat blocked on `acquire`. Every `POST /studio/editor/api/prompt` is therefore routed through
`_KEEPER`, which holds one `comfy.lease()` for as long as any job started through this proxy
is still in flight, then runs the drain-and-release cycle. The agent's own path
(`tools_impl/comfy_tool.execute`) already does this; the editor now shares it.

`_KEEPER` is reference-counted rather than one-lease-per-prompt on purpose. The editor lets a
user queue five renders in three seconds, and acquiring, freeing, draining and releasing
between each would unload and reload 12 GB of weights four unnecessary times. A lease held
across a burst is still "for a job" in the sense CLAUDE.md means; a lease held for the
lifetime of the ComfyUI process is what it forbids, and that is not what happens here.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
import typing

from . import httpclient
import websockets
from fastapi import APIRouter, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse

from . import agent, comfy, graph as graphmod, inference, registry, workflows, workspace
from .gate import (COOKIE, COOKIE_LEGACY, COOKIE_PATH, HEADER, enabled, local_bypass,
                   present_token,
                   token_ok)
from .tools_impl import host  # noqa: F401  (also completes tool registration)

__all__ = ["router", "ui_router"]

router = APIRouter()
ui_router = APIRouter()

#: How long the shared lease lingers after the last in-flight job finishes. A burst of renders
#: from the editor arrives with gaps of a second or two while the user clicks; releasing
#: instantly would unload and reload the weights between them. Overridable, and measured in
#: the `/state` reply so it is never a mystery number.
LINGER_S = float(os.environ.get("SYMONEURAL_STUDIO_LEASE_LINGER", "8"))

#: Ceiling on how long a job started through the editor can hold the shared lease. ComfyUI
#: reports completion through `/history`, and if a job vanishes without ever landing there
#: (server killed mid-render) this is what stops the lock being held forever.
JOB_TIMEOUT_S = float(os.environ.get("SYMONEURAL_STUDIO_JOB_TIMEOUT", "1800"))


# ---------------------------------------------------------------------------
# gate
# ---------------------------------------------------------------------------
class Denied(Exception):
    """Raised by `_guard`; carries the response it wants sent."""

    def __init__(self, status: int, payload: dict) -> None:
        super().__init__(payload.get("detail", ""))
        self.status = status
        self.payload = payload


def _guard(request: Request) -> None:
    """503 when the surface is switched off, 401 when the token is wrong. Never 404 -- a 404
    here would be a lie about whether the route exists, and the operator debugging their own
    environment variables is the person who suffers for it.

    The local bypass is consulted FIRST and can only ever let a loopback request through. It
    cannot loosen the public path: everything below this line is unchanged, so a request that
    crossed Caddy meets the same `enabled()` + `token_ok()` pair it met before. See
    `gate.local_bypass` for the three conditions and for why it calls `switched_on()` rather
    than `enabled()` -- it may drop the secret, never the switch.
    """
    if local_bypass(request.client.host if request.client else None, request.headers):
        return
    if not enabled():
        raise Denied(503, {
            "error": "studio_disabled",
            "detail": "set SYMONEURAL_STUDIO_ENABLED=1 and restart the API",
        })
    if not token_ok(present_token(request.headers, request.query_params, request.cookies)):
        raise Denied(401, {"error": "bad_token",
                           "detail": f"present the shared secret in {HEADER}"})


def _denied(exc: Denied) -> JSONResponse:
    return JSONResponse(exc.payload, status_code=exc.status)


# ---------------------------------------------------------------------------
# the shared lease
# ---------------------------------------------------------------------------
class _LeaseKeeper:
    """One GPU lease, held while any proxied job is in flight, given back when they are done.

    `comfy.lease()` is an async context manager and the natural way to use it is inside the
    call that does the work. That does not fit here: the HTTP handler must return ComfyUI's
    `prompt_id` immediately, while the lease has to outlive the response. So the context is
    driven by a supervisor task and the handlers only move a reference count.

    Failure to acquire is reported to the caller, not swallowed: `enter()` re-raises whatever
    `lease()` raised, so a queue attempt during a fine-tune returns the governor's own message
    ("could not acquire 'comfy': held by train") instead of a render that silently never runs.
    """

    def __init__(self) -> None:
        self._count = 0
        self._task: asyncio.Task | None = None
        self._ready: asyncio.Future | None = None
        self._idle = asyncio.Event()
        self._record: dict = {}
        self._last: dict = {}
        self._mutex = asyncio.Lock()
        self._job_error: dict = {}

    # -- state for /state ---------------------------------------------------
    def snapshot(self, *, full: bool) -> dict:
        """`full=False` is what a tokenless `/state` gets.

        Everything here except the error is a surface name, a boolean, a VRAM figure or a
        prompt id, all of which a page has to be able to draw without holding the secret.
        `last_job_error["error"]` is a formatted exception from a `/history` poll, so it can
        carry a filesystem path, an upstream URL or a chunk of a response body -- none of which
        is presence/absence, which is the only thing `/state` says it discloses. Tokenless
        callers get the fact that a job failed and when; the string itself needs the token.
        """
        error = None
        if self._job_error:
            error = (dict(self._job_error) if full
                     else {"present": True, "at": self._job_error["at"]})
        return {
            "in_flight": self._count,
            "holding": self._task is not None and not self._task.done(),
            "linger_s": LINGER_S,
            "current": dict(self._record) if self._record else None,
            "last": dict(self._last) if self._last else None,
            "last_job_error": error,
        }

    async def _supervise(self, ready: asyncio.Future) -> None:
        try:
            async with comfy.lease("comfy") as record:
                self._record = record
                if not ready.done():
                    ready.set_result(True)
                # Held until the count returns to zero and stays there for LINGER_S.
                while True:
                    await self._idle.wait()
                    if LINGER_S > 0:
                        await asyncio.sleep(LINGER_S)
                    if self._count == 0:
                        break
        except Exception as exc:  # governor refusal, cancellation, anything
            if not ready.done():
                ready.set_exception(exc)
            raise
        finally:
            self._last = {**self._record, "ended_at": time.time()}
            self._record = {}
            self._task = None
            self._ready = None

    async def enter(self) -> None:
        async with self._mutex:
            self._count += 1
            self._idle.clear()
            if self._task is None or self._task.done():
                self._ready = asyncio.get_running_loop().create_future()
                self._task = asyncio.create_task(self._supervise(self._ready),
                                                 name="studio-gpu-lease")
            ready = self._ready
        try:
            await ready
        except Exception:
            # Acquisition failed: undo the count so a later attempt can start a fresh
            # supervisor rather than inheriting a dead one.
            async with self._mutex:
                self._count = max(0, self._count - 1)
                if self._count == 0:
                    self._idle.set()
            raise

    async def leave(self) -> None:
        async with self._mutex:
            self._count = max(0, self._count - 1)
            if self._count == 0:
                self._idle.set()

    def note_job_error(self, prompt_id: str | None, exc: BaseException) -> None:
        """Record why a job's tracking task died. Reported by `/state` as `last_job_error`.

        The string is only handed to a caller that presented the token -- see `snapshot`.

        The lease is not at risk here -- it is released in a `finally` -- but a job whose
        `/history` poll blew up has no other surface. Kept to the last one, because this is a
        status field and not a log.
        """
        self._job_error = {"prompt_id": prompt_id, "at": time.time(),
                           "error": f"{type(exc).__name__}: {exc}"}


_KEEPER = _LeaseKeeper()

#: Strong references to the per-job release tasks launched by `_intercept_prompt`. asyncio holds
#: only a weak reference to a running task, so a task nobody else holds can be collected while it
#: is awaiting `/history` -- and this particular task is the only thing that ever calls
#: `_KEEPER.leave()`. Losing one leaves `_count` above zero forever, which keeps the supervisor
#: alive, which holds the governor lock for the life of the process: the one thing CLAUDE.md
#: says never to do on a single-card box.
_JOBS: set = set()


def _track_job(coro, prompt_id: str | None) -> asyncio.Task:
    """Launch a job-tracking task, keep it alive, and record it if it dies.

    A function rather than three inline lines because it is the part with the failure mode:
    tested by `JobTrackingTests` in `test_studio.py`, which asserts both that the task is
    referenced while it runs and that an exception inside it reaches `/state`.
    """
    task = asyncio.ensure_future(coro)
    _JOBS.add(task)

    def _forget(finished: asyncio.Task) -> None:
        _JOBS.discard(finished)
        if finished.cancelled():
            return
        exc = finished.exception()
        if exc is not None:
            # `_release_when_done` gives the lease back in a `finally`, so the lease is already
            # home by the time this runs; what would otherwise be lost is the reason. Nobody
            # awaits this task, so without this the only record is asyncio's "Task exception was
            # never retrieved" on the API's stderr.
            _KEEPER.note_job_error(prompt_id, exc)

    task.add_done_callback(_forget)
    return task


async def _relay_event(ws, event: dict) -> None:
    """Send one `ComfyClient.watch` event to a browser socket: JSON header, then image.

    `watch` yields latent previews as `{"type": "preview", "data": {...}, "binary": b"..."}` and
    `send_json` raises `TypeError: Object of type bytes is not JSON serializable` on that, so
    the first preview of the first render killed the relay. The bytes go out as a real binary
    frame right behind their header, which is the shape ComfyUI itself uses.
    """
    blob = event.pop("binary", None)
    await ws.send_json(event)
    if blob is not None:
        await ws.send_bytes(blob)


async def _await_history(client: comfy.ComfyClient, prompt_id: str,
                         timeout: float = JOB_TIMEOUT_S) -> dict:
    """Wait for a prompt to land in `/history`, by polling.

    Not by watching the WebSocket, and the reason matters: ComfyUI sends execution events
    only to the `client_id` that queued the prompt (`server.py` routes by sid). The editor
    queues with *its own* client id and needs those frames itself, so this proxy must not
    substitute one -- and therefore cannot receive the events either. `/history/{id}` is
    populated on completion regardless of who queued it, so polling it is the only observer
    that does not steal the user's progress bar.
    """
    deadline = time.monotonic() + timeout
    delay = 0.4
    while time.monotonic() < deadline:
        try:
            hist = await client.history(prompt_id)
        except httpclient.HTTPError:
            hist = {}
        entry = (hist or {}).get(prompt_id)
        if entry:
            status = (entry.get("status") or {})
            if status.get("completed") is not None or status.get("status_str"):
                return entry
            return entry
        await asyncio.sleep(delay)
        delay = min(2.0, delay * 1.3)
    return {"timeout": True, "waited_s": round(timeout, 1)}


# ---------------------------------------------------------------------------
# /api/studio  --  state, tools, workflows
# ---------------------------------------------------------------------------
@router.get("/state")
async def state(request: Request) -> JSONResponse:
    """Tokenless, and presence/absence only -- the pattern `apps/gateway` established.

    A page has to be able to say "the surface is switched off" without holding the secret, so
    this reports whether things are up and what would switch them on. It does not read files,
    does not list the workspace contents and does not run anything.

    Two fields needed work to make that sentence true rather than aspirational. The workspace
    root is a path and is disclosed deliberately -- `page.js` prints it, and a page that cannot
    say where it is pointing is not reporting presence, it is hiding it. The other was
    `last_job_error`, a formatted exception that can carry more than its own existence; it is
    now reduced to presence and a timestamp unless the caller presented the token.

    The rest is booleans, counts and names of things the page lists anyway -- except one field,
    which is bigger than this paragraph used to admit. `comfy.alive()` returns ComfyUI's
    `/system_stats` body under `system`, unchanged, and that body is not a VRAM figure:
    `ComfyUI/server.py:686` puts `os`, `ram_total`/`ram_free`, the ComfyUI, frontend and
    template versions, `comfy_package_versions`, the whole `sys.version` string, the torch
    version, `deploy_environment` and **`sys.argv`** in it, plus per-device name and VRAM.
    `sys.argv` is that process's command line. All of it is disclosed here with no token
    whenever ComfyUI is up. Quoted from that source and not from a live reading, deliberately:
    ComfyUI is down on this box, so the tokenless body measured here carries `"up": false` and
    no `system` key at all, and the shape above is what the handler will return when it is up.
    """
    on = enabled()
    try:
        _guard(request)
        privileged = True
    except Denied:
        privileged = False
    client = comfy.ComfyClient()
    comfy_state, llm_state = await asyncio.gather(client.alive(), inference.state())
    return JSONResponse({
        "enabled": on,
        "detail": None if on else ("set SYMONEURAL_STUDIO_ENABLED=1 and "
                                   "SYMONEURAL_STUDIO_TOKEN=<secret>, then restart the API"),
        # `workspace.describe()`, not `workspace.root()`. `root()` *raises* when discovery
        # found nothing, so the one endpoint that exists to report absence without a token was
        # the endpoint that 500'd on it -- and `page.js`'s `ws.root || 'not found'` branch could
        # never run. `describe()` returns `root: null` and says how it looked.
        "workspace": workspace.describe(),
        "tools": len(registry.names()),
        "workflows": workflows.names(),
        "inference": llm_state,
        "render_ui": {**comfy_state, "editor": "/studio/editor/"},
        "lease": _KEEPER.snapshot(full=privileged),
        "max_steps": agent.MAX_STEPS,
        # What a `permissions: "ask"` or `"deny"` run will stop on. Published here, without a
        # token, so a client does not have to import the backend to know which tools it is
        # about to be asked about -- and so that "what is gated" is answered by the registry
        # that decides it, rather than by a list copied into a client and left to drift.
        "gated": sorted(n for n in registry.names()
                        if getattr(registry.get(n), "dangerous", False)),
    })


@router.get("/tools")
async def tools(request: Request) -> JSONResponse:
    """The live registry -- the same list the system prompt is generated from, so the UI can
    never show a tool the model does not have or miss one it does."""
    try:
        _guard(request)
    except Denied as exc:
        return _denied(exc)
    specs = registry.tool_specs()
    return JSONResponse({
        "count": len(specs),
        "groups": sorted({t.group for t in registry.TOOLS.values()}),
        "tools": [{
            "name": t.name,
            "group": t.group,
            "dangerous": t.dangerous,
            "description": t.description,
            "parameters": t.parameters,
        } for t in sorted(registry.TOOLS.values(), key=lambda t: (t.group, t.name))],
        "specs": specs,
    })


@router.post("/tool/{name}")
async def call_tool(name: str, request: Request) -> JSONResponse:
    """Run one tool directly, bypassing the model. This is what makes the tool layer testable
    by hand -- `curl` with the operator token, no model in the path.

    No page calls it: `page.js` renders the tool table from `/api/studio/state` and has no
    inspector. Nor does anything call `/interrupt`, `/nodes` or `/workflow/{name}` -- and the MCP
    server is not the consumer either, since it calls `registry` in-process and never speaks HTTP
    to this router. These four are an operator surface, reached with `curl` and a token."""
    try:
        _guard(request)
    except Denied as exc:
        return _denied(exc)
    if registry.get(name) is None:
        return JSONResponse({"error": "unknown_tool", "name": name,
                             "available": registry.names()}, status_code=404)
    try:
        arguments = await request.json()
    except ValueError:
        arguments = {}
    started = time.monotonic()
    try:
        result = await registry.call(name, arguments if isinstance(arguments, dict) else {})
    except Exception as exc:  # a tool raising is a result, not a server fault
        return JSONResponse({"tool": name, "ok": False,
                             "error": f"{type(exc).__name__}: {exc}",
                             "elapsed_s": round(time.monotonic() - started, 3)})
    return JSONResponse({"tool": name, "ok": True, "result": result,
                         "elapsed_s": round(time.monotonic() - started, 3)})


@router.get("/workflows")
async def list_workflows(request: Request) -> JSONResponse:
    try:
        _guard(request)
    except Denied as exc:
        return _denied(exc)
    return JSONResponse({"default": workflows.DEFAULT,
                         "workflows": [workflows.describe(n) for n in workflows.names()]})


@router.get("/workflow/{name}")
async def get_workflow(name: str, request: Request) -> JSONResponse:
    """The prompt graph, plus the same graph run back through `graph.from_prompt`.

    Not for the editor, and nothing in this repo calls it. The embedded editor is ComfyUI's own
    frontend in an iframe (`page.html:169`), proxied at `/studio/editor/`; it loads graphs through
    ComfyUI's own API and has never seen this route or the canvas format -- `graph.py`'s header
    says the same thing from the other end. Neither `page.js` nor `tests/studio.mjs` fetches it.

    It is here for a client that wants a stored workflow in both shapes without importing the
    package, and it is the only surface `from_prompt` has: the sole other call is
    `graph.py`'s own docstring naming this route.
    """
    try:
        _guard(request)
    except Denied as exc:
        return _denied(exc)
    try:
        prompt = workflows.get(name)
    except KeyError as exc:
        return JSONResponse({"error": "unknown_workflow", "detail": str(exc)}, status_code=404)
    return JSONResponse({"name": name, "prompt": prompt,
                         "canvas": graphmod.from_prompt(prompt),
                         "describe": workflows.describe(name)})


@router.get("/nodes")
async def nodes(request: Request, refresh: bool = False) -> Response:
    """ComfyUI's `/object_info`, proxied. ~2 MB, cached in the client for the process
    lifetime; `?refresh=1` re-reads it after installing a custom node pack."""
    try:
        _guard(request)
    except Denied as exc:
        return _denied(exc)
    client = comfy.ComfyClient()
    try:
        catalogue = await client.object_info(refresh=refresh)
    except httpclient.HTTPError as exc:
        return JSONResponse({"error": "comfyui_unreachable", "url": comfy.base_url(),
                             "detail": f"{type(exc).__name__}: {exc}",
                             "fix": "scripts/symoneural-ui.sh start"}, status_code=503)
    return JSONResponse({"count": len(catalogue), "nodes": catalogue})


# ---------------------------------------------------------------------------
# /api/studio/agent  --  the cognitive loop, over SSE
# ---------------------------------------------------------------------------
def _sse(event: dict) -> bytes:
    return f"data: {json.dumps(event, default=str)}\n\n".encode()


@router.post("/agent")
async def run_agent(request: Request) -> Response:
    """Stream one agent turn: thinking, every tool call, every raw tool result, the answer.

    Server-sent events rather than a WebSocket because this is strictly one-directional and
    SSE reconnects by itself. Each frame is one JSON object keyed `"event"`, exactly as
    `agent.run()` yields it (see its own docstring's list) -- the transport adds nothing and
    interprets nothing, so what the browser renders is what the loop actually did. The two frames
    this function generates itself, in the `except` below, use the same key for that reason.
    """
    try:
        _guard(request)
    except Denied as exc:
        return _denied(exc)
    try:
        body = await request.json()
    except ValueError:
        body = {}
    query = (body.get("query") or body.get("message") or "").strip()
    if not query:
        return JSONResponse({"error": "empty_query",
                             "detail": "POST {\"query\": \"...\"}"}, status_code=400)
    history = body.get("history") if isinstance(body.get("history"), list) else None
    max_steps = body.get("max_steps")

    # The permission mode, validated here rather than in the loop so a typo is a 400 and not
    # a silently permissive run. `"allow"` is the default because it is what this endpoint did
    # before the mode existed: the /studio page cannot answer a `permission_required` frame,
    # so defaulting to "ask" would have gated the browser surface by accident.
    # The valid set comes from `agent.PERMISSION_MODES` rather than being spelled again here:
    # a mode this file accepted and the loop did not recognise would fall through the gate's
    # `in ("ask", "deny")` test and run as "allow".
    permissions = str(body.get("permissions") or "allow")
    if permissions not in agent.PERMISSION_MODES:
        return JSONResponse({"error": "bad_permissions",
                             "detail": "permissions must be one of: "
                                       + ", ".join(agent.PERMISSION_MODES),
                             "got": permissions}, status_code=400)
    allow = [str(x) for x in body.get("allow") or [] if isinstance(x, (str, int))]
    # Messages that belong AFTER the user query: an approved tool call and its result, handed
    # back by a caller resuming a turn that stopped on `permission_required`. Kept separate
    # from `history` because history goes before the query and this must go after it.
    resume = body.get("resume") if isinstance(body.get("resume"), list) else None

    async def stream() -> typing.AsyncIterator[bytes]:
        try:
            async for event in agent.run(query, history,
                                         max_steps=int(max_steps) if max_steps else None,
                                         context=str(body.get("context") or ""),
                                         model=body.get("model"),
                                         permissions=permissions, allow=allow,
                                         resume=resume):
                yield _sse(event)
                if await request.is_disconnected():
                    break
        except Exception as exc:
            # `agent.run` keys its frames "event"; the transport must not invent a
            # different shape for its own errors or the client needs two parsers.
            yield _sse({"event": "error", "error": f"{type(exc).__name__}: {exc}"})
            yield _sse({"event": "done", "reason": "transport_error"})

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        # Caddy does not buffer, but this stack has been behind other proxies and an SSE
        # stream that arrives in one lump at the end is indistinguishable from a hang.
        "X-Accel-Buffering": "no",
    })


# ---------------------------------------------------------------------------
# /api/studio/queue  --  run a graph under the lease
# ---------------------------------------------------------------------------
@router.post("/queue")
async def queue(request: Request) -> JSONResponse:
    """Queue a render and wait for it, returning the images.

    Accepts, in order of precedence: `prompt` (a ComfyUI prompt graph), `canvas` (an editor
    document, converted by `graph.to_prompt`), or `workflow` (a name from the library).
    `params` is applied through `graph.inject` either way.

    This is the blocking, batteries-included path -- the one the agent and the API use. The
    editor's own queue button goes through the proxy below instead, which returns as soon as
    the prompt is accepted so its progress bar can do the waiting.
    """
    try:
        _guard(request)
    except Denied as exc:
        return _denied(exc)
    try:
        body = await request.json()
    except ValueError:
        body = {}

    params = body.get("params") if isinstance(body.get("params"), dict) else {}
    unapplied: list[dict] = []
    try:
        if isinstance(body.get("prompt"), dict):
            prompt = dict(body["prompt"])
        elif isinstance(body.get("canvas"), dict):
            prompt = graphmod.to_prompt(body["canvas"])
        else:
            prompt = workflows.get(body.get("workflow") or workflows.DEFAULT)
        if params:
            report = graphmod.inject(prompt, _addresses(params))
            prompt, unapplied = report["graph"], report["unapplied"]
    except (graphmod.GraphError, KeyError) as exc:
        return JSONResponse({"error": "bad_graph", "detail": str(exc)}, status_code=400)

    from .tools_impl import comfy_tool
    result = await comfy_tool.execute(prompt, timeout_s=int(body.get("timeout_s") or 900))
    if unapplied:
        result = {**result, "unapplied": unapplied}
    return JSONResponse(result, status_code=200 if result.get("ok") else 502)


def _addresses(params: dict) -> dict:
    """Friendly parameter names to `node.input` addresses, leaving explicit addresses alone.

    `graph.inject` addresses one input on one node -- `"7.width"` -- because that is the only
    form that works on an arbitrary canvas graph, where node 7 might be anything. The page and
    the agent both speak the friendly form (`width`), so the translation has to happen
    somewhere, and `workflows.PARAMETER_MAP` is where the stock graph's ids are already
    written down; `tools_impl/comfy_tool.py` uses the same map for the same reason.

    This function is the fix for a bug the browser check caught and no unit test would have:
    `queue` used to hand `{"width": 1024}` straight to `inject`, which wants a dot in every
    address, so every parameter silently landed in `unapplied` -- and then the *report* dict
    `inject` returns was passed on as if it were the graph, which is what actually produced
    the 500. Rendering with no parameters worked fine, which is why it survived.

    A name with a dot is passed through untouched, so a caller that knows its own graph can
    still address it exactly. A name in neither form is passed through too, and comes back in
    `unapplied` with `inject`'s own explanation rather than being dropped here in silence.
    """
    out = {}
    for key, value in params.items():
        name = str(key)
        out[workflows.PARAMETER_MAP.get(name, name) if "." not in name else name] = value
    return out


@router.post("/interrupt")
async def interrupt(request: Request) -> JSONResponse:
    try:
        _guard(request)
    except Denied as exc:
        return _denied(exc)
    client = comfy.ComfyClient()
    try:
        return JSONResponse({"interrupted": await client.interrupt()})
    except httpclient.HTTPError as exc:
        return JSONResponse({"error": "comfyui_unreachable",
                             "detail": f"{type(exc).__name__}: {exc}"}, status_code=503)


# ---------------------------------------------------------------------------
# /api/studio/image  --  the render, proxied
# ---------------------------------------------------------------------------
@router.get("/image")
async def image(request: Request, filename: str, subfolder: str = "",
                kind: str = Query("output", alias="type")) -> Response:
    """`GET /view` from ComfyUI, on this origin.

    The browser never talks to port 8188: that port is bound to loopback, so it could not
    anyway, and keeping every URL same-origin is what lets the whole app be exercised from one
    host -- the same reason `api.py` mounts `site/` last. `type` shadows the builtin because
    that is ComfyUI's query parameter name and renaming it here would break the contract.
    """
    try:
        _guard(request)
    except Denied as exc:
        return _denied(exc)
    client = comfy.ComfyClient()
    try:
        payload, content_type = await client.view(filename, subfolder, kind)
    except httpclient.HTTPStatusError as exc:
        # ComfyUI answers 404 for a filename it cannot find; that is a real answer about the
        # render, not a failure of this proxy, so it is passed through as one.
        return JSONResponse({"error": "not_found", "filename": filename,
                             "subfolder": subfolder, "type": kind,
                             "upstream_status": exc.response.status_code},
                            status_code=exc.response.status_code)
    except httpclient.HTTPError as exc:
        return JSONResponse({"error": "comfyui_unreachable", "url": comfy.base_url(),
                             "detail": f"{type(exc).__name__}: {exc}",
                             "fix": "scripts/symoneural-ui.sh start"}, status_code=503)
    return Response(payload, media_type=content_type or "image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


# ---------------------------------------------------------------------------
# /api/studio/events  --  ComfyUI's socket, relayed
# ---------------------------------------------------------------------------
@router.websocket("/events")
async def events(ws: WebSocket) -> None:
    """Relay ComfyUI's event stream to a browser that is not running the editor.

    Nothing in this repo consumes this yet -- the chrome reads `/api/studio/state` and the
    editor iframe drives its own socket at `/studio/editor/ws`. It is here for a client that
    wants the event stream without the editor, and its frame protocol is tested rather than
    assumed (`test_studio.py`, `EventRelayTests`).

    Frames go out through `_relay_event`, which splits a preview's bytes off its JSON header --
    see there for why `send_json` alone was a crash on the first latent preview.
    """
    await ws.accept()
    # The local bypass drops the token for a loopback caller and nothing else. It cannot
    # reach the `studio_disabled` branch below -- `gate.local_bypass` requires `switched_on()`
    # -- so a switched-off Studio still closes 1008 on every caller.
    if not local_bypass(ws.client.host if ws.client else None, ws.headers):
        if not enabled():
            await ws.send_json({"type": "error", "error": "studio_disabled"})
            await ws.close(code=1008)
            return
        if not token_ok(present_token(ws.headers, ws.query_params, ws.cookies)):
            await ws.send_json({"type": "error", "error": "bad_token"})
            await ws.close(code=1008)
            return

    client = comfy.ComfyClient(client_id=ws.query_params.get("clientId") or None)
    try:
        async with client.socket() as upstream:
            await ws.send_json({"type": "relay_open", "client_id": client.client_id,
                                "url": comfy.base_url()})
            async for event in client.watch(upstream, idle_timeout=86400):
                await _relay_event(ws, event)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        # The hint only where it is true. `client.socket()` failing to connect is a ComfyUI that
        # is not running; anything else that comes out of here is a bug in this process, and
        # telling the operator to start a service that is already up sends them the wrong way.
        payload = {"type": "error", "error": f"{type(exc).__name__}: {exc}"}
        if isinstance(exc, (OSError, asyncio.TimeoutError)):
            payload["fix"] = "scripts/symoneural-ui.sh start"
        with contextlib.suppress(Exception):
            await ws.send_json(payload)
    with contextlib.suppress(Exception):
        await ws.close()


# ---------------------------------------------------------------------------
# /studio/editor/*  --  the editor, reverse-proxied
# ---------------------------------------------------------------------------
#: Headers a proxy must not forward. `content-length` because the outbound client recomputes it and a stale
#: value truncates the body; the rest are per-connection by RFC 9110 §7.6.1.
_HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
    "trailers", "transfer-encoding", "upgrade", "content-length", "content-encoding", "host",
})

# Dropped on the way *up*, and each one for its own reason.
#
# `origin`, `referer` and the `sec-fetch-*` family: ComfyUI runs
# `create_origin_only_middleware` (server.py:158) which compares the request's `Host` against
# its `Origin` and answers **403** when they differ. Forwarded unchanged, those headers say
# `Origin: http://127.0.0.1:8875` while the outbound client sets `Host: 127.0.0.1:8188`, so every asset the
# editor loaded came back 403 and the canvas never booted -- exactly the failure
# `tests/studio.mjs` reported as seven `net::ERR_ABORTED` lines. Chrome reports an aborted
# module load rather than the status, which is why this looked like an auth problem for
# longer than it should have. Upstream's check is about a *browser* talking directly to
# 127.0.0.1:8188; the browser here is talking to this proxy, which does its own auth, and
# relaying the outer page's origin to a different port is simply wrong.
#
# `cookie`: the operator token lives in one now (see `gate.present_token`). ComfyUI has no
# use for it and no reason to have it in its access log.
#
# `authorization`: same argument.
_STRIP_UPSTREAM = frozenset({
    "origin", "referer", "cookie", "authorization",
    "sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest", "sec-fetch-user",
})

# Dropped on the way *back*: uvicorn writes its own, and two of each in a response is the kind
# of thing that reads as a proxy bug when someone later looks at the headers.
_STRIP_DOWNSTREAM = frozenset({"date", "server"})


def _clean(headers: typing.Iterable[tuple[str, str]], *, upstream: bool = False) -> dict[str, str]:
    drop = _HOP_BY_HOP | (_STRIP_UPSTREAM if upstream else _STRIP_DOWNSTREAM)
    return {k: v for k, v in headers if k.lower() not in drop}


async def _intercept_prompt(body: bytes) -> Response:
    """The editor's queue button, routed through the GPU governor.

    Returns ComfyUI's own reply verbatim and as soon as it arrives -- the editor needs the
    `prompt_id` to start tracking, and a 400 with `node_errors` is far more useful to the user
    than anything this could summarise. The lease is held by a detached task until the job
    lands in `/history`.
    """
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        payload = None
    if not isinstance(payload, dict) or "prompt" not in payload:
        # Not a shape we understand; pass it straight through rather than guess. ComfyUI will
        # reject it with its own message, which is the correct answer.
        return await _forward("POST", "api/prompt", body, {"content-type": "application/json"})

    try:
        await _KEEPER.enter()
    except comfy.GovernorError as exc:
        # The governor's message names the surface holding the card. Surfaced as a 409 with
        # `node_errors` empty so the editor's error toast has something to render.
        return JSONResponse({"error": {"type": "gpu_busy", "message": str(exc)},
                             "node_errors": {}}, status_code=409)

    client = comfy.ComfyClient(client_id=payload.get("client_id") or None)
    try:
        reply = await client.queue(payload["prompt"], payload.get("extra_data"),
                                   front=bool(payload.get("front")))
    except Exception as exc:
        await _KEEPER.leave()
        return JSONResponse({"error": {"type": "queue_failed", "message": str(exc)},
                             "node_errors": {}}, status_code=502)

    if not reply.get("ok"):
        await _KEEPER.leave()
        status = int(reply.get("http_status") or 400)
        return JSONResponse({k: v for k, v in reply.items()
                             if k not in ("ok", "http_status")}, status_code=status)

    prompt_id = reply.get("prompt_id")

    async def _release_when_done() -> None:
        try:
            await _await_history(client, prompt_id)
        finally:
            await _KEEPER.leave()

    _track_job(_release_when_done(), prompt_id)
    return JSONResponse({k: v for k, v in reply.items() if k != "ok"})


async def _forward(method: str, path: str, body: bytes | None,
                   headers: dict[str, str], params=None) -> Response:
    url = f"{comfy.base_url()}/{path.lstrip('/')}"
    try:
        async with httpclient.AsyncClient(timeout=300, follow_redirects=False) as c:
            upstream = await c.request(method, url, content=body, headers=headers,
                                       params=params)
    except httpclient.HTTPError as exc:
        return JSONResponse({"error": "comfyui_unreachable", "url": url,
                             "detail": f"{type(exc).__name__}: {exc}",
                             "fix": "scripts/symoneural-ui.sh start"}, status_code=503)
    return Response(content=upstream.content, status_code=upstream.status_code,
                    headers=_clean(upstream.headers.items()),
                    media_type=upstream.headers.get("content-type"))


@ui_router.websocket("/ws")
async def editor_socket(ws: WebSocket) -> None:
    """Pump the editor's own event socket both ways.

    The editor connects to `<api_base>/ws?clientId=…`, which resolves to `/studio/editor/ws`.
    Its client id is passed through untouched -- that is what makes ComfyUI route this user's
    progress events to this user's editor, and substituting one here would silently blank
    every progress ring in the UI.
    """
    await ws.accept()
    # Same shape as `_guard` and the events socket: loopback may skip the token, a switched-off
    # Studio closes regardless, and a request that crossed Caddy is refused because
    # `local_request` rejects anything carrying proxy headers. This is the socket BLOCKER-1 is
    # about, so the ordering here is load-bearing -- the bypass is a narrowing, never a widening.
    if not local_bypass(ws.client.host if ws.client else None, ws.headers):
        if not enabled() or not token_ok(present_token(ws.headers, ws.query_params, ws.cookies)):
            await ws.close(code=1008)
            return

    query = "&".join(f"{k}={v}" for k, v in ws.query_params.items() if k != "token")
    upstream_url = comfy.base_url().replace("http://", "ws://").replace("https://", "wss://")
    upstream_url = f"{upstream_url}/ws" + (f"?{query}" if query else "")
    try:
        upstream = await websockets.connect(upstream_url, max_size=None, open_timeout=15,
                                            ping_interval=20)
    except Exception:
        await ws.close(code=1011)
        return

    async def to_upstream() -> None:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                raise WebSocketDisconnect(message.get("code", 1000))
            if message.get("text") is not None:
                await upstream.send(message["text"])
            elif message.get("bytes") is not None:
                await upstream.send(message["bytes"])

    async def to_browser() -> None:
        async for frame in upstream:
            if isinstance(frame, (bytes, bytearray)):
                await ws.send_bytes(bytes(frame))
            else:
                await ws.send_text(frame)

    tasks = [asyncio.create_task(to_upstream()), asyncio.create_task(to_browser())]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    except Exception:
        pass
    finally:
        with contextlib.suppress(Exception):
            await upstream.close()
        with contextlib.suppress(Exception):
            await ws.close()


@ui_router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE",
                                              "HEAD", "OPTIONS"])
async def editor(path: str, request: Request) -> Response:
    """Everything else the editor asks for, forwarded to 127.0.0.1:8188 unchanged.

    No URL rewriting happens here and none is needed: the frontend derives its API base from
    `location.pathname`, so under `/studio/editor/` it already addresses `/studio/editor/api/…`
    and every asset reference is relative. The one request that is *not* passed through is
    `api/prompt`, which is where the GPU lease is imposed.
    """
    try:
        _guard(request)
    except Denied as exc:
        return _denied(exc)

    body = await request.body()
    if request.method == "POST" and path.rstrip("/") in ("api/prompt", "prompt"):
        return await _intercept_prompt(body)

    headers = _clean(request.headers.items(), upstream=True)
    # The token rides in the query string for the entry document; do not leak it upstream,
    # where it would end up in ComfyUI's access log for every single file the editor loads.
    params = [(k, v) for k, v in request.query_params.multi_items() if k != "token"]
    response = await _forward(request.method, path or "", body or None, headers, params or None)
    _mint_cookie(request, response)
    return response


def _mint_cookie(request: Request, response: Response) -> None:
    """Hand the browser a session cookie when the token arrived on the URL.

    Only the iframe's own entry URL carries `?token=`; everything the editor loads after that
    -- `assets/index-*.js`, `materialdesignicons.min.css`, `api/userdata/user.css` -- is a
    relative URL fetched by the browser itself, with no header and no query string. Those all
    401'd, seven of them, and the canvas never appeared. A cookie is the only credential a
    browser attaches to requests it issues on its own behalf.

    Scoped to `/studio/editor`, so it is not sent to `/api/studio` and not to any other page on
    this site. `HttpOnly`, so page script cannot read the operator token back out of it -- the
    page already has its own copy in `sessionStorage` and does not need this one. `SameSite=Strict`,
    because nothing off-origin has any business loading the editor. No `Max-Age` and no
    `Expires`, so it is a session cookie and dies with the browser, matching `sessionStorage`.
    No `Secure`: this is served over plain HTTP on 127.0.0.1 in development, and marking it
    Secure there means the browser silently drops it and the bug comes straight back.
    """
    if request.query_params.get("token") is None:
        return
    # Either spelling counts as "already minted", or every open session mid-rename would get a
    # fresh Set-Cookie on every entry-document load. `COOKIE_LEGACY` is still read by
    # `present_token`, so a tab holding it is authorised and needs no re-mint this request.
    if request.query_params.get("token") in (request.cookies.get(COOKIE),
                                             request.cookies.get(COOKIE_LEGACY)):
        return          # already set; do not re-send the header on every asset
    response.set_cookie(COOKIE, request.query_params["token"], path=COOKIE_PATH,
                        httponly=True, samesite="strict")
