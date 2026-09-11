"""Real numbers about the model's work, read from the hardware and the engine. Never asserted.

Owner instruction, 2026-09-11: *"gauge and metric the model based off real fucking numbers
from the hardware"*, and then *"bring all this out to the html"*.

## The one rule this module exists to enforce

**Every figure published here is a reading, and every reading carries where it came from.**
Nothing in this file computes a number from a specification sheet, a config default, or a
previous measurement. If a source cannot be read right now, the field is `None` and the
`source` says why -- it is never filled in with the value it "should" be.

That rule is not decorative. `backend/studio/docs/qlora-27b-measured.md` records that budgeting against
this card's **nameplate** 15.92 GiB instead of the ~14.2 GiB actually free is how a run OOMs at
step 0, and `registry.py` carries three more constants that each cost a real run to learn. A
page that prints a plausible number with no source attached is how that happens again.

So each group below is a `Reading`: a value, a unit, and a one-line `source` naming the exact
command or endpoint. The HTML renders the source beside the number.

## Where the three sources are, and what each one alone cannot tell you

| source | answers | cannot answer |
|---|---|---|
| `nvidia-smi` | what the *card* is doing: VRAM, utilisation, temperature, power, clocks | anything about tokens |
| llama-server `/props` | how the model is *configured*: context window, slots, which weights | how fast it ran |
| the stream's final chunk | what the last request actually *cost*: tokens in/out, tok/s, cache hits | the card's state |

The third is the interesting one and it is free. llama-server appends a `timings` object to the
final SSE chunk of every `/v1/chat/completions` stream. `api.py::chat_deltas` used to read the
content delta out of each chunk and discard everything else, so those numbers were measured on
every request this box has ever served and thrown away every time. `record_timings()` below is
what catches them. **No probe request is issued to produce them** -- a metrics page that asks
the model a question to find out how fast the model is would take the GPU lease to do it, and
would be measuring itself.

## Why a ring buffer and not a running average

An average over all time hides the thing an operator is looking at the page to find: that it
got slower ten minutes ago. `RECENT` keeps the last `WINDOW` requests with their timestamps so
the page can show the series. It is in memory and dies with the process, which is correct --
this is a live gauge, not a history, and `run/` already holds the durable records.

## What this module deliberately does not do

* **It does not start the engine.** If llama-server is not resident, context and timings read
  `None` with a source saying so, and the card group still answers. Starting a 7B to populate a
  status page would evict whatever holds the card, which is `guide_ask_model`'s rule too.
* **It does not take the GPU lease.** Every read here is either a `nvidia-smi` query, an HTTP
  GET to an already-running process, or a dictionary lookup.
"""
from __future__ import annotations

import asyncio
import collections
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict, field
from typing import Any

#: llama-server. Same constant as `api.py::LLAMA_PORT`, and the duplication is deliberate:
#: importing `api` from a module `api` imports would be a cycle. The test asserts they agree.
LLAMA_PORT = 8081

#: How many recent requests the page can draw. Small on purpose -- this is a gauge.
WINDOW = 60

#: Timings from the last `WINDOW` completed requests, newest last.
RECENT: collections.deque[dict[str, Any]] = collections.deque(maxlen=WINDOW)


@dataclass
class Reading:
    """One published figure: what it is, and where it was read from.

    `value is None` means **could not be read**, and `source` then says why. It never means
    zero. The page renders a dash for `None` and the reason on hover, which is the difference
    between "the card is idle" and "nobody asked the card".
    """

    value: float | int | str | None
    unit: str
    source: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _reading(value, unit: str, source: str) -> dict[str, Any]:
    return Reading(value, unit, source).as_dict()


# ------------------------------------------------------------------ 1. the card


#: The exact fields asked of nvidia-smi, in order. Kept as data so the reader, the source
#: string and the test cannot disagree about what was queried.
SMI_FIELDS = (
    ("name",             "",      str),
    ("memory.total",     "MiB",   int),
    ("memory.used",      "MiB",   int),
    ("memory.free",      "MiB",   int),
    ("utilization.gpu",  "%",     int),
    ("temperature.gpu",  "°C",    int),
    ("power.draw",       "W",     float),
    ("power.limit",      "W",     float),
    ("clocks.sm",        "MHz",   int),
)

SMI_CMD = ("nvidia-smi", "--query-gpu=" + ",".join(f for f, _, _ in SMI_FIELDS),
           "--format=csv,noheader,nounits")


async def read_card() -> dict[str, Any]:
    """One `nvidia-smi` call, every field a separate Reading naming that call.

    Off-thread. `subprocess.run` from a coroutine blocks the event loop, which on this box
    made every engine spawn look like an outage to its own watchdog -- fixed in `121806af`
    and not worth re-learning.
    """
    import subprocess

    src = " ".join(SMI_CMD)
    try:
        proc = await asyncio.to_thread(
            subprocess.run, list(SMI_CMD), capture_output=True, text=True, timeout=10)
    except Exception as exc:                                        # noqa: BLE001
        why = f"{src} did not run ({type(exc).__name__})"
        return {f: _reading(None, u, why) for f, u, _ in SMI_FIELDS}
    if proc.returncode != 0:
        why = f"{src} exited {proc.returncode}"
        return {f: _reading(None, u, why) for f, u, _ in SMI_FIELDS}

    cells = [c.strip() for c in (proc.stdout.strip().splitlines() or [""])[0].split(",")]
    out: dict[str, Any] = {}
    for i, (fieldname, unit, cast) in enumerate(SMI_FIELDS):
        raw = cells[i] if i < len(cells) else ""
        try:
            out[fieldname] = _reading(cast(raw), unit, src)
        except (TypeError, ValueError):
            # "[N/A]" is what nvidia-smi prints for a field this card does not report. That
            # is a real answer and it is not zero.
            out[fieldname] = _reading(None, unit, f"{src} answered {raw!r}")
    return out


# ------------------------------------------------------------------ 2. the context window


def _engine_get(path: str, timeout: float = 3.0) -> dict[str, Any] | None:
    """A plain GET to the already-running engine. Never starts it, never retries."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{LLAMA_PORT}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


async def read_context() -> dict[str, Any]:
    """The context window, read from the engine that is actually serving.

    **The number an operator wants is the per-slot context, not the total**, and those differ
    by the parallel-slot count. This box runs `-c 65536 -np 2`, so the total is 65,536 and a
    single conversation gets 32,768. Publishing the total would overstate every chat's headroom
    by a factor of two. `/props` reports the per-slot figure directly as
    `default_generation_settings.n_ctx`; `total_slots` is what makes it explicable.
    """
    src = f"GET http://127.0.0.1:{LLAMA_PORT}/props"
    props = await asyncio.to_thread(_engine_get, "/props")
    if props is None:
        why = f"{src} -- engine not resident; nothing was started to find out"
        return {"n_ctx_per_slot": _reading(None, "tokens", why),
                "total_slots": _reading(None, "slots", why),
                "n_ctx_total": _reading(None, "tokens", why),
                "model_path": _reading(None, "", why)}

    per_slot = (props.get("default_generation_settings") or {}).get("n_ctx")
    slots = props.get("total_slots")
    total = per_slot * slots if isinstance(per_slot, int) and isinstance(slots, int) else None
    return {
        "n_ctx_per_slot": _reading(per_slot, "tokens", f"{src} .default_generation_settings.n_ctx"),
        "total_slots": _reading(slots, "slots", f"{src} .total_slots"),
        # The one computed figure on the page, and it is labelled as such rather than passed
        # off as a reading: it is the product of two readings, both named.
        "n_ctx_total": _reading(total, "tokens", f"{src} -- per-slot x slots, computed"),
        "model_path": _reading(props.get("model_path"), "", f"{src} .model_path"),
    }


# ------------------------------------------------------------------ 3. the model's work


#: The keys llama.cpp puts in `timings`. Anything else in the object is ignored rather than
#: passed through, so a future engine field cannot silently appear on the page unlabelled.
TIMING_KEYS = ("cache_n", "prompt_n", "prompt_ms", "prompt_per_token_ms", "prompt_per_second",
               "predicted_n", "predicted_ms", "predicted_per_token_ms", "predicted_per_second")


def record_timings(timings: dict[str, Any] | None, *, surface: str = "chat",
                   now: float | None = None) -> bool:
    """Keep one request's measured timings. Returns whether anything was kept.

    Called from `api.py::chat_deltas` with the `timings` object off the final SSE chunk.
    **Total cost: a dict copy.** No request is issued, nothing is measured here -- the engine
    already measured it while doing the work, and this is the first thing that does not throw
    the measurement away.

    Tolerant on purpose: a chunk without timings is the normal case for every chunk but the
    last, and a caller that hands this one is not making an error worth raising over.
    """
    if not isinstance(timings, dict):
        return False
    kept = {k: timings[k] for k in TIMING_KEYS if isinstance(timings.get(k), (int, float))}
    if not kept:
        return False
    kept["surface"] = surface
    kept["at"] = now if now is not None else time.time()
    RECENT.append(kept)
    return True


def read_work() -> dict[str, Any]:
    """The last request's cost, plus the recent series. Nothing is issued to produce this."""
    src = "llama-server timings, final SSE chunk of the last real request"
    if not RECENT:
        why = "no request has completed since this process started"
        empty = {k: _reading(None, _UNITS[k], why) for k in TIMING_KEYS}
        return {"last": empty, "at": None, "surface": None, "samples": 0, "series": []}

    last = RECENT[-1]
    return {
        "last": {k: _reading(last.get(k), _UNITS[k], src) for k in TIMING_KEYS},
        "at": last.get("at"),
        "surface": last.get("surface"),
        "samples": len(RECENT),
        # Only what a sparkline needs. The full object per sample would be most of the payload
        # for a line nobody reads.
        "series": [{"at": s.get("at"),
                    "predicted_per_second": s.get("predicted_per_second"),
                    "prompt_per_second": s.get("prompt_per_second"),
                    "predicted_n": s.get("predicted_n")} for s in RECENT],
    }


_UNITS = {
    "cache_n": "tokens", "prompt_n": "tokens", "prompt_ms": "ms",
    "prompt_per_token_ms": "ms/token", "prompt_per_second": "tok/s",
    "predicted_n": "tokens", "predicted_ms": "ms",
    "predicted_per_token_ms": "ms/token", "predicted_per_second": "tok/s",
}

#: What each figure means, in one line, for the page. Kept beside the units so the page and
#: the API cannot drift into describing the same number two ways.
LABELS = {
    "cache_n": ("prompt cache hits", "tokens reused from the previous turn instead of re-read"),
    "prompt_n": ("tokens read", "the prompt the model had to take in"),
    "prompt_ms": ("read time", "wall time spent taking the prompt in"),
    "prompt_per_token_ms": ("per token read", ""),
    "prompt_per_second": ("read speed", "prefill -- how fast it consumed the prompt"),
    "predicted_n": ("tokens written", "what the model generated"),
    "predicted_ms": ("write time", "wall time spent generating"),
    "predicted_per_token_ms": ("per token written", ""),
    "predicted_per_second": ("write speed", "generation -- the number people mean by tok/s"),
}


# ------------------------------------------------------------------ the whole picture


async def snapshot() -> dict[str, Any]:
    """Everything, in one object, with every figure carrying its source.

    The two I/O reads run concurrently: `nvidia-smi` is a process spawn and `/props` is a
    socket, and doing them in series would make the page's refresh the sum of two timeouts on
    a box where the engine is down.
    """
    card, context = await asyncio.gather(read_card(), read_context())
    return {
        "read_at": time.time(),
        "card": card,
        "context": context,
        "work": read_work(),
        "labels": LABELS,
        # Stated, not implied. A page that shows figures without saying this invites the
        # reader to assume the blanks are zeroes.
        "contract": ("every figure on this page is a reading with its source attached; "
                     "a dash means it could not be read, never that it is zero"),
    }
