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
import hashlib
import json
import logging
import os
import pathlib
import re
import secrets
import signal
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import (Depends, FastAPI, HTTPException, Request, Response, WebSocket,
                     WebSocketDisconnect, status as http)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send  # for RackPowerGate, which is raw ASGI on purpose
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

HERE = pathlib.Path(__file__).resolve().parent
# backend/ sits one level below the repo root. models/, site/, run/, scripts/ and
# contrib/ all hang off the root, not off here. This calculation has been wrong four
# times in this repo and it fails silently, because the wrong parent usually exists.
ROOT = HERE.parent
# The message names the file, not a conclusion about the root. Commissioning moved
# gpu-governor.sh aside to see what an operator would read, and got "repo root not found at
# /home/google/Symoneural" -- which is the one thing that was NOT wrong. The check is
# unchanged; only the diagnosis it offers is, because a loud error pointing at the wrong
# cause costs more than a quiet one.
assert (ROOT / "scripts" / "gpu-governor.sh").is_file(), (
    f"{ROOT / 'scripts' / 'gpu-governor.sh'} is not a file. Either that script is missing, "
    f"or ROOT is wrong (computed {ROOT} from {HERE}). On a complete checkout the first is "
    "far likelier; the API cannot start either way."
)
# ROOT, emphatically not HERE. gpu-governor.sh takes its mkdir lock in <root>/run,
# so pointing this at backend/run would give the API and the governor two different
# lock directories -- both would acquire, both would load weights, and ~12 GB of
# models would hit a 16 GB card. It is the failure this repo documents most loudly
# and it was one character away from happening during the backend/ move.
RUN = ROOT / "run"
RUN.mkdir(exist_ok=True)

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
from hardware.lib.gpu import record_engine
from hardware.lib import telemetry
# Imported as a module, not `from hardware.lib.modelmetrics import record_timings`, so the
# metrics buffer has one identity. `apps/gpu.md` records what the alternative cost.
from hardware.lib import modelmetrics  # noqa: E402
from hardware import router as metricsroutes  # noqa: E402
from runtime.lib import runtimeconfig  # noqa: E402
runtimeconfig.load()

from runtime.lib import symoneuralenv  # noqa: E402
symoneuralenv.promote()

import asicminer  # noqa: E402
import cryptominer  # noqa: E402  -- the GPU miner. A DIFFERENT surface from asicminer:
                    # different hardware and the only tenant that yields to everything.
import coder      # noqa: E402  -- local-only developer surface. Takes NO GPU lease and
                  # has NO route: it is driven from the desktop session. See §2g.
import gateway    # noqa: E402  -- TRON licensing surface, see backend/gateway/
import licensing  # noqa: E402  -- contract keys and the dev-fee disclosure
# The port registry. Nothing in this file names a surface port as a literal any more: which
# surfaces run as their own process, and on which port, is `ops/PORTS.tsv`. See apps/ports.py
# for why it refuses to report a surface delegated unless the registry also gives it a port.
from registry.lib import ports  # noqa: E402
import httpx  # noqa: E402  -- only for polling a delegated surface's /healthz; see poll_delegated

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
from streamer.guide import router as guide_routes  # noqa: E402  -- question ->
# channel filter. Imported as `routes` for the same reason accounts is: the package exports
# bare names (catalogue, status, unit_state) that would shadow this module's own.
import sigils  # noqa: E402  -- the sticker surface. Bound to the package for
# the same reason as guide: it exports `status`, `router` and `PACKS`, and a bare `status`
# would shadow this module's own. It reaches the same sd-cli as /api/image but takes the
# card under its own governor name, so the rack can say which of the two holds it.
from accounts import router as accounts_routes  # noqa: E402  -- signup,
# login and sessions. Imported as `routes` rather than the package so the package's
# many bare names (verify, enabled, status) cannot shadow anything in this module.
import voice  # noqa: E402  -- speech to text on the CPU. Bound to the package so
# its bare `status`/`enabled`/`installed` cannot shadow this module's own. Importing it drags
# in no new dependency: the engine is a subprocess, not a library.
from studio.plugins import reinforce  # noqa: E402  -- the training bay. Bound to the package so its
# bare `status`/`enabled` cannot shadow this module's own. Importing it is cheap and safe
# whether or not the surface is switched on: `apps/studio/plugins/reinforce/__init__.py` defines
# `enabled()` BEFORE it imports `.routes`, and every route calls it and answers 503 when
# both SYMONEURAL_REINFORCE_ENABLED and SYMONEURAL_REINFORCE_TOKEN are not set. Mounting an off surface
# is not the same as enabling it. What it now mounts does preference and reinforcement
# tuning as well as supervised -- see `apps/studio/plugins/reinforce/TRAINING_BAY.md`.
import studio  # noqa: E402  -- the local agent and the
# visual bench it drives. Bound to an alias because `studio` is already the name of a concept
# in this file (`/api/studio/models`, the `studio` rate bucket) and a bare `enabled`/`status`
# from the package would shadow this module's own. Importing it is free with the switch off:
# `apps/studio/gate.py` is stdlib-only, and every route calls `enabled()` first and
# answers 503 when SYMONEURAL_STUDIO_ENABLED and SYMONEURAL_STUDIO_TOKEN are not both set. It imports no
# torch, spawns no process, and does not touch the GPU until a job is queued.
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

from registry.lib import appdocs  # noqa: E402  -- the per-application documentation registry and
# renderer. Deliberately after every surface import above and deliberately importing none of
# them: it holds no reference to a router, only to path PREFIXES, and reads the real route
# table out of `app.routes` at request time. That is what keeps it from becoming a second
# copy of the route list -- the failure `apps/route_matrix.py` was written about.

GOVERNOR = ROOT / "scripts" / "gpu-governor.sh"
# The two GPU engines, and they are ours. They pointed into `external/` until 2026-08-20,
# which broke two standing rules at once -- nothing under `external/` is imported, built or
# linked, and nothing here ships under a third-party name -- and it took chat and image
# offline the moment that tree moved. `tools/sh/fork_engines.sh` builds both from our own tree
# and renames every shipped artefact; the constants below carry our names because a constant
# spelling a third-party product is the same leak as a filename doing it.
#
# Provenance is checkable, and `grep` is not how you check it: a name matches whether or not
# an engine is on disk. `readelf -d` on either binary shows a RUNPATH inside `engines/`, and
# each reports the *SyMoNeuRaL* commit it was built from -- the fork excludes `.git/`, so
# CMake walks up and reads this repo's HEAD. That is kept deliberately.
#: Both engine paths accept an environment override, added 2026-08-26 for the runtime cutover.
#:
#: The default is the historical `build/bin` location, so an unset variable changes nothing --
#: that is deliberate: a cutover mechanism whose OFF state differs from today's behaviour is
#: a second thing to debug when the cutover goes wrong.
#:
#: The override exists because a rebuilt engine is a whole RUNTIME DIRECTORY, not one file.
#: `readelf -d` shows RUNPATH `$ORIGIN` on the staged set, so the executable resolves its
#: eight SyMoNeuRaL shared objects from whatever directory it is launched out of. Copying
#: only the executable over the old one would leave it loading the OLD libraries beside it
#: and reporting a new hash while running old code -- which would pass a checksum test and
#: fail as a runtime.
#:
#: Rollback is therefore `unset SYMONEURAL_LLM_ENGINE` (or remove the line from
#: /etc/symoneural/api.env) and restart; the previous engine directory is untouched.
def _engine_path(env_var: str, default: pathlib.Path) -> pathlib.Path:
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        return default
    p = pathlib.Path(raw)
    # A non-existent override is a misconfiguration that must be loud at import, not a
    # surface that silently reports `offline` for a reason nobody can find.
    if not p.is_file():
        # `logging.getLogger(...)` inline rather than the module-level `log`: this function is
        # CALLED at import time, ~130 lines before `log` is assigned, so referencing it here
        # would raise NameError and take the whole API down -- and only on the misconfigured
        # path, which is the one nobody exercises before shipping.
        logging.getLogger("symoneural.api").error(
            "%s points at %s which is not a file; falling back to %s", env_var, p, default)
        return default
    return p


LLM_ENGINE = _engine_path(
    "SYMONEURAL_LLM_ENGINE",
    ROOT / "symoneural-llm" / "build" / "bin" / "symoneural-llm")
DIFFUSE_ENGINE = _engine_path(
    "SYMONEURAL_DIFFUSE_ENGINE",
    ROOT / "symoneural-diffuse" / "build" / "bin" / "symoneural-diffuse")
MODELS = HERE / "models"  # weights are a backend concern; backend/models/
SITE = ROOT / "site"          # the website: static files Caddy serves and deploy.sh publishes
# Renders are API output, not site content. They used to be written into site/, which meant
# deploy.sh copied every one of them into the public webroot -- 19 dead PNGs were sitting
# there -- even though nothing links to them: they are served by GET /api/gen/<name>.
RENDERS = HERE / "output"
RENDERS.mkdir(exist_ok=True)

# Switched from symon-1.0-7b-q4_k_m.gguf (qwen2, 7.6B dense) on 2026-09-11.
# Measured on this card, same harness, same questions:
#     30B-A3B  236.6 tok/s   3.35B active of 30.5B   all QA answers correct
#     7B       153.5 tok/s   7.62B active            all QA answers correct
# It is faster BECAUSE it is sparse -- 4 of 128 experts per token, so it reads 1.2 GiB
# per token against the 7B's 4.5 GiB, and this card is memory-bandwidth bound.
CHAT_MODEL = MODELS / "llm" / "symon-1.0-30b-a3b-q2_k_l.gguf"
CHAT_ADAPTER = ROOT / "training" / "adapter" / "symoneural-lora.gguf"

#: The product label for CHAT_MODEL. Pinned to the model by
#: `test_chat_model_and_its_label_change_together`, because this string is what the rack unit
#: and the site show, and a label naming the wrong model is the one kind of wrong this project
#: cannot ship. Change the model, change this, or the test fails.
CHAT_MODEL_LABEL = "SymonChat S1-30B-A3B"

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
CHAT_CTX_TOTAL = 33792


def _gguf_arch(path):
    """`general.architecture` out of a GGUF header, or None if it cannot be read.

    Reads a few KB, not the weights: the architecture is one of the first KV pairs, so this
    returns long before it has touched any tensor data. Deliberately total -- a truncated
    file, a non-GGUF file, a missing file and an unknown value type all return None rather
    than raising, because every caller is a status surface or a launch decision and neither
    should crash over metadata.
    """
    import struct
    _SCALAR = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
    try:
        with open(path, "rb") as fh:
            if fh.read(4) != b"GGUF":
                return None
            _version, _n_tensors, n_kv = struct.unpack("<IQQ", fh.read(20))

            def skip(vtype):
                if vtype == 8:                                    # string
                    (n,) = struct.unpack("<Q", fh.read(8))
                    fh.seek(n, 1)
                elif vtype == 9:                                  # array
                    (elem,) = struct.unpack("<I", fh.read(4))
                    (n,) = struct.unpack("<Q", fh.read(8))
                    for _ in range(n):
                        skip(elem)
                else:
                    fh.seek(_SCALAR[vtype], 1)

            for _ in range(min(n_kv, 4096)):
                (klen,) = struct.unpack("<Q", fh.read(8))
                key = fh.read(klen)
                (vtype,) = struct.unpack("<I", fh.read(4))
                if key == b"general.architecture" and vtype == 8:
                    (n,) = struct.unpack("<Q", fh.read(8))
                    return fh.read(n).decode("utf-8", "replace")
                skip(vtype)
    except Exception:
        return None
    return None


def draft_applies():
    """Whether DRAFT_MODEL can be used with CHAT_MODEL -- not merely whether it is on disk.

    Same defect as `adapter_applies` and the same fix, one flag along. `-md` was added
    whenever the file existed, which was safe only while chat and draft were both qwen2.
    The 30B-A3B is `qwen3moe`; the draft is `qwen2`. Speculative decoding needs the two to
    share a vocabulary, and a mismatched draft either refuses at load or -- worse -- starts
    and buys nothing while looking like it works. MEASURED 2026-09-11: the production argv
    with this draft against the 30B exits 1 at load, `cudaMalloc failed` after the draft's
    own weights and KV are added on top.

    Architecture equality is a coarse proxy for vocabulary equality and deliberately so: it
    is readable from the file without loading either model, and it fails in the safe
    direction. Losing speculative decoding costs throughput; applying a mismatched draft
    costs the surface.
    """
    if not DRAFT_MODEL.exists():
        return False
    a, b = _gguf_arch(DRAFT_MODEL), _gguf_arch(CHAT_MODEL)
    return bool(a) and a == b


def adapter_applies():
    """Whether CHAT_ADAPTER can actually be applied to CHAT_MODEL -- not merely whether the
    file is on disk.

    Every caller used to ask `CHAT_ADAPTER.exists()`, which answers a different question, and
    the difference is not academic. MEASURED 2026-08-22: launching the production argv with
    this qwen2 adapter against the gpt-oss candidate exits 1 with

        llama_adapter_lora_init: failed to apply lora adapter: model arch and LoRA arch mismatch

    so on a mismatch the chat surface does not degrade, it fails to start. Worse, the status
    surfaces would have gone on reporting `adapter: true` and advertising "+ persona adapter"
    for an adapter the engine had refused -- a product claiming a persona it is not running.

    Unknown counts as NO. If either architecture cannot be read, this returns False, and the
    asymmetry is deliberate: not applying a matching adapter costs the persona and still
    serves, while applying a mismatched one takes the whole surface down.
    """
    if not CHAT_ADAPTER.exists():
        return False
    model_arch = _gguf_arch(CHAT_MODEL)
    adapter_arch = _gguf_arch(CHAT_ADAPTER)
    if not model_arch or not adapter_arch:
        return False
    return model_arch == adapter_arch
# Draft model for speculative decoding. Measured on this box: shallow drafting wins and
# deep drafting loses badly -- see SPEC_DRAFT_MAX.
DRAFT_MODEL = MODELS / "llm" / "symon-1.0-draft-0.5b-q4_k_m.gguf"
# Two, not the default. Speculative decoding trades compute for bandwidth, and this box has
# spare compute but no spare bandwidth -- the draft model reads its own weights through the
# same 752 GB/s everything else is queuing for. Measured here at 150 tokens, temp 0.2:
#   depth 2 -> 157.4 t/s (43.8% accepted)   +5% over baseline
#   depth 3 -> 155.1 t/s (39.0% accepted)
#   depth 5 -> 121.4 t/s (27.1% accepted)   -19%
#   default -> 139.1 t/s (32.9% accepted)   -7%
# The default configuration is a net loss on this hardware. Depth 2 is a modest real win.
SPEC_DRAFT_MAX = 2
FLUX = {
    "unet": MODELS / "image" / "symoneural-image-unet-q4_k.gguf",
    "vae": MODELS / "image" / "symoneural-image-vae.safetensors",
    "clip": MODELS / "image" / "symoneural-image-clip.safetensors",
    "t5": MODELS / "image" / "symoneural-image-t5-q8_0.gguf",
}

PORT = int(os.getenv("SYMONEURAL_PORT", "8800"))
LLAMA_PORT = 8081

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s",
    handlers=[logging.FileHandler(RUN / "api.log"), logging.StreamHandler()],
)
log = logging.getLogger("symoneural.api")
# The logger is configured here, above the limits, because _rate_for() warns on a
# malformed override and LIMITS is built at import time. Defined the other way round it
# is a NameError on startup that only fires when someone sets the env var wrongly.

MAX_PROMPT_CHARS = 100_000
QUEUE_DEPTH = 24
JOB_TIMEOUT_S = 1800

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
_RATE_SUGGESTED = {
    "ravencalc": (240, 6000),   # CPU only, never queues, ~0.1 s
    "chat":  (120, 2000),       # ~1-3 s of GPU, and the queue is the real backstop
    "remix": (40,  600),        # a longer generation
    "image": (20,  300),        # ~9 s of exclusive GPU each
    # Stickers. Same engine and the same exclusive GPU as image, so the same budget --
    # the name is listed here for a reason that is not cosmetic: LIMITS is built by
    # iterating this dict, and `check_rate` returns True for any surface it does not
    # find. A name absent from here is not "unlimited by choice", it is *unmeterable*,
    # and SYMONEURAL_RATE_SIGIL would be read by nothing. This surface is the one aimed at a
    # phone app, so leaving it unmeterable was the wrong default to inherit.
    "sigil": (20,  300),
    # Voice is the first surface where the comment above does NOT apply. It is CPU work with
    # no GPU queue in front of it, so nothing else rations it and the bucket is the only
    # backstop there is. ~0.65 s of CPU each: an order cheaper than image, an order dearer
    # than RavenCalc. The key must exist even while unset -- throttled_for() reads LIMITS on
    # its deny path, and LIMITS is built from this dict.
    "voice": (60,  900),
    # `/api/studio/models`. No GPU, no CPU to speak of -- one `read_text` and a validation
    # pass -- so this bucket is not protecting the card, and today it is unset like every
    # other one here. It is listed for the reason spelled out under "sigil": a surface absent
    # from this dict is not unlimited by choice, it is *unmeterable*, and SYMONEURAL_RATE_STUDIO
    # would be read by nothing. This is a public, unauthenticated list that a client polls,
    # which is exactly the shape where the operator may later want a ceiling, so the knob
    # exists ahead of the need. Same numbers as voice: cheap, but not free.
    "studio": (60,  900),
    # The plugin runtime's reads (`/api/exp/state`, `/plugins`, `/events`). Listed for the
    # reason spelled out under "sigil" and repeated under "studio": absent from this dict is
    # not unlimited-by-choice, it is unmeterable, and SYMONEURAL_RATE_EXP would be read by nothing.
    # The page polls `/events` with a cursor while it is open, so the ceiling has to sit above
    # a poll loop rather than below it -- the same shape as voice, and the same numbers.
    "exp": (60,  900),
}


from runtime.lib.ratelimits import BUDGETS as _BUDGETS


def _rate_for(surface: str) -> tuple[int, int]:
    """Read a surface's budget from the environment. Unset means no limit."""
    raw = os.getenv(f"SYMONEURAL_RATE_{surface.upper()}", "").strip()
    if raw:
        try:
            per_min, per_hour = (int(x) for x in raw.split("/", 1))
            return per_min, per_hour
        except ValueError:
            log.warning("ignoring malformed SYMONEURAL_RATE_%s=%r, want N/N",
                        surface.upper(), raw)
    # Fall back to the published budget rather than to no limit. This returned (0, 0),
    # which check_rate reads as "allow", so every figure on /docs was decorative: 150
    # ravencalc posts in 1.64 s drew no 429 on 2026-09-08. A published ceiling that is not
    # applied is worse than no ceiling, because a reader plans against it.
    return _BUDGETS.get(surface, (0, 0))


LIMITS = {name: _rate_for(name) for name in _RATE_SUGGESTED}
RATE_PER_MIN, RATE_PER_HOUR = LIMITS["chat"]
# Mirrors ACQUIRE_TIMEOUT_S in gpu-governor.sh. A serving request waits this long
# behind a CLI job or a fine-tune before telling the visitor to try RavenCalc.
ACQUIRE_TIMEOUT_S = 300

# How often the chat handler asks whether the visitor is still on the other end. It is
# one ASGI receive poll, so it costs nothing; the interval only bounds how long a dead
# request can keep holding the card, against the ACQUIRE_TIMEOUT_S the next tenant would
# otherwise wait. Measured detection here: ~0.5 s.
DISCONNECT_POLL_S = 0.25

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
_MINOR = re.compile(r"\b(child|children|kid|kids|toddler|infant|baby|babies|minor|minors|"
                    r"underage|preteen|pre-teen|teen|teens|teenage|teenager|schoolgirl|"
                    r"schoolboy|loli|lolita|shota|"
                    # Ages ONE TO SEVENTEEN only. `\d` matched a single digit, so "12 year
                    # old" walked straight through -- caught by tests/deny_regex.py, which
                    # is the entire reason that file exists. `\d{1,2}` would have been the
                    # obvious fix and is wrong in the other direction: it refuses "a 25
                    # year old woman, nude", which is exactly the legitimate adult prompt
                    # this gate must not touch. Enumerating 1-17 refuses neither.
                    r"(?:1[0-7]|[1-9]|one|two|three|four|five|six|seven|eight|nine|ten|"
                    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen)[\s-]*"
                    r"years?[\s-]*old)\b", re.I)
_SEXUAL = re.compile(r"\b(nude|nudity|naked|topless|undress\w*|nsfw|porn\w*|erotic\w*|"
                     r"sexual\w*|sexy|sex|xxx|hentai|fellatio|genital\w*|penis|vagina|"
                     r"pussy|breasts?|boobs?|nipples?|buttocks|masturbat\w*|orgasm\w*|"
                     r"intercourse|fucking|blowjob|cum|lewd|explicit\s+sex\w*)\b", re.I)


def denied(prompt: str) -> bool:
    """True only for the intersection of a child term and a sexual term."""
    return bool(_MINOR.search(prompt) and _SEXUAL.search(prompt))


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


class CalcRequest(BaseModel):
    """A symbolic computation. Exact in, exact out -- no floats that lost the argument."""
    expression: str = Field(..., max_length=MAX_PROMPT_CHARS, examples=["x**2*sin(x)"])
    operation: Literal["differentiate", "integrate", "limit", "series",
                       "solve", "simplify", "evaluate"] = "simplify"
    variable: str | None = Field("x", max_length=64)
    point: str | None = Field(None, max_length=64,
                              description="Only meaningful for `limit`.")


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


class SubUnit(BaseModel):
    """One half of a surface that owns two kinds of hardware.

    This exists for exactly one case and should not be spread further without a reason:
    the miner is a single surface on the rack -- one row, one name -- but it is two pieces
    of hardware with two independent states (KawPow on the RTX 5070 Ti, and Antminer /
    MicroBT rigs reached over the network). Merging them into a single `state` would force
    one of the two readings to become a lie, which is the one thing this rack may not do.
    So the row carries the merged headline and this carries the parts.

    `site/console.js` never reads it -- the rack renders the parent -- and `/miner.html`
    reads it to give each half its own card and its own status chip.
    """
    id: str
    label: str
    # `unreachable` matters here too: once a parent surface is split, its folded
    # children are reached through the same process, so a dead process takes the
    # children with it and /miner.html must not show them ready.
    state: Literal["ready", "busy", "queued", "offline", "unreachable"]
    bus: Literal["gpu", "cpu", "asic", "net"]
    detail: str


class Unit(BaseModel):
    id: str
    label: str
    slot: str
    # `unreachable` is the split's state and is deliberately NOT folded into
    # `offline`. `offline` means the weights or the engine are missing -- an
    # operator goes looking for a file. `unreachable` means the process that owns
    # this row did not answer -- they go looking for a unit. Collapsing them would
    # send someone hunting for weights that are sitting on disk. Added 2026-09-10
    # with the RavenCalc pilot; site/console.js renders it dark with an amber blink.
    state: Literal["ready", "busy", "queued", "offline", "unreachable"]
    # The bus a surface actually runs on. `asic` is external mining hardware reached over
    # the network, `net` is a surface whose work is I/O rather than compute -- neither
    # contends for the GPU lock, which is why they are distinct values rather than being
    # folded into `cpu`. `site/console.js` maps these to the plate text and prints '--'
    # for anything it does not recognise rather than guessing.
    bus: Literal["gpu", "cpu", "asic", "net"]
    href: str
    spec: str
    detail: str
    # Present only on a surface that owns two kinds of hardware; see SubUnit. Optional so
    # every other unit serialises exactly as it did before.
    sub: list[SubUnit] | None = None


class GpuState(BaseModel):
    name: str
    vram_free_mib: int | None = None
    vram_total_mib: int | None = None
    vram_used_pct: int | None = None
    power_w: float | None = None
    temp_c: int | None = None
    holder: str | None = None
    queued: int = 0
    # The driver's own health, reported as its own thing rather than folded into the unit
    # states. A GPU driver mismatch used to show up only as "every GPU request 500s", which
    # an operator reads as an application fault; the one action that fixes it -- a reboot --
    # is not something you would try in response to that. `driver_detail` names the action.
    driver: Literal["ok", "mismatch", "persistenced_down", "absent", "unreadable"] = "ok"
    driver_detail: str | None = None


class Status(BaseModel):
    """What the rack on the home page renders. Every field is read from the machine."""
    units: list[Unit]
    gpu: GpuState
    link: dict
    # The dev fee, on the public status endpoint on purpose. A rate that applies without
    # being visible is the failure mode this whole design exists to rule out, so disclosure
    # rides on the same response the rack already fetches rather than on an endpoint someone
    # has to know to ask for. With no contract installed it reports state "none" and no rate,
    # because there is no default fee anywhere in this codebase.
    license: dict


# ======================================================================== plumbing

class AsicCache:
    """Last known rig readings, refreshed off the request path.

    `/api/status` is polled and also drives the websocket, so it must never block. Probing
    rigs means spawning a subprocess that waits on network timeouts -- up to 30s if a rig
    has been unplugged, which is exactly when it is slowest and exactly when someone is
    looking. So the endpoint reads whatever was last measured and a background task does the
    waiting.

    `None` means "not yet probed", which `asicminer.unit_state` reports as offline rather
    than inventing an optimistic default. A stale reading is labelled by `age_s` rather than
    being silently presented as current -- the whole rack argues that its numbers are real,
    and "real but N seconds old" is a different claim from "real right now".
    """

    TTL = 20.0

    def __init__(self) -> None:
        self._value: dict | None = None
        self._at: float = 0.0

    def get(self) -> dict | None:
        if self._value is None:
            return None
        return {**self._value, "age_s": round(time.monotonic() - self._at, 1)}

    def stale(self) -> bool:
        return time.monotonic() - self._at >= self.TTL

    def put(self, value: dict) -> None:
        self._value, self._at = value, time.monotonic()


_asic_cache = AsicCache()


async def asic_refresher() -> None:
    """Keep `_asic_cache` warm while the surface is enabled. Started in the lifespan."""
    while True:
        try:
            if asicminer.enabled() and asicminer.installed():
                _asic_cache.put(await asicminer.probe())
        except asyncio.CancelledError:
            raise
        except Exception:                      # never let this kill the loop
            log.exception("asic refresh failed")
        await asyncio.sleep(AsicCache.TTL)


# The token bucket, the two-bucket check and the client key moved to `apps/ratelimits.py`
# on 2026-09-10, alongside the BUDGETS they enforce. A split surface must apply the same
# published cap from its own process, and the alternatives were to import this or to write a
# second one -- and a second implementation of a published cap is the exact drift
# `ratelimits.py` was created to end. The reasoning moved with the code.
from runtime.lib.ratelimits import (allowed as _allowed,  # noqa: E402
                             client_key_from_headers as _client_key_from_headers,
                             limiters_for as _limiters_for)

# A surface with no configured budget gets NO limiter object at all, rather than one
# built with capacity 0. A zero-capacity bucket never refills to 1.0, so it would deny
# every single request forever -- the exact inversion of "no limit", and indistinguishable
# from a broken endpoint. Absent from this dict means unmetered; see check_rate.
_limiters = _limiters_for(LIMITS)


def client_key(request: Request) -> str:
    """Caddy sits in front, so the real client is in the forwarded header."""
    return _client_key_from_headers(request.headers,
                                    request.client.host if request.client else None)


async def check_rate(surface: str, key: str) -> bool:
    """Both buckets must allow, and the minute bucket is charged first.

    Ordering matters slightly: if the hourly bucket is the one that denies, the minute token
    is still spent. That is deliberate -- refunding it would mean tracking partial charges,
    and the drift is a token an hour.
    """
    return await _allowed(_limiters, surface, key)


def throttled_for(surface: str):
    """A dependency that rate-limits against this endpoint's own budget."""
    async def dep(request: Request) -> None:
        key = client_key(request)
        if not await check_rate(surface, key):
            per_min, per_hour = LIMITS[surface]
            log.warning("rate limited %s on %s", key, surface)
            raise HTTPException(
                429,
                f"Easy — {surface} is capped at {per_min}/min and {per_hour}/hour per "
                f"address. RavenCalc runs on the CPU and is far less restricted.")
    return dep


Throttled = Annotated[None, Depends(throttled_for("chat"))]


class GpuQueue:
    """Serialises GPU work.

    The lock is global rather than per-surface because the constraint is physical: 15.92
    GiB does not hold both weight sets, so 'chat is busy' and 'image is busy' are the same
    condition wearing different names.
    """

    def __init__(self, depth: int):
        self._lock = asyncio.Lock()
        self._slots = asyncio.Semaphore(depth)
        self.waiting = 0
        self.current: str | None = None

    @asynccontextmanager
    async def hold(self, surface: str):
        """Hold the card for the duration of one job -- and only that.

        This used to be an in-process lock only, while the *governor* lock was taken once
        when llama-server started and kept for as long as the weights stayed loaded. The
        card was therefore marked busy during the 99% of the time chat was merely resident
        and idle, and nothing outside this process could ever get in: a CLI image request
        sat behind it until the 300 s acquire timeout expired.

        Residency and work are different things. llama-server staying loaded is residency,
        tracked by the governor's `resident` file. Holding the lock is work. So the
        governor lock is now taken here, per job, and released the moment the job ends --
        which is what lets `symoneural-cli image` from a terminal take its turn like any other
        tenant, and lets the governor evict a resident-but-idle surface to make room.
        """
        if not _try(self._slots):
            raise HTTPException(
                http.HTTP_503_SERVICE_UNAVAILABLE,
                "The box is busy and the queue is full. Try again shortly.")
        contended = self._lock.locked()
        # Count waiters, not the holder. Incrementing before taking the lock meant a single
        # job with nobody behind it reported queued=1, which tripped the rack into an amber
        # "1 job(s) waiting" banner while the queue was in fact empty.
        if contended:
            self.waiting += 1
        try:
            if contended:
                # Say so before blocking. A client that knows it is third in line behind an
                # image render can show that, or go use RavenCalc, instead of watching a
                # spinner that explains nothing.
                await bus.announce(surface, "queued", behind=self.current, depth=self.waiting)
            async with self._lock:
                # Now take the cross-process lock. This can block on a CLI job or a
                # fine-tune, so it gets the full acquire timeout and reports honestly if it
                # loses the race rather than proceeding onto a card somebody else owns.
                rc, _out, _err = await run(str(GOVERNOR), "acquire", surface,
                                           timeout=ACQUIRE_TIMEOUT_S + 15, env_owner=True)
                if rc != 0:
                    raise HTTPException(
                        http.HTTP_503_SERVICE_UNAVAILABLE,
                        "Something else is using the GPU right now -- RavenCalc is on the "
                        "CPU and still available.")
                self.current = surface
                await bus.announce(surface, "acquired")
                await push_rack()
                try:
                    yield
                finally:
                    self.current = None
                    await run(str(GOVERNOR), "release", surface, timeout=90)
                    await bus.announce(surface, "released")
                    await push_rack()
        finally:
            if contended:
                self.waiting -= 1
            self._slots.release()


def _try(sem: asyncio.Semaphore) -> bool:
    try:
        sem.acquire_nowait()  # type: ignore[attr-defined]
        return True
    except AttributeError:
        # asyncio.Semaphore has no acquire_nowait; emulate it.
        if sem._value <= 0:  # noqa: SLF001
            return False
        sem._value -= 1      # noqa: SLF001
        return True
    except Exception:
        return False


gpu = GpuQueue(QUEUE_DEPTH)


class Bus:
    """The three-way channel: frontend <-> backend, agent <-> agent, agent <-> user.

    Polling was the alternative and it is genuinely wasteful. The rack asked /api/status
    every 2.5 seconds per open tab and almost always learned nothing -- a full request,
    response, and header set to be told the state had not changed. One upgraded connection
    plus a push when something actually happens is fewer bytes, fewer wakeups, and less
    power on both ends.

    Two rules keep it that way:

    **Only on change.** Every publish is diffed against the last frame sent and dropped if
    identical. A socket that chatters on a timer is just polling with extra steps.

    **Agents publish, they do not address.** A surface announces what it did -- acquired the
    card, started a render, released -- and every listener decides what that means to it.
    The rack redraws, a waiting client learns why it is waiting, and another agent can react,
    all from one event and one send.
    """

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._last: str | None = None
        # Baseline per connection, not one global. A single shared snapshot let a late
        # joiner reset the diff baseline for everybody: the delta against the newer
        # baseline came out empty, so clients already connected never learned about the
        # change and stayed wrong for those fields forever.
        self._snapshots: dict[int, dict] = {}

    async def join(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.add(ws)

    async def leave(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)
            self._snapshots.pop(id(ws), None)

    @property
    def listeners(self) -> int:
        return len(self._clients)

    def seed(self, ws: WebSocket, snapshot: dict) -> None:
        """Record the baseline this particular client was just given."""
        self._snapshots[id(ws)] = snapshot

    async def publish_delta(self, snapshot: dict) -> None:
        """Send only what moved since the last push.

        The client holds the rack state and patches it, so the wire carries the change
        rather than the world. A chat request starting is genuinely four fields --
        one unit's state, the holder, the queue depth, a VRAM figure -- and re-sending the
        whole rack to say that is most of a kilobyte to communicate about forty bytes of
        news. Over a night of traffic with several tabs open that is the difference between
        a socket that whispers and one that shouts the same sentence repeatedly.

        The baseline comes from the snapshot sent at handshake, so a client is never asked
        to patch state it does not have.
        """
        async with self._lock:
            targets = list(self._clients)
        dead = []
        for ws in targets:
            baseline = self._snapshots.get(id(ws))
            delta = _diff(baseline, snapshot) if baseline else {}
            self._snapshots[id(ws)] = snapshot
            if not delta:
                continue
            try:
                await ws.send_text(json.dumps({"t": "patch", **delta}, separators=(",", ":")))
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)
                    self._snapshots.pop(id(ws), None)

    async def publish(self, frame: dict, *, dedupe_key: str | None = None) -> None:
        """Broadcast a frame. If dedupe_key is given, skip identical consecutive frames."""
        text = json.dumps(frame, separators=(",", ":"))
        if dedupe_key is not None:
            if text == self._last:
                return
            self._last = text
        async with self._lock:
            dead = []
            for ws in self._clients:
                try:
                    await ws.send_text(text)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._clients.discard(ws)

    async def announce(self, source: str, event: str, **fields) -> None:
        """An agent saying what it just did, to whoever is listening."""
        await self.publish({"t": "bus", "from": source, "event": event, **fields})


def _diff(old: dict, new: dict) -> dict:
    """Structural difference, keyed the way the client stores it.

    Units are diffed by id rather than by list position, so the patch says
    `{"units": {"chat": {"state": "busy"}}}` -- addressed, not ordinal. A positional patch
    breaks silently the day a unit is added or reordered, and it breaks in the worst way:
    the client applies it to the wrong row and shows a confident wrong answer.
    """
    if not old:
        return {}
    out: dict = {}

    old_units = {u["id"]: u for u in old.get("units", [])}
    unit_delta = {}
    for unit in new.get("units", []):
        was = old_units.get(unit["id"])
        if was is None:
            unit_delta[unit["id"]] = unit
            continue
        changed = {k: v for k, v in unit.items() if was.get(k) != v}
        if changed:
            unit_delta[unit["id"]] = changed
    if unit_delta:
        out["units"] = unit_delta

    old_gpu, new_gpu = old.get("gpu") or {}, new.get("gpu") or {}
    gpu_delta = {k: v for k, v in new_gpu.items() if old_gpu.get(k) != v}
    if gpu_delta:
        out["gpu"] = gpu_delta
    return out


bus = Bus()




# Gallery pruning. It lived between `smi()` and `refresh_telemetry()` in the old layout and
# was moved into telemetry.py by e08eaa98 purely because of that adjacency -- it is a
# serving concern over RENDERS, not a card reading. It came back here the moment /api/image
# raised NameError in production. Proximity is not a subject.
GALLERY_KEEP = 60


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


async def run(*argv: str, timeout: int = JOB_TIMEOUT_S, env_owner: bool = False,
              is_engine: bool = False) -> tuple[int, bytes, bytes]:
    """Run a subprocess in its own session, and kill the whole group on timeout.

    Killing only the direct child is not enough: the governor is a wrapper script and the
    engine (sd-cli, llama-server) is its child. SIGKILL to the wrapper leaves the engine
    orphaned, still holding several gigabytes of VRAM, and skips the wrapper's release trap
    so the lock leaks too. A process group makes "stop this job" mean all of it.

    `is_engine` must be opt-in, and the default must be False. This helper is general: it
    also runs `gpu-governor.sh acquire` and `release` at :829 and :843. Recording EVERY
    child as the engine was a real regression, shipped and caught on the live box the same
    day: a chat request left `run/engine` naming the governor's own acquire shell, which had
    already exited, while the actual engine ran on under a different pid. Eviction would
    then have found a dead pid, logged "already exited -- nothing to signal", cleared the
    record and never stopped the engine holding 8.3 GB. Worse than the pattern kill it
    replaced, because it fails silently and looks correct in the log.
    """
    env = dict(os.environ)
    if env_owner:
        # Name ourselves as the lock owner so the holder pid is a process that will still
        # exist while the card is held.
        env["SYMONEURAL_OWNER_PID"] = str(os.getpid())
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=True, env=env)
    if is_engine:
        await record_engine(proc.pid)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()
        raise HTTPException(504, "That took too long and was stopped.")
    return proc.returncode or 0, out, err




# ======================================================================== chat surface

SYSTEM_PROMPT = (
    "You are SyMoNeuRaL, the admin representative and resident expert for SyMoNeuRaL, a "
    "SymonSays LLC company that builds custom local AI infrastructure. You run locally on "
    "the machine you are describing. Be concise, concrete and never oversell. "
    "Measured facts about this machine, which you may cite: NVIDIA RTX 5070 Ti, Blackwell "
    "sm_120, 70 SMs x 128 = 8,960 CUDA cores, 15.92 GiB VRAM (15,858 MB), 256-bit bus at "
    "14,001 MHz, 896.1 GB/s theoretical DRAM bandwidth, ~752 GB/s measured (~84% of peak), "
    "48 MB L2, PCIe Gen 3 x8 host cap (the GPU supports Gen 5) giving ~6.94 GB/s H2D and "
    "~7.20 GB/s D2H pinned. Decode is memory-bandwidth bound: every token reads the full "
    "weight set once, so tokens/second is roughly bandwidth divided by weight bytes. "
    "Never invent a number you were not given, and never quote a price -- direct pricing "
    "questions to symonsayadmin@symoneural.com."
)

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

_OPERATION_WORDS = [
    (re.compile(r"\b(integrat\w*|antideriv\w*)\b", re.I), "integrate"),
    (re.compile(r"\b(differentiat\w*|derivat\w*|d/d[a-z])\b", re.I), "differentiate"),
    (re.compile(r"\blimit\b", re.I), "limit"),
    (re.compile(r"\b(solve|roots?\s+of|solutions?\s+(?:to|of))\b", re.I), "solve"),
    (re.compile(r"\b(simplif\w*|reduce)\b", re.I), "simplify"),
    (re.compile(r"\b(expand|series|taylor)\b", re.I), "series"),
    (re.compile(r"\b(evaluat\w*|compute|calculate|what\s+is)\b", re.I), "evaluate"),
]

# A run of characters that could plausibly be an expression. Deliberately conservative:
# it must contain an operator or a function call, so ordinary prose does not qualify.
_EXPR_CANDIDATE = re.compile(r"[0-9A-Za-z_+\-*/^().,\s]{3,120}")
_HAS_MATH = re.compile(r"[+\-*/^]|\b[a-z]+\s*\(")
_VARIABLE = re.compile(r"\b(?:with respect to|wrt|in terms of|for)\s+([a-zA-Z])\b", re.I)


def extract_math(prompt: str) -> tuple[str, str, str] | None:
    """Find (operation, expression, variable) in a natural-language question.

    Returns None far more often than not, and that is the correct behaviour -- a false
    positive here means an irrelevant "verified result" is handed to the model and it
    dutifully works it into an answer about something else. The parser is the gate: a
    candidate only survives if RavenCalc's own strict whitelist parser accepts it, so
    prose, code and pasted logs fall out on their own.
    """
    try:
        from ravencalc.apps import ravencalc
    except ImportError:
        return None

    operation = next((op for pattern, op in _OPERATION_WORDS if pattern.search(prompt)), None)
    if operation is None:
        return None

    variable = "x"
    if match := _VARIABLE.search(prompt):
        variable = match.group(1)

    # Fenced text wins outright -- if someone put it in backticks they meant it literally.
    for fenced in re.findall(r"`([^`]{2,120})`", prompt):
        if _parses(ravencalc, fenced):
            return operation, fenced.strip(), variable

    # Otherwise search word spans, longest first, and let the parser decide. Trying to
    # strip English with a regex does not survive contact with real phrasing: "integrate
    # x**2 with respect to x" has prose on both sides, and one pass of prefix-removal
    # leaves the tail behind. Testing spans costs nothing on a sentence and is simply
    # correct -- the strict whitelist parser is a far better judge of "is this an
    # expression" than any pattern of mine.
    # Drop the operation words before searching. SymPy's namespace contains functions with
    # exactly these names, so "simplify (x**2-1)/(x-1)" parses happily as a call to
    # simplify() -- and "integrate (x)" would parse as an integral that we then integrate a
    # second time. The verb belongs to the request, not to the expression.
    cleaned = re.sub(r"\b(integrate|integral|antiderivative|differentiate|derivative|"
                     r"diff|limit|solve|simplify|expand|factor|series|taylor|evaluate|"
                     r"compute|calculate)\b", " ", prompt, flags=re.I)
    words = re.sub(r"[?]", " ", cleaned).split()
    n = len(words)
    for length in range(min(n, 14), 0, -1):
        for start in range(0, n - length + 1):
            candidate = " ".join(words[start:start + length]).strip(" .,?:;")
            if len(candidate) < 3 or not _HAS_MATH.search(candidate):
                continue
            if not any(ch.isalnum() for ch in candidate):
                continue
            if _parses(ravencalc, candidate):
                return operation, candidate, variable
    return None


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


async def anticipate(prompt: str) -> dict | None:
    """Speculatively solve any mathematics in the prompt, on the CPU, in parallel.

    Started before the GPU surface is ready and awaited after, so on a cold chat the whole
    computation happens inside time that was going to be spent loading weights anyway.
    """
    found = extract_math(prompt)
    if not found:
        return None
    operation, expression, variable = found
    started = time.time()
    result = await asyncio.to_thread(_compute_exact, operation, expression, variable)
    if not result:
        return None
    result["_anticipated_ms"] = round((time.time() - started) * 1000, 1)
    result["_operation"] = operation
    await bus.announce("ravencalc", "anticipated", operation=operation,
                       expression=expression, ms=result["_anticipated_ms"])
    log.info("anticipated %s(%s) in %sms", operation, expression, result["_anticipated_ms"])
    return result


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
_llama_lock = asyncio.Lock()


async def llama_up() -> bool:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", LLAMA_PORT), timeout=2)
        writer.write(b"GET /health HTTP/1.0\r\nHost: localhost\r\n\r\n")
        await writer.drain()
        head = await asyncio.wait_for(reader.read(64), timeout=3)
        writer.close()
        return b"200" in head
    except Exception:
        return False


async def start_llama() -> bool:
    global _llama
    async with _llama_lock:
        if await llama_up():
            return True
        if not CHAT_MODEL.exists() or not LLM_ENGINE.exists():
            return False
        # No acquire here: every caller is already inside gpu.hold("chat"), so the card
        # is ours. Taking a second, longer-lived lock here is exactly what locked the CLI
        # out for the lifetime of the process.
        argv = [str(LLM_ENGINE), "-m", str(CHAT_MODEL), "-ngl", "99",
                "--host", "127.0.0.1", "--port", str(LLAMA_PORT),
                # `-c` is the TOTAL context, divided by `-np`. At the old 8192/4 every
                # chat slot had 2,048 tokens -- roughly 8,000 characters of prompt, reply
                # and entire replayed transcript combined. That, not MAX_PROMPT_CHARS, was
                # the real ceiling on a long conversation, and raising the character cap
                # without raising this would have moved the failure rather than removed it.
                #
                # 65536/2 gives each slot 32,768 -- the full context Qwen2.5-7B was trained
                # for, so it is now the model's own limit rather than one we imposed.
                #
                # MEASURED on this card 2026-08-17, not projected. Started with exactly this
                # argv including --lora, confirmed `n_slots = 2, n_ctx_slot = 32768` in the
                # server log, and generated a real completion:
                #     9,485 MiB of 16,303 used     (idle baseline 1,084 MiB)
                # so chat costs ~8.2 GiB here, up from the ~5.4 GiB measured at -c 8192 in
                # run/governor.log. 6.6 GiB stays free, which clears the governor's 1.5 GB
                # drain floor with room to spare.
                #
                # An earlier revision of this comment said "~8.7 GB" and was ARITHMETIC I
                # had done, written in a voice that read as a reading off the card. On a
                # site whose entire argument is that its numbers are measured, that is the
                # one mistake that matters. It was also, at the time, describing a config
                # that had never once been started. Measure it, or label it projected.
                #
                # 2026-09-11: 65536 was measured for Qwen2.5-7B (4.36 GiB of weights) and
                # OOMs on the 30B-A3B (10.55 GiB): `cudaMalloc failed: out of memory`
                # allocating the KV. So the number moved into CHAT_CTX_TOTAL beside the
                # model it belongs to, because a context size is a property of the MODEL and
                # the CARD together, and hardcoding one here made it look like a property of
                # the surface.
                "-c", str(CHAT_CTX_TOTAL), "--no-warmup",
                # Continuous batching: one pass over the weights serves every slot in
                # flight, which is the single highest-value lever measured on this card
                # (47.3x from batch 1 to batch 64). Two slots rather than four, because
                # slots divide the context and context is what was actually scarce.
                "-cb", "-np", "2"]
        if draft_applies():
            argv += ["-md", str(DRAFT_MODEL), "-ngld", "99",
                     "--spec-draft-n-max", str(SPEC_DRAFT_MAX)]
        elif DRAFT_MODEL.exists():
            # On disk but not applicable. Say so, for the reason the adapter branch says it:
            # a surface that quietly runs without an accelerator it believes it has produces
            # a throughput number nobody can explain.
            log.warning("draft model NOT applied: %s is %s, chat model is %s",
                        DRAFT_MODEL.name, _gguf_arch(DRAFT_MODEL), _gguf_arch(CHAT_MODEL))
        if adapter_applies():
            argv += ["--lora", str(CHAT_ADAPTER)]
        elif CHAT_ADAPTER.exists():
            # On disk but not applicable. Say so loudly: the alternative is a surface that
            # quietly serves without its persona and a log that never mentions it.
            log.warning("persona adapter NOT applied: %s is %s, chat model is %s",
                        CHAT_ADAPTER.name, _gguf_arch(CHAT_ADAPTER), _gguf_arch(CHAT_MODEL))
        log.info("starting chat surface")
        _llama = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        # No `start_new_session=True` here, deliberately: the chat engine is long-lived and
        # `stop_llama()` already stops it by handle. So this child shares OUR process group,
        # `record_engine` will decline to offer a pgid, and eviction signals the single pid.
        # That is still an identity, which the pattern it replaces was not.
        await record_engine(_llama.pid)
        for _ in range(120):
            if await llama_up():
                log.info("chat surface up")
                return True
            await asyncio.sleep(1)
        log.error("chat surface failed to come up")
        return False


async def stop_llama() -> None:
    global _llama
    async with _llama_lock:
        if _llama and _llama.returncode is None:
            _llama.terminate()
            try:
                await asyncio.wait_for(_llama.wait(), timeout=20)
            except asyncio.TimeoutError:
                _llama.kill()
        _llama = None


async def chat_deltas(messages: list[dict], max_tokens: int, temperature: float,
                      surface: str = "chat"):
    """Yield content deltas from llama-server's OpenAI-compatible endpoint.

    Also captures the engine's own measurements on the way past -- see the `timings` branch
    below. `surface` only labels which caller produced the sample on the metrics page.
    """
    body = json.dumps({"model": "symoneural", "messages": messages, "stream": True,
                       "max_tokens": max_tokens, "temperature": temperature}).encode()
    reader, writer = await asyncio.open_connection("127.0.0.1", LLAMA_PORT)
    writer.write(
        b"POST /v1/chat/completions HTTP/1.1\r\nHost: localhost\r\n"
        b"Content-Type: application/json\r\nConnection: close\r\n"
        + f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    await writer.drain()
    try:
        while True:
            raw = await asyncio.wait_for(reader.readline(), timeout=JOB_TIMEOUT_S)
            if not raw:
                break
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except Exception:
                continue
            # llama-server appends a `timings` object to the FINAL chunk of every stream:
            # tokens read and written, tok/s both ways, prompt-cache hits -- all measured by
            # the engine while it was already doing the work. Until 2026-09-11 this loop
            # read the content out of each chunk and discarded everything else, so those
            # numbers were measured on every request this box has ever served and thrown
            # away every time. This is the line that keeps them.
            #
            # Cost is one dict copy. NO probe request is issued: a metrics page that asks the
            # model a question to find out how fast the model is would take the GPU lease to
            # do it, and would be measuring itself.
            if "timings" in chunk:
                modelmetrics.record_timings(chunk["timings"], surface=surface)
            try:
                delta = chunk["choices"][0].get("delta", {})
            except (KeyError, IndexError, TypeError):
                continue
            if piece := delta.get("content"):
                yield piece
    finally:
        writer.close()


# ---------------------------------------------------------------- guide's model half

#: The event loop, captured in `lifespan`. Guide's local pass runs in a worker thread via
#: `asyncio.to_thread`, so its optional model call has to get back onto the loop to reach
#: llama-server; there is no running loop in that thread to ask.
_LOOP: asyncio.AbstractEventLoop | None = None


def guide_ask_model(prompt: str) -> str:
    """Ask the chat surface for one line, on Guide's behalf. Called from a worker thread.

    **It never starts the model.** If chat is not already resident this raises, and Guide
    falls back to its local pass and says so. Starting a 7B to answer "show me motorsport"
    would evict whatever holds the card -- possibly an image render somebody is waiting
    on -- to do work that the CPU already did in under a millisecond. The contended card
    is the whole reason Guide has a local pass at all.
    """
    loop = _LOOP
    if loop is None:
        raise guide.ModelUnusable("the api is not running an event loop yet")

    async def _run() -> str:
        if not await llama_up():
            raise guide.ModelUnusable(
                "the chat surface is not resident; Guide will not evict another surface "
                "to answer a channel filter")
        pieces: list[str] = []
        async for piece in chat_deltas([{"role": "user", "content": prompt}],
                                       max_tokens=64, temperature=0.2):
            pieces.append(piece)
        return "".join(pieces)

    try:
        return asyncio.run_coroutine_threadsafe(_run(), loop).result(timeout=45)
    except guide.ModelUnusable:
        raise
    except Exception as exc:                      # noqa: BLE001
        # Never surface the underlying message: it can quote a socket path or an internal
        # address, and Guide's answer is shown to a visitor.
        raise guide.ModelUnusable(f"chat surface unreachable ({type(exc).__name__})") from None


# ======================================================================== app

async def telemetry_loop() -> None:
    """Keep the live modules actually live.

    push_rack only fired when a job started or ended, so between jobs the VRAM, power and
    temperature readings sat frozen -- on modules badged `live`, on a page whose argument is
    that its numbers are real. Worse, the HTTP polling fallback was fresher than the
    WebSocket we tell clients to prefer.

    Only runs while somebody is listening, and the delta filter means an idle machine still
    sends nothing: temperature that has not moved produces no frame.
    """
    while True:
        try:
            await asyncio.sleep(3)
            if bus.listeners:
                await telemetry.refresh_telemetry()
                await push_rack()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("telemetry loop hiccup")


@asynccontextmanager
async def lifespan(_: FastAPI):
    log.info("symoneural api on 127.0.0.1:%d (loopback only)", PORT)
    global _LOOP
    _LOOP = asyncio.get_running_loop()
    guide_routes.ASK_MODEL = guide_ask_model
    # "0/min, 0/hr" would read as "nothing is allowed" in a log someone skims at 3am, when
    # it means the exact opposite. Print the state, not the number.
    metered = ", ".join(f"{s} {p}/min {h}/hr" for s, (p, h) in LIMITS.items() if p) or "none"
    log.info("caps: prompt<=%d chars, queue %d, rate limited: %s",
             MAX_PROMPT_CHARS, QUEUE_DEPTH, metered)
    # DispatchOS creates its tables once at startup rather than on the first request, so an
    # operator opening the page never races two requests both running CREATE TABLE. Guarded
    # by the switch: with the surface off this touches no disk at all, which keeps the
    # default state of this box free of a database nobody asked for.
    if dispatchos.enabled():
        try:
            dispatchos.init_db()
            log.info("dispatchos surface enabled; store at %s", dispatchos.lib.store.db_path())
        except Exception:
            # A store that will not open is a reason for that surface to answer 503, not a
            # reason for the whole API to fail to start. `status()` reports it as offline.
            log.exception("dispatchos store could not be initialised; surface stays down")
    ticker = asyncio.create_task(telemetry_loop())
    # Only run when an operator has switched the surface on. With the env unset this task
    # would loop forever doing nothing, so it is not started at all -- and the rack still
    # reports the ASIC unit correctly, because `unit_state` reads the switches directly.
    asic = asyncio.create_task(asic_refresher()) if asicminer.enabled() else None
    if asic:
        log.info("asic surface enabled; probing %d configured rig(s)", len(asicminer.rigs()))
    # Same reasoning as the ASIC probe, for the same reason: a public TRON node measured
    # 0.4-2.3 s from this box, and /api/status drives the rack websocket for every visitor.
    # A reading that slow cannot sit on the status path, so it is cached off it.
    gw = asyncio.create_task(gateway.refresher()) if gateway.enabled() else None
    # Same pattern again, and the same reason: a pass over thirteen third-party feeds took
    # 13.4-41.2 s measured on 2026-08-20, which cannot sit anywhere near a request. It is
    # cached off the path entirely and `/api/news/ticker` only ever reads the cache. With the
    # switch off no task is started, so the default state of this box makes no outbound
    # request at all. Not called `ticker`: that name is the telemetry loop's, four lines up.
    newsfeed = asyncio.create_task(news.refresher()) if news.enabled() else None
    # Only if something is actually delegated -- on a box where the monolith answers
    # everything this task would poll nothing forever.
    delegates = (asyncio.create_task(poll_delegated())
                 if ports.delegated_surfaces() else None)
    if newsfeed:
        log.info("news surface enabled; %d sources, %d search engines, %.0fs interval",
                 len(news.apps.feeds.SOURCES), len(news.apps.feeds.SEARCHES), news.interval_s())
    # The project store is created by `store.connect()`, which every write route goes
    # through -- but the rack poll uses `probe()`, read-only by design, so before this line
    # existed a fresh install reported "no project store initialised" until someone happened
    # to POST. Honest, and also permanently offline for a surface whose only prerequisite is
    # a file. `bootstrap()` is a no-op when the switch is off; it does not create a database
    # for a surface nobody enabled.
    store_path = project.bootstrap()
    if store_path:
        log.info("project surface enabled; store at %s", store_path)
    # The obs-websocket client. Started here and never from a route: a connection per request
    # would re-run the SHA256 challenge/response on every page load, and obs-websocket rate
    # limits nothing, so that fault is invisible except as latency. `start()` returns as soon
    # as the task is scheduled and never raises -- an absent OBS is the normal state of this
    # box, not an error, and it must not be able to stop the API booting.
    await live.bridge.start()
    yield
    ticker.cancel()
    if asic:
        asic.cancel()
    if gw:
        gw.cancel()
    if newsfeed:
        newsfeed.cancel()
    if delegates:
        delegates.cancel()
    # Without this a reload leaks one ffmpeg per live stream: the sessions outlive the
    # process that spawned them and nothing else knows their pids.
    streamer.lib.sessions.MANAGER.shutdown()
    # Closes the socket and cancels the reconnect loop. Without it a `--reload` cycle leaves
    # the old task backing off against an OBS the new process is also connecting to, which is
    # two clients holding one credential and a reconnect storm nobody can see from a log.
    await live.bridge.stop()
    await stop_llama()


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


class RackPowerGate:
    """Refuse HTTP work on a surface an operator has taken off the rack.

    THIS IS WHAT MAKES THE BUTTON REAL. `.claude/CLAUDE.md`: *"No decorative status
    indicators."* A control that flips a rack row to `offline` while `POST /api/chat` keeps
    answering is the fake activity light with a worse failure mode -- an operator would
    believe a surface was down and act on it. The rack reading in `build_status()` and this
    gate are two halves of one fact, and neither may ship without the other.

    Deliberately a middleware and not an edit to any endpoint. The standing instruction is
    that `api.py`'s existing endpoints, image generation logic and `gpu-governor.sh` calls
    are not to be altered; this touches none of the three. It also means a surface added
    later inherits the switch by adding one line to `rackpower.ROUTES` rather than by
    remembering to paste a guard into a new handler.

    Cost when nothing is switched off: one dict walk over five prefixes. `is_disabled()`
    (which reads the file) is only reached for a path that actually belongs to a governed
    surface, so `/api/status` -- the polled one -- never touches the disk here.

    503 with `Retry-After`, not 404: the surface exists and is coming back. 404 would tell a
    visitor the feature was never built, and the honest answer is that an operator took it
    down and the detail line on the rack says when.

    **Written as a raw ASGI class rather than as `@app.middleware("http")`, and that is not a
    style choice -- it is load-bearing for a defect one layer down. Do not convert it back.**
    `@app.middleware("http")` is `BaseHTTPMiddleware`, which runs the endpoint in a task and
    hands it a *substitute* receive channel. `http.disconnect` never reaches the endpoint's
    own `Request`, so `await request.is_disconnected()` blocks forever instead of answering
    True, and `/api/chat`'s disconnect watchdog -- the thing that gives the GPU lease back
    when a visitor closes the tab -- never fires. Measured here 2026-08-21, four stacks, one
    handler, one abandoned socket:

        bare app                     -> RELEASED   ['saw disconnect', 'released']
        + GZipMiddleware             -> RELEASED   ['saw disconnect', 'released']
        + BaseHTTPMiddleware         -> LEAKED     []
        + this gate as raw ASGI      -> RELEASED   ['saw disconnect', 'released']

    Note the empty list on the third row: neither the watchdog nor the generator's `finally`
    ran at all, so nothing appears in any log to read. GZip is above this in the stack and is
    exonerated by row two -- it is pure ASGI and passes `receive` straight through, as this
    now does. `backend/SMOKE-lease-503.md` has the run.

    What it decides is unchanged from the `BaseHTTPMiddleware` version: same prefix walk, same
    503 body, same `Retry-After`, same position in the stack (added after GZip, so still the
    outer of the two and its 503 is still uncompressed).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        # `Request(scope)` with no `receive` bound: this reads the path and nothing else, so
        # the endpoint downstream still owns the one real receive channel. That ownership is
        # the entire point of the class -- see the docstring.
        unit_id = rackpower.unit_for_path(Request(scope).url.path)
        if unit_id is not None and rackpower.is_disabled(unit_id):
            response = JSONResponse(
                status_code=503,
                headers={"Retry-After": "300"},
                content={"error": f"{unit_id} has been taken off the rack by an operator. "
                                  f"It is not faulty and nothing was lost; see the rack on the "
                                  f"home page for when it went down."},
            )
            return await response(scope, receive, send)
        return await self.app(scope, receive, send)


# Added after GZip, so it is the OUTER of the two -- the order the `@app.middleware("http")`
# registration it replaced produced, kept deliberately.
app.add_middleware(RackPowerGate)


DOCS_HEADER = """
<header>
  <div class="wrap bar">
    <a class="logo" href="/">
      <img src="/mark-64.png" srcset="/mark-32.png 1x, /mark-64.png 2x" alt="SyMoNeuRaL"
           width="30" height="30">
      <b>SyMoNeu<i>RaL</i></b>
    </a>
    <nav>
      <a class="live" href="/chat.html"><s></s>Talk to the box</a>
      <a class="live" href="/image.html"><s></s>Make it draw</a>
      <a href="/ravencalc.html">RavenCalc</a>
      <a href="/#rack">Stack</a>
      <a class="cta ghost" href="/openapi.json">openapi.json</a>
    </nav>
  </div>
</header>
<div class="wrap" style="padding-top:26px">
  <p class="eyebrow"><img src="/terminal-64.png" alt="" width="20" height="20"
     style="display:inline-block;vertical-align:-4px;margin-right:8px">API Reference</p>
  <h1 style="margin:0;font-size:clamp(26px,3.4vw,38px);letter-spacing:-.022em;font-weight:680">
    SyMoNeuRaL API</h1>

  <div class="console" style="margin-top:20px">
    <div class="mod" data-src="live"><div class="tag"><s></s>VRAM free</div>
      <div class="val" id="m-vram">&mdash;</div><div class="sub">of 15.92 GiB</div>
      <div class="meter" id="m-vrambar"><i style="width:0%"></i></div></div>
    <div class="mod" data-src="live"><div class="tag"><s></s>Power draw</div>
      <div class="val" id="m-pwr">&mdash;</div><div class="sub">300 W limit</div>
      <div class="meter" id="m-pwrbar"><i style="width:0%"></i></div></div>
    <div class="mod" data-src="live"><div class="tag"><s></s>Resident</div>
      <div class="val sm" id="m-holder">idle</div><div class="sub">one surface at a time</div></div>
    <div class="mod" data-src="live"><div class="tag"><s></s>Queue</div>
      <div class="val" id="m-queue">0</div><div class="sub">jobs waiting</div></div>
    <div class="mod" data-src="measured"><div class="tag"><s></s>Rate limit</div>
      @@RATE@@</div>
    <div class="mod" data-src="measured"><div class="tag"><s></s>Prompt cap</div>
      <div class="val">@@CAP@@</div><div class="sub">chars &middot; refused, not truncated</div></div>
  </div>

  <div class="callout" style="margin-top:22px">
    <h3>Prefer the socket to the poller</h3>
    <p>
      <code style="color:var(--dim)">GET /api/ws</code> upgrades to a WebSocket and then stays
      quiet until the machine actually changes &mdash; one handshake, one baseline snapshot,
      then patches of a few dozen bytes. Polling <code style="color:var(--dim)">/api/status</code>
      works too and supports <code style="color:var(--dim)">If-None-Match</code>, so an
      unchanged rack costs a bare <code style="color:var(--dim)">304</code> with no body.
    </p>
    <p>
      <strong>Frames.</strong> Server sends <code style="color:var(--dim)">welcome</code> &rarr;
      <code style="color:var(--dim)">rack</code> (full) &rarr;
      <code style="color:var(--dim)">patch</code> (deltas, units addressed by id) and
      <code style="color:var(--dim)">bus</code> (an agent announcing what it did).
      Client may send <code style="color:var(--dim)">ping</code>,
      <code style="color:var(--dim)">rack</code>,
      <code style="color:var(--dim)">chat</code>, <code style="color:var(--dim)">ravencalc</code>,
      <code style="color:var(--dim)">remix</code> &mdash; rate limited exactly like the REST
      routes, because holding a socket open is not a way around the caps.
    </p>
  </div>
</div>
"""


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
API_REFERENCE_STYLE = """<style>
/* The scoped-application index at the top of this page. `ar-` prefixed like everything
   else here, for the reason the block comment above gives at length. */
.ar-index{margin:0 0 34px;padding:0 0 30px;border-bottom:1px solid var(--sfline)}
.ar-index h2{margin:0 0 10px;font-size:clamp(20px,2.4vw,27px);letter-spacing:-.015em;
  font-weight:665}
.ar-runtimes{display:grid;gap:14px;margin-top:20px;
  grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
.ar-rt{background:var(--sf3);border:1px solid var(--sfline);border-radius:var(--r-panel);
  padding:16px 18px}
.ar-rt h3{margin:0;font:600 var(--t6)/1.4 ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  letter-spacing:.05em;color:var(--accent)}
.ar-rt>p{margin:5px 0 12px;color:var(--faint);font-size:var(--t6);line-height:1.5}
.ar-apps{display:flex;flex-direction:column;gap:9px}
.ar-applink{display:block;text-decoration:none;color:var(--fg);font-size:var(--t5);
  min-height:32px;display:flex;align-items:center}
.ar-applink:hover b{color:var(--accent)}
.ar-applink b{font-weight:620;letter-spacing:-.003em}
.ar-appkids{display:flex;flex-wrap:wrap;gap:7px;margin:5px 0 3px 13px;
  padding-left:11px;border-left:1px solid var(--sfline)}
.ar-appkid{display:inline-flex;align-items:center;min-height:30px;padding:3px 10px;
  border:1px solid var(--sfline);border-radius:var(--r-pill);text-decoration:none;
  color:var(--dim);font-size:var(--t6)}
.ar-appkid:hover{color:var(--accent);border-color:var(--accent)}

.ar-wrap{max-width:1080px;margin:0 auto;padding:0 22px 80px}
.ar-note{color:var(--dim);margin:18px 0 26px;max-width:78ch;line-height:1.55}
.ar-group{margin:34px 0 0}
.ar-group>h2{font-size:15px;letter-spacing:.04em;text-transform:uppercase;color:var(--dim);
  font-weight:640;margin:0 0 10px;padding-bottom:8px;border-bottom:1px solid var(--line)}
.ar-op{border:1px solid var(--line);border-radius:9px;margin:9px 0;background:var(--panel)}
.ar-op>summary{cursor:pointer;padding:11px 14px;display:flex;gap:11px;align-items:baseline;
  flex-wrap:wrap;list-style:none}
.ar-op>summary::-webkit-details-marker{display:none}
.ar-op>summary:hover{background:rgba(255,255,255,.028)}
.ar-verb{font:600 11px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.07em;
  padding:3px 8px;border-radius:5px;border:1px solid var(--line);flex:none}
.ar-get{color:#7fd1b9;border-color:#2f5f52}
.ar-post{color:#8fb8f0;border-color:#33507d}
.ar-put,.ar-patch{color:#e0c07a;border-color:#6b5a2e}
.ar-delete{color:#e59a9a;border-color:#7a3f3f}
.ar-ws{color:#c9a2e8;border-color:#5d3f74}
.ar-path{font:500 13.5px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;
  word-break:break-word;overflow-wrap:anywhere}
.ar-sum{color:var(--dim);font-size:13.5px;line-height:1.6;flex:1 1 220px;min-width:0}
.ar-body{padding:4px 14px 16px;border-top:1px solid var(--line)}
.ar-body p{line-height:1.6;max-width:80ch}
.ar-body h3{font-size:12px;letter-spacing:.05em;text-transform:uppercase;color:var(--dim);
  margin:18px 0 7px;font-weight:640}
.ar-tbl{width:100%;border-collapse:collapse;font-size:13.5px;display:block;overflow-x:auto}
.ar-tbl th,.ar-tbl td{text-align:left;padding:6px 12px 6px 0;vertical-align:top;
  border-bottom:1px solid var(--line);line-height:1.55}
.ar-tbl th{color:var(--dim);font-weight:600;font-size:11.5px;letter-spacing:.04em;
  text-transform:uppercase;white-space:nowrap}
.ar-mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}
.ar-req{color:#e59a9a;font-size:11px;letter-spacing:.04em}
.ar-pre{background:var(--sunk,rgba(0,0,0,.28));border:1px solid var(--line);border-radius:7px;
  padding:11px 13px;overflow-x:auto;font:400 12.5px/1.65 ui-monospace,SFMono-Regular,Menlo,
  monospace;white-space:pre;margin:0}
.ar-fold{margin:9px 0 0}
.ar-fold>summary{cursor:pointer;color:var(--dim);font-size:12.5px;padding:4px 0}
.ar-count{color:var(--dim);font-size:12px;font-variant-numeric:tabular-nums}
.ar-fail{border:1px solid #7a3f3f;border-radius:9px;padding:14px 16px;color:#e59a9a;
  line-height:1.6}
@media (max-width:560px){.ar-op>summary{gap:8px}.ar-sum{flex-basis:100%}}
</style>
"""

# Reads `/openapi.json` -- the same document `/api/status` and the CLI read -- and renders it.
# There is no build step and no data of its own: if the schema changes, this page changes,
# because it has nothing else to draw from.
API_REFERENCE_SCRIPT = """
<script>
(function () {
  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  };

  // $ref resolution, depth-capped. A schema may legitimately reference itself -- a tree
  // node with children of its own type is the ordinary case -- so an uncapped walk hangs
  // the tab rather than failing visibly. Six levels renders every schema this API has.
  function resolve(node, doc, depth) {
    if (!node || typeof node !== "object" || depth > 6) return node;
    if (node.$ref) {
      var parts = String(node.$ref).replace(/^#\\//, "").split("/");
      var at = doc;
      for (var i = 0; i < parts.length; i++) {
        at = at && at[parts[i]];
      }
      return at ? resolve(at, doc, depth + 1) : { type: "object" };
    }
    return node;
  }

  function typeOf(schema, doc, depth) {
    var s = resolve(schema, doc, depth || 0);
    if (!s) return "any";
    if (s.anyOf || s.oneOf) {
      return (s.anyOf || s.oneOf).map(function (m) {
        return typeOf(m, doc, (depth || 0) + 1);
      }).join(" | ");
    }
    if (s.enum) return s.enum.map(function (v) { return JSON.stringify(v); }).join(" | ");
    if (s.type === "array") return typeOf(s.items, doc, (depth || 0) + 1) + "[]";
    if (s.type) return s.format ? s.type + " (" + s.format + ")" : s.type;
    if (s.properties) return "object";
    return "any";
  }

  // Fields are listed in full, never sampled. A reference that shows "the first few"
  // properties is the same failure as a truncated attribution: the reader cannot tell
  // whether what they need is missing or absent.
  function fieldTable(schema, doc) {
    var s = resolve(schema, doc, 0);
    if (!s || !s.properties) return "";
    var required = s.required || [];
    var rows = Object.keys(s.properties).map(function (name) {
      var p = resolve(s.properties[name], doc, 0) || {};
      var need = required.indexOf(name) >= 0
        ? '<span class="ar-req">required</span>' : "";
      var extra = [];
      if (p.minimum !== undefined) extra.push("min " + p.minimum);
      if (p.maximum !== undefined) extra.push("max " + p.maximum);
      if (p.maxLength !== undefined) extra.push("max length " + p.maxLength);
      if (p.default !== undefined) extra.push("default " + JSON.stringify(p.default));
      return "<tr><td class=\\"ar-mono\\">" + esc(name) + "</td>"
        + '<td class="ar-mono">' + esc(typeOf(s.properties[name], doc, 0)) + "</td>"
        + "<td>" + need + "</td>"
        + "<td>" + esc(p.description || "")
        + (extra.length ? " <span class=\\"ar-count\\">" + esc(extra.join(" \\u00b7 "))
            + "</span>" : "")
        + "</td></tr>";
    });
    if (!rows.length) return "";
    return '<table class="ar-tbl"><thead><tr><th>Field</th><th>Type</th><th></th>'
      + "<th>Notes</th></tr></thead><tbody>" + rows.join("") + "</tbody></table>";
  }

  function paramTable(params, doc) {
    if (!params || !params.length) return "";
    var rows = params.map(function (p) {
      return "<tr><td class=\\"ar-mono\\">" + esc(p.name) + "</td>"
        + "<td>" + esc(p.in) + "</td>"
        + '<td class="ar-mono">' + esc(typeOf(p.schema, doc, 0)) + "</td>"
        + "<td>" + (p.required ? '<span class="ar-req">required</span>' : "") + "</td>"
        + "<td>" + esc(p.description || "") + "</td></tr>";
    });
    return "<h3>Parameters</h3>"
      + '<table class="ar-tbl"><thead><tr><th>Name</th><th>In</th><th>Type</th><th></th>'
      + "<th>Notes</th></tr></thead><tbody>" + rows.join("") + "</tbody></table>";
  }

  function schemaOf(content, doc) {
    if (!content) return null;
    var key = Object.keys(content)[0];
    return key ? content[key].schema : null;
  }

  function render(doc) {
    var root = document.getElementById("ar-root");
    var groups = {}, order = [], total = 0;

    Object.keys(doc.paths || {}).sort().forEach(function (path) {
      var item = doc.paths[path];
      Object.keys(item).forEach(function (verb) {
        if (["get", "post", "put", "patch", "delete", "head", "options"]
            .indexOf(verb) < 0) return;
        var op = item[verb];
        var tag = (op.tags && op.tags[0]) || path.split("/")[2] || "root";
        if (!groups[tag]) { groups[tag] = []; order.push(tag); }
        groups[tag].push({ path: path, verb: verb, op: op });
        total++;
      });
    });

    if (!total) {
      root.innerHTML = '<div class="ar-fail">The schema loaded but declares no '
        + "operations. That is a fault in the API, not in this page.</div>";
      return;
    }

    var html = ['<p class="ar-count">' + total + " operations across "
      + order.length + ' groups, read from <span class="ar-mono">/openapi.json</span> '
      + "at " + esc(new Date().toLocaleTimeString()) + ".</p>"];

    order.sort().forEach(function (tag) {
      html.push('<section class="ar-group"><h2>' + esc(tag) + "</h2>");
      groups[tag].forEach(function (entry) {
        var op = entry.op, doc_ = doc;
        var body = [];
        if (op.description) {
          body.push("<p>" + esc(op.description) + "</p>");
        }
        body.push(paramTable(op.parameters, doc_));

        var reqSchema = schemaOf(op.requestBody && op.requestBody.content, doc_);
        if (reqSchema) {
          var t = fieldTable(reqSchema, doc_);
          body.push("<h3>Request body</h3>" + (t ||
            '<p class="ar-count">Free-form; see the schema below.</p>'));
          body.push('<details class="ar-fold"><summary>Raw request schema</summary>'
            + '<pre class="ar-pre">'
            + esc(JSON.stringify(resolve(reqSchema, doc_, 0), null, 2))
            + "</pre></details>");
        }

        var responses = op.responses || {};
        var codes = Object.keys(responses).sort();
        if (codes.length) {
          body.push("<h3>Responses</h3>");
          body.push('<table class="ar-tbl"><thead><tr><th>Code</th><th>Meaning</th>'
            + "</tr></thead><tbody>"
            + codes.map(function (code) {
                return "<tr><td class=\\"ar-mono\\">" + esc(code) + "</td><td>"
                  + esc((responses[code] || {}).description || "") + "</td></tr>";
              }).join("")
            + "</tbody></table>");
          codes.forEach(function (code) {
            var rs = schemaOf((responses[code] || {}).content, doc_);
            if (!rs) return;
            body.push('<details class="ar-fold"><summary>Response schema for '
              + esc(code) + "</summary>"
              + (fieldTable(rs, doc_) || "")
              + '<pre class="ar-pre">'
              + esc(JSON.stringify(resolve(rs, doc_, 0), null, 2))
              + "</pre></details>");
          });
        }

        html.push('<details class="ar-op"><summary>'
          + '<span class="ar-verb ar-' + entry.verb + '">'
          + esc(entry.verb.toUpperCase()) + "</span>"
          + '<span class="ar-path">' + esc(entry.path) + "</span>"
          + '<span class="ar-sum">' + esc(op.summary || "") + "</span>"
          + '</summary><div class="ar-body">' + body.join("") + "</div></details>");
      });
      html.push("</section>");
    });

    root.innerHTML = html.join("");
  }

  fetch("/openapi.json", { headers: { accept: "application/json" } })
    .then(function (r) {
      if (!r.ok) throw new Error("/openapi.json answered " + r.status);
      return r.json();
    })
    .then(render)
    .catch(function (err) {
      // Says what actually failed. A reference page that renders an empty list on a fetch
      // error reads as "this API has no endpoints", which is a worse lie than an error.
      document.getElementById("ar-root").innerHTML =
        '<div class="ar-fail">Could not read <span class="ar-mono">/openapi.json</span>: '
        + esc(err && err.message ? err.message : err)
        + ". The reference is generated from the running service, so this means the "
        + "service is not answering -- not that the reference is missing.</div>";
    });
})();
</script>
"""


def _application_docs_index() -> str:
    """The index of scoped application documentation, grouped by functional runtime.

    This sits at the TOP of `/docs` rather than at the bottom, and grouped by runtime rather
    than listed flat, because the two questions a visitor arrives with are "which application
    am I looking for" and "what actually runs it" -- and a flat alphabetical list of
    twenty-two slugs answers neither. The grouping is read from the registry, so a new
    application appears here the moment it is given an owner and never has to be added twice.

    Global versus scoped is stated rather than implied: this page is the platform-wide
    reference and every link below narrows it to one application's own routes.
    """
    by_runtime: dict[str, list] = {}
    for a in appdocs.APPLICATIONS:
        by_runtime.setdefault(a.runtime, []).append(a)

    blocks = []
    for runtime in appdocs.RUNTIMES:
        apps_here = [a for a in by_runtime.get(runtime, []) if a.parent is None]
        children = {a.parent: [] for a in by_runtime.get(runtime, []) if a.parent}
        for a in by_runtime.get(runtime, []):
            if a.parent:
                children.setdefault(a.parent, []).append(a)
        if not apps_here and not children:
            continue
        rows = []
        for a in apps_here:
            kids = children.get(a.id, [])
            kid_links = "".join(
                f'<a class="ar-appkid" href="/docs/{k.id}">{appdocs.e(k.label)}</a>'
                for k in kids)
            rows.append(
                f'<div class="ar-app"><a class="ar-applink" href="/docs/{a.id}">'
                f'<b>{appdocs.e(a.label)}</b></a>'
                + (f'<div class="ar-appkids">{kid_links}</div>' if kid_links else "")
                + "</div>")
        # A child whose parent runs on a DIFFERENT runtime still needs a home here, or it
        # would be silently absent from the index while having a perfectly good page.
        for parent_id, kids in children.items():
            if any(a.id == parent_id for a in apps_here):
                continue
            for k in kids:
                rows.append(f'<div class="ar-app"><a class="ar-applink" href="/docs/{k.id}">'
                            f'<b>{appdocs.e(k.label)}</b></a></div>')
        blocks.append(
            f'<div class="ar-rt"><h3>{appdocs.e(runtime)}</h3>'
            f'<p>{appdocs.e(appdocs.RUNTIMES[runtime])}</p>'
            f'<div class="ar-apps">{"".join(rows)}</div></div>')

    return (
        '<div class="ar-index">'
        '<h2>Documentation by application</h2>'
        '<p class="ar-note">This page is the <strong>platform-wide</strong> reference: every '
        'route this service mounts, from the schema it generates. Each link below is a '
        '<strong>scoped</strong> page carrying only that application&rsquo;s own routes, its '
        'runtime owner, its authentication boundary and its operational limits. Applications '
        'are grouped by the runtime that executes their work; indented entries are child '
        'surfaces of the application above them, not runtimes of their own.</p>'
        f'<div class="ar-runtimes">{"".join(blocks)}</div>'
        '</div>'
    )




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
DELEGATE_POLL_S = 2.0
#: Older than this and the row is `unreachable`. Three missed polls, so one slow answer does
#: not flap the rack -- the failure this must not have is a surface that alternates.
DELEGATE_STALE_S = 6.0

#: surface -> (row, monotonic fetched_at, error or None). Absent means never yet polled.
_delegated_rows: dict[str, tuple[dict | None, float, str | None]] = {}


async def poll_delegated() -> None:
    """Keep `_delegated_rows` warm for every surface another process owns."""
    while True:
        try:
            surfaces = ports.delegated_surfaces()
            if surfaces:
                async with httpx.AsyncClient(timeout=1.5) as client:
                    for surface in surfaces:
                        base = ports.base_url(surface)
                        try:
                            r = await client.get(f"{base}/healthz")
                            r.raise_for_status()
                            _delegated_rows[surface] = (r.json(), time.monotonic(), None)
                        except Exception as exc:
                            # Keep the last good row and record the error. Which one wins is
                            # decided by age in `_merge_delegated`, not here -- a single
                            # dropped poll must not blank the rack.
                            prev = _delegated_rows.get(surface, (None, 0.0, None))[0]
                            _delegated_rows[surface] = (
                                prev, _delegated_rows.get(surface, (None, 0.0, None))[1],
                                f"{type(exc).__name__}: {exc}"[:160])
            await asyncio.sleep(DELEGATE_POLL_S)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("delegated poll hiccup")
            await asyncio.sleep(DELEGATE_POLL_S)


def _merge_delegated(units: list[Unit]) -> list[Unit]:
    """Replace each delegated surface's row with what its own process last said.

    Runs BEFORE `rackpower.apply`, which keeps the last word: an operator who has taken a
    surface off the rack must still see `offline`, not `unreachable`, because they know why
    it is down and the reason they chose is more useful than the reason it is quiet.
    """
    try:
        delegated = set(ports.delegated_surfaces())
    except Exception:
        # A malformed registry must not take the rack down. Report the monolith's own view.
        log.exception("port registry unreadable; reporting in-process state")
        return units
    if not delegated:
        return units
    out: list[Unit] = []
    for u in units:
        if u.id not in delegated:
            out.append(u)
            continue
        row, fetched, err = _delegated_rows.get(u.id, (None, 0.0, "not polled yet"))
        age = time.monotonic() - fetched if fetched else None
        if row is not None and age is not None and age <= DELEGATE_STALE_S:
            out.append(u.model_copy(update={
                "state": row.get("state", "ready"),
                "detail": row.get("detail", u.detail),
            }))
        else:
            # The reason has to be actionable: which process, on which port, and what the
            # last error was. "unreachable" with a blank detail is the same failure as a
            # stale `ready` -- it tells an operator nothing they can do.
            where = ports.base_url(u.id) or "no port in ops/PORTS.tsv"
            aged = f"last answered {age:.0f}s ago" if age is not None else "never answered"
            out.append(u.model_copy(update={
                "state": "unreachable",
                "detail": (f"{u.id} runs as its own process and did not answer: {where} "
                           f"({aged}). {err or ''} "
                           f"Start it: sudo systemctl start symoneural-{u.id}").strip(),
            }))
    return out


def build_status() -> Status:
    """Per-unit state for the rack.

    Four states, and they mean different things: `ready` (take it now), `busy` (this unit
    holds the card), `queued` (something else holds it and this unit would wait), `offline`
    (weights or engine missing). `queued` is the one worth being careful about -- a visitor
    stuck behind someone's render should be able to see why, and see that RavenCalc is free.
    """
    # The API's own queue is not the only thing that can own the card. A training run or a
    # CLI invocation takes the governor directly, and a rack that reports "ready" while a
    # fine-tune is mid-epoch is lying to the visitor -- they click, wait five minutes behind
    # a lock, and conclude the site is broken. So the governor's own record wins.
    holder = gpu.current or external_holder()
    chat_ok = CHAT_MODEL.exists() and LLM_ENGINE.exists()
    image_ok = all(p.exists() for p in FLUX.values()) and DIFFUSE_ENGINE.exists()

    # A driver the card cannot talk through makes every GPU surface unserveable no matter
    # what is on disk, so it is read once here and applied to the GPU rows below. Deliberately
    # NOT an ExecStartPre check: that would refuse to start the whole service, taking
    # ravencalc -- which is CPU-only and perfectly able to serve through a driver fault --
    # down with it.
    driver_state, driver_detail = telemetry.gpu_driver_health()
    driver_ok = driver_state in ("ok", "persistenced_down")

    def gpu_unit(name: str, ok: bool) -> str:
        """`ready` means LOADABLE ON DEMAND, not resident. Stated because it was misread.

        `chat_ok`/`image_ok` above are filesystem existence checks -- weights present, engine
        binary present -- and this box loads nothing until a request arrives. So `ready` is the
        honest word for "click it and it will serve", and an idle card underneath it is normal
        rather than a contradiction. A reviewer reasonably read `ready` + an empty GPU as a
        false claim, which is why the meaning is now written down beside the computation
        instead of living in whoever last read this function.

        What would be dishonest is a DETAIL line asserting present-tense residency, and two of
        them did until 2026-09-03 -- see the `~N GB when loaded` strings below.
        """
        # The driver is checked BEFORE the on-disk check, because "offline" for a missing
        # model and "offline" for an unusable driver need different actions and the detail
        # line has to say which. `driver_detail` on GpuState carries the reason.
        if not driver_ok:
            return "offline"
        if not ok:
            return "offline"
        if holder == name:
            return "busy"
        return "queued" if holder else "ready"

    # The ASIC surface never touches the GPU lock, so it is read outside the block above.
    # Disabled is the default and costs nothing: `unit_state` short-circuits on the env
    # switches, so no subprocess is spawned unless an operator has turned the surface on.
    asic_state, asic_detail = asicminer.unit_state(_asic_cache.get())
    # The CACHED reading, never a live fetch: see the refresher above. `unit_state`
    # with no argument would go to the network on the status path.
    gateway_state, gateway_detail = gateway.unit_state(gateway.CACHE.get())
    # Cheap: reads a pidfile and, only when a miner is actually running, tails its log.
    # Unconfigured -- which is the state of this box -- it does no work at all. `/api/status`
    # is polled and drives the websocket, so nothing in here may block.
    gpuminer_state, gpuminer_detail = cryptominer.unit_state()
    coder_state, coder_detail = coder.unit_state()

    # The two mining halves are one rack row (see the Unit below), so the row needs one
    # state without either half's reading becoming a lie.
    #
    # The GPU half wins whenever it is doing something, and deliberately so: it is the only
    # half that takes the card, so `busy` and `queued` there are facts every other surface
    # on this box feels. Below that, a surface is `ready` if EITHER half can be started --
    # anything else would report a startable miner as offline. `offline` only when neither
    # can do anything, which is the truth about both.
    if gpuminer_state in ("busy", "queued"):
        miner_state = gpuminer_state
    elif "ready" in (gpuminer_state, asic_state):
        miner_state = "ready"
    else:
        miner_state = "offline"
    # Both halves are always named, in that order, so the row can never imply that a
    # reading from one is a reading from the other. No ellipsis: the rack wraps.
    miner_detail = f"GPU: {gpuminer_detail} · ASIC: {asic_detail}"

    # ---- the Studio family --------------------------------------------------------------
    # Studio is the parent application and the runtime owner; Reinforce and Exp are child
    # surfaces of it, not runtimes of their own. Both were top-level rows until 2026-08-29
    # and are now `SubUnit`s, which is the shape `gateway` under `miner` established: the id
    # survives, the page survives, the reading survives, and only the top-level row goes.
    #
    # These are computed HERE rather than inline in the row below because `train`'s state has
    # to stay a reading of `adapter_applies()` and the governor holder -- see the long note
    # at the fold site further down. Splatting `reinforce.status()` over it would assert a
    # different true thing (whether the HTTP surface accepts work) in place of this one
    # (whether an adapter is loaded), which is the merge that comment refuses.
    train_state = ("busy" if holder == "train"
                   else ("ready" if adapter_applies() else "offline"))
    train_detail = ("fine-tune in progress — serving surfaces queue" if holder == "train"
                    else ("adapter loaded · for model/adapter tuning"
                          if adapter_applies() else "no adapter built"))
    # DEFECT 6, fixed the way the note above argues for. The rack reported `train` as
    # `ready` while all four of its parameterless GETs answered 503 -- "SyMoNeuRaL Reinforce
    # is off". Both readings were true: an adapter IS loaded, and the HTTP surface is NOT
    # accepting work. The comment above deliberately refuses to merge them, because `state`
    # here means "is an adapter loaded" and overwriting it would assert a different true
    # thing in place of that one.
    #
    # So `state` is left alone and the detail says the other half. A reader who sees `ready`
    # now also sees that nothing will answer, which is the gap that mattered -- `studio`
    # already reports offline with a precise reason, so the rack could express this and
    # simply did not for this unit.
    if not reinforce.enabled():
        train_detail += " · surface off — set SYMONEURAL_REINFORCE_ENABLED=1 and " \
                        "SYMONEURAL_REINFORCE_TOKEN; routes answer 503 until then"
    # `exp` keeps publishing its own status dict; only the shape it is carried in changes.
    # Read once so the child and any future reader of it cannot disagree within one response.
    exp_row = exp.status()

    free, total = telemetry.smi("memory.free"), telemetry.smi("memory.total")
    return Status(
        license=licensing.disclosure(),
        # `rackpower.apply` gets the LAST word on unit state, and only ever in one
        # direction: it can force a unit to `offline` when an operator has taken it down,
        # and it can do nothing else. Every state below is still derived from a real reading
        # -- weights on disk, the governor's holder, the surface's own switches -- and an
        # override replaces the derived state with a detail line that says an operator did
        # it, so the rack never reports an intervention as a fault. With the switch off this
        # is the identity function and costs one dict lookup.
        units=rackpower.apply(_merge_delegated([
            Unit(id="chat", label="SyMoNeuRaL Chat", slot="1U", state=gpu_unit("chat", chat_ok),
                 bus="gpu", href="/chat.html",
                 # Product names first -- these are our builds: our quantization, our
                 # adapter, our serving stack. The upstream model stays visible in the
                 # detail line because both bases are Apache-2.0 and attribution is a
                 # licence condition, not a courtesy -- and because a page arguing that
                 # its numbers are real cannot hide where its weights came from.
                 spec=CHAT_MODEL_LABEL + (" + persona adapter" if adapter_applies()
                                          else " · Q4_K_M"),
                 detail="~5 GB when loaded · SymonChat S1-7B"),
            Unit(id="image", label="SyMoNeuRaL Image", slot="2U",
                 state=gpu_unit("image", image_ok), bus="gpu", href="/image.html",
                 spec="SymonImage F1 · q4_k",
                 detail="~7 GB when loaded · SymonImage F1" if image_ok
                        else "weights loading"),
            Unit(id="remix", label="SyMoNeuRaL Remix", slot="1U",
                 state=gpu_unit("remix", chat_ok), bus="gpu", href="/remix.html",
                 spec="client of the chat surface", detail="no weights of its own"),
            Unit(id="ravencalc", label="SyMoNeuRaL RavenCalc", slot="1U", state="ready",
                 bus="cpu", href="/ravencalc.html", spec="exact symbolic algebra",
                 detail="cpu only, never queues"),
            # The adapter bay. Idle most of the time, but when a fine-tune is running it
            # owns the card outright and every serving surface waits behind it -- so it
            # belongs on the rack rather than being invisible infrastructure.
            # Renamed 2026-08-17 on Garrett's instruction. The old label was
            # "SyMoNeuRaL Quantized Low-Rank Adaptation Tool", which was not a product name
            # at all -- it was our prefix bolted onto the expansion of a generic technique,
            # breaking the convention every other unit follows (Chat, Image, Remix,
            # RavenCalc, Miner, Tuner, Gateway). It was also the longest string on the rack
            # by a wide margin and wrapped to FIVE lines in the compact GPU panel beside
            # every prompt box, which is what made that stack look out of proportion.
            #
            # NOTE FOR WHOEVER READS THIS NEXT: `backend/studio/plugins/reinforce/` holds two things
            # that answer to "Reinforce" -- the CUDA engine (the `symoneural/` subpackage,
            # with its own FastAPI app on port 8000, which must NOT be reused here) and the
            # training bay built on it. An agent told to "look at Reinforce" will land on
            # the engine first. That is deliberate on Garrett's part; see
            # docs/specs/qlora-upgrade.md, which is a spec and not a description of state.
            #
            # The href now points at the bay rather than at the manual. `site/reinforce.html`
            # is written by `tools/build/build_reinforce.py`, which wires up the `page.html` and
            # `page.js` that the bay's author left in `apps/studio/plugins/reinforce/` with nothing
            # referencing them. THIS MEANS THE PAGE MUST BE DEPLOYED BEFORE THE API IS
            # RESTARTED: `sudo scripts/deploy.sh --prune` first, then
            # `sudo systemctl restart symoneural-api`. Reversed, the rack advertises a page
            # the webroot does not have yet and every visitor who clicks the unit gets a 404.
            # `deploy.sh`'s reference check will not catch that -- it greps the deployed HTML
            # for src=/href=, and a rack href arrives as JSON from /api/status, so it is
            # never in the markup to be checked. The ordering is the only protection.
            #
            # `state` is still read from adapter_applies() and NOT from
            # `reinforce.status()`, deliberately. The two assert different true things: this
            # unit says an adapter is loaded, and the reinforce app's own status says whether
            # its HTTP surface will accept work. Splatting one over the other would flip a
            # unit that reads `ready` to `offline` the moment the env vars are unset, which
            # is not what a visitor is being told here. The merge is available and is a
            # separate decision.
            # THE REINFORCE ROW IS GONE FROM HERE AND ITS READING IS NOT. It was folded into
            # `studio` on 2026-08-29, the same way `gateway` was folded into `miner` on
            # 2026-08-22 -- the row stops being a top-level unit, the `id` does not change,
            # and the reading moves onto a `SubUnit` so nothing that reads `/api/status`
            # loses it. The state above is still computed, at `train_state` below, and is
            # still computed from `adapter_applies()` rather than from `reinforce.status()`
            # for the reason this comment already gave.
            #
            # Why: `apps/studio/plugins/reinforce/` is a Studio plugin in the code and always
            # has been -- `/api/train/*` is served by
            # `studio.plugins.reinforce.routes`. A top-level rack row presented it as an
            # independent runtime peer of Studio, which is a claim the implementation does
            # not make anywhere. `docs/specs/symoneural-live-stack.md` §4 called this fold
            # "target architecture; may stay separately addressable during transition"; the
            # transition is over and the separate address survives it, because
            # `/reinforce.html` still answers and the child still carries the id `train`.
            # ONE miner on the rack, two kinds of mining hardware under it.
            #
            # These were two rows until 2026-08-17: "SyMoNeuRaL Miner", OFFLINE on the ASIC
            # bus with no rig attached, and "SyMoNeuRaL Miner GPU", READY and the only one
            # that has ever hashed. The clean product name sat on the dead row while the
            # working one wore a qualifier, which reads as one surface that is half broken.
            # Garrett's call was to merge them, on the condition that both halves have
            # working parts.
            # Verified before merging, on this box and not in a worktree: the GPU half has
            # hashed (52.3 - 53.2 MH/s measured across four runs), and the ASIC half has
            # its venv and probe installed, 20 real firmware packages on disk, both QEMU
            # binaries present and 42 green tests. It is switched off, not broken.
            #
            # The merge does NOT flatten the two states into one, because that is where a
            # merged row would start lying: the halves fail independently and one of them
            # can be hashing while the other has no rig attached. The row carries the
            # headline; `sub` carries both readings, and /miner.html gives each its own
            # card. `bus` is `gpu` because that is the only mining hardware physically in
            # this box -- the ASIC half is remote by definition, and claiming an ASIC bus
            # on a machine with no rig attached was always the overstatement.
            Unit(id="miner", label="SyMoNeuRaL Miner", slot="6U",
                 state=miner_state, bus="gpu", href="/miner.html",
                 spec="KawPow on the RTX 5070 Ti · Antminer + MicroBT ops · TRON USDT licensing",
                 detail=miner_detail,
                 sub=[SubUnit(id="gpuminer", label="GPU · Ravencoin",
                              state=gpuminer_state, bus="gpu", detail=gpuminer_detail),
                      SubUnit(id="asicminer", label="ASIC · Antminer + MicroBT",
                              state=asic_state, bus="asic", detail=asic_detail),
                      # Folded from its own 1U row on 2026-08-22 -- see the comment further
                      # down, where the rack count is kept. `bus` is `net` and not `gpu`:
                      # this half settles licences on TRON and never touches the card, and
                      # claiming a GPU bus for it would be the same overstatement the ASIC
                      # half's comment above rejects. Its `id` is unchanged so that
                      # `/gateway.html`, which reads its own state out of `/api/status`,
                      # keeps finding it -- that page searches `sub` as well as `units`.
                      SubUnit(id="gateway", label="Gateway · TRON USDT licensing",
                              state=gateway_state, bus="net", detail=gateway_detail)]),
            # Stream copy, not transcode: the work is network I/O and muxing, so it never
            # contends for the card. `ready` is honest here -- unlike the mining surfaces
            # this one is functional right now; it holds no content of its own because the
            # visitor supplies the playlist and nothing is stored on the box.
            Unit(**{**streamer.status(), "bus": "net"}),
            # The developer surface. It appears on the rack as a peer because Garrett asked
            # for it there -- "it will be symoneural coder and in the live stack just like
            # the other agents" -- and it holds no weights and takes no GPU lease. `bus="cpu"`
            # is the honest bus: it is file I/O and subprocesses.
            #
            # This comment used to end *"and deliberately has NO HTTP route"*, and the href
            # beside it was `/documentation.html` -- the one surface whose entire point is
            # that you can use it handing the visitor a manual instead. #87 gave it a page.
            #
            # WHAT DID NOT CHANGE is the conclusion recorded in HANDOVER §2g, because it was
            # about `/api/`, not about routes in general: an agent that can develop the site
            # is arbitrary code execution on the box serving the public internet, and
            # `ops/Caddyfile` delegates the whole `/api/*` subtree, so an `/api/coder/...`
            # route would be publicly reachable the instant it existed. There is still no
            # such route and there must not be one. The page reads from `/local/coder/*`,
            # which Caddy does not delegate and `_require_local` refuses off-box anyway, and
            # that mount is read-only -- see its banner further down this file.
            # `/livestack/coder`, not `/live-stack/coder`. The hyphenated form is R-160's
            # spelling and led until 2026-08-22, when Garrett asked for one published
            # address: *"we need to get rid of live-stack i believe its only livestack"*.
            # Both routes still answer and neither redirects -- what changed is which one
            # this site puts in front of a person. NOT because a bookmark would break: this
            # surface reads from `/local/coder/*`, which is refused off-box, so there is no
            # public audience holding the old address, and he said so directly. The routes
            # stay because R-160, `apps/coder/SMOKE-surface.md` and #81's title still name
            # that spelling, so a reader of those will type it.
            # `apps/test_deploy_routes.py` asserts nothing published carries the hyphen.
            Unit(id="coder", label="SyMoNeuRaL Coder", slot="1U",
                 state=coder_state, bus="cpu", href="/livestack/coder",
                 spec="local workspace agent · reads over /local, never /api",
                 detail=coder_detail),
            # GUIDE IS NOT A UNIT ANY MORE -- it is folded into the Streamer above, and this
            # comment is the record of why rather than a leftover.
            #
            # Garrett: "symon guide and symon tuner should be migrated together", then "you
            # need to migrate tuner and guide to be 1". The two units had the SAME `href`
            # (/tuner.html), so the rack was showing one page twice and disagreeing with
            # itself about how many things this box runs.
            #
            # The reversal is the interesting part: Guide's own author argued for exactly
            # this fold on architecture -- it owns no weights and no hardware -- and was
            # overruled only because Garrett had named it separately in the live stack. He
            # has now decided the other way, so the code and the intent finally agree.
            #
            # Nothing is dropped. `streamer.guide` is untouched, `/api/streamer/guide/*`
            # still serves the page's filter, and the claim that made Guide worth showing --
            # that it answers on the CPU while the card is busy, never taking the GPU lock --
            # is now in the Streamer unit's own detail line. See
            # `apps/streamer/routes.py::status()`.
            #
            # GATEWAY IS NOT A UNIT ANY MORE either -- it is a third `sub` of the Miner
            # above, folded 2026-08-22. Garrett: *"gateway is a miner app so it can merge
            # into miner"*. Same move as Guide into Streamer and for a related reason: it
            # was a 1U tile whose LED had never been anything but grey, because there is no
            # contract, no wallet and no key material, and it was taking a rack slot to say
            # so. The Miner row already exists to carry halves that fail independently, and
            # a licensing surface that is switched off is exactly that shape.
            #
            # WHAT WAS NOT DONE, on purpose: `backend/gateway/` did not move. It is
            # thirteen modules of TRON settlement -- chain, abi, keccak, entitlement,
            # verify, store -- and putting payment code inside a mining package would be a
            # rename dressed as an architecture. The fold is a rack decision, not a code
            # one, and `/gateway.html` still answers and still owns the surface.
            #
            # The rack is therefore TWELVE units, in the order they are built below:
            # chat, image, remix, ravencalc, miner, streamer, coder, project, sigils,
            # studio, live, dispatchos. Eleven before `studio` and `exp` landed alongside
            # their pages -- and this comment said TWELVE for the change that added both,
            # because a number kept only in prose drifts. `apps/test_status_rack.py` now
            # counts the `Unit(...)` calls in this function with an AST walk, so the next
            # mistake is a test failure and not a sentence.
            #
            # It drifted again anyway, in the other direction, and the AST walk is what
            # caught it: `dispatchos` was added as a row and this comment, `ROSTER.md`,
            # `EXPECTED` and the roster reconciliation were all left saying thirteen. Six
            # tests were red on that count before 2026-08-29. The number here is now the
            # post-fold one -- fourteen rows minus `train` and `exp`, which became children
            # of `studio` above, plus `dispatchos`, which was always being built and was
            # only ever missing from the places that describe the rack.
            #
            # `tests/frontend.mjs` does NOT guard the count, deliberately: it asserts the
            # invariant that no two tiles claim the same page and the same bus (see the comment
            # at frontend.mjs:97), which survives the rack growing. `units.length >= 5` is all
            # it says about the number.
            #
            # The shared workspace. Like Coder it has no page yet, so it links to the
            # documentation rather than to a 404; unlike Coder it DOES carry a route,
            # because it stores nothing executable -- it is SQLite and text.
            Unit(**project.status()),
            # Stickers. Its own unit rather than a mode of Image, because it takes the
            # card under its own governor name and the rack's "who holds it" readout keys
            # off that name -- folding them would make one of the two invisible in exactly
            # the display this site exists to be honest about.
            Unit(**sigils.status()),
            # The Studio. Reports `offline` until both switches are set -- it can write to
            # the host, so it is off by default -- and never `busy`: it orchestrates work
            # that other rows already report. A second row lighting up for somebody else's
            # job would be a decorative indicator, which this rack does not have.
            #
            # THE STUDIO FAMILY: one row, two children, three surfaces.
            #
            # `sub` carries Reinforce and Exp. They are children in the code and were peers
            # only on the rack: `/api/train/*` is `studio.plugins.reinforce.routes` and
            # `/api/exp/*` is `studio.plugins.exp.routes`, both mounted from inside the
            # Studio package. A flat rack presented two Studio plugins as independent
            # runtimes, which is the "do not invent a runtime merely because an application
            # has a separate page" failure with the invention already shipped.
            #
            # THE IDS DO NOT CHANGE, and that is load-bearing rather than tidy. `train` is
            # read by `site/reinforce.html`, by the governor's holder name, and by
            # `apps/controlboard`'s exclusion list; `exp` is read by `/exp.html`. Both pages
            # search `sub` as well as `units`, exactly as `/gateway.html` does since its own
            # fold, so a folded child still finds its reading and never renders
            # "not present". `apps/test_status_rack.py::FOLDED` asserts both halves of that
            # for all four folds now: not a row, and not deleted either.
            #
            # `bus` per child, not inherited: Reinforce takes the card under the governor and
            # is `gpu`; Exp mounts plugin manifests and is `cpu`. Averaging them onto the
            # parent would be the same overstatement the miner row's ASIC half rejects.
            Unit(**{**studio.status(), "sub": [
                SubUnit(id="train", label="Reinforce · adapter training",
                        state=train_state, bus="gpu", detail=train_detail),
                # `queued` until the first request to /api/exp mounts the default preset,
                # `ready` after -- and never a state that describes what it is *about* to
                # mount, which would be reporting intent as a reading. There is no
                # `degraded` in SubUnit.state, so a failed plugin is counted at the front of
                # `detail` rather than dropped.
                SubUnit(id="exp", label="Exp · experience plugins",
                        state=exp_row["state"], bus=exp_row["bus"],
                        detail=exp_row["detail"]),
            ]}),
            # SyMoNeuRaL Live. `busy` while a playlist is growing on disk and never from an
            # obs-websocket frame -- `apps/live/routes.py::status()` has the argument, and it
            # is the same one `studio` above makes for refusing to go `busy`. `bus="net"`
            # rather than `gpu` is deliberate and is a claim about the GOVERNOR: OBS's NVENC
            # session is held outside `gpu-governor.sh`, which cannot see it and does not
            # count it against the drain floor, so putting this row in the rack's "who holds
            # the card" readout would advertise management that does not exist.
            Unit(**live.status()),
            # SyMoNeuRaL DispatchOS. `bus="cpu"` because it is: booking, quoting and
            # dispatching are reads and writes to a small SQLite store, and no code path in
            # that package takes a governor lease. Its one model call goes out through
            # `guide_ask_model`, which refuses to start the card -- so this row can never be
            # the reason `holding` names something. The state READS the switch rather than
            # asserting one: `offline` when SYMONEURAL_DISPATCHOS_ENABLED is unset, which is
            # what miner, coder, gateway and studio already do and what #95 exists to settle
            # for the one row that does not.
            Unit(**dispatchos.status()),
        ])),
        gpu=GpuState(
            name="RTX 5070 Ti", vram_free_mib=free, vram_total_mib=total,
            vram_used_pct=round(100 * (1 - free / total)) if free and total else None,
            power_w=telemetry.smi("power.draw"), temp_c=telemetry.smi("temperature.gpu"),
            holder=holder, queued=gpu.waiting,
            driver=driver_state, driver_detail=driver_detail or None,
        ),
        link={"gen": 3, "width": 8, "note": "Gen 3 x8 -- host capped"},
    )


def semantic_etag(body: dict) -> str:
    """Hash what a caller actually cares about, not every drifting sensor.

    Hashing the whole payload produced a tag that changed on every single request, because
    power draw and temperature never hold still -- 37.9 W becomes 38.1 W and the cache is
    busted for a difference nobody is waiting on. The result was an ETag that cost a hash
    and saved nothing, which is worse than having none at all.

    So the tag covers the semantic state: which units exist, what state each is in, who
    holds the card, how deep the queue is, and VRAM rounded to the nearest 256 MiB. While
    the machine is genuinely idle -- which is most of the time -- this is stable and every
    poll costs a bare 304 instead of the full body. Telemetry still rides along in the body
    for anyone who fetches it; it just does not get a vote on freshness.
    """
    gpu_body = body.get("gpu") or {}
    free = gpu_body.get("vram_free_mib")
    stable = {
        "units": [(u["id"], u["state"]) for u in body.get("units", [])],
        "holder": gpu_body.get("holder"),
        "queued": gpu_body.get("queued"),
        "vram_bucket": round(free / 256) if isinstance(free, int) else None,
    }
    return hashlib.sha1(
        json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]


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


async def ws_calc(ws: WebSocket, msg: dict) -> None:
    try:
        body = CalcRequest(**{k: v for k, v in msg.items() if k != "t"})
    except Exception as exc:
        await ws.send_text(json.dumps({"t": "error", "code": 422, "error": str(exc)[:300]}))
        return
    try:
        from ravencalc.apps import ravencalc
    except ImportError:
        await ws.send_text(json.dumps({"t": "error", "code": 503,
                                       "error": "RavenCalc is unavailable."}))
        return
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
        await ws.send_text(json.dumps({"t": "error", "code": 400, "error": exc.message}))
        return
    result["seconds"] = round(time.time() - started, 4)
    await ws.send_text(json.dumps({"t": "calc.result", **json.loads(json.dumps(result, default=str))},
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








async def calc(body: CalcRequest,
                _: Annotated[None, Depends(throttled_for("ravencalc"))]) -> dict:
    """Exact symbolic mathematics. No GPU, no lock, no queue.

    Returns a `ravencalc/result/v1` document. Note `check`: where verification is cheap the
    engine does it -- an antiderivative is differentiated back and simplified against zero --
    and `check.passed` is three-valued. `null` means the check could not confirm the result,
    which is reported rather than rounded up to success.
    """
    try:
        from ravencalc.apps import ravencalc
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

OPERATOR_HEADER = "X-Symoneural-Token"
OPERATOR_HEADER_LEGACY = "X-Sym-Token"


def _operator_token(request: Request) -> str | None:
    """The operator token off the request, new header name first, then the one it replaced.

    The legacy name is read because the senders are cached JavaScript. `site/miner.html` and
    `site/console.js` are served with a cache-busting query string, but the HTML that
    references them is not immutable, and a browser holding yesterday's copy sends the old
    header until it turns over. Renaming only this side would answer 401 to an operator whose
    token is correct, which is the failure mode hardest to diagnose from the browser end.

    `request.headers` is case-insensitive (Starlette normalises), so one spelling of each name
    is enough here -- unlike the gate modules, which are handed plain dicts by their tests.

    The 401 below names only the new header. A caller sending the legacy one was accepted, so
    naming both in the error would describe a rejection that did not happen for that reason.
    """
    return (request.headers.get(OPERATOR_HEADER)
            or request.headers.get(OPERATOR_HEADER_LEGACY))


def _asic_auth(request: Request) -> None:
    if not asicminer.enabled():
        raise HTTPException(503, "the miner surface is disabled on this installation")
    if not asicminer.token_ok(_operator_token(request)):
        raise HTTPException(401, f"bad or missing {OPERATOR_HEADER}")


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

def _miner_auth(request: Request) -> None:
    if not cryptominer.enabled():
        raise HTTPException(503, "the GPU miner surface is disabled on this installation")
    if not cryptominer.token_ok(_operator_token(request)):
        raise HTTPException(401, f"bad or missing {OPERATOR_HEADER}")


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
    _asic_auth=_asic_auth,
    _miner_auth=_miner_auth,
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
# Off unless SYMONEURAL_VOICE_ENABLED=1 and SYMONEURAL_VOICE_TOKEN are both set; see apps/voice/__init__.py.
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
# Reads are open, mutations need SYMONEURAL_EXP_ENABLED=1 and SYMONEURAL_EXP_TOKEN. The split is narrower
# than studio's and deliberate: the whole argument for this surface is that what is mounted,
# in what state, and waiting on what is inspectable, and a plugin table behind a secret is a
# plugin table nobody reads. One thing is withheld from a tokenless caller -- each entry's
# `config`, which is where a plugin's credentials would live.
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
STUDIO_REGISTRY_FILE = RUN / "registry.json"

# Only these keys survive a read, and each is checked against the type it must be. Re-validated
# even though `tools/build/build_registry.py` wrote it, exactly as `apps/studio/plugins/reinforce/jobs.py` re-validates
# `progress.json`: `run/` is world-readable state on a box that also runs a web server, and
# trusting a field because we wrote it is how a validated field silently becomes an unvalidated
# one the next time somebody edits the writer.
#
# `path` is deliberately NOT in this list, even though the file carries it. Caddy delegates the
# whole `/api/*` subtree publicly and this route has no surface flag in front of it, so the
# response is world-readable; the row in the file reads
# `backend/models/hf/hub/models--Qwen--Qwen2.5-7B-Instruct/snapshots/<hash>`, which is this
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


def _studio_rows(raw: object) -> list[dict]:
    """Keep the rows that are shaped like rows, drop everything else without comment.

    A row must at least name itself; anything without a string `id` is not a model and is not
    reported as one. Absent and wrong-typed fields become `None` rather than being omitted, so
    the client decodes one stable shape whether or not the writer has caught up with this list.
    """
    if not isinstance(raw, list):
        return []
    out = []
    for row in raw:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            continue
        clean: dict = {}
        for key, want in _STUDIO_FIELDS.items():
            val = row.get(key)
            # `bool` is a subclass of `int` in Python, so an unguarded isinstance(True, int)
            # would let `present: true` through as a byte count.
            if want is not bool and isinstance(val, bool):
                val = None
            clean[key] = val if isinstance(val, want) else None
        out.append(clean)
    return out




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
SECTION_PAGES = {
    "overview": "overview.html",
    "livestack": "livestack.html",
    "controlboard": "controlboard.html",
    "receipts": "receipts.html",
}


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
LIVESTACK_PAGES = {
    "image": "image.html",
}


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
LOCAL_ONLY = ("127.0.0.1", "::1", "localhost")

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
_PROXY_HEADERS = (
    "forwarded",                # RFC 7239
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",        # Caddy sets this on everything it proxies
    "x-forwarded-port",
    "x-real-ip",
    "via",                      # RFC 9110; any conforming proxy appends it
)


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


def _coder_token() -> str | None:
    """The one variable, by name.

    `os.environ.get`, never a sweep -- R-174: *"do not read a whole process environment to
    answer a narrow question."*
    """
    return os.environ.get("SYMONEURAL_CODER_TOKEN")


def _coder_read(request: Request, fn, **kw) -> JSONResponse:
    """Run one `coder` read as this box and hand its own dict back verbatim.

    `coder` reports a refusal as `{"ok": false, "error": ...}` under a 200, and that shape is
    preserved rather than translated into an HTTP status. The page has to render a refusal as
    an instrument reading -- *which gate said no* -- and an HTTP error code puts that sentence
    where `fetch()` makes it awkward to read and where an intermediary is free to replace it
    with its own. The transport succeeded; the answer is "no", and those are different facts.

    The peer is the real one off the socket, not a literal: `_require_local` has already
    established it is loopback, and passing what was actually observed means `coder`'s own
    gate is evaluating the same thing this route evaluated.
    """
    _require_local(request)
    peer = request.client.host if request.client else ""
    return JSONResponse(fn(token=_coder_token(), peer=peer, **kw),
                        headers={"Cache-Control": "no-store"})













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
_RETIRED_PAGES = {"/tuner.html": "/streamer.html",
                  "/tuner-watch.html": "/streamer-watch.html"}




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
from coders.router import router as _coders_router  # noqa: E402



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
    _coder_read=_coder_read,
    _coder_token=_coder_token,
    _require_local=_require_local,
    _studio_rows=_studio_rows,
)
_require(*['API_REFERENCE_SCRIPT', 'API_REFERENCE_STYLE', 'CHAT_MODEL', 'ChatRequest', 'DIFFUSE_ENGINE', 'DISCONNECT_POLL_S', 'DOCS_HEADER', 'EmuBody', 'FLUX', 'ImageRequest', 'ImageResult', 'IntakeSet', 'LIMITS', 'MAX_PROMPT_CHARS', 'MinerBody', 'QUEUE_DEPTH', 'RENDERS', 'ROOT', 'RemixRequest', 'RemixResult', 'SITE', 'STUDIO_REGISTRY_FILE', 'SYSTEM_PROMPT', 'ScanBody', 'Status', 'TaskNote', 'Track', '_RETIRED_PAGES', '_application_docs_index', '_asic_auth', '_coder_read', '_coder_token', '_miner_auth', '_require_local', '_studio_rows', 'adapter_applies', 'anticipate', 'build_status', 'bus', 'chat_deltas', 'check_rate', 'client_key_ws', 'denied', 'exact_context', 'gpu', 'log', 'prune_gallery', 'run', 'semantic_etag', 'start_llama', 'stop_llama', 'throttled_for', 'ws_calc', 'ws_chat', 'ws_remix'])


# Component routers. Paths in these are absolute, so no prefix.
from asicminer.router import router as asicminer_router  # noqa: E402
from chat.router import router as chat_router  # noqa: E402
from coders.root import router as coders_root  # noqa: E402
from cryptominer.router import router as cryptominer_router  # noqa: E402
from dispatchos.root import router as dispatchos_root  # noqa: E402
from docs.router import router as docs_router  # noqa: E402
from exp.root import router as exp_root  # noqa: E402
from home.router import router as home_router  # noqa: E402
from image.router import router as image_router  # noqa: E402
from live.root import router as live_root  # noqa: E402
from local.router import router as local_router  # noqa: E402
from remix.root import router as remix_root  # noqa: E402
from retired.router import router as retired_router  # noqa: E402
from status.router import router as status_router  # noqa: E402
from studio.root import router as studio_root  # noqa: E402

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
