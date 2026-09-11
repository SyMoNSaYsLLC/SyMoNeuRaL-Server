"""local: routes that were declared on `app` in server.py.

Paths here are absolute, so this router is mounted WITHOUT a prefix.
Globals come off `core.context.ctx`; importing server would be a cycle.
"""
from __future__ import annotations
from core.config import ROOT

import re
import time
from fastapi import (Depends, FastAPI, HTTPException, Request, Response, WebSocket,
                     WebSocketDisconnect, status as http)
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
import coder      # noqa: E402  -- local-only developer surface. Takes NO GPU lease and
import streamer  # noqa: E402  -- the IPTV surface AND the Guide that filters
from streamer import guide  # noqa: E402  -- the library half: matching, clustering,
import studio  # noqa: E402  -- the local agent and the

from fastapi import APIRouter

from core.context import ctx

router = APIRouter()


@router.post("/local/intake", include_in_schema=False)
async def local_intake(body: ctx.IntakeSet, request: Request) -> JSONResponse:
    """Set one assignment's box in INTAKE.md: `[ ]`, `[x]` ready, or `[-]` dropped.

    Rewrites the ONE box line belonging to the named entry and nothing else -- Garrett's
    answers, briefs, task numbers and prose are lines this never looks at. Written to a
    temporary file in the same directory and renamed over the target, at mode 600, so a crash
    midway leaves the original rather than half a ledger, and the copy is never briefly
    world-readable on a box that also runs a web server.
    """
    ctx._require_local(request)
    target = ROOT / "INTAKE.md"
    if not target.is_file():
        raise HTTPException(status_code=404, detail="INTAKE.md has not been generated yet")

    head = re.compile(r"^## (A-[A-Z0-9]+) \[")
    box = re.compile(r"^\[[ xX-]\]\s*$")
    lines = target.read_text().splitlines()
    current, hit = None, False
    for i, line in enumerate(lines):
        m = head.match(line)
        if m:
            current = m.group(1)
        elif current == body.id and box.match(line):
            lines[i] = f"[{body.set}]"
            hit = True
            break            # the FIRST box under the heading, never a later one
    if not hit:
        raise HTTPException(status_code=404, detail=f"no assignment {body.id} in INTAKE.md")

    tmp = target.with_suffix(".md.tmp")
    tmp.write_text("\n".join(lines) + "\n")
    tmp.chmod(0o600)
    tmp.replace(target)
    ctx.log.info("intake %s -> [%s]", body.id, body.set)
    return JSONResponse({"id": body.id, "set": body.set})
@router.post("/local/tasknote", include_in_schema=False)
async def local_tasknote(body: ctx.TaskNote, request: Request) -> JSONResponse:
    """Append one `note:` line to a task's indented detail block in PROJECT-TASKS.md.

    Append-only on purpose: it inserts after the last indented line of the task and rewrites
    nothing, so two comments cannot collide and no existing line can be lost to a bug here.

    THE INDENTATION IS LOAD-BEARING, not cosmetic. `tools/lib/archive_tasks.py` ends a task block
    at the first non-blank column-zero line, so a comment written flush left would sever its
    own task from every detail line below it the next time the archiver ran. Newlines inside
    the comment are re-prefixed for the same reason, and keeping `note:` on every line also
    stops a comment that happens to read `owner: garrett` or `check: exists x` from being
    parsed by `build_progress.py` as a directive somebody declared.
    """
    ctx._require_local(request)
    target = ROOT / "PROJECT-TASKS.md"
    if not target.is_file():
        raise HTTPException(status_code=404, detail="PROJECT-TASKS.md not found")

    row = re.compile(r"^[◼◻▶⊘] ((?:\(unnumbered[^)]*\))|#\d+) — ")
    lines = target.read_text().splitlines()
    start = None
    for i, line in enumerate(lines):
        m = row.match(line)
        if m and m.group(1) == body.id:
            start = i
            break
    if start is None:
        raise HTTPException(status_code=404, detail=f"no task {body.id} in PROJECT-TASKS.md")

    # The end of the block is the last INDENTED line under the row. Trailing blank lines are
    # not part of it -- inserting into them would drift the comment away from its task by one
    # line per comment, and eventually out of the block entirely.
    end = start
    for i in range(start + 1, len(lines)):
        if lines[i].startswith((" ", "\t")):
            end = i
        elif lines[i].strip() == "":
            continue
        else:
            break

    stamp = time.strftime("%Y-%m-%d")
    body_lines = [ln.strip() for ln in body.text.splitlines() if ln.strip()]
    new = [f"        note: {stamp} {body.who} — {body_lines[0]}"]
    new += [f"        note: {ln}" for ln in body_lines[1:]]
    lines[end + 1:end + 1] = new

    tmp = target.with_suffix(".md.tmp")
    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(target)
    ctx.log.info("tasknote %s by %s (%d chars)", body.id, body.who, len(body.text))
    # The rendered line goes back so the page shows exactly what was written, rather than the
    # browser guessing at the format and drifting from the file it claims to mirror.
    return JSONResponse({"id": body.id, "line": new[0].strip()[len("note: "):]})
@router.get("/local/progress", include_in_schema=False)
async def local_progress(request: Request) -> FileResponse:
    """Serve run/progress.html from this origin, so the buttons above are same-origin.

    The page still works opened straight off disk -- it detects `file:` and tells Garrett what
    to type instead. This route exists so that it does not have to.
    """
    ctx._require_local(request)
    f = ROOT / "run" / "progress.html"
    if not f.is_file():
        raise HTTPException(status_code=404,
                            detail="run/progress.html has not been generated; "
                                   "run python3 tools/build/build_progress.py")
    # no-store: the page is regenerated every two minutes by symoneural-progress.timer, and a
    # cached copy of a status page is worse than no status page.
    return FileResponse(f, media_type="text/html", headers={"Cache-Control": "no-store"})
@router.get("/local/coder/status", include_in_schema=False)
async def local_coder_status(request: Request) -> JSONResponse:
    """What the surface is, plus each gate separately.

    `authorize()` returns the FIRST refusal and stops, which is right for an answer and
    useless for an instrument: an operator reading "surface disabled" cannot tell whether the
    token is also missing, so turning the flag on would just move them to the next refusal.
    The three predicates are read individually here so the page can show all three at once
    and say what to set. They are booleans about configuration -- no value is disclosed.
    """
    ctx._require_local(request)
    peer = request.client.host if request.client else ""
    body = coder.status(token=ctx._coder_token(), peer=peer)
    body["gates"] = {
        "enabled": coder.enabled(),
        "token_set": bool(ctx._coder_token()),
        "peer_loopback": coder.peer_is_loopback(peer),
        "allow_remote": coder.allow_remote(),
    }
    # A property of THIS MOUNT, not of the module: `coder` can write and can run processes,
    # and the page says so rather than implying the capability does not exist.
    body["mount"] = {"read_only": True, "prefix": "/local/coder", "peer": peer}
    return JSONResponse(body, headers={"Cache-Control": "no-store"})
@router.get("/local/coder/ls", include_in_schema=False)
async def local_coder_ls(request: Request, path: str = ".",
                         recursive: bool = False) -> JSONResponse:
    return ctx._coder_read(request, coder.list_dir, path=path, recursive=recursive)
@router.get("/local/coder/file", include_in_schema=False)
async def local_coder_file(request: Request, path: str) -> JSONResponse:
    return ctx._coder_read(request, coder.read_file, path=path)
@router.get("/local/coder/history", include_in_schema=False)
async def local_coder_history(request: Request, path: str) -> JSONResponse:
    return ctx._coder_read(request, coder.history, path=path)
@router.get("/local/coder/journal", include_in_schema=False)
async def local_coder_journal(request: Request, n: int = 50) -> JSONResponse:
    """The audit trail. Gated like every other read -- it names paths."""
    return ctx._coder_read(request, coder.journal_tail, n=max(1, min(500, n)))
