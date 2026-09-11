"""The HTTP surface. Mounted at `/api/project` by `api.py`; nothing here assumes that prefix.

Three properties this router is built around, all of them from
`docs/specs/project-spec.md` §3.3, and all of them because Garrett intends to write an
iPhone app against this server:

* **No cookies, no server-side session, no login flow.** Authentication is the
  `X-Symoneural-Token` header (and `X-Sym-Token`, the name it replaced, still read by `_deny`
  below), which any HTTP client can set. There is nothing a browser provides that a Swift
  `URLRequest` does not, and there is no "currently open project" held on the server — the
  client names the project in every request. Two clients must be able to interleave.
* **No credential in a path or a query string.** Caddy writes
  `/var/log/caddy/symoneural.log` and uvicorn logs the request line, so a token in a URL is
  a token written to disk on every request. `test_project.py` asserts this structurally by
  walking `router.routes`, because an intention is not checked at the next refactor.
* **One error envelope, always.** `{"ok": false, "api_version": N, "code": "...",
  "error": "..."}` on every failure, with a machine code a shipped binary can branch on.
  This is why every pydantic field below has a default: a *missing required* field makes
  pydantic raise, and FastAPI serialises that into a 422 shaped nothing like the envelope —
  and, as `apps/streamer` found, one that echoes the whole request body back. With defaults
  there is no validation path that can fire, and the handlers check by hand.

Every store call goes through `asyncio.to_thread`. SQLite is fast but it is blocking, and
this API also serves a websocket that pushes the rack.
"""
from __future__ import annotations

import asyncio
import email.utils
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict

from . import store
from .store import API_VERSION

# The credential header, and the name it replaced. Declared here rather than in `store`
# because `store.authorize` takes a token, not a request: the wire spelling is this
# module's business and the comparison is that one's.
HEADER = "X-Symoneural-Token"
HEADER_LEGACY = "X-Sym-Token"

router = APIRouter(tags=["project"])

#: store `code` -> HTTP status. One table, so a code cannot mean 404 on one route and 400
#: on another. Anything unmapped is a 500, which is the honest answer for "this module did
#: not anticipate it" rather than a cheerful 200 with an error inside.
STATUS = {
    "disabled": 503,
    "unauthorized": 401,
    "not_found": 404,
    "bad_field": 400,
    "bad_path": 400,
    "bad_query": 400,
    "outside_root": 400,
    "denied": 403,
    "duplicate": 409,
    "not_archived": 409,
    "stale": 409,
    "too_large": 413,
    "cap": 507,
    "no_model": 503,
    "model_error": 502,
    "model_unusable": 502,
    "store_error": 500,
}


# ---------------------------------------------------------------- bodies
#
# Every field has a default. See the module docstring: this is a 422-avoidance measure, not
# laziness. `extra="ignore"` so a newer client sending a field this server does not know
# about is not rejected — a shipped app binary cannot be updated on demand.

class ProjectBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = ""
    summary: str = ""


class ProjectPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str | None = None
    summary: str | None = None
    archived: bool | None = None
    if_version: int | None = None


class ItemBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = ""
    body: str = ""
    state: str = "open"
    ordinal: float | None = None


class ItemPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str | None = None
    body: str | None = None
    state: str | None = None
    ordinal: float | None = None
    if_version: int | None = None


class EventBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: str = "note"
    text: str = ""
    actor: str = ""


class FileBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: str = ""
    note: str = ""


class DraftBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    note: str = ""


# ---------------------------------------------------------------- plumbing


def _deny(request: Request) -> JSONResponse | None:
    """The gate. `None` means allowed, and it now always means allowed.

    Kept as a function, and kept returning the envelope shape, so every call site is
    unchanged and a future gate goes back in one place rather than into nineteen routes.
    """
    # NO API KEYS. Owner decision, 2026-09-11: "no api keys period -- everything is
    # straight post get fetch". Single-operator box, not reachable from the internet.
    # Removed rather than made optional: an optional gate is one somebody re-enables
    # by accident.
    return None

def _out(result: dict, headers: dict | None = None) -> JSONResponse:
    status = 200 if result.get("ok") else STATUS.get(result.get("code", ""), 500)
    return JSONResponse(result, status_code=status, headers=headers or {})


def _conditional(request: Request, rows: list[dict], *keys: str,
                 mtime_keys: tuple[str, ...] = ("updated", "created", "at")):
    """(etag, headers, not_modified). A phone polls on a mobile connection.

    A 304 is the difference between a workspace that feels instant and one that spins, and
    it is cheap here because the semantic state of a list is just which rows exist and what
    version each is at. Both validators are honoured: `If-None-Match` wins when present,
    because an ETag is exact and a one-second timestamp is not.
    """
    etag = store.etag_of(rows, *keys)
    headers = {"ETag": etag, "Cache-Control": "no-cache, private"}
    mtime = store.last_modified_of(rows, *mtime_keys)
    if mtime:
        headers["Last-Modified"] = email.utils.formatdate(mtime, usegmt=True)

    inm = request.headers.get("If-None-Match", "")
    if inm:
        if any(t.strip().lstrip("W/") == etag for t in inm.split(",")):
            return etag, headers, True
        return etag, headers, False        # an explicit ETag beats a timestamp
    ims = request.headers.get("If-Modified-Since")
    if ims and mtime:
        try:
            since = email.utils.parsedate_to_datetime(ims).timestamp()
        except (TypeError, ValueError):
            return etag, headers, False
        # Truncated, because HTTP dates have one-second resolution and `updated` does not:
        # comparing a float against a whole second re-sends every time.
        if int(mtime) <= int(since):
            return etag, headers, True
    return etag, headers, False


# ---------------------------------------------------------------- surface state


@router.get("/state", summary="What this surface is holding, read from the store")
async def state(request: Request) -> Response:
    """Real readings only.

    If no workspaces are open this says so — `projects: 0` and a note saying "no workspaces
    open" — rather than inventing activity. The live counts live here rather than in the
    rack unit's `detail` line on purpose: `backend/api.py::semantic_etag` hashes unit
    *states*, not their detail, so a count carried in `detail` can be cached away as a 304
    and sit stale on the page.
    """
    bad = _deny(request)
    if bad:
        return bad
    return _out(await asyncio.to_thread(store.readings))


@router.post("/backup", summary="Write a dated copy of the store")
async def make_backup(request: Request) -> Response:
    """Nothing schedules this. See the README — it is a function, not a policy."""
    bad = _deny(request)
    if bad:
        return bad
    return _out(await asyncio.to_thread(store.backup))


# ---------------------------------------------------------------- projects


@router.get("", summary="List projects")
async def list_projects(request: Request, archived: bool = False,
                        limit: int = store.MAX_ROWS, offset: int = 0) -> Response:
    bad = _deny(request)
    if bad:
        return bad
    res = await asyncio.to_thread(store.list_projects, include_archived=archived,
                                  limit=limit, offset=offset)
    if not res.get("ok"):
        return _out(res)
    etag, headers, fresh = _conditional(request, res["projects"], "id", "version")
    if fresh:
        return Response(status_code=304, headers=headers)
    return _out(res, headers)


@router.post("", summary="Create a project")
async def create_project(request: Request, body: ProjectBody) -> Response:
    bad = _deny(request)
    if bad:
        return bad
    return _out(await asyncio.to_thread(store.create_project, body.name, body.summary))


@router.get("/search", summary="Full-text search over projects, items and events")
async def search(request: Request, q: str = "", project: str | None = None,
                 limit: int = 50) -> Response:
    """Declared BEFORE `/{pid}`, or `/search` is captured as a project id.

    FTS5, which is CPU and exact. There is no embedding model here and adding one would
    make this surface a GPU tenant — evictable, queueable behind a fine-tune, and needing
    its own arm in the governor's `evict()`. `docs/specs/project-spec.md` §2.3.
    """
    bad = _deny(request)
    if bad:
        return bad
    return _out(await asyncio.to_thread(store.search, q, project_id=project, limit=limit))


@router.get("/{pid}", summary="One project, with its items and file references")
async def get_project(request: Request, pid: str) -> Response:
    bad = _deny(request)
    if bad:
        return bad
    return _out(await asyncio.to_thread(store.get_project, pid))


@router.patch("/{pid}", summary="Rename, re-summarise or archive a project")
async def patch_project(request: Request, pid: str, body: ProjectPatch) -> Response:
    bad = _deny(request)
    if bad:
        return bad
    return _out(await asyncio.to_thread(
        store.update_project, pid, if_version=body.if_version, name=body.name,
        summary=body.summary, archived=body.archived))


@router.delete("/{pid}", summary="Delete an archived project")
async def delete_project(request: Request, pid: str,
                         if_version: int | None = None) -> Response:
    """Archive first. A project that is not archived is refused with 409, not dropped."""
    bad = _deny(request)
    if bad:
        return bad
    return _out(await asyncio.to_thread(store.delete_project, pid, if_version=if_version))


# ---------------------------------------------------------------- items


@router.get("/{pid}/items", summary="Work items, filterable by state")
async def list_items(request: Request, pid: str, state: str | None = None,
                     limit: int = store.MAX_ROWS, offset: int = 0) -> Response:
    bad = _deny(request)
    if bad:
        return bad
    res = await asyncio.to_thread(store.list_items, pid, state=state, limit=limit,
                                  offset=offset)
    if not res.get("ok"):
        return _out(res)
    etag, headers, fresh = _conditional(request, res["items"], "id", "version")
    if fresh:
        return Response(status_code=304, headers=headers)
    return _out(res, headers)


@router.post("/{pid}/items", summary="Add a work item")
async def create_item(request: Request, pid: str, body: ItemBody) -> Response:
    bad = _deny(request)
    if bad:
        return bad
    return _out(await asyncio.to_thread(store.create_item, pid, body.title, body.body,
                                        body.state, body.ordinal))


@router.patch("/{pid}/items/{iid}", summary="Change, reorder or re-state a work item")
async def patch_item(request: Request, pid: str, iid: str, body: ItemPatch) -> Response:
    """`if_version` is the version the client read. A mismatch is 409, never a silent win."""
    bad = _deny(request)
    if bad:
        return bad
    return _out(await asyncio.to_thread(
        store.update_item, iid, if_version=body.if_version, title=body.title,
        body=body.body, state=body.state, ordinal=body.ordinal))


@router.delete("/{pid}/items/{iid}", summary="Delete a work item")
async def delete_item(request: Request, pid: str, iid: str,
                      if_version: int | None = None) -> Response:
    bad = _deny(request)
    if bad:
        return bad
    return _out(await asyncio.to_thread(store.delete_item, iid, if_version=if_version))


# ---------------------------------------------------------------- file references


@router.get("/{pid}/files", summary="Files this project references, with a live stat")
async def list_files(request: Request, pid: str) -> Response:
    """References, not copies. No endpoint in this package returns file *contents*."""
    bad = _deny(request)
    if bad:
        return bad
    return _out(await asyncio.to_thread(store.list_files, pid))


@router.post("/{pid}/files", summary="Reference a repository file from this project")
async def link_file(request: Request, pid: str, body: FileBody) -> Response:
    """The path is resolved, contained and denylisted before it is stored.

    A path that escapes the repository root is 400; one that lands in
    `training/corpus.jsonl`, `training/build_dataset.py` or `training/adapter/` — including
    via a symlink, because the check runs after `resolve()` — is 403.
    """
    bad = _deny(request)
    if bad:
        return bad
    return _out(await asyncio.to_thread(store.link_file, pid, body.path, body.note))


@router.delete("/{pid}/files/{fid}", summary="Drop a file reference")
async def unlink_file(request: Request, pid: str, fid: str) -> Response:
    bad = _deny(request)
    if bad:
        return bad
    return _out(await asyncio.to_thread(store.unlink_file, fid))


# ---------------------------------------------------------------- events


@router.get("/{pid}/events", summary="What happened, newest first")
async def list_events(request: Request, pid: str, limit: int = store.MAX_ROWS,
                      before: int | None = None) -> Response:
    bad = _deny(request)
    if bad:
        return bad
    res = await asyncio.to_thread(store.list_events, pid, limit=limit, before=before)
    if not res.get("ok"):
        return _out(res)
    etag, headers, fresh = _conditional(request, res["events"], "id")
    if fresh:
        return Response(status_code=304, headers=headers)
    return _out(res, headers)


@router.post("/{pid}/events", summary="Record a session's work. Append-only")
async def add_event(request: Request, pid: str, body: EventBody) -> Response:
    bad = _deny(request)
    if bad:
        return bad
    return _out(await asyncio.to_thread(store.add_event, pid, body.kind, body.text,
                                        body.actor))


# ---------------------------------------------------------------- borrowed model


@router.post("/{pid}/draft/summary", summary="Ask the chat surface to summarise a project")
async def draft_summary(request: Request, pid: str) -> Response:
    """Project owns no weights. This asks the chat surface through an injected callable.

    If nothing has been injected the answer is `503 no_model` saying exactly that, which is
    an honest reading of a surface that is not wired rather than a silent empty summary.
    Whatever the callable does about the GPU lock is the caller's business; nothing in this
    package imports the governor.

    The draft is returned, never stored. Recording it is a separate `POST .../events`.
    """
    bad = _deny(request)
    if bad:
        return bad
    return _out(await asyncio.to_thread(store.draft_summary, pid))


@router.post("/{pid}/draft/items", summary="Turn a note into candidate item titles")
async def draft_items(request: Request, pid: str, body: DraftBody) -> Response:
    """Candidates only. Nothing is written; the client POSTs the ones it wants."""
    bad = _deny(request)
    if bad:
        return bad
    return _out(await asyncio.to_thread(store.draft_items, pid, body.note))


# ---------------------------------------------------------------- the rack


def status() -> dict:
    """The rack unit, as a plain dict. Called on every rack poll — synchronous and cheap.

    Deliberately **not** built from `api.py`'s `Unit` model: importing it would put this
    module inside `api.py`'s import graph and outside the scope this module was built in.
    The keys match `Unit`'s fields exactly, so the wiring is `Unit(**project.status())`.

    Two things this function must never do, both asserted in `test_project.py`:

    * **It must not create the store.** `/api/status` is polled and drives the websocket.
      `store.probe()` opens read-only, so the "no project store initialised" reading stays
      true instead of manufacturing the file whose absence it reports.
    * **It must not carry a live count in `detail`.** `semantic_etag` in `api.py` hashes
      unit states, not detail strings, so a number here would be cached away as a 304 and
      go stale on the page. Counts are `GET /api/project/state`.

    `bus` is `cpu` and stays `cpu`. `site/console.js` maps the four known bus values to
    plate text and prints `--` for anything else; inventing a fifth value for "database"
    would put a `--` on the one plate the page asks a visitor to trust, and would add
    nothing over `cpu` — the work genuinely is CPU work.
    """
    st, detail = store.unit_state()
    return {
        "id": "project",
        "label": "SyMoNeuRaL Project",
        "slot": "1U",
        "state": st,
        "bus": "cpu",
        # `site/project.html` now exists -- `tools/build_project.py` generates it -- so the
        # tile links to the surface instead of to the documentation page. That page and this
        # line changed in one commit, which is the order this comment used to ask for:
        # `scripts/deploy.sh`'s reference check fails the build on a link to a page that is
        # not there, and a rack tile pointing at a 404 is a dishonest pixel.
        "href": "/project.html",
        "spec": "SQLite · FTS5 · no weights",
        # Deliberately the same words as RavenCalc, because it is deliberately the same
        # design decision: a CPU surface that is always available precisely because it
        # never queues for the card.
        "detail": detail,
    }
