"""SyMoNeuRaL Reinforce -- the HTTP surface, mounted at `/api/train` by `backend/server.py`.

That is true as of the `include_router` call beside the `tuner` one, and it had to be *made*
true: an earlier revision of this line asserted the mount while `backend/server.py` contained no
reference to this package at all, so every route here was unreachable and the docstring said
otherwise. Verified rather than assumed -- with the gate shut every route answers 503, and with
it open `/presets` answers 200.

Nothing here assumes that prefix, the way `apps/streamer` does not assume its own. Mounting is
necessary to reach these routes and **not** sufficient to start a run -- the gate below is what
decides that, and it is shut by default.

## Why this is an APIRouter and not a second server

`.claude/CLAUDE.md` fixes the architecture: **FastAPI does all the routing**, and `api.py`
mounts `site/` at `/` last so it never shadows an API route. The Reinforce engine in the
sibling `symoneural/` package ships its own FastAPI app on port 8000; that is precisely what
must NOT be reused here. A second origin breaks `console.js`, which opens a WebSocket and
falls back to polling, and neither survives a split origin.

## The gate, which is now one switch -- and what happened to the second one

A training route is long-running, takes the whole GPU, and is **never evicted** -- the
governor refuses to evict `train` on purpose. A world-callable one is therefore a rack-wide
denial of service that costs a single HTTP request: one POST takes chat, image and remix
offline for the duration of a fine-tune. So:

    SYMONEURAL_REINFORCE_ENABLED=1              # the surface exists at all

**There used to be a second requirement, `SYMONEURAL_REINFORCE_TOKEN`, and it was removed on
2026-09-11 by owner decision: "no api keys period -- everything is straight post get fetch".**
The paragraph above is still the reason this surface is off by default, and that has not
changed. What changed is what stands between a caller and the card: the switch, and the fact
that this box is not reachable from the internet. The phrase "open to the internet" in the
503 detail describes the hazard the switch exists for, not a network this machine is on.

Off unless the switch is set. With it unset every route answers 503 and the rack unit reads
`offline` with the switch named in its detail line -- an honest reading of a surface that
genuinely cannot accept work.

Once the surface is enabled, reads (`/models`, `/presets`, `/status`) and writes (`/start`,
`/stop`) are equally reachable. The reads publish only what the site already publishes --
weight file sizes, quantisations, parameter arithmetic, the preset table. That is the repo's
own line: publish the numbers, keep the methods.

## What this surface does NOT do

* **It does not fetch models.** A row for a model that is not on disk states its download size
  and stops there. A 27.5 GiB transfer kicked off from an HTTP handler is not a route, it is
  an incident.
* **It does not serve a log file, a dataset, or an adapter.** `/status` is built from an
  allowlist of known-shaped runner output; the raw log is on disk for an operator with shell
  access and has no URL.
* **It does not promote a run to the serving adapter.** The trainer emits PEFT safetensors and
  the chat surface loads a GGUF adapter. Reporting "trained" while chat still runs the old
  adapter would be a dishonest status, so the conversion stays a deliberate manual step and
  the manifest says so.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from . import dataset_guard, enabled, jobs, presets, registry, rewards, rollout

router = APIRouter(tags=["reinforce"])


def _require_surface() -> None:
    if not enabled():
        raise HTTPException(
            status_code=503,
            detail=("SyMoNeuRaL Reinforce is off. Set SYMONEURAL_REINFORCE_ENABLED=1 to "
                    "enable it. It is off by default because a "
                    "never-evicted GPU route open to the internet takes the whole rack "
                    "offline for one request."))


def _require_token(token: str | None) -> None:
    """Checks the surface switch and nothing else. There is no token on this box.

    NO API KEYS. Owner decision, 2026-09-11: "no api keys period -- everything is straight
    post get fetch". The name is kept so the four call sites below are untouched, and so the
    one thing this function still does is stated where it is done.

    What used to guard this route was a constant-time token compare, and the reason given for
    it was real: this route authorises taking the whole card. **That protection has not been
    deleted, it has moved to the switch and the network.** `SYMONEURAL_REINFORCE_ENABLED` is
    off by default, and the box is not reachable from the internet. A token in front of a
    surface that only loopback can reach was protecting the owner from the owner.
    """
    _require_surface()


class StartBody(BaseModel):
    # `extra="ignore"` and a default for every field, for the reason `apps/streamer` documents: a
    # *missing* required field makes pydantic raise a ValidationError whose `input` is the whole
    # request body, and FastAPI serialises that into the 422 response. On this surface the body
    # carries a dataset path, so an echoed body is a path disclosure. With defaults there is no
    # validation path that can touch these values and the handler checks them by hand.
    model_config = ConfigDict(extra="ignore")
    model: str = ""
    preset: str = ""
    dataset: str = ""
    # The starting adapter, read-only. There is deliberately no `method` field here: a method is
    # a property of the preset, not an independent choice, so a body cannot pair
    # `preset="voice"` with `method="reinforcement"` and produce a configuration whose dataset
    # schema and hyperparameters contradict each other.
    init_adapter: str = ""


# ---------------------------------------------------------------- reads


@router.get("/models")
def list_models() -> dict:
    """The model picker: everything on this box, qualified, with the arithmetic.

    Rejected rows are included with a reason. Three of the four largest model files here are
    GGUF and none of them can be trained; hiding them would make the picker look broken to an
    operator who has just watched the chat surface serve one.
    """
    _require_surface()
    free, free_label = registry.free_vram_bytes()
    return {
        "models": [e.to_dict() for e in registry.catalogue()],
        "free_vram_bytes": free,
        "free_vram_label": free_label,
        "budget_bytes": registry.PRACTICAL_BUDGET_BYTES,
        "budget_label": "projected",
        "budget_note": ("~14.2 GiB is what is free in practice on a 15.92 GiB card. Budgeting "
                        "against the nameplate is how a run OOMs at step 0."),
        "fetch_note": ("rows with present=false are not fetched and there is no fetch button. "
                       "The download size is stated so the choice is informed."),
    }


@router.get("/presets")
def list_presets(model: str = "Qwen/Qwen2.5-7B-Instruct") -> dict:
    """The predetermined tuning methods, each costed against a chosen base model."""
    _require_surface()
    free, free_label = registry.free_vram_bytes()
    return {
        "presets": [p.to_dict() for p in presets.PRESETS.values()],
        "shared": presets.SHARED,
        "fit": presets.fit_table(model, free_bytes=free),
        "free_vram_label": free_label,
        "measured_peaks": jobs.measured_peaks(),
        "not_offered": presets.NOT_IN_V1,
        # The three objectives, the schema each needs, and which one is actually RL.
        "methods": presets.METHODS,
        "schemas": dataset_guard.SCHEMAS,
        # The reward table: names, rationale, provenance and weight. Never the patterns -- see
        # `rewards.py`. Availability here is unresolved because no dataset is named on this
        # route; `/preflight` resolves it against the chosen file's columns.
        "rewards": rewards.offered(),
        "rollout": rollout.describe(),
        "rl_note": ("nothing about the preference or reinforcement methods has been measured on "
                    "this box. Their VRAM terms are arithmetic derived from the trl source with "
                    "the source lines cited, and their error bar is wider than the supervised "
                    "model's, which has one real run behind it. No quality claim is made for any "
                    "method, and a reward curve is a reading of a reward function rather than of "
                    "the model."),
        "labels": {
            "measured": "read off this machine",
            "vendor": "a published specification from somebody else",
            "projected": "arithmetic, not a result",
        },
        "note": ("every VRAM figure here is projected until a run of that exact model and "
                 "preset records a real peak. Nothing about training quality or throughput has "
                 "been measured on this box, so no preset carries a quality claim."),
    }


@router.get("/datasets")
def list_datasets(schema: str = "") -> dict:
    """Datasets an operator has staged. Never anything from `training/`.

    This route exists as much to state the refusal as to list anything. See `dataset_guard.py`:
    `training/corpus.jsonl` and `training/build_dataset.py` are trade secret, and the obvious
    implementation of a dataset picker -- glob the sibling directory -- would publish the
    product's recipe.
    """
    _require_surface()
    if schema and schema not in dataset_guard.SCHEMAS:
        raise HTTPException(status_code=400, detail={
            "reason": "unknown_schema",
            "message": f"No such dataset schema. Available: "
                       f"{', '.join(dataset_guard.SCHEMAS)}."})
    return {
        "datasets": [d.to_dict() for d in dataset_guard.staged(schema or None)],
        "schemas": dataset_guard.SCHEMAS,
        "filtered_by": schema or None,
        "schema_note": ("each staged file is sniffed for its schema rather than assumed to be "
                        "chat examples, and `?schema=` filters to the ones a given method can "
                        "use. Offering a file that preflight will refuse is the same class of "
                        "dishonesty as a control that cannot be clicked. Sniffing reads at most "
                        "five rows and reports the SHAPE it matched -- never a row."),
        "stage_dir": str(dataset_guard.STAGE.relative_to(registry.ROOT)),
        "default": None,
        "policy": ("There is no default dataset and no fallback. Protected SyMoNeuRaL "
                   "artefacts are refused by resolved path and are never listed, previewed, "
                   "counted or served. No response from this surface -- including an error -- "
                   "contains a line of dataset content."),
    }


@router.get("/status")
def run_status() -> dict:
    """The current run, or an honest statement that there is not one."""
    _require_surface()
    return jobs.snapshot()


@router.post("/preflight")
def run_preflight(body: StartBody) -> dict:
    """Cost the run before a single weight is read.

    A configuration that does not fit returns **501, not 500**. That is Reinforce's
    `CapabilityWaived` semantics: picking a 14B at sequence 2048 on this card is a capability
    this box does not have, not a fault, and answering 500 would make "cannot run here"
    masquerade as "broken". The arithmetic comes back in the body either way, because a refusal
    without its sum is indistinguishable from a bug.
    """
    _require_surface()
    result = jobs.preflight(body.model, body.preset, body.dataset, body.init_adapter)
    if not result["ok"] and result.get("reason") == "capability":
        # Reached by two things now, and both are genuinely "this box cannot" rather than "this
        # is broken": a configuration whose projected peak does not fit, and a reinforcement
        # preset whose rollout backend is not reachable. An unreachable external vLLM server is
        # not a fault of this API's.
        raise HTTPException(status_code=501, detail=result)
    return result


# ---------------------------------------------------------------- writes


@router.post("/start")
def start_run(body: StartBody, x_reinforce_token: str | None = Header(default=None)) -> dict:
    """Start a fine-tune. Token required.

    **Starting a run takes the whole rack offline for its duration.** The governor never evicts
    `train`, so chat, image and remix queue behind it until it finishes or is stopped
    deliberately. That is architectural, not a limitation to engineer away, and the page says
    it next to the button.
    """
    _require_token(x_reinforce_token)
    try:
        job = jobs.start(body.model, body.preset, body.dataset, body.init_adapter)
    except dataset_guard.Refused as exc:
        raise HTTPException(status_code=400, detail={"reason": exc.code, "message": exc.message})
    except jobs.AdapterRefused as exc:
        raise HTTPException(status_code=400, detail={"reason": "init_adapter",
                                                    "message": str(exc)})
    except rewards.RewardError as exc:
        raise HTTPException(status_code=400, detail={"reason": "rewards", "message": str(exc)})
    except jobs.JobError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"started": True, "job": job,
            "warning": ("this run holds the GPU until it completes. Chat, image and remix will "
                        "queue behind it -- a training run is never evicted to serve a page.")}


@router.post("/stop")
def stop_run(x_reinforce_token: str | None = Header(default=None)) -> dict:
    """Stop a run deliberately. Token required.

    SIGTERM to the process group, so the governor's release trap runs and waits for VRAM to
    drain below the floor. A SIGKILL would return the lock before the CUDA context finished
    tearing down, and the next surface would allocate into memory that is still held.
    """
    _require_token(x_reinforce_token)
    return jobs.stop()


__all__ = ["router"]
