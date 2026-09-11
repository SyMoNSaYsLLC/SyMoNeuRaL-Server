"""RavenCalc as its own process — the split pilot.

    <root>/backend/ravencalc/.. is not on the path; run it from `backend/`:
        python3 -m uvicorn ravencalc.service:app --host 127.0.0.1 --port 8811

    or, the way the unit does it:
        ops/symoneural-surface@.service  ->  Environment=SURFACE=ravencalc

## Why RavenCalc first

It is the minimal case: 785 lines already in this package, `sympy` its only dependency, CPU
only, **no GPU lease**, and `api.py:75` — *"an app, not a helper module"*. If the packaging
pattern does not work here it works nowhere.

**And it proves the skeleton, not the split.** It takes no lease, so it exercises nothing of
the governor invariant. It has no rack power state worth gating. Its unit row is derivable
from a constant, so it barely tests the aggregation. The one hard thing it CAN carry is
whether the rack tells the truth when this process is gone — see `/healthz` below and
`tools/surface_pilot_proof.py`.

## What it does NOT duplicate

The request contract, the rate limits and the client key all come from shared code:
`apps.ratelimits` holds the published budgets **and** the token bucket, so this process
enforces the same cap `api.py` does rather than a second policy that can drift. That was the
first thing the split forced, and it is the pattern every later surface follows.

## The authority question

While `ops/PORTS.tsv` marks `ravencalc` DELEGATED, `backend/server.py` does **not** register its
inline `/api/ravencalc` route, so exactly one process can answer. While it says `no`, the
monolith answers and this process is spare capacity nobody routes to. There is deliberately
no state in which both answer: see `apps/ports.py`, which refuses to report a surface
delegated unless it also has a port.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import time
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

HERE = pathlib.Path(__file__).resolve().parent
# `ravencalc.py` sits beside this file and is imported by bare name, exactly as `api.py:79`
# arranges it. Doing it here too is what lets this process run without api.py present.
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
# `apps.*` for the shared libraries.
BACKEND = HERE.parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from runtime.lib import ratelimits  # noqa: E402
from registry.lib.ports import base_url, port_of  # noqa: E402

SURFACE = "ravencalc"
MAX_EXPRESSION_CHARS = 100_000

_limiters = ratelimits.limiters_for(ratelimits.BUDGETS)


class CalcRequest(BaseModel):
    """A symbolic computation. Exact in, exact out -- no floats that lost the argument.

    Field-for-field the same contract `api.py`'s inline route served, because a split must
    not be visible to a client. The model lives here rather than in `api.py` because the
    surface owns its own contract once it owns its own process -- that is the dependency
    direction the split is for.
    """
    expression: str = Field(..., max_length=MAX_EXPRESSION_CHARS, examples=["x**2*sin(x)"])
    operation: Literal["differentiate", "integrate", "limit", "series",
                       "solve", "simplify", "evaluate"] = "simplify"
    variable: str | None = Field("x", max_length=64)
    point: str | None = Field(None, max_length=64,
                              description="Only meaningful for `limit`.")


async def throttle(request: Request) -> None:
    """The published cap, enforced from the same table `api.py` publishes."""
    key = ratelimits.client_key_from_headers(
        request.headers, request.client.host if request.client else None)
    if not await ratelimits.allowed(_limiters, SURFACE, key):
        per_min, per_hour = ratelimits.BUDGETS[SURFACE]
        raise HTTPException(
            429,
            f"Easy — {SURFACE} is capped at {per_min}/min and {per_hour}/hour per address.")


app = FastAPI(
    title="SyMoNeuRaL RavenCalc",
    description="Exact symbolic mathematics. No GPU, no lock, no queue.",
    docs_url=None, redoc_url=None,   # the monolith owns /docs; a second copy would confuse
)


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    """The unit row this surface owns, for the rack to poll.

    **This is the piece the pilot exists to test.** In the monolith `/api/status` read this
    from memory; split, it has to come over HTTP, and the interesting case is when it does
    not come at all. So this returns the row and nothing else — no aggregation, no opinion
    about other surfaces — and the caller decides what an absent answer means.

    `state` is `ready` unconditionally and that is honest for this surface: RavenCalc has no
    weights to be missing and no lock to be behind. `api.py`'s own comment says it *"never
    queues behind anything"*. A surface with weights returns `offline` here when they are
    absent, which is the same contract.
    """
    ok = True
    detail = "cpu only, never queues"
    try:
        import ravencalc  # noqa: F401
    except ImportError as exc:      # pragma: no cover -- would mean a broken deployment
        ok, detail = False, f"ravencalc module not importable: {exc}"
    return {
        "id": SURFACE,
        "label": "SyMoNeuRaL RavenCalc",
        "slot": "1U",
        "state": "ready" if ok else "offline",
        "bus": "cpu",
        "href": "/ravencalc.html",
        "spec": "exact symbolic mathematics",
        "detail": detail,
        "pid": __import__("os").getpid(),
        "port": port_of(SURFACE),
    }


@app.post("/api/ravencalc", tags=["surfaces"])
async def calc(body: CalcRequest, _: Annotated[None, Depends(throttle)]) -> dict:
    """Exact symbolic mathematics. No GPU, no lock, no queue.

    Byte-for-byte the same response document `api.py` returned: a `ravencalc/result/v1` with
    `check` three-valued, where `null` means the check could not confirm the result and is
    reported rather than rounded up to success.
    """
    try:
        import ravencalc
    except ImportError:
        raise HTTPException(503, "RavenCalc is unavailable.")

    doc = {"schema": "ravencalc/request/v1", "operation": body.operation,
           "expression": body.expression}
    if body.variable:
        doc["variable"] = body.variable
    if body.point:
        doc["point"] = body.point

    started = time.time()
    try:
        result = await asyncio.to_thread(ravencalc.run_request, doc)
    except ravencalc.RavenCalcError as exc:
        raise HTTPException(400, exc.message)
    result["seconds"] = round(time.time() - started, 4)
    return json.loads(json.dumps(result, default=str))


def main() -> int:  # pragma: no cover -- the unit's entry point
    import uvicorn
    port = port_of(SURFACE)
    if port is None:
        print(f"{SURFACE} has no PORT in ops/PORTS.tsv -- refusing to guess", file=sys.stderr)
        return 1
    print(f"symoneural-{SURFACE} on {base_url(SURFACE)} (loopback only)")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
