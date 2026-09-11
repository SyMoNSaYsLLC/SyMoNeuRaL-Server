"""HTTP surface for SyMoNeuRaL Exp.

One router, mounted at `/api/exp` above `api.py`'s static mount. The page at `/exp` is a plain
generated page like every other one in this repo; there is no proxy here and no WebSocket.

## The read/write line

    GET  /api/exp/state       what is mounted, in what state, with what services      open
    GET  /api/exp/plugins     the entry table, the same data the page draws            open
    GET  /api/exp/services    service names, owners, epochs                            open
    GET  /api/exp/events      the trace, from a sequence cursor                        open
    GET  /api/exp/catalogue   plugins available to mount, and presets available        open
    POST /api/exp/preset      mount a named preset (diffed against what is running)   token
    POST /api/exp/apply       mount an arbitrary manifest                             token
    POST /api/exp/add         add one entry                                           token
    POST /api/exp/remove      dispose one entry                                       token
    POST /api/exp/patch       replace one entry's config and restart it               token
    POST /api/exp/enable      hot-plug, both directions                               token
    POST /api/exp/reload      re-import the module and restart against the new code   token
    POST /api/exp/call        call a method on a live service                         token

Reads are open because the entire argument for this runtime is that its state is inspectable,
and a plugin table nobody can see without a secret is a plugin table nobody looks at. One thing
is withheld from a tokenless reader and it is named precisely: **an entry's `config`**. That is
where a plugin's credentials live, and `Fiber.snapshot` leaves it out for the same reason.

`POST /call` is genuinely unrestricted as of 2026-08-20 -- any method on any mounted service,
with whatever arguments are posted. The token is the line, and past it no allow-list of
callable methods is implemented. That is a deliberate pre-launch state, not a cleared posture
(request ledger R-98, held, being re-scoped per surface).

## Errors

`ContextError` is the runtime's own way of saying "you asked for something that is not there
or is not valid", and it becomes a 400 with the message intact. Every message this package
raises is written to be read by a person -- "no entry 'clok'; have: bus, memory, gpu, clock" --
so wrapping it in a generic detail string would throw away the part that is useful.
"""
from __future__ import annotations

import typing

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from . import DEFAULT_PRESET, boot, runtime
from .context import ContextError
from .gate import ENV_ENABLED, enabled, present_token, token_ok

__all__ = ["router"]

router = APIRouter()


# ---------------------------------------------------------------------------
# gate
# ---------------------------------------------------------------------------
class Denied(Exception):
    """Raised by `_guard`; carries the response it wants sent."""

    def __init__(self, status: int, payload: dict) -> None:
        super().__init__(payload.get("detail", ""))
        self.status = status
        self.payload = payload


def _may_write(request: Request) -> bool:
    return enabled() and token_ok(present_token(request.headers, request.query_params))


def _guard(request: Request) -> None:
    """503 when the mutation surface is switched off, 401 when the token is wrong.

    Never 404. A 404 on a route that exists tells the caller their URL is wrong, which sends
    them to look in the wrong place -- the surface is off, and saying so with the two variable
    names is the difference between a two-minute fix and an afternoon.
    """
    if not enabled():
        raise Denied(503, {"detail": f"exp mutations are off; set {ENV_ENABLED}=1 "
                                     f"to switch them on",
                           "enabled": False})
    # NO API KEYS, 2026-09-11. `token_ok` is unconditionally true, so this branch cannot
    # fire; it is kept as the one place a gate would go back if one were ever wanted, which
    # is the same reason `token_ok` itself was kept rather than deleted.
    if not token_ok(present_token(request.headers, request.query_params)):
        raise Denied(401, {"detail": "bad or missing token", "enabled": True})


async def _loaded():
    """The loader, with the default preset mounted if this is the first request."""
    await boot()
    return runtime()


def _fail(exc: ContextError) -> JSONResponse:
    return JSONResponse({"detail": str(exc), "error": type(exc).__name__}, status_code=400)


async def _body(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:                                             # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------
@router.get("/state")
async def state(request: Request):
    """Everything the page needs for one render, in one call.

    `config` appears on each entry only for a caller that presented the token. A tokenless
    reader sees every entry, its state, what it injects and what is missing -- and not one
    configured value.
    """
    loader = await _loaded()
    writable = _may_write(request)
    payload = loader.state(with_config=writable)
    payload.update({
        "enabled": enabled(),
        "writable": writable,
        "default_preset": DEFAULT_PRESET,
        "trace_path": str(loader.runtime.trace.path) if loader.runtime.trace.path else None,
        "dropped_writes": loader.runtime.trace.dropped_writes,
    })
    return payload


@router.get("/plugins")
async def plugins(request: Request):
    loader = await _loaded()
    writable = _may_write(request)
    return {"entries": [e.snapshot(with_config=writable) for e in loader.all_entries()],
            "fibers": [f.snapshot() for f in loader.runtime.fibers],
            "writable": writable}


@router.get("/services")
async def services():
    """Every service in the container, including the ones inside isolated realms.

    Keyed by realm-qualified key rather than by name, because two isolated sessions each
    providing `llm` are two rows here and collapsing them to one would be the exact confusion
    `isolate()` exists to make visible.
    """
    loader = await _loaded()
    return {"services": [
        {"key": s.key, "name": s.name, "realm": s.key.split(":", 1)[0] or None,
         "epoch": s.epoch, "owner": s.owner.label if s.owner else None,
         "owner_fiber": s.owner.id if s.owner else None,
         "type": type(s.value).__name__,
         "methods": sorted(n for n in dir(s.value)
                           if not n.startswith("_") and callable(getattr(s.value, n, None)))}
        for s in loader.runtime.services.values()]}


@router.get("/events")
async def events(since: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=2000)):
    """The trace from a sequence cursor. The page polls with the last `seq` it saw.

    A sequence, not a timestamp: two events can share a millisecond, and a timestamp cursor
    either re-delivers them or drops one. Neither is acceptable in the feed you debug reloads
    from.
    """
    loader = await _loaded()
    return {"events": loader.runtime.trace.since(since, limit),
            "seq": loader.runtime.trace.seq,
            "buffered": len(loader.runtime.trace)}


@router.get("/catalogue")
async def catalogue():
    """What can be mounted: the example plugins, described without mounting them, and the
    presets on disk. This is what the page's "add a plugin" control is built from."""
    from . import loader as loadermod, registry as registrymod
    from .plugins import CATALOGUE

    out = []
    for short in CATALOGUE:
        ref = f"studio.plugins.exp.plugins.{short}"
        try:
            described = registrymod.describe(loadermod.resolve_ref(ref))
        except (ContextError, ImportError) as exc:                # pragma: no cover
            out.append({"name": short, "use": ref, "error": str(exc)})
            continue
        out.append({**described, "use": ref})
    return {"plugins": out, "presets": loadermod.presets()}


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------
@router.post("/preset")
async def mount_preset(request: Request):
    """Mount a named preset. A diff against what is already running, not a rebuild.

    Matching is by entry id: an entry in both manifests with the same `use:` and the same config
    is left running -- same fiber, same instance, no teardown. `dev` and `failures` both name
    `bus` with the same config for exactly this reason, and
    `test_exp.py::PresetTests::test_switching_presets_leaves_the_shared_bus_alone` asserts the
    instance survives, not just the id: an entry whose *config* changed keeps its fiber id too,
    because `_patch_fiber` restarts that same handle.
    """
    try:
        _guard(request)
        loader = await _loaded()
        from .loader import preset_path
        name = str((await _body(request)).get("name") or "")
        if not name:
            raise ContextError("send {\"name\": \"<preset>\"}; "
                               f"have: {', '.join(loader.state()['presets']) or '(none)'}")
        await loader.apply(preset_path(name), label=name)
    except Denied as denied:
        return JSONResponse(denied.payload, status_code=denied.status)
    except ContextError as exc:
        return _fail(exc)
    return loader.state(with_config=True)


@router.post("/apply")
async def apply_manifest(request: Request):
    """Mount an arbitrary manifest: `{"manifest": "<yaml>"}` or `{"manifest": {...}}`."""
    try:
        _guard(request)
        loader = await _loaded()
        manifest = (await _body(request)).get("manifest")
        if manifest is None:
            raise ContextError("send {\"manifest\": \"<yaml text>\"} or a parsed object")
        await loader.apply(manifest, label="posted")
    except Denied as denied:
        return JSONResponse(denied.payload, status_code=denied.status)
    except ContextError as exc:
        return _fail(exc)
    return loader.state(with_config=True)


@router.post("/add")
async def add_entry(request: Request):
    """Mount one entry without touching anything else. The body is a manifest entry:
    `{"id": "clock2", "use": "studio.plugins.exp.plugins.clock", "config": {...}}`."""
    try:
        _guard(request)
        loader = await _loaded()
        body = await _body(request)
        raw = body.get("entry") if isinstance(body.get("entry"), dict) else body
        entry = await loader.add(raw)
    except Denied as denied:
        return JSONResponse(denied.payload, status_code=denied.status)
    except ContextError as exc:
        return _fail(exc)
    return {"entry": entry.snapshot(with_config=True), "state": loader.state()}


@router.post("/remove")
async def remove_entry(request: Request):
    try:
        _guard(request)
        loader = await _loaded()
        await loader.remove(str((await _body(request)).get("id") or ""))
    except Denied as denied:
        return JSONResponse(denied.payload, status_code=denied.status)
    except ContextError as exc:
        return _fail(exc)
    return loader.state(with_config=True)


@router.post("/patch")
async def patch_entry(request: Request):
    """Replace one entry's config and restart its fiber. `loader/patch-context` is emitted, so
    a plugin watching for its own reconfiguration hears about it before the restart."""
    try:
        _guard(request)
        loader = await _loaded()
        body = await _body(request)
        config = body.get("config")
        if not isinstance(config, dict):
            raise ContextError("send {\"id\": \"...\", \"config\": {...}}")
        entry = await loader.patch(str(body.get("id") or ""), config)
    except Denied as denied:
        return JSONResponse(denied.payload, status_code=denied.status)
    except ContextError as exc:
        return _fail(exc)
    return {"entry": entry.snapshot(with_config=True), "state": loader.state()}


@router.post("/enable")
async def enable_entry(request: Request):
    try:
        _guard(request)
        loader = await _loaded()
        body = await _body(request)
        entry = await loader.enable(str(body.get("id") or ""), bool(body.get("on", True)))
    except Denied as denied:
        return JSONResponse(denied.payload, status_code=denied.status)
    except ContextError as exc:
        return _fail(exc)
    return {"entry": entry.snapshot(with_config=True), "state": loader.state()}


@router.post("/reload")
async def reload_entry(request: Request):
    """Re-import the plugin's module and restart the fiber against the new code.

    The reply carries `entry.error`, and reading it matters: a module that no longer parses
    leaves the fiber running the code it has and reports why, which is a success for the
    process and a failure for the edit. Both are true and the caller needs to see both.
    """
    try:
        _guard(request)
        loader = await _loaded()
        entry = await loader.reload(str((await _body(request)).get("id") or ""))
    except Denied as denied:
        return JSONResponse(denied.payload, status_code=denied.status)
    except ContextError as exc:
        return _fail(exc)
    return {"entry": entry.snapshot(with_config=True), "state": loader.state()}


@router.post("/call")
async def call_service(request: Request):
    """Call a method on a live service: `{"service": "gpu", "method": "vram", "args": []}`.

    No allow-list of methods is implemented as of 2026-08-20 (R-98, held). The design argument
    for that stands on its own: a plugin runtime whose services can only be poked through
    endpoints written in advance is a runtime you cannot experiment with, and experimenting is
    what the app is called. The token is the line.

    `service` is a realm-qualified key when the service lives in one -- `GET /services` returns
    exactly the string to send. A plain name resolves in the root realm.
    """
    try:
        _guard(request)
        loader = await _loaded()
        body = await _body(request)
        name = str(body.get("service") or "")
        service = loader.runtime.services.get(name) or loader.runtime.services.get(f":{name}")
        if service is None:
            raise ContextError(f"no service {name!r}; have: "
                               f"{', '.join(sorted(loader.runtime.services)) or '(none)'}")
        method_name = str(body.get("method") or "")
        target = getattr(service.value, method_name, None)
        if not callable(target):
            raise ContextError(
                f"{name}.{method_name} is not callable; "
                f"{type(service.value).__name__} offers: "
                f"{', '.join(sorted(n for n in dir(service.value) if not n.startswith('_')))}")
        args = list(body.get("args") or ())
        kwargs = dict(body.get("kwargs") or {})
        result = target(*args, **kwargs)
        if hasattr(result, "__await__"):
            result = await result
    except Denied as denied:
        return JSONResponse(denied.payload, status_code=denied.status)
    except ContextError as exc:
        return _fail(exc)
    except Exception as exc:                                      # noqa: BLE001
        # The plugin's own exception, verbatim. Reporting it as a 500 with no detail would make
        # `/call` useless for the thing it exists for, which is finding out what a service does.
        return JSONResponse({"detail": f"{type(exc).__name__}: {exc}", "error": "plugin"},
                            status_code=400)
    return {"result": _jsonable(result), "service": service.key, "method": method_name,
            "epoch": service.epoch}


def _jsonable(value: typing.Any) -> typing.Any:
    """Best effort, then `repr`. A service method may return anything at all -- that is what a
    service is -- and returning `repr(obj)` is more useful than a 500 saying it did not
    serialise."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in value]
    return repr(value)
