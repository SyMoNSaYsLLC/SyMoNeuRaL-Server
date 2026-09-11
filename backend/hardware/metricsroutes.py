"""`/api/metrics` — the dashboard's data. One router over four reader modules.

Owner, 2026-09-11: *"i want everything shown and available on the ui for model hardware gpu
cpu ram parameters sliders etc"*, and *"bring all testing and benchmarking also"*.

## Why a separate router module

`backend/server.py` is 4,241 lines and the house rule is that no code file exceeds 500. Four
readers (`modelmetrics`, `hostmetrics`, `fabric`, `suites`) plus this router keep each piece
under that on its own, and each piece is separately testable -- which is the point of the
rule rather than a side effect of it.

## Every route here is a READ

Nothing in this module starts a process, takes the GPU lease, writes a file, or runs a test.
The heaviest thing that happens is one `nvidia-smi` spawn and one HTTP GET to a llama-server
that is already running. That is a deliberate property and `test_metrics.py` asserts it: a
status page that can change the system's state is a control panel wearing a gauge's clothes.

The one write-shaped thing on the dashboard -- the sliders -- does **not** post here. The
sliders build a body for `POST /api/chat`, which is the route that already exists, already
validates, and already holds the lease correctly. Adding a second way to reach the model would
be a second thing to keep correct.

## Refresh cost, measured

`/api/metrics/host` samples CPU over 200 ms x2 and is the slow one. `/api/metrics/live` exists
so the page can poll the fast-moving numbers at a short interval without paying for the test
inventory (an `ast` walk of 121 files, ~0.5 s) or the fabric registry read on every tick.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter

from . import hostmetrics, modelmetrics, overclock
from registry import fabric
from registry import suites

router = APIRouter(tags=["metrics"])


@router.get("/live")
async def live() -> dict[str, Any]:
    """The fast-moving half: card, context, last request, CPU/RAM. Poll this one.

    Deliberately excludes the test inventory and the fabric registry read -- both are ~0.5 s
    of file walking that cannot change between two ticks of a 2-second poll.
    """
    model, host = await asyncio.gather(modelmetrics.snapshot(), hostmetrics.snapshot())
    return {"model": model, "host": host}


@router.get("/static")
def static_parts() -> dict[str, Any]:
    """The slow-moving half: fabric status, test inventory, benchmarks. Fetch once.

    Sync on purpose. These are file reads with no await in them, and wrapping them in a
    coroutine that never yields would move the same blocking work onto the event loop while
    looking like it had been fixed.
    """
    return {"fabric": fabric.snapshot(), "suites": suites.snapshot()}


@router.get("/params")
async def params() -> dict[str, Any]:
    """The model's generation parameters, and which of them this box will actually honour.

    **The honest part of this route is the split.** llama-server reports 42 generation
    parameters in `/props`. `POST /api/chat` accepts exactly three of them -- `temperature`,
    `max_tokens` and `system`. So the dashboard gets three live sliders and thirty-nine
    read-only rows, rather than forty-two sliders of which thirty-nine quietly do nothing.

    A slider that does not reach the engine is worse than no slider: it invites somebody to
    tune a run, watch the output change for unrelated reasons, and conclude the control
    works. The bounds below are read from `api.ChatRequest`'s own Field constraints, so they
    cannot drift from what the route will accept.
    """
    props = await asyncio.to_thread(modelmetrics._engine_get, "/props")
    engine_defaults = (props or {}).get("default_generation_settings", {}).get("params", {})

    settable = [
        {"name": "temperature", "type": "float", "min": 0.0, "max": 5.0, "step": 0.05,
         "default": 0.7, "engine_default": engine_defaults.get("temperature"),
         "what": "low keeps it factual; high makes it wander. Above ~2 is incoherent by "
                 "construction, not by policy — it is yours to try."},
        {"name": "max_tokens", "type": "int", "min": 1, "max": 32768, "step": 1,
         "default": 512, "engine_default": engine_defaults.get("max_tokens"),
         "what": "upper bound on the reply length."},
        {"name": "system", "type": "text", "default": None,
         "engine_default": None,
         "what": "system prompt. Replaces the persona for this request only."},
    ]
    settable_names = {s["name"] for s in settable}
    read_only = sorted(
        ({"name": k, "value": v} for k, v in engine_defaults.items()
         if k not in settable_names and not isinstance(v, (dict, list))),
        key=lambda d: d["name"])

    return {
        "settable": settable,
        "settable_source": "backend/server.py ChatRequest field constraints",
        "read_only": read_only,
        "read_only_source": (f"GET http://127.0.0.1:{modelmetrics.LLAMA_PORT}"
                             f"/props .default_generation_settings.params"
                             if props else "engine not resident; nothing was started to ask"),
        "engine_resident": props is not None,
        "why_split": ("POST /api/chat accepts only the three above. The rest are the "
                      "engine's own defaults, shown because they describe how your model is "
                      "actually running — but a slider for them would not reach the engine, "
                      "and a control that does nothing is worse than no control."),
        "post_to": "/api/chat",
    }


@router.get("/overclock")
def overclock_envelopes() -> dict[str, Any]:
    """SyMoNeuRaL Local Model Overclocking: the bounds, and the presets. Applies nothing."""
    return {"envelopes": overclock.envelopes(), "presets": overclock.PRESETS,
            "unit": overclock.UNIT}


@router.get("/overclock/plan")
def overclock_plan(gpu: float = 100, cpu: float = 100, ram: float = 100) -> dict[str, Any]:
    """Three percentages in; the real limits and the exact commands out. **Runs nothing.**

    A GET on purpose. This route has no side effect whatsoever -- it is arithmetic over four
    readings -- and making it a POST would imply it did something.
    """
    return overclock.plan(gpu, cpu, ram)


@router.get("")
async def everything() -> dict[str, Any]:
    """Everything in one object, for a cold page load or a `curl` on the box."""
    fast = await live()
    return {**fast, **static_parts(), "params": await params(),
            "overclock": overclock_envelopes()}
