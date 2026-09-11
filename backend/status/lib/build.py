"""Lifted from server.py, 2026-09-11.

Runtime objects come off `core.context.ctx`; importing server would be a cycle.
"""
from __future__ import annotations
from core.config import CHAT_MODEL, CHAT_MODEL_LABEL, DELEGATE_POLL_S, DELEGATE_STALE_S, DIFFUSE_ENGINE, FLUX, LLM_ENGINE

import asyncio
import hashlib
import json
import time
from typing import Annotated, Literal
from pydantic import BaseModel, Field
from hardware.lib import telemetry
import asicminer  # noqa: E402
import cryptominer  # noqa: E402  -- the GPU miner. A DIFFERENT surface from asicminer:
import coder      # noqa: E402  -- local-only developer surface. Takes NO GPU lease and
import gateway    # noqa: E402  -- TRON licensing surface, see backend/gateway/
import licensing  # noqa: E402  -- contract keys and the dev-fee disclosure
from registry.lib import ports  # noqa: E402
import httpx  # noqa: E402  -- only for polling a delegated surface's /healthz; see poll_delegated
import streamer  # noqa: E402  -- the IPTV surface AND the Guide that filters
import project  # noqa: E402  -- the shared workspace surface. Brings its
from streamer import guide  # noqa: E402  -- the library half: matching, clustering,
import sigils  # noqa: E402  -- the sticker surface. Bound to the package for
from studio.plugins import reinforce  # noqa: E402  -- the training bay. Bound to the package so its
import studio  # noqa: E402  -- the local agent and the
from studio.plugins import exp  # noqa: E402  -- the plugin runtime. Bound to an
import live  # noqa: E402  -- his OBS stream, watchable while it runs and after it
import dispatchos  # noqa: E402  -- the transport dispatch application for a named

from core.context import ctx


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
            ctx.log.exception("delegated poll hiccup")
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
        ctx.log.exception("port registry unreadable; reporting in-process state")
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
    holder = ctx.gpu.current or ctx.external_holder()
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
        # line has to say which. `driver_detail` on ctx.GpuState carries the reason.
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
    asic_state, asic_detail = asicminer.unit_state(ctx._asic_cache.get())
    # The CACHED reading, never a live fetch: see the refresher above. `unit_state`
    # with no argument would go to the network on the status path.
    gateway_state, gateway_detail = gateway.unit_state(gateway.CACHE.get())
    # Cheap: reads a pidfile and, only when a miner is actually running, tails its ctx.log.
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
    # to stay a reading of `ctx.adapter_applies()` and the governor holder -- see the long note
    # at the fold site further down. Splatting `reinforce.status()` over it would assert a
    # different true thing (whether the HTTP surface accepts work) in place of this one
    # (whether an adapter is loaded), which is the merge that comment refuses.
    train_state = ("busy" if holder == "train"
                   else ("ready" if ctx.adapter_applies() else "offline"))
    train_detail = ("fine-tune in progress — serving surfaces queue" if holder == "train"
                    else ("adapter loaded · for model/adapter tuning"
                          if ctx.adapter_applies() else "no adapter built"))
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
                 spec=CHAT_MODEL_LABEL + (" + persona adapter" if ctx.adapter_applies()
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
            # backend/studio/docs/qlora-upgrade.md, which is a spec and not a description of state.
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
            # `state` is still read from ctx.adapter_applies() and NOT from
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
            # still computed from `ctx.adapter_applies()` rather than from `reinforce.status()`
            # for the reason this comment already gave.
            #
            # Why: `apps/studio/plugins/reinforce/` is a Studio plugin in the code and always
            # has been -- `/api/train/*` is served by
            # `studio.plugins.reinforce.routes`. A top-level rack row presented it as an
            # independent runtime peer of Studio, which is a claim the implementation does
            # not make anywhere. `backend/live/docs/symoneural-live-stack.md` §4 called this fold
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
            # card. `bus` is `ctx.gpu` because that is the only mining hardware physically in
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
                      # down, where the rack count is kept. `bus` is `net` and not `ctx.gpu`:
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
            # is `ctx.gpu`; Exp mounts plugin manifests and is `cpu`. Averaging them onto the
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
            # rather than `ctx.gpu` is deliberate and is a claim about the GOVERNOR: OBS's NVENC
            # session is held outside `ctx.gpu-governor.sh`, which cannot see it and does not
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
            holder=holder, queued=ctx.gpu.waiting,
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
