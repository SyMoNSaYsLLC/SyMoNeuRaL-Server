"""`/local/coders/*` -- the multi-coder session surface. R-184.

MOUNTED UNDER /local AND NOT /api, and that is a security boundary rather than a naming
preference. `ops/Caddyfile` reverse-proxies the entire `/api/*` subtree to the public
internet -- `https://symoneural.com/api/status` answers 200 right now -- so an
`/api/coders/...` route would be reachable from outside the moment it existed. These
routes spawn provider CLIs **using the operator's own logged-in sessions**, so a public
route here would hand an anonymous caller his Claude account and his Codex quota.

`api.py` already reached this conclusion once, for the Coder surface, and the reasoning is
recorded in the `Unit(id="coder", ...)` comment in `build_status()`. This follows it.

Every route depends on `_require_local`, which checks the peer address AND refuses
`x-forwarded-*` headers, so even a future `handle /local*` block in the Caddyfile could not
quietly open this up.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import (CODER_IDS, MAX_PROMPT_CHARS, DEADLINE_S, ENV_ENABLED, enabled,
               get_session, preset_rows, providers, recent, run_session, run_debate,
               record_decision, MAX_DEBATE_ROUNDS)


def _require_enabled() -> None:
    """The switch, checked on every route rather than at mount time.

    At mount time it would be read ONCE, at import, so flipping the switch would need an API
    restart to take effect in one direction and -- worse -- a surface enabled at boot would
    stay enabled for the life of the process no matter what the environment said afterwards.
    Reading it per request costs one dict lookup and means the switch means what it says.

    404, not 403, and it is the same 404 `_require_local` returns to an off-box caller: a
    surface that is switched off should be indistinguishable from a surface that was never
    built, so probing cannot map what this box could do if it were turned on.
    """
    if not enabled():
        raise HTTPException(status_code=404)


#: Both gates on the router itself, so a route added to this file later inherits them rather
#: than relying on its author to remember. `_require_local` is applied where the router is
#: mounted, in api.py, because it needs the request's peer; this one needs nothing but the
#: environment and so belongs with the surface it guards.
router = APIRouter(dependencies=[Depends(_require_enabled)])


class AskRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    coder_ids: list[str] = Field(min_length=1, max_length=3)


class DecisionRequest(BaseModel):
    # Which coder's answer the OPERATOR chose. Free-text is deliberately not accepted: this
    # records a choice between answers that exist, not a new answer.
    coder_id: str
    expected_round: int = Field(default=0, ge=0)


class DebateRequest(BaseModel):
    clarification: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    expected_round: int = Field(ge=0)


@router.get("/providers", include_in_schema=False)
async def get_providers() -> dict:
    """Measured readiness, re-read on every call.

    Never cached. A cached `available: true` outliving the thing it describes is how #94's
    rack read READY over a dead bench.
    """
    return {
        "providers": [
            {"id": p.coder_id, "display": p.display, "available": p.available,
             "detail": p.detail, "answer_only_proven": p.answer_only_proven}
            for p in providers()
        ],
        "presets": preset_rows(),
        "discussion": {"available": True, "max_rounds": MAX_DEBATE_ROUNDS},
        "modes": {
            # The other two modes are SPECIFIED and not built. They are reported as
            # unavailable with the reason, rather than rendered as buttons that look
            # clickable and do nothing -- "do not make decorative controls appear
            # functional" is in this batch's own plan.
            "multi_response": {"available": True, "detail": "one prompt, every coder answers"},
            "rotation": {"available": False,
                         "detail": "R-182 sequential plan/execute/handoff is file-based "
                                   "today; not driven from this surface yet"},
            "training": {"available": False,
                         "detail": "R-185 requires trainer/receiver selection and unanimous "
                                   "trainer approval; not implemented"},
        },
    }


@router.post("/ask", include_in_schema=False)
async def ask(body: AskRequest) -> dict:
    """One prompt to every selected coder. Returns when they have all answered or failed."""
    unknown = [c for c in body.coder_ids if c not in CODER_IDS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown coder(s): {unknown}")
    if len(set(body.coder_ids)) != len(body.coder_ids):
        raise HTTPException(status_code=400, detail="a coder was selected twice")
    if not body.prompt.strip():
        raise HTTPException(status_code=400, detail="enter a prompt")
    s = await run_session(body.prompt.strip(), body.coder_ids, DEADLINE_S)
    return s.to_dict()


@router.get("/session/{sid}", include_in_schema=False)
async def session(sid: str) -> dict:
    s = get_session(sid)
    if s is None:
        raise HTTPException(status_code=404, detail="no such session")
    return s.to_dict()


@router.get("/sessions", include_in_schema=False)
async def sessions() -> dict:
    return {"sessions": recent()}


@router.post("/session/{sid}/decide", include_in_schema=False)
async def decide(sid: str, body: DecisionRequest) -> dict:
    """Record which answer the operator chose when the coders disagreed.

    This is the whole of R-184's resolution step: the machine surfaced the options and the
    human picked. There is deliberately no auto-select, no ranking, and no "best answer"
    heuristic -- the owner reserved that decision, and a launcher that quietly picks for him
    would be answering a question he asked to be shown.
    """
    s = get_session(sid)
    if s is None:
        raise HTTPException(status_code=404, detail="no such session")
    try:
        record_decision(s, body.coder_id, body.expected_round)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return s.to_dict()


@router.post("/session/{sid}/debate", include_in_schema=False)
async def debate(sid: str, body: DebateRequest) -> dict:
    s = get_session(sid)
    if s is None:
        raise HTTPException(status_code=404, detail="no such session")
    try:
        await run_debate(s, body.clarification, body.expected_round)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return s.to_dict()
