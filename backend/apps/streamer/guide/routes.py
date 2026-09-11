"""The HTTP surface for SyMoNeuRaL Guide. Mounted at `/api/streamer/guide` by `backend/api.py`.

The prefix is NESTED under the streamer's rather than sitting beside it, and that is the
one thing to know before moving it: this router and the streamer's both declare `/state`,
so a shared flat prefix registers the second one where the first already answers and the
guide's probe silently becomes unreachable. It was `/api/guide` until the merge.

Guide turns a sentence into a filter over a channel list. The module beside this one does
all of that; this file is only the boundary.

**Why this is a unit and not a hidden helper inside the Streamer.** The module's author
recommended folding it into the Streamer, and on architecture grounds that is defensible --
it owns no weights and no hardware. It is a unit anyway, for a reason that is about
honesty rather than structure: the Streamer page runs a local pass in the visitor's browser
and only sometimes reaches for the model, and a visitor watching a filter resolve
instantly has no way to know whether anything on this box was involved. A named unit on
the rack, reporting what it actually did, is how that stays legible. `source` and
`model_used` come back on every answer for the same reason.

**Nothing here is stored.** The channel list arrives in the request body, is used, and is
dropped. Same contract as the Streamer: the playlist belongs to the visitor's browser.

**No content filtering, and there is no denylist in this package.** Guide narrows a list
to what somebody asked for; it never removes anything they did not ask to remove. If a
question matches an adult category, that category is what comes back.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import ModelUnusable, apply_filter, catalogue, filter_from_question, unit_state

log = logging.getLogger("symoneural.guide")

router = APIRouter(tags=["guide"])

#: The same generous ceiling the Streamer uses for a pasted playlist, for the same reason: a
#: provider export genuinely is tens of thousands of entries, and an unbounded request body
#: is a memory bug with a friendly name.
MAX_CHANNELS = 40_000

#: Set by `backend/api.py` at import: a `str -> str` callable that asks the chat surface.
#: Left as None the module is local-only and says so in every answer it gives -- it does
#: not pretend the model was consulted.
ASK_MODEL: Callable[[str], str] | None = None


class Channel(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = ""
    group: str = ""
    kind: str = ""
    url: str = ""


class FilterBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    question: str = ""
    channels: list[Channel] = Field(default_factory=list)
    #: Ask the model when the local pass is thin. Default off, so the caller decides
    #: whether a question is worth queueing behind whatever holds the card.
    use_model: bool = False
    #: Return the matching channels, not just the filter. Off by default because the
    #: caller usually already holds the list and only needs the filter to apply.
    apply: bool = False


class CatalogueBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    channels: list[Channel] = Field(default_factory=list)


def _channels(body_channels: list[Channel]) -> list[dict]:
    if not body_channels:
        raise HTTPException(400, "send the channel list to filter; this box stores none")
    if len(body_channels) > MAX_CHANNELS:
        raise HTTPException(413, f"more than {MAX_CHANNELS:,} channels in one request")
    return [c.model_dump() for c in body_channels]


@router.post("/catalogue", summary="Kinds, groups and group clusters for a channel list")
async def catalogue_route(body: CatalogueBody) -> dict:
    """What vocabulary this playlist actually uses. Nothing is stored."""
    chans = _channels(body.channels)
    return await asyncio.to_thread(catalogue, chans)


@router.post("/filter", summary="Turn a question into a channel filter")
async def filter_route(body: FilterBody) -> dict:
    """Local pass first; the model only if asked for AND the local pass came back thin.

    The model half is deliberately opt-in per request. Guide answers in well under a
    millisecond on this box, and queueing every question behind a 7B that may be evicted
    for an image render would make the fast path invisible.
    """
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(400, "ask a question")
    chans = _channels(body.channels)

    cat = await asyncio.to_thread(catalogue, chans)
    ask = ASK_MODEL if (body.use_model and ASK_MODEL is not None) else None

    def _run() -> dict:
        return filter_from_question(
            question,
            kinds=list(cat.get("kinds", {}).keys()),
            groups=[c.get("group", "") for c in chans],
            names=[c.get("name", "") for c in chans],
            # `catalogue()` returns its clusters under "groups" -- there is no
            # "clusters" key, and asking for one silently passed None, which made
            # the module recompute the clustering it had just been handed.
            clusters=cat.get("groups"),
            ask_model=ask)

    try:
        filt = await asyncio.to_thread(_run)
    except ModelUnusable as exc:
        # The model answering badly is not the same as the question being unanswerable,
        # and collapsing the two is what makes a refusal look like a filter. Say which.
        raise HTTPException(502, f"the model half failed: {exc}") from None

    out: dict[str, Any] = {
        **filt,
        "model_offered": ASK_MODEL is not None,
        "model_asked": ask is not None,
    }
    if body.apply:
        matched, used, dropped = await asyncio.to_thread(_relax, chans, filt)
        out["count"] = len(matched)
        out["channels"] = matched
        out["relaxed"] = dropped
        if dropped:
            # The filter that was actually applied, not the one that was derived. A
            # response whose `why` and whose `channels` disagree is worse than either.
            out.update({k: used[k] for k in ("kind", "match", "groups") if k in used})
            out["why"] = str(out.get("why", "")) + _relax_note(dropped, len(matched))
    return out


# --------------------------------------------------------------- empty-result relaxation

#: Constraints in order of how much evidence stands behind them, WEAKEST FIRST -- this is
#: the order they get dropped in when the combination matches nothing.
#:
#: `kind` is weakest because it is inferred from a generic English word: "movies" sets
#: kind=vod whether or not this provider marks anything as vod, and `m3u.py::_classify()`
#: admits it is "honestly wrong-by-default (live)". `match` terms come next -- they are the
#: visitor's own words, but matched against channel names, which providers write however
#: they like. `groups` is strongest and is dropped last, because a group title is a string
#: THIS playlist actually contains; it was not guessed.
_RELAX_ORDER = ("kind", "match")


def _relax(chans: list[dict], filt: dict) -> tuple[list[dict], dict, list[str]]:
    """Apply a filter; if it matches nothing, drop its weakest constraint and retry.

    **Why this exists.** "adult movies" on a real playlist derives kind=vod AND
    group=XXX ADULT, and the provider classifies its adult channels as live -- so the
    intersection is empty and the visitor is shown nothing. From the outside that is
    indistinguishable from the category being censored, which is precisely the complaint
    that started this work, and there is no filter anywhere in this codebase doing it.

    An empty answer is still allowed to be the answer: relaxation stops before dropping the
    last constraint, so this can never quietly hand back the entire playlist. Whatever it
    drops is returned, and the caller must say so -- a filter that silently searched for
    something other than what was asked is the dishonest version of this feature.
    """
    matched = apply_filter(chans, filt)
    if matched:
        return matched, filt, []

    live = [k for k in ("kind", "match", "groups") if filt.get(k)]
    if len(live) < 2:
        return matched, filt, []          # one constraint, and it matched nothing. True.

    relaxed = dict(filt)
    dropped: list[str] = []
    for key in _RELAX_ORDER:
        if not relaxed.get(key):
            continue
        remaining = [k for k in ("kind", "match", "groups") if relaxed.get(k)]
        if len(remaining) < 2:
            break                          # never drop the last one
        was = relaxed[key]
        relaxed = {**relaxed, key: None if key == "kind" else []}
        dropped.append(f"{key}={was}" if key == "kind" else f"{key}={', '.join(was)}")
        matched = apply_filter(chans, relaxed)
        if matched:
            return matched, relaxed, dropped
    return matched, relaxed, dropped


def _relax_note(dropped: list[str], n: int) -> str:
    what = " and then ".join(dropped)
    return (f" \u2014 nothing matched all of that, so {what} was set aside and this is "
            f"what is left ({n} channel{'s' if n != 1 else ''}). Nothing was filtered out "
            f"on this box; the combination simply had no members.")


@router.get("/state", summary="What Guide can do on this box right now")
async def state() -> dict:
    """Real readings only. `channels_known` is zero and always will be: the playlist lives
    in the visitor's browser and this box holds none of it."""
    state_, detail = unit_state()
    return {
        "state": state_,
        "detail": detail,
        "model_available": ASK_MODEL is not None,
        "channels_known": 0,
        "max_channels_per_request": MAX_CHANNELS,
        "note": "no playlist, credential or question is stored on this box",
    }


def status() -> dict:
    """The rack unit, shaped for `api.py`'s `Unit`.

    `Unit.state` is a `Literal["ready","busy","queued","offline"]` -- a fifth word here is
    not a bad LED, it is a pydantic ValidationError on `/api/status`, which drives the
    rack websocket for every visitor. `unit_state()` returns `ready` from that vocabulary.
    """
    state_, detail = unit_state()
    return {
        "id": "guide", "label": "SyMoNeuRaL Guide", "slot": "1U",
        "state": state_, "bus": "cpu", "href": "/streamer.html",
        "spec": "question → channel filter · CPU",
        "detail": detail,
    }
