#!/usr/bin/env python3
"""SyMoNeuRaL API. FastAPI over one consumer GPU, bound to loopback.

123 routes across 24 components. Each component owns its own router; this file builds the
app, holds the shared runtime, and mounts them. The five that contend for hardware:

    POST /api/chat        GPU. Proxied to symoneural-llm, streamed token by token.
    POST /api/image       GPU. Evicts chat, runs symoneural-diffuse, returns a PNG url.
    POST /api/remix       GPU indirectly -- a client of chat, not its own tenant.
    POST /api/ravencalc   CPU. Exact symbolic. Never queues behind anything.
    GET  /api/status      Per-unit state for the rack display.

One GPU job at a time, globally -- not per-IP, not per-surface. The card cannot do two
things, so the queue is a property of the hardware, not a policy.

Bounds are enforced here, never trusted from the client. Out-of-range fields are clamped
rather than rejected; an oversized prompt hard-fails, because answering a truncation is
worse than refusing.

System interpreter, no virtualenv in the serving path.

Corrected 2026-09-11: this said "four surfaces" above a list of five, and described five
routes as if they were the whole API.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from typing import Annotated, Literal

from fastapi import (Depends, FastAPI, HTTPException, Request, Response, WebSocket,
                     WebSocketDisconnect, status as http)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

# The ASIC miner surface. Imported as a package rather than put on sys.path, because unlike
# RavenCalc it is a thin shim over a subprocess: the rig protocols need 31 packages and live
# in backend/asicminer/.venv, which this interpreter must never import from.

# Before ANY app import, and that ordering is the whole point rather than tidiness. Every
# environment variable in this repo was once spelled `SYM_*` and is now `SYMONEURAL_*`; the
# env file on a running box (`/etc/symoneural/api.env`, root-owned and hand-edited) still
# carries the old spelling, so this copies each legacy name onto its new one and logs a
# deprecation notice. It has to run above the imports because
# `apps/studio/inference.py` reads two variables at MODULE scope -- a promotion
# after the app packages were imported would be too late for those two and for any that
# join them. See `apps/symoneuralenv.py` for why this is promotion rather than a
# read-both-spellings helper at 771 call sites.
# Read this box's own configuration BEFORE promoting, and before any app package is imported.
# Order matters twice over. Before `promote()`, so a legacy `SYM_*` name that arrives from a
# config file is promoted exactly like one that arrives from the environment -- otherwise the
# file would be a second-class source with subtly different behaviour. And before the app
# imports below, for the reason the comment above gives: modules that read a variable at module
# scope have already read it by the time a later loader would run.
#
# This is what makes `/etc/symoneural` optional rather than load-bearing. That directory is
# root-owned, is attached through a drop-in `systemctl cat` does not show, and is declared
# `ignore_errors=yes` -- so deleting it disabled every surface on this box while the service
# still reported healthy. The process now reads its own configuration from a directory owned by
# the account that runs it. `EnvironmentFile` still wins where it is present, because a name
# already in `os.environ` is never overridden.
# The lease's Python side and the card reading, extracted from this file. `gpu` is
# deliberately thin: `class GpuQueue` could not come with it, because it calls
# `bus.announce()`, `push_rack()` and therefore `build_status()` -- the rack, which is
# most of this file. That extraction is blocked behind the rack's, not behind gpu.py.
# `record_engine` by NAME, not `from hardware.lib import gpu`: this file already binds
# `gpu = GpuQueue(QUEUE_DEPTH)` below, which SHADOWS the module -- so `gpu.record_engine`
# resolved to the queue instance and would have raised AttributeError at the next engine
# spawn. Import succeeded regardless, because nothing calls it at import time. Caught by
# asking the imported module for the attribute rather than trusting that `import api` passing
# meant the wiring was right.
# Imported as a module, not `from hardware.lib.modelmetrics import record_timings`, so the
# metrics buffer has one identity. `apps/gpu.md` records what the alternative cost.
from hardware import hardware as metricsroutes  # noqa: E402
from runtime.lib import runtimeconfig  # noqa: E402
runtimeconfig.load()

from runtime.lib import symoneuralenv  # noqa: E402
symoneuralenv.promote()

import asicminer  # noqa: E402

# Paths, limits and tunables.
from core.config import (  # noqa: E402,F401
    ACQUIRE_TIMEOUT_S,
    API_REFERENCE_SCRIPT,
    API_REFERENCE_STYLE,
    CHAT_ADAPTER,
    CHAT_CTX_TOTAL,
    CHAT_MODEL,
    CHAT_MODEL_LABEL,
    DELEGATE_POLL_S,
    DELEGATE_STALE_S,
    DIFFUSE_ENGINE,
    DISCONNECT_POLL_S,
    DOCS_HEADER,
    DRAFT_MODEL,
    FLUX,
    GALLERY_KEEP,
    GOVERNOR,
    HERE,
    JOB_TIMEOUT_S,
    LIMITS,
    LIVESTACK_PAGES,
    LLAMA_PORT,
    LLM_ENGINE,
    LOCAL_ONLY,
    MAX_PROMPT_CHARS,
    MODELS,
    PORT,
    QUEUE_DEPTH,
    RENDERS,
    ROOT,
    RUN,
    SECTION_PAGES,
    SITE,
    SPEC_DRAFT_MAX,
    STUDIO_REGISTRY_FILE,
    SYSTEM_PROMPT,
    _EXPR_CANDIDATE,
    _HAS_MATH,
    _MINOR,
    _OPERATION_WORDS,
    _PROXY_HEADERS,
    _RATE_SUGGESTED,
    _RETIRED_PAGES,
    _SEXUAL,
    _VARIABLE,
)
import cryptominer  # noqa: E402  -- the GPU miner. A DIFFERENT surface from asicminer:
                    # different hardware and the only tenant that yields to everything.
                  # has NO route: it is driven from the desktop session. See §2g.
import gateway    # noqa: E402  -- TRON licensing surface, see backend/gateway/
# The port registry. Nothing in this file names a surface port as a literal any more: which
# surfaces run as their own process, and on which port, is `ops/PORTS.tsv`. See apps/ports.py
# for why it refuses to report a surface delegated unless the registry also gives it a port.
from registry.lib import ports  # noqa: E402

import streamer  # noqa: E402  -- the IPTV surface AND the Guide that filters
# it, merged into one package on Garrett's instruction ("you need to migrate tuner and
# guide to be 1", then that the pair migrates to `streamer`). It exports one `router` and
# the guide's, which is mounted NESTED at /api/streamer/guide -- both declare `/state`, so
# a shared flat prefix would shadow the second registration. `status()` is the streamer's,
# because the merged pair is ONE rack row and always was -- the two used to share an href
# and disagree.
import project  # noqa: E402  -- the shared workspace surface. Brings its
# own APIRouter. Note it never invokes coder and imports no subprocess/socket/urllib;
# a test in that package enforces it, and making Coder poll Project for work would
# turn Project's token into an RCE gate.
from streamer import guide  # noqa: E402  -- the library half: matching, clustering,
# ModelUnusable. Bound to the package, not its names, so nothing of its vocabulary
# (catalogue, status, unit_state) lands in this module's namespace.
# channel filter. Imported as `routes` for the same reason accounts is: the package exports
# bare names (catalogue, status, unit_state) that would shadow this module's own.
import sigils  # noqa: E402  -- the sticker surface. Bound to the package for
# the same reason as guide: it exports `status`, `router` and `PACKS`, and a bare `status`
# would shadow this module's own. It reaches the same sd-cli as /api/image but takes the
# card under its own governor name, so the rack can say which of the two holds it.
from accounts import accounts as accounts_routes  # noqa: E402  -- signup,
# login and sessions. Imported as `routes` rather than the package so the package's
# many bare names (verify, enabled, status) cannot shadow anything in this module.
import voice  # noqa: E402  -- speech to text on the CPU. Bound to the package so
# its bare `status`/`enabled`/`installed` cannot shadow this module's own. Importing it drags
# in no new dependency: the engine is a subprocess, not a library.
from studio.plugins import reinforce  # noqa: E402  -- the training bay. Bound to the package so its
# bare `status`/`enabled` cannot shadow this module's own. Importing it is cheap and safe
# whether or not the surface is switched on. It does preference and reinforcement tuning
# as well as supervised -- see studio/plugins/reinforce/docs/.
import studio  # noqa: E402  -- the local agent and the
# visual bench it drives. Bound to an alias because `studio` is already the name of a concept
# in this file (`/api/studio/models`, the `studio` rate bucket) and a bare `enabled`/`status`
# from the package would shadow this module's own. Importing it is free with the switch off:
# studio/gate.py is stdlib-only. It imports no torch, spawns no process, and does not
# touch the GPU until a job is queued.
from studio.plugins import exp  # noqa: E402  -- the plugin runtime. Bound to an
# alias for the same reason as `studio`: a bare `enabled`/`status` from the package would
# shadow this module's own. Importing it starts nothing -- `runtime()` is created on first
# request and `boot()` mounts the preset there, not here -- and the runtime modules under it
# are stdlib-only, so this import cannot fail for a missing PyYAML or a missing FastAPI. It is
# the layer the other apps will eventually mount into rather than a surface of its own.
import news  # noqa: E402  -- the ticker's collector. Bound to
# the package, not its names: a bare `enabled`/`status` pulled out of it would shadow this
# module's own, the same reason as `studio` and `exp`. (This used to read "bound to an alias",
# which was true when the package was `symoneuralnews` and needed `as news`. It is now named
# `news`, so there is no alias -- but the binding rule it described is unchanged and is the
# part that matters.) Importing it is free and makes no outbound
# request: `feeds.py` is a tuple of literals, and nothing fetches until `refresher()` is
# started below, which only happens when SYMONEURAL_NEWS_ENABLED=1. Placed above `rackpower`
# because that import claims the last word and should keep it.
import live  # noqa: E402  -- his OBS stream, watchable while it runs and after it
# ends. Bound to the package for the same shadowing reason as `news` and `studio`: it exports
# a bare `enabled`. Importing it opens no socket and reads no directory -- `live/__init__.py`
# constructs the bridge but connects only when `start()` is awaited in `lifespan` below, and
# `hls.py` touches the disk only inside a request. Placed above `rackpower` because that
# import claims the last word and should keep it.
import dispatchos  # noqa: E402  -- the transport dispatch application for a named
# customer, served at /demo/dispatchos behind basicauth in ops/Caddyfile. Bound to the package
# because it exports a bare `enabled` and a bare `status`, either of which would shadow
# something here. Importing it is free with the switch off: it opens no socket, touches no
# database until `enabled()` passes inside a request, and takes no governor lease ever -- its
# only model call goes back out through `set_ask_model` below and refuses to start anything.
import controlboard as rackpower  # noqa: E402  -- the per-unit power switch. Bound to the package
# so its bare `enabled`/`status_rows`/`apply` cannot shadow anything here. Importing it is
# free and safe with the switch off: it reads no file until `enabled()` passes, spawns
# nothing, and `apply()` returns its argument unchanged. It is imported LAST of the apps
# because it is the only one that rewrites another surface's rack reading, and reading the
# import list top to bottom should end at the thing that has the last word.


# Moved out of this file; imported back so the names still resolve here.
from core.bus import Bus  # noqa: E402,F401
from core.gpu_queue import GpuQueue  # noqa: E402,F401
from core.engine import _gguf_arch, adapter_applies, anticipate, chat_deltas, draft_applies, guide_ask_model, llama_up, run, start_llama, stop_llama  # noqa: E402,F401
from core.lifespan import AsicCache, asic_refresher, lifespan, telemetry_loop  # noqa: E402,F401
from status.lib.build import Status, SubUnit, Unit, _diff, _merge_delegated, build_status, poll_delegated, semantic_etag  # noqa: E402,F401
from controlboard.lib.gate import RackPowerGate  # noqa: E402,F401
from ravencalc.lib.math import CalcRequest, calc, extract_math, ws_calc  # noqa: E402,F401
from docs.lib.index import _application_docs_index  # noqa: E402,F401
from studio.lib.rows import _studio_rows  # noqa: E402,F401
# renderer. Deliberately after every surface import above and deliberately importing none of
# them: it holds no reference to a router, only to path PREFIXES, and reads the real route
# table out of `app.routes` at request time. That is what keeps it from becoming a second
# copy of the route list -- the failure `apps/route_matrix.py` was written about.



# Renders are API output, not site content. They used to be written into site/, which meant
# deploy.sh copied every one of them into the public webroot -- 19 dead PNGs were sitting
# there -- even though nothing links to them: they are served by GET /api/gen/<name>.
RENDERS.mkdir(exist_ok=True)

# Switched from symon-1.0-7b-q4_k_m.gguf (qwen2, 7.6B dense) on 2026-09-11.
# Measured on this card, same harness, same questions:
#     30B-A3B  236.6 tok/s   3.35B active of 30.5B   all QA answers correct
#     7B       153.5 tok/s   7.62B active            all QA answers correct
# It is faster BECAUSE it is sparse -- 4 of 128 experts per token, so it reads 1.2 GiB
# per token against the 7B's 4.5 GiB, and this card is memory-bandwidth bound.

#: The product label for CHAT_MODEL. Pinned to the model by
#: `test_chat_model_and_its_label_change_together`, because this string is what the rack unit
#: and the site show, and a label naming the wrong model is the one kind of wrong this project
#: cannot ship. Change the model, change this, or the test fails.

#: TOTAL context, divided by the two slots below -- so each conversation gets half of it.
#:
#: MEASURED by pushing to OOM and stepping back (`tools/bench/bench_maxfit.py`, 2026-09-11):
#:
#:     -c 40960   peak 15,844 MiB    459 MiB headroom   <- the edge, and unusable
#:     -c 33792   peak 15,188 MiB  1,115 MiB headroom   <- this
#:
#: 33792 rather than the edge because 459 MiB is BELOW the governor's 1024 MiB drain floor,
#: where `scripts/gpu-governor.sh` can no longer tell a drained card from an occupied one --
#: so the edge breaks the SCHEDULER even while the model itself runs.
#:
#: The honest cost of the switch, stated where the number lives: 33792/2 gives each slot
#: 16,896 tokens against the 32,768 the 7B gave. Conversations are half as long. That buys
#: 236 tok/s against 153 and a 30B model against a 7B.






# Draft model for speculative decoding. Measured on this box: shallow drafting wins and
# deep drafting loses badly -- see SPEC_DRAFT_MAX.
# Two, not the default. Speculative decoding trades compute for bandwidth, and this box has
# spare compute but no spare bandwidth -- the draft model reads its own weights through the
# same 752 GB/s everything else is queuing for. Measured here at 150 tokens, temp 0.2:
#   depth 2 -> 157.4 t/s (43.8% accepted)   +5% over baseline
#   depth 3 -> 155.1 t/s (39.0% accepted)
#   depth 5 -> 121.4 t/s (27.1% accepted)   -19%
#   default -> 139.1 t/s (32.9% accepted)   -7%
# The default configuration is a net loss on this hardware. Depth 2 is a modest real win.


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s",
    handlers=[logging.FileHandler(RUN / "api.log"), logging.StreamHandler()],
)
log = logging.getLogger("symoneural.api")

# Structured events get their OWN file as well as the shared one. run/events.log is a single
# shape -- `HH:MM:SS.mmm event key=value ...` -- so it can be parsed without a regex that
# has to tolerate prose. Milliseconds because two phases on the same second is the normal
# case, and a startup you cannot order is a startup you cannot diagnose. See core/events.py.
_events = logging.FileHandler(RUN / "events.log")
_events.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(message)s", "%H:%M:%S"))
logging.getLogger("symoneural.events").addHandler(_events)
# The logger is configured here, above the limits, because _rate_for() warns on a
# malformed override and LIMITS is built at import time. Defined the other way round it
# is a NameError on startup that only fires when someone sets the env var wrongly.


# Per-endpoint rate limits. OFF BY DEFAULT, at the operator's instruction (2026-08-17):
# nothing here is to cap what he can send until he has decided himself what should pass.
#
# The mechanism is kept rather than deleted, precisely because he said he would set these
# later. Dial any surface in without editing code -- per-minute/per-hour:
#
#     SYMONEURAL_RATE_CHAT=120/2000   SYMONEURAL_RATE_IMAGE=20/300   SYMONEURAL_RATE_RAVENCALC=240/6000
#
# Unset means unlimited. The pre-2026-08-17 values are kept below as _RATE_SUGGESTED so
# that restoring them is copy-and-paste rather than re-derivation; nothing reads it.
#
# Worth knowing when he does set them: on one GPU a rate limit never bought throughput --
# the queue is one job deep and rations the card by itself. The only thing a limit does
# here is stop one address filling the queue. It is a monopolisation guard, not a
# hardware guard, so "off" costs capacity nothing.
#
#                       per-minute, per-hour






RATE_PER_MIN, RATE_PER_HOUR = LIMITS["chat"]
# Mirrors ACQUIRE_TIMEOUT_S in gpu-governor.sh. A serving request waits this long
# behind a CLI job or a fine-tune before telling the visitor to try RavenCalc.

# How often the chat handler asks whether the visitor is still on the other end. It is
# one ASGI receive poll, so it costs nothing; the interval only bounds how long a dead
# request can keep holding the card, against the ACQUIRE_TIMEOUT_S the next tenant would
# otherwise wait. Measured detection here: ~0.5 s.

# Strong references to in-flight disconnect watchdogs. The event loop holds only a weak
# reference to a task, so one created inside a request frame can be garbage-collected
# before it ever runs. Discarded by a done-callback, so this cannot grow without bound.
_WATCHDOGS: set[asyncio.Task] = set()

# Image prompt gate. GUTTED 2026-08-17 on the operator's instruction: he had not asked
# for any of the previous list, it was written into the initial commit (bf7c8fb) rather
# than chosen, and it is his hardware and his model. Adult content, gore, violence and
# political or historical imagery are no longer filtered here at all.
#
# It was also just broken. The old pattern was `\b(...|cp|execution|explicit|minor|child|
# sex|...)\w*` and every alternative matched as a PREFIX, on the image endpoint of a
# company that sells GPUs:
#
#     "cp"        -> matched "cpu"          "explicit" -> matched "explicitly"
#     "execution" -> matched "execution"    "minor"    -> matched "minor"
#     "sex"       -> matched "sexagesimal"
#
# so "a cpu die shot", "the execution model of a warp" and "a minor revision of the rack"
# were all 400s. Measured, not supposed -- run `python3 tests/deny_regex.py`, which prints
# the ten legitimate prompts the old gate refused and confirms this one refuses none.
#
# What remains is one condition and only one: a prompt that pairs a child term with a
# sexual term. That is not a taste filter, it is the one output that is illegal to
# produce, and it is left in place deliberately. Because it requires BOTH halves, it does
# not fire on "a child's drawing of a raven" or on "a naked woman" -- only on the
# intersection. If it ever false-positives on something real, tell me and I will narrow it
# further; it is not meant to cost you a single legitimate render.




# ======================================================================== models

class Turn(BaseModel):
    """One prior exchange, replayed so the model can follow a conversation."""
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=MAX_PROMPT_CHARS)


class ChatRequest(BaseModel):
    """A question for the local model."""
    prompt: str = Field(..., max_length=MAX_PROMPT_CHARS,
                        description="What to ask. Longer than the cap is refused, not truncated.",
                        examples=["Why is decode memory-bandwidth bound on this card?"])
    # Multi-turn. The client keeps the transcript -- nothing is stored on this box -- and
    # replays it here, which is why there is no conversation id and no history endpoint.
    # Capped at 20 turns because a 7B at Q4 has a finite context and silently dropping the
    # beginning of a long chat is worse than refusing to take it.
    history: list[Turn] = Field(default_factory=list, max_length=2000,
                                description="Prior turns, oldest first. The client holds "
                                            "the transcript; the server keeps nothing.")
    temperature: float = Field(0.7, ge=0.0, le=5.0,
                               description="Low keeps it factual; high makes it wander. "
                                           "Above ~2 is incoherent by construction, not "
                                           "by policy -- it is yours to try.")
    max_tokens: int = Field(512, ge=1, le=32768,
                            description="Upper bound on the reply length.")
    system: str | None = Field(None, max_length=MAX_PROMPT_CHARS,
                               description="Replace the built-in persona prompt outright. "
                                           "Omit to keep it.")


class ImageRequest(BaseModel):
    """A prompt for FLUX.1-schnell."""
    prompt: str = Field(..., max_length=MAX_PROMPT_CHARS,
                        examples=["a raven perched on a server rack, volumetric light"])
    steps: int = Field(4, ge=1, le=100,
                       description="schnell is distilled for four. More costs time and buys "
                                   "little -- but the ceiling is yours to find.")
    size: int = Field(768, ge=64, le=2048, multiple_of=64,
                      description="Square edge length in pixels. Must be a multiple of 64: "
                                  "the VAE downsamples by 8 and the transformer patches by "
                                  "2, so anything else is not representable and "
                                  "symoneural-diffuse silently rounds it. Above ~1536 will "
                                  "OOM this card.")
    seed: int | None = Field(None, ge=0, le=2**31 - 1,
                             description="Omit for random. Supply to reproduce an earlier image.")


class ImageResult(BaseModel):
    url: str = Field(..., description="Path to the rendered PNG, served from this site.")
    seconds: float = Field(..., description="Wall-clock the card actually took, queue excluded.")
    seed: int
    steps: int
    size: int
    model: str
    bytes: int




class RemixRequest(BaseModel):
    """A brief for a sequenced tracklist."""
    prompt: str = Field(..., max_length=MAX_PROMPT_CHARS,
                        examples=["late-night drive through a rainy city, building slowly"])
    count: int = Field(12, ge=1, le=500)


class Track(BaseModel):
    artist: str = ""
    title: str = ""
    why: str = ""


class RemixResult(BaseModel):
    tracks: list[Track]
    seconds: float
    note: str










# ======================================================================== plumbing



_asic_cache = AsicCache()




# The token bucket, the two-bucket check and the client key moved to `apps/ratelimits.py`
# on 2026-09-10, alongside the BUDGETS they enforce. A split surface must apply the same
# published cap from its own process, and the alternatives were to import this or to write a
# second one -- and a second implementation of a published cap is the exact drift
# `ratelimits.py` was created to end. The reasoning moved with the code.
from core.ratelimit import (Throttled, check_rate, client_key, denied,  # noqa: E402,F401
                            throttled_for, _limiters, _try)















gpu = GpuQueue(QUEUE_DEPTH)






bus = Bus()




# Gallery pruning. It lived between `smi()` and `refresh_telemetry()` in the old layout and
# was moved into telemetry.py by e08eaa98 purely because of that adjacency -- it is a
# serving concern over RENDERS, not a card reading. It came back here the moment /api/image
# raised NameError in production. Proximity is not a subject.


def prune_gallery(keep: int = GALLERY_KEEP) -> None:
    """Keep the most recent renders, delete the rest.

    Newest-first by mtime rather than by the timestamp in the filename: the name is
    generated by us and could drift, the mtime is what the filesystem actually knows.
    """
    try:
        shots = sorted(RENDERS.glob("gen-*.png"), key=lambda p: p.stat().st_mtime,
                       reverse=True)
        for stale in shots[keep:]:
            stale.unlink(missing_ok=True)
    except Exception:
        log.exception("gallery prune failed")






# ======================================================================== chat surface


# ---------------------------------------------------------------- anticipation
#
# RavenCalc observing the chat surface, and having the answer ready before it is asked for.
#
# This only works because of an asymmetry in the hardware. Speculation costs whatever the
# speculating agent consumes, so a GPU agent guessing ahead would take the card away from
# the request actually in flight and make the queue worse. RavenCalc is SymPy on the CPU:
# it contends for nothing the serving surfaces want. So while the chat surface is loading
# ~5 GB of weights across a Gen 3 x8 link -- hundreds of milliseconds during which the GPU
# path can do nothing useful -- the calculator has already parsed the question, decided
# whether there is real mathematics in it, and computed the exact answer.
#
# What the model then receives is not a hint. It is a verified result with its own check
# attached, which the model is told to quote rather than recompute. That is the difference
# between a language model that is usually right about algebra and a system that is exactly
# right: the model routes, the algebra engine answers.


# A run of characters that could plausibly be an expression. Deliberately conservative:
# it must contain an operator or a function call, so ordinary prose does not qualify.




def _parses(ravencalc, text: str) -> bool:
    """Does RavenCalc's strict parser accept this as an expression?

    This is the gate that keeps prose out. The parser whitelists characters and refuses
    attribute access, so ordinary English, pasted logs and code all fail it without any
    heuristic of ours having to recognise them.
    """
    text = text.strip()
    if not text or len(text) > 200:
        return False
    try:
        expr = ravencalc.parse(text)
    except Exception:
        return False
    # A bare number or a lone symbol parses fine but is not what anyone meant by
    # "integrate this" -- require some actual structure.
    return bool(getattr(expr, "args", ()))


def _compute_exact(operation: str, expression: str, variable: str) -> dict | None:
    from ravencalc.apps import ravencalc
    doc = {"schema": "ravencalc/request/v1", "operation": operation, "expression": expression}
    if operation in {"differentiate", "integrate", "limit", "series", "solve"}:
        doc["variable"] = variable
    if operation == "limit":
        doc["point"] = "0"
    try:
        return ravencalc.run_request(doc)
    except Exception:
        return None




def exact_context(result: dict) -> str:
    """Phrase the verified result for the model, with instructions not to second-guess it."""
    check = result.get("check") or {}
    verdict = ("verified by back-substitution" if check.get("passed") is True
               else "computed but unconfirmed" if check.get("performed")
               else "computed")
    return (
        "\n\nRavenCalc, the exact symbolic engine running alongside you, has already "
        f"computed this and you should quote its result rather than deriving your own:\n"
        f"  operation: {result.get('_operation')}\n"
        f"  input:     {result['input'].get('text')}\n"
        f"  result:    {result['result'].get('text')}\n"
        f"  status:    {verdict} ({result.get('engine')})\n"
        "State that result exactly as written. You may explain the method, but do not "
        "recompute it and do not present a different answer -- this one is exact and yours "
        "would be a guess. Mention that RavenCalc computed it."
    )


_llama: asyncio.subprocess.Process | None = None










# ---------------------------------------------------------------- guide's model half

#: The event loop, captured in `lifespan`. Guide's local pass runs in a worker thread via
#: `asyncio.to_thread`, so its optional model call has to get back onto the loop to reach
#: llama-server; there is no running loop in that thread to ask.
_LOOP: asyncio.AbstractEventLoop | None = None




# ======================================================================== app





app = FastAPI(
    title="SyMoNeuRaL API",
    version="1.0",
    lifespan=lifespan,
    # Served through Caddy at symoneural.com; the assets are local, see /docs below.
    docs_url=None, redoc_url=None,
    openapi_url="/openapi.json",
    description=(
        "The production API behind [symoneural.com](https://symoneural.com) — four "
        "surfaces on one RTX 5070 Ti.\n\n"
        "**Chat**, **Image** and **Remix** all want the same GPU, and the chat and image "
        "weight sets do not both fit in 15.92 GiB. So exactly one holds the card at a time "
        "and the others queue. **RavenCalc** is symbolic algebra on the CPU and never queues — which "
        "is why it is always available even when the rack shows everything else busy.\n\n"
        "Rate limits are per endpoint, scaled to cost: **calc** 240/min, **chat** 120/min, "
        "**remix** 40/min, **image** 20/min (hourly budgets are 25x the minute). Every "
        "parameter is clamped server-side; the values documented here are the real "
        "bounds.\n\n"
        "This is a demonstration on the smallest machine we would ever ship, not a "
        "statement of capacity."
    ),
    openapi_tags=[
        {"name": "surfaces", "description": "The four things you can actually run."},
        {"name": "status", "description": "What the rack on the home page reads."},
    ],
)


app.add_middleware(GZipMiddleware, minimum_size=500, compresslevel=6)




# Added after GZip, so it is the OUTER of the two -- the order the `@app.middleware("http")`
# registration it replaced produced, kept deliberately.
app.add_middleware(RackPowerGate)




# The API reference renderer. Ours, and inline on purpose -- see `api_reference()` below.
#
# Every class is prefixed `ar-`. That is not tidiness: three separate bugs in this repo have
# come from generic class names colliding across components -- `.bar` collapsed the site
# header to 7px sitewide, `.live` styled the control board legend from the nav badge, and
# `#console .sub` outranked `.mod .sub` and rendered a footnote larger than the sentence
# above it. This page loads `/symoneural.css` and `/rack-detail.css`, so an unprefixed
# `.method` or `.path` here is that bug waiting to be written again.
#
# No `text-overflow`. Long paths, long descriptions and long schemas wrap or fold into a
# `<details>`; they are never trimmed. An ellipsis on a reference page is data loss with
# extra steps, and every such rule was deliberately deleted from the site's CSS after
# `built on Qwen2.5-7B-Instruct` -- an Apache-2.0 condition -- was cut to `...7B-Ins...`.
# The opening `<style>` belongs HERE, above the first rule, and it was one line lower.
#
# This constant is interpolated into `<head>` at :2242. The `.ar-index` block was added
# above the existing `<style>` line instead of below it, so twenty rules and a CSS comment
# were emitted into `<head>` as bare character data. Non-whitespace text in `<head>` makes
# the HTML parser implicitly close it and open `<body>` -- so a visitor saw the CSS as the
# first paragraph of the page, none of those rules applied, and everything after it landed
# in the body as well. One misplaced line, two visible symptoms.
#
# Caught 2026-09-10 by rendering the page, which is the only way this shows up: the source
# reads as a perfectly ordinary stylesheet, and `.ar-wrap` below is wrapped correctly, so
# there was nothing to notice by reading.

# Reads `/openapi.json` -- the same document `/api/status` and the CLI read -- and renders it.
# There is no build step and no data of its own: if the schema changes, this page changes,
# because it has nothing else to draw from.






def external_holder() -> str | None:
    """Who holds the governor lock, if it is not us.

    The lock directory only exists while held, and the holder file names the surface and
    its pid. A stale entry whose process is gone is treated as free -- the governor breaks
    those itself, and reporting a dead holder would wedge the display long after the card
    was actually released.
    """
    holder_file = RUN / "gpu.lock.d" / "holder"
    try:
        surface, pid = holder_file.read_text().split()
        os.kill(int(pid), 0)
        return surface
    except Exception:
        return None


# ------------------------------------------------------------------ delegated surfaces
#
# A surface that runs as its own process (`ops/PORTS.tsv`, DELEGATED) no longer has its state
# in this process's memory. `/api/status` has to get it over HTTP -- and the interesting case
# is when it does not arrive.
#
# **Polled in the background, never in the request.** `build_status()` is synchronous and is
# called from four places including a WebSocket loop (`:2707`) and the bus publisher
# (`:2633`); a blocking fetch in there would stall the event loop for every listener. So a
# task refreshes a cache and `build_status()` reads it. The rack page therefore pays NO added
# latency for the split -- the cost is one request per delegated surface per interval, which
# at nine surfaces and 2 s is 4.5 req/s of loopback traffic against a 240/min budget.
#
# The pattern is the one `asic_refresher` already uses (`:703`), started in `lifespan`.
#: Older than this and the row is `unreachable`. Three missed polls, so one slow answer does
#: not flap the rack -- the failure this must not have is a surface that alternates.











async def push_rack() -> None:
    """Push what changed, and nothing at all if nothing did."""
    if bus.listeners:
        await bus.publish_delta(build_status().model_dump())






def client_key_ws(ws: WebSocket) -> str:
    fwd = ws.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (ws.client.host if ws.client else "unknown")


async def ws_chat(ws: WebSocket, msg: dict) -> None:
    try:
        body = ChatRequest(**{k: v for k, v in msg.items() if k != "t"})
    except Exception as exc:
        await ws.send_text(json.dumps({"t": "error", "code": 422, "error": str(exc)[:300]}))
        return
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": body.prompt}]
    async with gpu.hold("chat"):
        if not await start_llama():
            await ws.send_text(json.dumps({"t": "error", "code": 503,
                                           "error": "Chat surface is not available."}))
            return
        started, tokens = time.time(), 0
        async for piece in chat_deltas(messages, body.max_tokens, body.temperature):
            tokens += 1
            await ws.send_text(json.dumps({"t": "delta", "d": piece}, separators=(",", ":")))
        elapsed = time.time() - started
        await ws.send_text(json.dumps({
            "t": "done", "tokens": tokens, "seconds": round(elapsed, 2),
            "tok_per_s": round(tokens / elapsed, 1) if elapsed else None,
            "model": CHAT_MODEL.stem, "adapter": adapter_applies()},
            separators=(",", ":")))




async def ws_remix(ws: WebSocket, msg: dict) -> None:
    try:
        body = RemixRequest(**{k: v for k, v in msg.items() if k != "t"})
    except Exception as exc:
        await ws.send_text(json.dumps({"t": "error", "code": 422, "error": str(exc)[:300]}))
        return
    result = await remix(body, None)  # type: ignore[arg-type]
    await ws.send_text(json.dumps({"t": "remix.result", **result.model_dump()},
                                  separators=(",", ":")))










# Registered ONLY while the monolith owns this surface.
#
# When `ops/PORTS.tsv` marks `ravencalc` DELEGATED, `backend/ravencalc/service.py`
# answers `/api/ravencalc` on its own port and this route is never added -- so exactly one
# process can answer, and "which one is authoritative" is settled in code rather than in a
# document that can go stale. `apps/ports.py` refuses to report a surface delegated unless
# the registry also gives it a port, so no configuration removes this route while leaving
# nothing in its place.
#
# Registered by calling the decorator rather than applying it, because wrapping a 30-line
# handler in an `if` means indenting the body and the diff then hides what changed.
if not ports.delegated("ravencalc"):
    app.post("/api/ravencalc", tags=["surfaces"])(calc)




# ---------------------------------------------------------------------------
# Static site, mounted last so it never shadows an API route.
#
# In production Caddy serves site/ from the webroot and only proxies /api, so
# this mount is not on the public path. It exists so the box can serve the whole
# thing from one origin -- which is the only way to exercise the real frontend:
# console.js opens a WebSocket at /api/ws and falls back to polling /api/status,
# and neither works when the pages are served from a different port than the API.
# Testing the surfaces with curl proves the endpoints answer; it proves nothing
# about the JavaScript that has to render them.
# ------------------------------------------------------------------ asicminer control
#
# Operator routes. Every one requires SYMONEURAL_ASIC_TOKEN in X-Symoneural-Token, compared in
# constant time, and the surface has to be switched on at all -- so a box with the env unset
# serves nothing here rather than serving an unauthenticated scanner. The scan itself refuses
# any range that is not private; see backend/asicminer/scan.py.







class ScanBody(BaseModel):
    cidr: str = ""


class EmuBody(BaseModel):
    action: Literal["start", "stop", "status"] = "status"
    package: str = ""          # an id from /api/asicminer/firmware, never a path








# ------------------------------------------------------------------ GPU miner (Ravencoin)
#
# Same gate shape as the ASIC surface, and it matters more here: this one takes the card.
# Starting it from an unauthenticated route would let a stranger evict chat and image and
# hold the GPU indefinitely -- a denial of service with a wallet address attached.
#
# The token IS the gate now. Rate limiting was switched off across the API on the
# operator's instruction, so there is no second layer catching a brute-force attempt.



class MinerBody(BaseModel):
    action: Literal["start", "stop", "status"] = "status"


# ctx, part one. Decorators read ctx at IMPORT time -- studio's carries
# Depends(ctx.throttled_for(...)) -- so these must land before the first router import.
from core.context import configure as _configure, require as _require  # noqa: E402

_configure(
    API_REFERENCE_SCRIPT=API_REFERENCE_SCRIPT,
    API_REFERENCE_STYLE=API_REFERENCE_STYLE,
    CHAT_MODEL=CHAT_MODEL,
    ChatRequest=ChatRequest,
    DIFFUSE_ENGINE=DIFFUSE_ENGINE,
    DISCONNECT_POLL_S=DISCONNECT_POLL_S,
    DOCS_HEADER=DOCS_HEADER,
    EmuBody=EmuBody,
    FLUX=FLUX,
    ImageRequest=ImageRequest,
    ImageResult=ImageResult,
    LIMITS=LIMITS,
    MAX_PROMPT_CHARS=MAX_PROMPT_CHARS,
    MinerBody=MinerBody,
    QUEUE_DEPTH=QUEUE_DEPTH,
    RENDERS=RENDERS,
    ROOT=ROOT,
    RemixRequest=RemixRequest,
    RemixResult=RemixResult,
    SITE=SITE,
    SYSTEM_PROMPT=SYSTEM_PROMPT,
    ScanBody=ScanBody,
    Status=Status,
    Track=Track,
    _application_docs_index=_application_docs_index,
    adapter_applies=adapter_applies,
    anticipate=anticipate,
    build_status=build_status,
    bus=bus,
    chat_deltas=chat_deltas,
    check_rate=check_rate,
    client_key_ws=client_key_ws,
    denied=denied,
    exact_context=exact_context,
    gpu=gpu,
    log=log,
    prune_gallery=prune_gallery,
    run=run,
    semantic_etag=semantic_etag,
    start_llama=start_llama,
    stop_llama=stop_llama,
    throttled_for=throttled_for,
    ws_calc=ws_calc,
    ws_chat=ws_chat,
    ws_remix=ws_remix,
)







# The streamer brings its own router rather than having its routes written here. It must be
# included BEFORE the static mount below, for the same reason every other API route is
# declared before it: StaticFiles at "/" matches everything, so anything mounted after it
# is unreachable. Prefix matches the Backstage shape the backend is heading towards
# (§5 item 13) -- a surface answers at /api/<id>.
app.include_router(streamer.router, prefix="/api/streamer", tags=["streamer"])
app.include_router(accounts_routes.router, prefix="/api/accounts", tags=["accounts"])
app.include_router(gateway.router, prefix="/api/gateway", tags=["gateway"])
app.include_router(streamer.guide_router, prefix="/api/streamer/guide",
                   tags=["streamer-guide"])
app.include_router(project.router, prefix="/api/project", tags=["project"])
# The per-unit power switch. Mounting it is not enabling it: with SYMONEURAL_RACK_ENABLED unset
# every route answers 404 -- absent rather than forbidden, because the rack is public and a
# 403 would advertise to a visitor that this installation has an operator control.
app.include_router(rackpower.router, prefix="/api/rack", tags=["rack"])
# `/api/train`, not `/api/reinforce`: the router's own first line names this prefix, `page.js`
# hard-codes it, and the rack unit has been `train` since before either existed. The docstring
# in apps/studio/plugins/reinforce/routes.py said "Mounted at /api/train by backend/server.py" from the day it was
# written -- it simply was not true until this line, so every route in that package answered 404
# rather than the 503 it was designed to give. A 404 reads as "this was never built"; the 503
# names the two switches that turn it on, which is the difference between a missing surface and
# a configured one.
#
# No `ops/Caddyfile` change is needed for this, and that is worth stating because a new *section*
# path does need one. Caddy delegates the whole subtree with `handle /api/*`, so FastAPI decides
# what exists under it. Only a new top-level path -- the /overview /livestack /controlboard
# /receipts class -- has to be added there, and that has bitten before.
app.include_router(reinforce.router, prefix="/api/train", tags=["reinforce"])
# Speech in, on the CPU. This surface takes no governor lease -- measured, not asserted: the
# whisper.cpp build here is GGML_CUDA=OFF, 284 MiB RSS and 0 VRAM, so a spoken question is
# transcribed *while* a chat generation runs rather than after it. RavenCalc is the precedent.
# There is deliberately NO `voice` rack unit yet: status() is written and correct, but its href
# is /voice.html and that page does not exist, so the row would be a dead link on the front
# page. Add the row in the same commit as the page.
app.include_router(voice.router, prefix="/api/voice", tags=["voice"])

# Stickers is the one app router that spends the GPU, so it is the one that needs the
# meter actually connected. Listing "sigil" in _RATE_SUGGESTED builds the buckets; it does
# not spend from them. Without this dependency SYMONEURAL_RATE_SIGIL=20/300 would be read,
# validated, turned into two RateLimiter objects -- and consulted by nothing, which is a
# worse state than being openly unmetered because the operator would believe a cap was in
# force. Applied here rather than in apps/sigils/routes.py because throttled_for lives in
# this module and this module imports that one; the dependency the other way is a cycle.
#
# Router-wide, so it covers /packs and /state as well as the three POSTs. That is
# deliberate: a new route added to this surface later is metered by default rather than by
# remembering, and /state is exactly what a phone app polls.
app.include_router(sigils.router, prefix="/api/sigils", tags=["sigils"],
                   dependencies=[Depends(throttled_for("sigil"))])

# The Studio: a local agent with tools, and ComfyUI's own node editor in front of it.
#
# TWO routers, because the surface genuinely lives in two places:
#
#   /api/studio/*    the agent (SSE), the tool registry, the queue, the render proxy
#   /studio/editor/*  a same-origin reverse proxy in front of ComfyUI's shipped frontend
#
# The second one is not an API and does not belong under /api: it serves an HTML application
# and its assets. `comfyui_frontend_package` derives its own API base from `location.pathname`,
# so mounted at /studio/editor/ it addresses /studio/editor/api/... by itself and no path is
# rewritten anywhere -- FastAPI still owns every routing decision, which is the rule.
#
# `ops/Caddyfile` DOES need a delegation block for /studio, and this is the /overview class of
# change the /api comment above warns about: Caddy hands the whole /api subtree to the API but
# resolves any other path against /var/www/symoneural first, where there is no file called
# `studio`. Without the block the page 404s in production and answers perfectly on localhost,
# which is the exact failure the section pages hit when they were first deployed. The block is
# written; applying it needs `sudo ./scripts/install-caddy.sh`.
#
# Not metered by `throttled_for("studio")` even though the bucket exists and is configured:
# that bucket belongs to `/api/studio/models` below, which is a public read, and this surface
# is single-operator and token-gated. A 60/900 cap on it would throttle the editor's own asset
# loads -- one page open is dozens of requests -- and produce a broken UI that looks like a
# bug rather than a limit.
#
# What that costs, stated rather than left to be inferred from the reasons above: there is no
# ceiling on how many tokens a caller may try. `hmac.compare_digest` in `studio/gate.py` closes
# the timing channel and nothing closes the rate, so the guess budget is the network's. The
# token is the whole boundary in front of `run_command`, so it wants to be long and random --
# `openssl rand -hex 32`, not a word -- and that is a property of how it is set, which no code
# here can enforce. A lockout is the guard that would close this and is not implemented as of
# 2026-08-20 -- a deliberate pre-launch state, not a cleared posture (request ledger R-98, held,
# being re-scoped per surface). This is the strongest candidate on the list when it is.
app.include_router(studio.router, prefix="/api/studio", tags=["studio"])
app.include_router(studio.ui_router, prefix="/studio/editor", include_in_schema=False)

# ---- the plugin runtime ----------------------------------------------------
# Reads and mutations are both open. The whole argument for this surface is that what is
# mounted, in what state, and waiting on what, is inspectable.
#
# Touching `exp.router` here is what imports `apps/studio/plugins/exp/routes.py`, so a syntax error
# in it still fails the boot loudly despite the PEP 562 lazy attribute on the package.
app.include_router(exp.router, prefix="/api/exp", tags=["exp"])
# The dashboard's data. Every route under it is a READ -- nothing starts a process,
# takes the GPU lease, writes a file or runs a test. `test_metrics.py` asserts that.
app.include_router(metricsroutes.router, prefix="/api/metrics", tags=["metrics"])
# Tokenless and read-only, like `/api/gateway/state` and for the same reason: everything it
# returns is a headline eight publishers hand to anyone who asks. Unlike the gateway it
# answers 200 with an empty list rather than 503 when the surface is off, because its caller
# is `site/ui.js` on every page load and a 503 in the default state would put a red line in
# every visitor's console -- see `apps/news/routes.py`.
app.include_router(news.router.router, prefix="/api/news", tags=["news"])

# ---- the live stream -------------------------------------------------------
# Entirely tokenless, and that is the design rather than an omission. The video is HLS on
# disk written by OBS's Recording output; serving it needs no credential, and the credential
# this app does hold -- the obs-websocket password -- never leaves the process. A visitor can
# therefore watch before the bridge is configured at all, and a wrong password or a closed
# OBS costs the page its telemetry line and not its video. `apps/live/__init__.py` states
# that split as an import graph: `hls.py` does not import `obs.py`.
#
# Every handler in it is a plain `def`, not `async def`, and that is load-bearing rather than
# an oversight. Starlette runs a sync handler in the threadpool; `hls.scan()` globs and stats
# every segment of every session, which for a three-hour stream at two-second segments is
# ~5400 stat calls. Inside `async def` that would block the event loop -- and with it the rack
# websocket for every visitor on the site. Making them `async` again would look like a
# tidy-up and would be a regression.
app.include_router(live.router, prefix="/api/live", tags=["live"])

# DispatchOS. Two routers: the JSON API under /api/dispatchos, and the page itself at
# /demo/dispatchos -- an extensionless path, so it cannot be a file under a publisher that
# copies site/ at -maxdepth 1, and `ops/Caddyfile` reverse-proxies it here behind basicauth.
# `include_in_schema=False` on the UI half keeps a customer page out of the public API docs.
app.include_router(dispatchos.router, prefix="/api/dispatchos", tags=["dispatchos"])
app.include_router(dispatchos.ui_router)

# SyMon AI for DispatchOS, wired to the same local chat surface Guide uses -- and wired to the
# same PROMISE: `guide_ask_model` raises rather than starting the model, so a rider's question
# can never evict a render somebody is waiting on. The assistant degrades and says so.
dispatchos.set_ask_model(guide_ask_model)


# ---- the studio model list -------------------------------------------------
# A read of one pre-computed file, and deliberately nothing else.
#
# `apps/studio/plugins/reinforce/registry.py` can enumerate every model on this box, and it is stdlib-only
# specifically so this module may import it -- which it already does, at /api/train/models.
# That route walks the HF cache, opens each `config.json`, and parses the key/value header out
# of every GGUF present. It is the right thing behind the training bay, where an operator has
# asked for a fresh scan and will wait for it.
#
# This route is the opposite case: a client polling for a model list on the live path. The
# architecture rule for this stack is that the control plane's scans stay off that path
# entirely, so the scan happens out-of-band in `tools/build/build_registry.py` and lands in
# `run/registry.json`, and what happens here is one `read_text` and a validation pass. No
# directory walk, no subprocess, no network, and nothing that could ever take the GPU lock.
#
# Declared BEFORE the StaticFiles mount below, for the reason the section routes give.

# Only these keys survive a read, and each is checked against the type it must be. Re-validated
# even though `tools/build/build_registry.py` wrote it, exactly as `apps/studio/plugins/reinforce/jobs.py` re-validates
# `progress.json`: `run/` is world-readable state on a box that also runs a web server, and
# trusting a field because we wrote it is how a validated field silently becomes an unvalidated
# one the next time somebody edits the writer.
#
# `path` is deliberately NOT in this list, even though the file carries it. Caddy delegates the
# whole `/api/*` subtree publicly and this route has no surface flag in front of it, so the
# response is world-readable; the row in the file reads
# `models/hf/hub/models--Qwen--Qwen2.5-7B-Instruct/snapshots/<hash>`, which is this
# repo's internal directory layout rather than a fact about the model. `/api/train/models` does
# publish it, but that route is behind `_require_surface()`. Nothing needs it here: `id` names
# the model, `kind` says which loader reads it, and `reason` carries the "not fetched" story
# that the placeholder path was the only other witness to. Keeping it in `run/registry.json`
# costs nothing -- that file is local and gitignored -- so an operator reading the file directly
# still gets it. Publish the numbers, keep the layout.
_STUDIO_FIELDS: dict[str, type | tuple[type, ...]] = {
    "id": str, "name": str, "kind": str,
    "present": bool, "trainable": bool, "reason": str,
    "capabilities": list,
    "bytes_on_disk": int, "bytes_on_disk_label": str,
    "quantisation": str, "quantisation_label": str,
    "parameters": int, "parameters_label": str,
    "latency_ms": (int, float), "latency_label": str, "latency_measured_at": int,
}






# ---- per-application documentation ---------------------------------------------------
#
# `/docs` is the platform-wide reference and stays exactly what it was. `/docs/<id>` is one
# scoped page per application, listing ONLY the routes that application owns.
#
# WHY THIS SHAPE AND NOT `<application-page>/docs`. The obvious address for chat's docs is
# `/chat.html/docs`, and it cannot work: `site/` is mounted at `/` with `html=True`, so that
# path asks the file server for a directory inside a file. It would 404 in production while
# looking plausible in a link. `/docs*` on the other hand is ALREADY delegated to this
# service by `ops/Caddyfile` -- one `handle /docs*` block, prefix form -- and `scripts/
# deploy.sh`'s reference check already treats `docs/*` as a route rather than a file. So the
# clean canonical shape costs no Caddy change, no deploy change and no new delegation, and
# the handshake's "do not rely on an invalid file-server path trick" is satisfied by not
# needing a trick at all.
#
# Declared BEFORE the StaticFiles mount below, for the same reason every route here is: that
# mount matches everything at "/", so a route added after it is unreachable.






# ---- clean URLs for the four front-page sections ---------------------------
# tools/build/build_split.py writes one page per section. These give them addresses without a
# `.html`, which is what makes them shareable. It is done HERE because FastAPI does all
# the routing -- ops/Caddyfile has no rewrites and must not grow any.
#
# Declared BEFORE the StaticFiles mount below. That mount matches everything at "/", so a
# route added after it is unreachable; this is the same ordering rule the routers above
# depend on. The .html files stay reachable too -- these are an addition, not a redirect.


def _section_route(filename: str):
    async def page() -> FileResponse:
        f = SITE / filename
        if not f.is_file():
            # Never guess: this file only exists if build_split.py has run. A 404 naming
            # the generator is more useful than a blank page.
            raise HTTPException(status_code=404,
                                detail=f"{filename} has not been generated; "
                                       "run python3 tools/build/build_split.py")
        return FileResponse(f, media_type="text/html")
    return page


for _slug, _file in SECTION_PAGES.items():
    app.get(f"/{_slug}", include_in_schema=False)(_section_route(_file))








# The Coder page, at both spellings of the address he named.
#
# R-160, restated 2026-08-20: *"update task 87 to be browser then terminal url should be
# symoneural.com/live-stack/coder"*. The hyphen is his, so it is served exactly as typed and
# leads. `/livestack/coder` answers as well, because every other application on the rack
# lives under `/livestack/<name>` (#81) and both spellings appear in this repo's own prose --
# a surface reachable at only one of them is a 404 waiting for whoever types the other.
#
# NEITHER of them is a redirect, and neither is canonical over the other. `/livestack/live`
# above gives the general reason a page route here does not redirect; the specific one is
# that a redirect would make the address in the operator's URL bar disagree with the address
# they typed, which is precisely the confusion two spellings already threaten.

# Registered as two ordinary decorators and NOT as a `for` loop over a tuple, which is what
# this was written as first. The reason is not style. Two tests read the page routes out of
# THIS FILE AS TEXT rather than by importing it -- `apps/test_caddy_delegation.py` (is every
# page path delegated by ops/Caddyfile, or does Caddy's final `handle { file_server }` 404 it
# without ever asking the API) and `apps/test_deploy_routes.py` (does deploy.sh's reference
# check know this is a route and not a missing file). Both parse `@app.get("/literal")`.
#
# A loop is invisible to both unless they are taught about it. `SECTION_PAGES` is registered
# in a loop and needed bespoke AST support in the delegation test to be seen at all -- its
# docstring says a decorator-only scan *"silently misses all four section pages -- the very
# paths whose delegation block is the oldest one in the Caddyfile."*
#
# So the paths are literals here, both guards see them for free, and the delegation test went
# red for both of them until `@coder` was added to ops/Caddyfile. That red was the point.
#
# THAT ARGUMENT WAS RIGHT FOR ONE PAGE AND IS WRONG FOR TEN. It stood here until 2026-08-22
# reading *"writing a third registration form would mean teaching two parsers about it, and
# the failure if I forgot is silent"* -- and the conclusion drawn from it, literals only, is
# the one that does not survive #81 growing to every application on the rack. Garrett,
# 2026-08-22: *"Do not duplicate literal decorators for every app if #81 is going to grow to
# all rack apps. That will drift. The parser should learn the route declaration pattern."*
#
# He is describing the failure the literal form actually has. Twenty decorators over ten
# pages is twenty chances to type one spelling and not the other, and a page reachable at
# `/livestack/x` but not `/live-stack/x` is the same 404-at-the-address-he-types this whole
# block is about -- arriving from the opposite direction, and with no red line anywhere,
# because a missing decorator is not a broken one. `LIVESTACK_PAGES` below makes both
# spellings of both addresses a property of one dict entry, so they cannot disagree.
#
# The cost is real and is paid once, in the same commit, not deferred: both parsers were
# taught the form, and each carries a named assertion that it can SEE this dict rather than
# a general vacuity guard over the whole set. `test_deploy_routes.py` records why that
# distinction matters -- its own vacuity guard passed on a non-empty set that contained no
# two-segment path at all, while `/livestack/live` went undeployable.




# ---- /livestack/<name> for the generated surface pages ------------------------------------
#
# R-154, #81: *"the https://symoneural.com/image.html needs to be updated to
# https://symoneural.com/livestack/image"*, then *"apply this to all applications."*
#
# Keys are the application name; values are the file `tools/build/build_pages.py` writes. Each
# entry serves BOTH spellings -- `/livestack/<name>` and `/live-stack/<name>` -- for the
# reason the Coder block above gives at length: he typed the hyphen, every other application
# on the rack does not, and a surface reachable at only one of them is a 404 waiting for
# whoever types the other. Neither redirects to the other and neither is canonical.
#
# `.html` KEEPS WORKING AND THAT IS THE POINT, not a courtesy. `/image.html` is published and
# shared; `site/` is mounted at `/` below, so the file answers at its own name for anything
# that already links it, and #81 is explicit that these clean URLs "are an addition, not a
# redirect" -- the same words `SECTION_PAGES` uses. A 404 on a link that used to work is the
# one failure this site cannot afford, and a redirect is not the cheap alternative it looks
# like: `/livestack/live`'s docstring above records that one would break a `<video>`
# mid-playlist, since the player resolves segment URIs against the manifest it was handed.
#
# Coder and Live are deliberately NOT folded in here. Both are hand-authored tracked pages
# with no generator, so their 404s say `git checkout` -- and `_livestack_route` below says
# `run python3 tools/build/build_pages.py`, which is true of this dict and false of them. That is
# the same distinction `/studio` and `/exp` were given their own routes for: a 404 naming the
# wrong generator sends the next person to the wrong file.
#
# Declared BEFORE the StaticFiles mount below, for the same reason every route here is.


def _livestack_route(filename: str):
    async def page() -> FileResponse:
        f = SITE / filename
        if not f.is_file():
            raise HTTPException(status_code=404,
                                detail=f"{filename} has not been generated; "
                                       "run python3 tools/build/build_pages.py")
        return FileResponse(f, media_type="text/html")
    return page


for _name, _file in LIVESTACK_PAGES.items():
    _route = _livestack_route(_file)
    # Two registrations, one entry. The pair cannot drift apart because neither is written
    # down separately -- which is the whole reason this is a dict and not ten decorators.
    app.get(f"/livestack/{_name}", include_in_schema=False)(_route)
    app.get(f"/live-stack/{_name}", include_in_schema=False)(_route)


# ---- /local: this box only, never the internet ------------------------------------------
#
# Two routes that serve and edit the progress page's assignment list. Garrett, 2026-08-20:
# *"just add some js to the page please so i can delete and check the box"*.
#
# WHY THE PREFIX IS `/local` AND NOT `/api`
# `ops/Caddyfile` sends `handle /api*` to the gateway and out to the internet. INTAKE.md
# restates GARRETT-REQUESTS.md, which is mode 600 and never committed, so a public write
# handle on it is not a trade worth making for a checkbox. A path matching no `handle` block
# in that file falls through to `handle { file_server }`, which looks for `local/intake` in
# the webroot, does not find it, and 404s without ever asking this process.
#
# That is a fact about a config file, though, and config files change. So the guard below does
# not trust it: it checks the peer address itself, and refuses anything carrying proxy headers.
# If somebody adds a `handle /local*` block a year from now, these routes go dead rather than
# public -- the failure mode is a broken button, not a leaked ledger.
#
# Declared above the StaticFiles mount, for the same reason every route here is.

#: Headers whose presence proves a request crossed a reverse proxy.
#:
#: Was `x-forwarded-for`, `x-forwarded-host`, `x-real-ip`. Measured 2026-09-08: all six
#: probed `/local/*` routes accepted a request carrying `Forwarded`, `Via` or
#: `X-Forwarded-Proto`, none of which was checked. `X-Forwarded-Proto` is the one that
#: mattered most, because the docstring's whole argument is that Caddy sets these on
#: everything it proxies -- and Caddy sets that one on everything it proxies. `Forwarded`
#: is RFC 7239, the standardised replacement for the X- spellings, so a modern proxy may
#: send only it.
#:
#: The peer check was never bypassed; this is the secondary defence, and it was the half
#: the docstring leaned on for the future `handle /local*` case it was written to survive.


def _require_local(request: Request) -> None:
    """Refuse anything that did not come from a process on this machine.

    Two conditions, and both must hold. The peer address is the real check. The forwarded
    headers are the belt to its braces: Caddy sets them on everything it proxies, so their
    presence means the request crossed the reverse proxy even if the socket says loopback --
    which is exactly what a future `handle /local*` block would produce, and exactly the case
    the peer check alone would wave through.
    """
    peer = request.client.host if request.client else ""
    forwarded = any(h in request.headers for h in _PROXY_HEADERS)
    if peer not in LOCAL_ONLY or forwarded:
        # 404, not 403. A 403 confirms the route exists; there is no reason to tell a remote
        # caller that this box has a private intake surface at all.
        raise HTTPException(status_code=404, detail="Not Found")


class IntakeSet(BaseModel):
    """One box state on one assignment. Deliberately the narrowest thing that works.

    The endpoint cannot write prose, cannot create an entry and cannot remove one -- it sets a
    single character on a line that already exists. That is the whole of what the two buttons
    need, and it means a bug here can put INTAKE.md into a wrong state but never into an
    arbitrary one.
    """
    id: str = Field(pattern=r"^A-[A-Z0-9]{1,16}$")
    set: Literal[" ", "x", "-"]




class TaskNote(BaseModel):
    """One comment on one task. Garrett: *"i need a comments box for the the project tasks"*.

    As narrow as IntakeSet and for the same reason: this endpoint can add a line to a task's
    detail block and can do nothing else. It cannot edit a task, cannot change a state, cannot
    remove anything. The worst a bug here does is write a comment in the wrong place.

    `text` is bounded because it lands in a file that a generator re-reads, and `who` is bounded
    and charset-limited because it is written into the line unquoted.
    """
    id: str = Field(pattern=r"^#\d{1,6}$")
    who: str = Field(default="garrett", pattern=r"^[\w .-]{1,32}$")
    text: str = Field(min_length=1, max_length=2000)






# ---- /local/coder: the Coder surface's reads, and the prefix that is the whole safety case
#
# `backend/coder/__init__.py` is 972 lines of file I/O, subprocess execution and a
# rollback store, and until this commit it had no route at all. The rack row said so in as
# many words -- *"deliberately has NO HTTP route. It is imported and driven from the desktop
# session"* -- and that judgement is not being reversed here, it is being restated: an
# `/api/coder/...` endpoint is arbitrary file read on the public internet the instant it
# exists, because `ops/Caddyfile` delegates the whole `/api/*` subtree.
#
# What changed is the prefix, not the risk assessment. `/local/*` matches no `handle` block
# in ops/Caddyfile, so it falls through to `handle { file_server }`, is looked up in
# /var/www/symoneural, and 404s from disk without this process ever being asked. That is the
# same reasoning `/local/intake` is already built on, and `backend/test_caddy_delegation.py`
# deliberately excludes `/local/*` from the paths it requires a delegation for -- so this
# mount is consistent with what is already enforced rather than an exception carved out of it.
#
# And, as the `/local` banner above says of itself: the guard does not trust that config
# file. `_require_local` checks the peer address and refuses proxy headers, so if somebody
# adds a `handle /local*` block a year from now these routes go dead rather than public.
#
# THREE THINGS THIS MOUNT DELIBERATELY DOES NOT DO
#
#   1. It is READ-ONLY. `write_file`, `patch_file`, `delete_file`, `restore` and `run` are
#      not mounted. #87 is *"browser then terminal"* and says the order is not negotiable;
#      where the gate for the write half lands is #88's decision, not this task's.
#   2. It does not report what it refused as absent. `list_dir` flags denied entries instead
#      of omitting them -- its own docstring argues for that -- and the page renders the
#      flag. A tree that silently hides `training/corpus.jsonl` would be the decorative
#      dishonesty this site exists to argue against, and would also teach an operator that
#      the denylist is not there.
#   3. It does not weaken `coder`'s own gates. Every call below goes through
#      `coder.authorize()`, so the surface stays OFF unless SYMONEURAL_CODER_ENABLED=1 and a
#      token are both set, and the page renders that refusal as a reading rather than
#      spinning forever.
#
# WHY THE TOKEN COMES FROM THIS PROCESS AND IS NEVER SENT TO THE PAGE
# `coder.token_ok()` exists to stop a caller who reached the module over a network. These
# routes are already past `_require_local`, which is a *stricter* peer test than
# `coder.peer_ok()`: it refuses proxy headers outright and cannot be widened by
# SYMONEURAL_CODER_ALLOW_REMOTE. The alternative is a browser page that holds the token,
# which means the token in a URL, in localStorage, or committed into this repo's own HTML.
# R-174's finding is that a credential which has been displayed is spent. So it is read
# narrowly, used in-process, and never crosses to the client.

















# ---------------------------------------------------------------- retired page names
# The Tuner and the Guide merged into the Streamer and the pages were regenerated under new
# names (Garrett: "i said tuner and guide needed to be merged and migrated to streamer").
# A bookmark or an inbound link to the old name would 404, and unlike a stale cached page it
# does NOT resolve itself on a reload -- it stays broken for as long as somebody keeps the
# link. That is the distinction that decides what gets a redirect here and what does not:
#
#   * these two page names get one, because a bookmark is permanent;
#   * `/api/tuner/*` deliberately gets NOTHING. The only callers were our own pages, and a
#     visitor holding a cached copy of the old page is fixed by their next reload. Keeping
#     an API alias would leave the retired namespace answering forever, which is not a
#     migration -- it is two namespaces, and the second one would never be removed.
#
# 302, not 301, for the reason given on `root()` above: a permanent redirect is cached
# indefinitely by browsers and is painful to walk back.




# ---- /local/coders/* -- the multi-coder session surface (R-184) --------------------------
# Included BEFORE the catch-all static mount below, because `app.mount("/", ...)` swallows
# every path that no route claimed first.
#
# `dependencies=[Depends(_require_local)]` on the router, not on each handler: a new route
# added to `apps/coders/routes.py` later is then local-only by construction rather than by
# the author remembering. This surface spawns provider CLIs under the operator's own
# sessions, so "local-only unless someone forgot" is not a good enough default.
#
# `/local/*` is NOT delegated by ops/Caddyfile -- zero matchers for it -- and `_require_local`
# additionally refuses any request carrying x-forwarded-*, so a future `handle /local*` block
# could not silently expose this.
from coders.coders import router as _coders_router  # noqa: E402



app.include_router(_coders_router, prefix="/local/coders",
                   dependencies=[Depends(_require_local)])

if SITE.is_dir():
    app.mount("/", StaticFiles(directory=str(SITE), html=True), name="site")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info", access_log=False)


# ctx, part two. Read per request, so the whole module can be built first.
_configure(
    IntakeSet=IntakeSet,
    STUDIO_REGISTRY_FILE=STUDIO_REGISTRY_FILE,
    TaskNote=TaskNote,
    _RETIRED_PAGES=_RETIRED_PAGES,
    _require_local=_require_local,
    _studio_rows=_studio_rows,
)
_require(*['API_REFERENCE_SCRIPT', 'API_REFERENCE_STYLE', 'CHAT_MODEL', 'ChatRequest', 'DIFFUSE_ENGINE', 'DISCONNECT_POLL_S', 'DOCS_HEADER', 'EmuBody', 'FLUX', 'ImageRequest', 'ImageResult', 'IntakeSet', 'LIMITS', 'MAX_PROMPT_CHARS', 'MinerBody', 'QUEUE_DEPTH', 'RENDERS', 'ROOT', 'RemixRequest', 'RemixResult', 'SITE', 'STUDIO_REGISTRY_FILE', 'SYSTEM_PROMPT', 'ScanBody', 'Status', 'TaskNote', 'Track', '_RETIRED_PAGES', '_application_docs_index', '_require_local', '_studio_rows', 'adapter_applies', 'anticipate', 'build_status', 'bus', 'chat_deltas', 'check_rate', 'client_key_ws', 'denied', 'exact_context', 'gpu', 'log', 'prune_gallery', 'run', 'semantic_etag', 'start_llama', 'stop_llama', 'throttled_for', 'ws_calc', 'ws_chat', 'ws_remix'])


# Component routers. Paths in these are absolute, so no prefix.
from asicminer.asicminer import router as asicminer_router  # noqa: E402
from chat.chat import router as chat_router  # noqa: E402
from coders.coders_pages import router as coders_root  # noqa: E402
from cryptominer.cryptominer import router as cryptominer_router  # noqa: E402
from dispatchos.dispatchos_pages import router as dispatchos_root  # noqa: E402
from docs.docs import router as docs_router  # noqa: E402
from exp.exp_pages import router as exp_root  # noqa: E402
from home.home import router as home_router  # noqa: E402
from image.image import router as image_router  # noqa: E402
from live.live_pages import router as live_root  # noqa: E402
from local.local import router as local_router  # noqa: E402
from remix.remix_pages import router as remix_root  # noqa: E402
from retired.retired import router as retired_router  # noqa: E402
from status.status import router as status_router  # noqa: E402
from studio.studio_pages import router as studio_root  # noqa: E402

app.include_router(asicminer_router)
app.include_router(chat_router)
app.include_router(coders_root)
app.include_router(cryptominer_router)
app.include_router(dispatchos_root)
app.include_router(docs_router)
app.include_router(exp_root)
app.include_router(home_router)
app.include_router(image_router)
app.include_router(live_root)
app.include_router(local_router)
app.include_router(remix_root)
app.include_router(retired_router)
app.include_router(status_router)
app.include_router(studio_root)
