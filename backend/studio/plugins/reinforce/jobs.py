"""SyMoNeuRaL Reinforce -- job state, and the launch path onto the GPU.

## Real state, or the panel says there is no run

`.claude/CLAUDE.md`: *"No decorative status indicators. Every LED and gauge on the site
reflects a real reading."* That rule is why this module has no notion of a default job, no
placeholder progress and no simulated loss. `snapshot()` with nothing running returns
`state="none"` and the page says there is no run. A progress bar with no `total_steps` behind
it is precisely the dishonest pixel the rule exists to prevent.

Every number in a snapshot comes from one of three places, and each is labelled:

* `step`, `epoch`, `loss`, `val_loss`, `lr` -- printed by the runner from the trainer's own
  state. **measured.**
* `vram_peak_alloc_bytes`, `vram_peak_reserved_bytes` -- `torch.cuda.max_memory_allocated()`
  and `max_memory_reserved()` inside the training process. **measured**, and the only
  numbers on this surface that can retire a projection.
* `eta_s` -- elapsed divided by steps done, times steps left. **projected**, and labelled so
  in the payload, because it is arithmetic on a rate that is not constant.

## The GPU rule, which is the one that will bite

*"`train` is never evicted to serve a page view."* Three consequences are implemented here:

1. The run goes through `scripts/gpu-governor.sh with train -- ...`. The `with` form acquires,
   runs, and **always releases**, including on crash, via a trap. Nothing in this package ever
   calls `acquire` on its own, and nothing ever calls a bare `release` -- the release is the
   governor's, and it names its surface. An unscoped release once destroyed a running
   fine-tune's lock from the API's shutdown hook.
2. The child is started with **`start_new_session=True`**. This is not tidiness. `cmd_with`
   traps EXIT/INT/TERM to release the card; if the API were the process group leader, an API
   restart would fire that trap mid-run, hand the card to the next tenant while ~7 GiB of
   training state was still resident, and OOM it at step 0. A detached session means the run
   outlives the API, which is the correct relationship between a two-hour fine-tune and a web
   server.
3. Because the run outlives the API, **state lives in files under `run/`, not in memory**. A
   restarted API re-reads `job.json` and reports the run it did not start. `run/` is the right
   directory for this by the repo's own convention -- it holds the GPU mutex, the pidfile and
   the resident marker, and it is deliberately not called `logs/`.

## Log handling is an allowlist, and it has to be

The runner's stdout is the raw material for `/api/train/status`, and stdout from a training
process is not a trusted channel: a traceback out of the tokeniser can carry a training
example verbatim, and a training example is the trade secret this whole surface is most
likely to leak. A denylist -- "strip anything that looks like corpus text" -- cannot be
correct, because it has to anticipate every shape the data takes.

So the inversion: `parse_log()` **matches a small set of known-shaped lines and discards
everything else.** Unrecognised output is not sanitised, not truncated, not summarised -- it
is dropped on the floor. The raw log file is written under `run/` for an operator with shell
access, and **no route in this package serves it**. The runner cooperates by reporting errors
as an exception *class name* and a stage, never a message, for the same reason.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shlex
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass

from . import dataset_guard, presets, rewards, rollout
from . import registry
from .registry import GIB, ROOT

GOVERNOR = ROOT / "scripts" / "gpu-governor.sh"
TRAIN_PYTHON = ROOT / "training" / ".venv" / "bin" / "python"
RUNNER = pathlib.Path(__file__).resolve().parent / "runner.py"

JOBS_DIR = ROOT / "run" / "reinforce"
JOB_FILE = JOBS_DIR / "job.json"
PROGRESS_FILE = JOBS_DIR / "progress.json"
HOLDER_FILE = ROOT / "run" / "gpu.lock.d" / "holder"
MEASURED_FILE = JOBS_DIR / "measured-peaks.json"

# Where finished adapters land. NOT `training/adapter/` -- that directory holds the shipped
# adapter the chat surface serves, and an operator experiment must not overwrite it. Promoting
# a run to the serving adapter is a deliberate act, and it is not one this surface performs.
OUTPUT_DIR = JOBS_DIR / "adapters"

# The shipped persona adapter, offered as a READ-ONLY starting point for a run.
SHIPPED_ADAPTER = ROOT / "training" / "adapter"


class AdapterRefused(Exception):
    """An `--init-adapter` path that cannot be used. Message is ours."""


def _admit_init_adapter(path_str: str) -> str:
    """Validate a starting adapter and return its resolved path. Read-only, always.

    ## Why this is not `dataset_guard.admit()`, and must not be merged into it

    `dataset_guard` **denies** `training/adapter/` outright, and correctly: as a *dataset* that
    directory is a trade-secret artefact carrying the trained weights and the tokeniser, and
    globbing it into a data picker would publish the product.

    As a *starting adapter* it is the single most useful thing on the box, and the intended path.
    The standard alignment pipeline is supervised first and reinforcement on top; the shipped
    persona adapter IS the supervised stage. Refusing it here would mean every RL run starts from
    random low-rank matrices and asks a reward function to re-derive the company voice.

    So the same path is denied for one purpose and allowed for another, and that is a deliberate
    asymmetry rather than an inconsistency for a later agent to tidy away. What makes it safe is
    the direction of travel: this path is **only ever read**, it is never enumerated, its contents
    are never returned by a route, and the run writes its own separate output directory. The
    difference between reading weights to continue training and serving a corpus over HTTP is the
    entire difference.

    `training/corpus.jsonl` and `build_dataset.py` stay denied here too -- they are not adapters,
    and a caller reaching for one has made a mistake worth naming.
    """
    if not path_str or not path_str.strip():
        return ""
    candidate = pathlib.Path(path_str.strip())
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    resolved = candidate.resolve(strict=False)

    # The two protected artefacts remain refused: neither is an adapter, and asking for one as a
    # starting point is a confusion worth reporting rather than silently working around.
    if resolved in {p.resolve() for p in dataset_guard.DENIED}:
        raise AdapterRefused("That path is a protected SyMoNeuRaL artefact and is not an adapter.")
    if not resolved.is_dir():
        raise AdapterRefused("No such adapter directory.")
    if not (resolved / "adapter_config.json").is_file():
        # Checked by structure, not by name. A directory without this file is not a PEFT adapter,
        # and `PeftModel.from_pretrained` would fail on it well after the card was acquired.
        raise AdapterRefused("That directory is not a PEFT adapter -- no adapter_config.json in "
                             "it. Nothing was read.")
    return str(resolved)


class JobError(Exception):
    """Refusal to start. Message is ours; never built from file contents."""


# ---------------------------------------------------------------- the log allowlist
#
# Only lines of this exact shape are read. Everything else the child prints -- transformers'
# banner, bitsandbytes' warnings, a progress bar, a traceback -- is discarded unparsed.
_LINE = re.compile(r"^REINFORCE (?P<body>(?:[a-z_]+=[A-Za-z0-9_.:+-]{1,64} ?)+)$")
# The complete set of keys that may reach an API response. A key not in this set is dropped
# even if it appears on a well-formed line, so adding a field to the runner is a deliberate
# two-file change rather than something that leaks in by accident.
#
# ## Adding a metric is a two-file change, and forgetting the second file is silent
#
# The reinforcement and preference methods report quantities the supervised path has no
# equivalent of -- `reward`, `reward_std`, `kl`, `completion_len`, `clip_ratio`, `entropy` for
# GRPO; `reward_chosen`, `reward_rejected`, `reward_accuracy`, `reward_margin` for DPO. A key
# missing from this set is not an error anywhere: it is **dropped**, and the panel then shows a
# running RL job with an empty reward curve. That is the dishonest-pixel rule inverted -- a
# display that looks alive and reports nothing -- so `test_reinforce.py` asserts key by key that
# `runner._METRIC_KEYS` and this set agree.
#
# Note also what these names do NOT contain: a slash. trl logs `rewards/chosen`; the runner maps
# it to `reward_chosen` before printing, because `/` is outside the value character class and is
# also how a filesystem path would arrive. The mapping is the runner's job; the narrow character
# class stays.
_ALLOWED_KEYS = frozenset({
    "event", "step", "total_steps", "epoch", "loss", "lr", "elapsed_s", "val_loss",
    "rows", "val_rows", "vram_alloc", "vram_reserved", "peak_alloc", "peak_reserved",
    "kind", "stage", "seed", "trainable", "total_params",
    # shared
    "grad_norm", "tokens_seen",
    # reinforcement (GRPO)
    "reward", "reward_std", "kl", "entropy", "clip_ratio",
    "completion_len", "completion_len_ok", "rewards", "dropped_long",
    # preference (DPO)
    "reward_chosen", "reward_rejected", "reward_accuracy", "reward_margin",
    "logps_chosen", "logps_rejected",
})
_NUMERIC_KEYS = frozenset({
    "step", "total_steps", "epoch", "loss", "lr", "elapsed_s", "val_loss", "rows",
    "val_rows", "vram_alloc", "vram_reserved", "peak_alloc", "peak_reserved", "seed",
    "trainable", "total_params",
    "grad_norm", "tokens_seen",
    "reward", "reward_std", "kl", "entropy", "clip_ratio",
    "completion_len", "completion_len_ok", "rewards", "dropped_long",
    "reward_chosen", "reward_rejected", "reward_accuracy", "reward_margin",
    "logps_chosen", "logps_rejected",
})
# Free-text-shaped keys are constrained to a vocabulary rather than to a character class,
# because `kind=<exception class>` is the one field a Python traceback could otherwise steer.
#
# **`stage` is the dangerous one.** An unrecognised value here does not degrade a line, it
# discards the WHOLE line -- see the `ok = False` branch in `parse_log()` -- and that includes
# `event=error stage=<new stage> kind=<class>`. So a stage added to `runner.STAGES` and not
# added here turns the one report that has to survive into nothing at all: a failed run with no
# kind and no stage. The four new stages below are the RL path's, and a test asserts the two
# tuples match.
_ENUM_VALUES = {
    "event": {"start", "step", "eval", "done", "error"},
    "stage": {"load_dataset", "load_model", "build_adapter", "check_rewards", "load_reference",
              "train", "rollout", "evaluate", "save"},
}
_LOG_TAIL_BYTES = 64 * 1024


def parse_log(text: str) -> list[dict]:
    """Turn runner output into structured events, discarding anything unrecognised.

    ALLOWLIST, NOT DENYLIST -- see the module docstring. This is the guard that stops a
    traceback carrying a corpus line into an HTTP response. Do not add a fallback branch that
    passes unmatched lines through "just for debugging"; that branch is the leak.
    """
    events: list[dict] = []
    for line in text.splitlines():
        m = _LINE.match(line.strip())
        if not m:
            continue
        event: dict = {}
        ok = True
        for pair in m.group("body").split():
            key, _, raw = pair.partition("=")
            if key not in _ALLOWED_KEYS:
                continue
            if key in _NUMERIC_KEYS:
                try:
                    event[key] = float(raw) if ("." in raw or "e" in raw.lower()) else int(raw)
                except ValueError:
                    ok = False
                    break
            elif key in _ENUM_VALUES:
                if raw not in _ENUM_VALUES[key]:
                    ok = False
                    break
                event[key] = raw
            else:
                event[key] = raw
        if ok and event.get("event"):
            events.append(event)
    return events


def _tail(path: pathlib.Path, nbytes: int = _LOG_TAIL_BYTES) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > nbytes:
                fh.seek(size - nbytes)
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


# ---------------------------------------------------------------- job records


@dataclass
class Job:
    id: str
    model: str
    preset: str
    dataset_rows: int
    started_at: float
    pid: int
    log: str
    exit_file: str
    out_dir: str
    plan: dict
    # Everything below carries a default, and that is load-bearing rather than lazy. `_load_job`
    # does `Job(**raw)` over a JSON file that may have been written by an EARLIER version of this
    # module -- a run started before these fields existed, still on disk, possibly still running.
    # A field without a default turns reading that record into a TypeError, which `_load_job`
    # catches and reports as "no run has been started from this surface" while a fine-tune is
    # live on the card. Adding a required field here silently loses a running job.
    method: str = "sft"
    dataset_schema: str = "messages"
    init_adapter: str = ""

    def to_dict(self) -> dict:
        return {**self.__dict__}


def _load_job() -> Job | None:
    try:
        raw = json.loads(JOB_FILE.read_text())
        return Job(**raw)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def holder() -> str:
    """Which surface holds the GPU lock, read straight from the governor's holder file.

    One small file read, no subprocess. `status()` runs on every rack poll and a fork per poll
    would be a latency bug on every page view -- which is a real cost, not a theoretical one:
    this is the panel that sits beside every prompt box on the site.
    """
    try:
        return HOLDER_FILE.read_text().split()[0]
    except (OSError, IndexError):
        return ""


def _read_progress() -> dict:
    """The runner's latest reading, written atomically each step.

    Re-validated on read even though this package wrote it. The file lives under `run/`, which
    is world-readable state on a box that also runs a web server; trusting it because we wrote
    it is how a validated field becomes an unvalidated one after somebody edits the runner.
    """
    try:
        raw = json.loads(PROGRESS_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    for k, v in raw.items():
        if k in _NUMERIC_KEYS and isinstance(v, (int, float)):
            out[k] = v
    return out


# ---------------------------------------------------------------- the snapshot


def snapshot() -> dict:
    """Everything known about the current or most recent run.

    States, and each is a reading rather than an assertion:

    * `none`     -- no run has been started from this surface. The panel says so.
    * `queued`   -- launched, and waiting behind another surface for the card. Genuinely
                    reachable: the governor blocks up to 300s while chat's weights drain
                    below the 1.5 GiB floor, and "waiting" is the honest word for that.
    * `running`  -- the process is alive and holds the card.
    * `finished` -- exited 0.
    * `failed`   -- exited non-zero, or the process vanished without writing an exit code.
    """
    job = _load_job()
    if job is None:
        return {"state": "none",
                "detail": "no run has been started from this surface",
                "job": None, "events": [], "measured_peaks": measured_peaks()}

    exit_path = pathlib.Path(job.exit_file)
    exit_code: int | None = None
    if exit_path.is_file():
        try:
            exit_code = int(exit_path.read_text().strip())
        except (OSError, ValueError):
            exit_code = None

    alive = _alive(job.pid)
    held = holder()
    if exit_code is not None:
        state = "finished" if exit_code == 0 else "failed"
    elif alive:
        state = "running" if held == "train" else "queued"
    else:
        # The launcher is gone and left no exit code. That is a failure, and it is reported as
        # one rather than as "finished" -- an optimistic reading here would put a green light
        # on a run that died.
        state = "failed"

    events = parse_log(_tail(pathlib.Path(job.log)))
    progress = _read_progress()
    steps = [e for e in events if e.get("event") == "step"]
    latest = steps[-1] if steps else {}
    evals = [e for e in events if e.get("event") == "eval"]
    errors = [e for e in events if e.get("event") == "error"]
    done = next((e for e in reversed(events) if e.get("event") == "done"), {})

    step = int(progress.get("step") or latest.get("step") or 0)
    total = int(progress.get("total_steps") or latest.get("total_steps") or 0)
    elapsed = float(progress.get("elapsed_s") or latest.get("elapsed_s") or 0.0)
    if state in ("running", "queued"):
        elapsed = max(elapsed, time.time() - job.started_at)

    eta = None
    if state == "running" and step > 0 and total > step and elapsed > 0:
        eta = round(elapsed / step * (total - step), 1)

    peak_alloc = done.get("peak_alloc") or progress.get("vram_alloc") or latest.get("vram_alloc")
    peak_reserved = (done.get("peak_reserved") or progress.get("vram_reserved")
                     or latest.get("vram_reserved"))

    detail = {
        "none": "no run",
        "queued": "waiting for the card -- another surface holds it",
        "running": f"step {step} of {total}" if total else "running",
        "finished": "run complete",
        "failed": "run failed",
    }[state]
    if state == "failed" and errors:
        # Class name and stage only. The runner never prints an exception *message*, because a
        # tokeniser traceback can carry a training example in it.
        detail = f"failed during {errors[-1].get('stage', 'run')}: {errors[-1].get('kind', 'error')}"

    return {
        "state": state,
        "detail": detail,
        "job": job.to_dict(),
        "exit_code": exit_code,
        "holder": held or None,
        "step": step,
        "total_steps": total,
        "epoch": latest.get("epoch"),
        "train_loss": latest.get("loss"),
        "train_loss_label": "measured" if latest.get("loss") is not None else None,
        "val_loss": evals[-1].get("val_loss") if evals else None,
        "val_loss_label": "measured" if evals else None,
        "learning_rate": latest.get("lr"),
        "elapsed_s": round(elapsed, 1),
        "elapsed_label": "measured",
        "eta_s": eta,
        "eta_label": "projected" if eta is not None else None,
        "eta_note": ("elapsed / steps done x steps remaining -- arithmetic on a rate that is "
                     "not constant, so it is a projection and not a promise"),
        "vram_peak_alloc_bytes": peak_alloc,
        "vram_peak_reserved_bytes": peak_reserved,
        "vram_label": "measured" if peak_alloc else None,
        "vram_note": ("torch.cuda.max_memory_allocated() and max_memory_reserved() inside the "
                      "training process -- the only numbers on this surface that can retire a "
                      "projection"),
        # The method's own metrics, and ONLY the ones the run actually reported. A key absent
        # from the runner's output is absent here too rather than present as null: the panel
        # decides what to draw from what exists, so a null would become an axis with no data.
        "method": job.method,
        "method_label": presets.METHODS.get(job.method, {}).get("label", job.method),
        "metrics": {k: latest[k] for k in (
            "reward", "reward_std", "kl", "entropy", "clip_ratio", "completion_len",
            "completion_len_ok", "grad_norm", "loss",
            "reward_chosen", "reward_rejected", "reward_accuracy", "reward_margin",
            "logps_chosen", "logps_rejected") if latest.get(k) is not None},
        "metrics_label": "measured",
        "metrics_note": (
            ("reward is the weighted sum of this run's rules-based reward functions, read from "
             "the trainer. It is a real reading of THAT SCORE. A rising reward is evidence the "
             "program's score went up -- not by itself evidence the model got better, which is "
             "why the completions are logged for a human to read."
             if job.method == "reinforcement" else
             "DPO's rewards/* are implicit log-ratios against the reference policy, not a reward "
             "signal from a reward function. `reward_accuracy` is the fraction of pairs where the "
             "preferred completion scored higher -- it saturates early, and a margin that keeps "
             "growing after it does is memorisation."
             if job.method == "preference" else
             "supervised loss, read from the trainer's own state")),
        "events": events[-40:],
        "measured_peaks": measured_peaks(),
        "log_note": ("this response is built from an allowlist of known-shaped runner output; "
                     "unrecognised lines are discarded rather than sanitised, and the raw log "
                     "is not served by any route"),
    }


def measured_peaks() -> dict:
    """Real peak-VRAM readings, keyed `<model>|<preset>`.

    A cell here replaces the projection for **that cell only**. Scaling one measurement across
    the other eleven cells would be a projection wearing a measurement's label, which is the
    exact dishonesty `.claude/CLAUDE.md` names. Empty until a run of that model and preset has
    actually completed.
    """
    try:
        raw = json.loads(MEASURED_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    for key, val in raw.items():
        if isinstance(val, dict) and isinstance(val.get("peak_alloc"), (int, float)):
            out[key] = {"peak_alloc": val["peak_alloc"],
                        "peak_reserved": val.get("peak_reserved"),
                        "steps": val.get("steps"),
                        "at": val.get("at"),
                        "label": "measured"}
    return out


# ---------------------------------------------------------------- preflight and launch


def preflight(model_id: str, preset_id: str, dataset_path: str = "",
              init_adapter: str = "") -> dict:
    """Everything checked before a single weight is read.

    Reinforce's `plan_residency(free_bytes)` decides what fits before anything is loaded; this
    is the same idea with a training-shaped cost model. A refusal returns the itemised sum,
    because "won't fit" without arithmetic is indistinguishable from a bug, and because the
    OOM ladder can only name a rung when it knows which term is the large one.

    `ok=False` with `reason="capability"` is deliberately *not* an error: picking a 14B at
    sequence 2048 on this card is a capability this box does not have, not a fault. That
    distinction is Reinforce's `CapabilityWaived`, which its own server answers with 501
    rather than 500 so that "cannot run here" never masquerades as "broken".
    """
    preset = presets.PRESETS.get(preset_id)
    if preset is None:
        return {"ok": False, "reason": "unknown_preset",
                "message": f"No such preset. Available: {', '.join(presets.PRESETS)}."}

    entry = registry.find(model_id)
    if entry is None:
        return {"ok": False, "reason": "unknown_model",
                "message": "No such model on this box."}
    if not entry.trainable:
        return {"ok": False, "reason": "model_not_trainable", "message": entry.reason,
                "model": entry.to_dict()}

    free, free_label = registry.free_vram_bytes()
    arch = registry.Arch(**entry.arch)
    plan = registry.plan_fit(arch, rank=preset.rank, target_modules=preset.target_modules,
                             seq_len=preset.max_length, batch=1,
                             gradient_checkpointing=True, free_bytes=free,
                             method=preset.method, method_config=preset.method_config)
    plan["free_vram_label"] = free_label

    result = {"ok": True, "model": entry.to_dict(), "preset": preset.to_dict(), "plan": plan,
              "shared": presets.SHARED, "reason": "", "message": "",
              "method": preset.method,
              "method_info": presets.METHODS[preset.method],
              "dataset_schema": preset.dataset_schema,
              "schema_spec": dataset_guard.SCHEMAS[preset.dataset_schema]}

    if plan["verdict"] == "refused":
        result.update({"ok": False, "reason": "capability",
                       "message": ("This configuration does not fit on this card. That is a "
                                   "capability this box does not have, not a fault: " +
                                   plan["verdict_why"])})

    # The card, not the arithmetic. A run cannot start while another surface holds the lock --
    # it can queue, and the governor will wait, but the operator is told first.
    held = holder()
    if held and held != "train":
        result["gpu_note"] = (f"'{held}' currently holds the card. A run will queue behind it, "
                              f"and starting one takes chat, image and remix offline for the "
                              f"whole fine-tune -- the governor never evicts a training run.")
    snap = snapshot()
    if snap["state"] in ("running", "queued"):
        result.update({"ok": False, "reason": "busy",
                       "message": "A run is already in progress on this surface."})

    # The rollout backend, checked before the card is taken rather than at step 0. Only the
    # reinforcement method generates anything, so the other two skip this entirely.
    if preset.method == "reinforcement":
        backend = (preset.method_config or {}).get("rollout", "transformers")
        state = rollout.check(backend)
        result["rollout"] = {"backend": backend, **state}
        if not state["ok"]:
            result.update({"ok": False, "reason": state["reason"], "message": state["message"]})

    if dataset_path:
        try:
            # Admitted against the schema THIS PRESET'S METHOD requires, not against a default.
            # A preference run pointed at a file of chat examples is refused here, by name, with
            # the shape it wanted -- rather than failing inside a collator twenty minutes in.
            info = dataset_guard.admit(dataset_path, schema=preset.dataset_schema)
            result["dataset"] = info.to_dict()
            # Reward functions resolved against the columns the dataset actually has, so
            # `answer_match` is offered when there is an `answer` column and refused by name when
            # there is not. Resolved here because a reward selection that cannot be honoured is a
            # refusal to start, not a surprise at step 0.
            if preset.method == "reinforcement":
                names = (preset.method_config or {}).get("rewards", ())
                try:
                    plan_r = rewards.resolve(names, available_fields=info.fields)
                    result["rewards"] = {"active": plan_r["names"],
                                         "weights": plan_r["weights"],
                                         "refused": plan_r["refused"],
                                         "offered": rewards.offered(info.fields)}
                except rewards.RewardError as exc:
                    result.update({"ok": False, "reason": "rewards", "message": str(exc)})
        except dataset_guard.Refused as exc:
            result.update({"ok": False, "reason": f"dataset_{exc.code}", "message": exc.message})

    # The starting adapter. Validated even when empty, so the response always says which one a
    # run would use -- "a freshly initialised adapter" is a decision worth stating rather than
    # a blank field.
    try:
        resolved_init = _admit_init_adapter(init_adapter)
    except AdapterRefused as exc:
        resolved_init = ""
        result.update({"ok": False, "reason": "init_adapter", "message": str(exc)})
    result["init_adapter"] = resolved_init or None
    result["init_adapter_note"] = (
        ("continuing from an existing adapter. Its rank and target modules override this "
         "preset's -- an adapter's shape is fixed when it is created. Nothing is written back "
         "to it; this run writes its own output directory.")
        if resolved_init else
        ("starting from a freshly initialised adapter. For the reinforcement method that is "
         "usually the wrong choice: the standard pipeline is supervised first and RL on top, so "
         "the shipped persona adapter is the intended starting point. Pass it as init_adapter."
         if preset.method == "reinforcement" else
         "starting from a freshly initialised adapter, which is the normal choice for this "
         "method."))

    # Environment facts that are true or not, checked before the run rather than at step 0.
    problems = []
    if not TRAIN_PYTHON.is_file():
        problems.append("the training virtualenv interpreter is missing at training/.venv/bin/python")
    if not GOVERNOR.is_file():
        problems.append("scripts/gpu-governor.sh is missing -- nothing may touch the GPU without it")
    if not registry.HF_HOME.is_dir():
        problems.append("models/hf does not exist -- the weight cache would not resolve")
    if problems:
        result.update({"ok": False, "reason": "environment", "message": "; ".join(problems)})

    return result


def start(model_id: str, preset_id: str, dataset_path: str, init_adapter: str = "") -> dict:
    """Launch a run under the governor, detached, and record it on disk.

    The command is `gpu-governor.sh with train -- <training venv python> runner.py ...`:

    * `with` acquires and **always releases**, including on crash. Nothing here calls
      `acquire` directly and nothing calls a bare `release`.
    * the interpreter is `training/.venv/bin/python`, never this one. The serving API runs on
      the system interpreter by deliberate policy and has no torch; the training stack is
      cu128 because Blackwell sm_120 needs it. The subprocess boundary is what keeps those
      two facts from having to be reconciled.
    * `start_new_session=True` detaches it -- see the module docstring for why an API restart
      must not fire the governor's release trap under a live run.
    """
    pre = preflight(model_id, preset_id, dataset_path, init_adapter)
    if not pre["ok"]:
        raise JobError(pre.get("message") or pre.get("reason") or "preflight refused")

    preset = presets.PRESETS[preset_id]
    # Admitted again, against the preset's own schema; the guard is not optional and is not
    # cached from the preflight. A caller that reached `start()` without a preflight still gets
    # every check, which is the property that makes the guard a guard.
    info = dataset_guard.admit(dataset_path, schema=preset.dataset_schema)
    init_adapter = _admit_init_adapter(init_adapter)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    log_path = JOBS_DIR / f"{job_id}.log"
    exit_path = JOBS_DIR / f"{job_id}.exit"
    out_dir = OUTPUT_DIR / job_id

    argv = [
        str(TRAIN_PYTHON), str(RUNNER),
        "--model", pre["model"]["path"],
        "--model-id", pre["model"]["id"],
        "--dataset", info.path,
        "--out", str(out_dir),
        "--preset", preset.id,
        "--epochs", str(preset.epochs),
        "--rank", str(preset.rank),
        "--alpha", str(preset.lora_alpha),
        "--dropout", str(presets.SHARED["lora_dropout"]["value"]),
        "--lr", str(preset.learning_rate),
        "--scheduler", preset.lr_scheduler_type,
        "--max-length", str(preset.max_length),
        "--grad-accum", str(preset.gradient_accumulation_steps),
        "--val-split", str(preset.val_split),
        "--save-strategy", preset.save_strategy,
        "--seed", str(presets.SHARED["seed"]["value"]),
        "--target-modules", ",".join(preset.target_modules),
        "--progress-file", str(PROGRESS_FILE),
        "--measured-file", str(MEASURED_FILE),
    ]
    if preset.max_examples:
        argv += ["--max-examples", str(preset.max_examples)]
    if preset.max_steps:
        argv += ["--max-steps", str(preset.max_steps)]

    # ---- the method's own arguments ---------------------------------------------------
    #
    # Passed explicitly rather than as a serialised blob, so that every value crossing the
    # process boundary is one this module chose and `build_script` quoted. A `--method-config
    # '{...}'` argument would put operator-influenced JSON on a command line for the runner to
    # re-parse, and the argparse `choices=` on the far side would no longer be checking anything.
    cfg = preset.method_config or {}
    argv += ["--method", preset.method, "--dataset-schema", preset.dataset_schema]
    if init_adapter:
        argv += ["--init-adapter", init_adapter]
    if preset.method == "preference":
        argv += ["--beta", str(cfg.get("beta", 0.1))]
        if cfg.get("loss_type"):
            argv += ["--loss-type", str(cfg["loss_type"])]
        if cfg.get("precompute_ref_log_probs"):
            argv += ["--precompute-ref-log-probs"]
    elif preset.method == "reinforcement":
        argv += [
            "--num-generations", str(cfg.get("num_generations", 4)),
            "--max-completion-length", str(cfg.get("max_completion_length", 192)),
            "--beta", str(cfg.get("beta", 0.0)),
            "--temperature", str(cfg.get("temperature", 1.0)),
            "--top-p", str(cfg.get("top_p", 1.0)),
            "--scale-rewards", str(cfg.get("scale_rewards", "group")),
            "--rewards", ",".join(cfg.get("rewards", ())),
            "--rollout", str(cfg.get("rollout", "transformers")),
        ]
        if cfg.get("loss_type"):
            argv += ["--loss-type", str(cfg["loss_type"])]
        if cfg.get("mask_truncated_completions"):
            argv += ["--mask-truncated-completions"]
        if cfg.get("rollout") == "vllm":
            url = rollout.vllm_base_url()
            if url:
                argv += ["--vllm-base-url", url]

    script = build_script(argv, exit_path)

    log_fh = log_path.open("ab", buffering=0)
    try:
        proc = subprocess.Popen(
            ["/bin/bash", "-c", script],
            stdout=log_fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=True, cwd=str(ROOT),
            # A clean, explicit environment. HF_HOME is set here AND asserted in the runner:
            # `training/train_lora.py` has this wrong today (it resolves to /home/google/models/hf,
            # which does not exist) and a fresh run there silently re-downloads ~14 GiB into a
            # non-repo path. HF_HUB_OFFLINE stops that failure mode dead -- a path slip becomes
            # an immediate error instead of a quiet 14 GiB transfer.
            env={**os.environ,
                 "HF_HOME": str(registry.HF_HOME),
                 "HF_HUB_OFFLINE": "1",
                 "TRANSFORMERS_NO_ADVISORY_WARNINGS": "1",
                 "PYTHONUNBUFFERED": "1"},
        )
    finally:
        log_fh.close()

    job = Job(id=job_id, model=pre["model"]["id"], preset=preset.id,
              dataset_rows=info.rows, started_at=time.time(), pid=proc.pid,
              log=str(log_path), exit_file=str(exit_path), out_dir=str(out_dir),
              plan=pre["plan"], method=preset.method,
              dataset_schema=preset.dataset_schema, init_adapter=init_adapter)
    PROGRESS_FILE.unlink(missing_ok=True)
    JOB_FILE.write_text(json.dumps(job.to_dict(), indent=2))
    return job.to_dict()


def build_script(argv: list[str], exit_path: pathlib.Path) -> str:
    """The exact shell statement a run is launched as. Extracted so a test can assert on it.

    Three properties are load-bearing and each has a regression test in `test_reinforce.py`:

    1. it goes through `gpu-governor.sh **with train --**`, the form that always releases,
       including on crash, via a trap;
    2. it never contains a bare `release` -- an unscoped release once destroyed a running
       fine-tune's lock from the API's shutdown hook, and the governor now refuses a mismatched
       claimant, but the right fix is not to write one in the first place;
    3. the exit code is written *after* the governor returns, in the same statement, so it
       survives the launcher and a restarted API can tell finished from failed.

    Every argument is `shlex.quote`d: a dataset path is operator-supplied text going into a
    shell string, which is the classic place to lose a box.
    """
    inner = " ".join(shlex.quote(a) for a in [str(GOVERNOR), "with", "train", "--"] + argv)
    return f"{inner}; printf '%s' $? > {shlex.quote(str(exit_path))}"


def stop() -> dict:
    """Stop a run deliberately.

    SIGTERM to the **process group**, because the job is a detached session: the bash wrapper,
    the governor and the python child are all in it, and signalling only the leader would
    leave the trainer running with nothing left to release the card. SIGTERM rather than
    SIGKILL for the reason the governor documents at length -- killing a holder returns the
    lock long before the CUDA context has finished tearing down, and the next surface then
    allocates into memory that is still held. A TERM lets the governor's trap run, and the
    governor's release waits for the driver to hand the memory back.
    """
    job = _load_job()
    if job is None:
        return {"stopped": False, "reason": "no run has been started from this surface"}
    if not _alive(job.pid):
        return {"stopped": False, "reason": "that run is not running"}
    try:
        os.killpg(os.getpgid(job.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError) as exc:
        return {"stopped": False, "reason": f"could not signal the run ({type(exc).__name__})"}
    return {"stopped": True, "job": job.id,
            "note": ("SIGTERM sent to the run's process group. The governor releases the card "
                     "on its way out and waits for VRAM to drain below the floor before the "
                     "next surface is let in.")}


# ---------------------------------------------------------------- the rack unit


def status() -> dict:
    """The rack unit, as a plain dict whose keys match `backend/server.py`'s `Unit` model.

    Built as a dict rather than from `Unit` itself, for the reason `apps/streamer` gives: importing
    `api.py` would put this module inside its import graph. The wiring engineer splats it:
    `Unit(**reinforce.status())`.

    **Synchronous and cheap.** Called on every rack poll, so: two small file reads and no
    subprocess. No `nvidia-smi` here -- `api.py` already polls the card, and a fork per page
    view would be a latency bug on the panel that sits beside every prompt box on the site.

    `Unit.state` has four values -- ready, busy, queued, offline -- and they are NOT this
    module's job vocabulary. A finished or failed run maps to `ready` with the outcome in the
    detail line; anything else raises pydantic at `/api/status` and takes every other unit's
    rack row down with it.
    """
    from . import enabled                       # local import: avoids a package import cycle

    held = holder()
    snap_state = "none"
    detail_extra = ""
    job = _load_job()
    if job is not None:
        prog = _read_progress()
        exit_path = pathlib.Path(job.exit_file)
        if exit_path.is_file():
            try:
                code = int(exit_path.read_text().strip())
            except (OSError, ValueError):
                code = 1
            snap_state = "finished" if code == 0 else "failed"
        elif _alive(job.pid):
            snap_state = "running" if held == "train" else "queued"
        else:
            snap_state = "failed"
        step, total = int(prog.get("step") or 0), int(prog.get("total_steps") or 0)
        if snap_state in ("running", "queued") and total:
            method_bit = (f" · {job.method}" if job.method != "sft" else "")
            detail_extra = f" · step {step}/{total} · {job.preset} on {job.model}{method_bit}"
        elif snap_state in ("finished", "failed"):
            detail_extra = f" · last run: {snap_state} ({job.preset})"

    if not enabled():
        state = "offline"
        detail = ("operator surface off · set SYMONEURAL_REINFORCE_ENABLED=1 "
                  "to accept work · a never-evicted GPU route open to the internet is a "
                  "rack-wide outage that costs one request")
    elif snap_state == "queued":
        state = "queued"
        detail = f"waiting for the card behind '{held}'{detail_extra}"
    elif snap_state == "running" or held == "train":
        state = "busy"
        detail = f"fine-tune in progress — serving surfaces queue{detail_extra}"
    else:
        state = "ready"
        # Says what it can accept, not merely that a file exists on disk. The old unit reported
        # `ready` because `training/adapter/symoneural-lora.gguf` was present, which is a
        # different claim from "this unit can take work" and was the strongest single argument
        # that the surface was a status panel rather than a training bay.
        n_models = sum(1 for e in registry.catalogue() if e.trainable)
        n_rl = sum(1 for p in presets.PRESETS.values() if p.is_rl)
        detail = (f"{n_models} base model(s) loadable · {len(presets.PRESETS)} tuning presets "
                  f"across {len(presets.METHODS)} methods ({n_rl} reinforcement) · "
                  f"a run takes the whole card{detail_extra}")

    return {
        "id": "train",
        "label": "SyMoNeuRaL Reinforce",
        "slot": "2U",
        "state": state,
        "bus": "gpu",
        "href": "/reinforce.html",
        "spec": "4-bit low-rank adaptation · 15.92 GiB single card",
        "detail": detail,
    }
