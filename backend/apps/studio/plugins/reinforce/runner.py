#!/usr/bin/env python3
"""SyMoNeuRaL Reinforce -- the training runner. Runs in `training/.venv`, NOT in the API.

This is the only file in this package that imports torch, and it is never imported by the
serving API. It is exec'd as a subprocess:

    scripts/gpu-governor.sh with train -- training/.venv/bin/python runner.py --preset voice ...

Three boundaries meet here and all three are deliberate:

* **Interpreter.** The serving API runs on the system interpreter, which carries fastapi,
  uvicorn, pydantic and sympy and nothing else, on purpose. The training stack is torch
  cu128 because Blackwell sm_120 needs it. A subprocess is what lets both be true.
* **Process.** A crashed fine-tune cannot take the API down with it, and the API restarting
  cannot take the fine-tune down with it. `jobs.py` detaches the session for the second half
  of that.
* **Lock.** This process never talks to the governor. It is *run underneath* the governor's
  `with train` form, which acquires before it starts and releases after it exits, including
  on a crash. Nothing here calls acquire, and nothing here calls release -- a bare release
  once destroyed a running fine-tune's lock, and the fix is that the only code releasing the
  card is the code that took it.

## What this runner does that the existing trainer does not

`training/train_lora.py` produced the shipped adapter, and two of its choices are carried
forward here verbatim because they are right (see `_encode`). But it has no validation split,
no eval, no checkpoints, no seed and no run manifest, so nothing it produced can be measured
or reproduced. This runner adds exactly those:

* a held-out validation split, per the repo manual's *"hold out 5-10% BEFORE looking at
  training loss"*;
* a seed, recorded;
* `save_strategy` from the preset;
* a **run manifest** written beside the adapter with every hyperparameter, the seed, and the
  measured peak VRAM -- which is what lets a projected figure ever become a measured one;
* `--max-steps`, so a smoke test is genuinely a handful of steps rather than a short run.

## Output protocol -- read this before adding a print

Everything this process writes to stdout is captured into a log that feeds an API response.
`jobs.parse_log()` reads it with an **allowlist**: only lines of the exact form

    REINFORCE key=value key=value ...

with keys from a fixed set and values matching `[A-Za-z0-9_.:+-]{1,64}` are parsed; every
other line is discarded unparsed. That is the guard, and it is an allowlist rather than a
denylist because a denylist would have to anticipate every shape a leaked training example
could take.

**Which is why errors here report a class name and a stage, never a message.** A traceback out
of the tokeniser or the collator can carry a training example verbatim, and the corpus is the
trade secret this whole surface is most likely to leak. `_fail()` is the only error path and
it prints `kind=<ExceptionClassName> stage=<stage>` and nothing else. The full traceback goes
to stderr, into a log file under `run/` that no route serves.

## Three methods, one runner

`--method` selects the objective and therefore the trainer:

* `sft` -- `transformers.Trainer`. Unchanged, and deliberately so: this path produced the
  shipped adapter and every line of it behaves exactly as it did before the other two existed.
* `preference` -- `trl.DPOTrainer`. Needs a `preference` dataset.
* `reinforcement` -- `trl.GRPOTrainer`. Needs a `prompt` dataset and reward functions. This is
  the only one that samples, and the only one that is reinforcement learning in the ordinary
  sense; see `presets.METHODS` for why DPO is not called RL here.

### The reference policy costs no weights

Both new methods want a frozen reference to measure against. Neither loads one. `ref_model` is
left as `None` while a `peft_config`/adapter is attached, which makes trl **disable the adapter**
for the reference forward pass and re-enable it after -- so the reference is the base model that
is already resident. It costs a forward pass, not a second 4-bit 7B. This is the objection that
kept preference tuning out of v1, and `docs/specs/qlora-upgrade.md` §5.4 had already spotted the
answer.

### Metric names are normalised here, not in the parser

trl logs `rewards/chosen`, `rewards/rejected`, `train/reward` and friends. The log protocol's
value character class **does not include `/`**, so an unmodified key would be silently dropped
by `emit()` -- producing a live RL run with a blank reward curve, which is the dishonest-pixel
rule in reverse: a panel that looks healthy and reports nothing. `_METRIC_KEYS` maps every
trl metric name onto an allowlisted key, and `jobs._ALLOWED_KEYS` must contain each of them.
A test asserts the two ends agree, per key.

### Continuing from an existing adapter

`--init-adapter` loads an existing PEFT adapter as the starting point instead of a freshly
initialised one, and it exists because **the standard alignment pipeline is SFT first, then RL
on top.** The shipped SymonChat persona adapter *is* the supervised stage; a GRPO run starting
from a random adapter throws that away and tries to re-learn the company voice from a reward
function, which is the wrong way round and would take far more than a reward function can carry.

It is read-only in every sense that matters: the adapter is loaded as a starting point and the
run writes its **own** output directory. Nothing here writes back to `--init-adapter`, and
`training/adapter/` -- the adapter the chat surface serves -- is refused as an output path by
`jobs.py` and is never a default. Promotion remains a deliberate manual step.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import random
import sys
import time
import traceback

HERE = pathlib.Path(__file__).resolve().parent

# Take this script's own directory OFF sys.path before importing anything third-party.
#
# This is a real bug that happened, not a precaution. Python puts a script's directory at
# sys.path[0], so `from datasets import Dataset` -- the Hugging Face package -- resolved to the
# sibling module in this directory instead, which is a serving-path module full of relative
# imports, and the run died at `ImportError: attempted relative import with no known parent
# package` after waiting 74 seconds for the GPU. The sibling has since been renamed
# `dataset_guard.py`, but the rename fixes one collision and this line fixes the class of them:
# any future module here named `torch.py`, `peft.py` or `accelerate.py` would do the same
# thing, and the failure surfaces only after the card has been acquired.
sys.path[:] = [p for p in sys.path if pathlib.Path(p or ".").resolve() != HERE]
# wrong three times in this repo and it fails silently, because the wrong parent is usually a
# directory that exists -- `training/train_lora.py` has it wrong right now, producing an
# HF_HOME of /home/google/models/hf, which does not exist. Assert, the way
# tools/build_training.py does, so a misresolution is immediate and obvious.
# `backend/api.py` is the marker, and it is WALKED for rather than counted to. The counted
# form (`HERE.parent.parent.parent`) has now been wrong a FOURTH time: moving this app to
# `backend/apps/studio/plugins/reinforce` added two levels and the count resolved to
# `backend/apps`, which exists, so the only thing that caught it was the assert below.
# A walk survives the next move; a count has to be found and fixed by hand every time.
ROOT = next((_p for _p in (HERE, *HERE.parents) if (_p / "backend" / "api.py").is_file()), HERE)
assert (ROOT / "backend" / "api.py").is_file(), f"repo root misresolved to {ROOT}"

HF_HOME = ROOT / "backend" / "models" / "hf"
os.environ.setdefault("HF_HOME", str(HF_HOME))
# Offline by default. A path slip that would otherwise start a silent ~14 GiB re-download
# becomes an immediate, legible error instead.
os.environ.setdefault("HF_HUB_OFFLINE", "1")

# The two artefacts that must never be read by this surface. Duplicated from `datasets.py`
# rather than imported, on purpose: this process runs in a different interpreter under a
# different working directory, and a guard that depends on an import path is a guard that can
# be lost to a refactor. Both copies must agree, and the test suite asserts that they do.
DENIED = {
    (ROOT / "training" / "corpus.jsonl").resolve(),
    (ROOT / "training" / "build_dataset.py").resolve(),
}

# Every stage a run can fail in. This tuple and `jobs._ENUM_VALUES["stage"]` must agree, and
# the agreement is asserted by a test -- because `parse_log()` discards an ENTIRE LINE whose
# `stage` value is outside its set, including `event=error`. A stage added here and not there
# does not degrade the report, it deletes it: the run would show as failed with no kind and no
# stage, which is the least useful possible output from the one path that has to work.
STAGES = ("load_dataset", "load_model", "build_adapter", "check_rewards", "load_reference",
          "train", "rollout", "evaluate", "save")

# trl's metric name -> the allowlisted key it is emitted as.
#
# The log protocol's value character class does not include `/`, so `rewards/chosen` would be
# dropped by `emit()` and never reach the panel. Normalising here rather than widening the
# character class keeps the guard narrow: `/` in a value is also how a filesystem path would
# arrive, and a path is exactly what must not be emitted.
_METRIC_KEYS = {
    "loss": "loss",
    "grad_norm": "grad_norm",
    "learning_rate": "lr",
    "epoch": "epoch",
    # GRPO
    "reward": "reward",
    "reward_std": "reward_std",
    "kl": "kl",
    "entropy": "entropy",
    "clip_ratio": "clip_ratio",
    "completions/mean_length": "completion_len",
    "completions/mean_terminated_length": "completion_len_ok",
    "num_tokens": "tokens_seen",
    # DPO
    "rewards/chosen": "reward_chosen",
    "rewards/rejected": "reward_rejected",
    "rewards/accuracies": "reward_accuracy",
    "rewards/margins": "reward_margin",
    "logps/chosen": "logps_chosen",
    "logps/rejected": "logps_rejected",
}


def emit(**fields) -> None:
    """Print one allowlisted line. Values are coerced to the shape the parser accepts.

    Anything that would not survive `jobs.parse_log()` is dropped here rather than printed and
    silently discarded on the other side, so the two ends cannot drift without a test noticing.
    """
    parts = []
    for key, val in fields.items():
        if val is None:
            continue
        if isinstance(val, float):
            text = f"{val:.6g}"
        else:
            text = str(val)
        # The value character class the parser enforces. A value that does not fit is dropped,
        # never truncated into something that might still carry content.
        if not text or len(text) > 64 or any(c not in
                "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:+-" for c in text):
            continue
        parts.append(f"{key}={text}")
    if parts:
        print("REINFORCE " + " ".join(parts), flush=True)


def _fail(stage: str, exc: BaseException) -> int:
    """The only error path. Class name and stage to stdout; traceback to stderr only."""
    emit(event="error", kind=type(exc).__name__, stage=stage if stage in STAGES else "train")
    print("--- traceback (stderr only; not served by any route) ---", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    return 1


def _write_atomic(path: pathlib.Path, payload: dict) -> None:
    """Write JSON so a reader never sees a half-written file.

    `jobs.py` reads `progress.json` on a timer while this process is writing it; without the
    rename the API would intermittently parse a truncated document and report `state: none`
    over a live run.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload))
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser(description="SyMoNeuRaL Reinforce training runner")
    ap.add_argument("--model", required=True, help="path to the HF snapshot directory")
    ap.add_argument("--model-id", default="")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--preset", default="custom")
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--dropout", type=float, default=0.05)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--scheduler", default="cosine")
    ap.add_argument("--max-length", type=int, default=1024)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--val-split", type=float, default=0.1)
    ap.add_argument("--save-strategy", default="no")
    ap.add_argument("--seed", type=int, default=20260817)
    ap.add_argument("--target-modules",
                    default="q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj")
    ap.add_argument("--max-examples", type=int, default=0)
    ap.add_argument("--max-steps", type=int, default=0)
    ap.add_argument("--progress-file", default="")
    ap.add_argument("--measured-file", default="")
    # ---- the method dimension ---------------------------------------------------------
    ap.add_argument("--method", default="sft",
                    choices=("sft", "preference", "reinforcement"),
                    help="the objective: supervised, DPO, or GRPO")
    ap.add_argument("--dataset-schema", default="messages",
                    choices=("messages", "preference", "prompt"))
    # Start from an existing adapter instead of a fresh one. The standard pipeline is SFT then
    # RL, so this is how an RL run builds ON the persona adapter rather than against it.
    ap.add_argument("--init-adapter", default="",
                    help="path to an existing PEFT adapter to continue from (read-only)")
    # ---- preference (DPO) -------------------------------------------------------------
    ap.add_argument("--beta", type=float, default=0.1)
    ap.add_argument("--loss-type", default="")
    ap.add_argument("--precompute-ref-log-probs", action="store_true")
    # ---- reinforcement (GRPO) ---------------------------------------------------------
    ap.add_argument("--num-generations", type=int, default=4)
    ap.add_argument("--max-completion-length", type=int, default=192)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--top-p", type=float, default=1.0)
    ap.add_argument("--scale-rewards", default="group")
    ap.add_argument("--mask-truncated-completions", action="store_true")
    ap.add_argument("--rewards", default="",
                    help="comma-separated reward function names from rewards.py")
    ap.add_argument("--rollout", default="transformers",
                    choices=("transformers", "vllm"))
    ap.add_argument("--vllm-base-url", default="")
    args = ap.parse_args()

    # ---- guards, before anything is opened -------------------------------------------
    if not HF_HOME.is_dir():
        print(f"HF_HOME does not resolve: {HF_HOME}", file=sys.stderr)
        emit(event="error", kind="MissingWeightCache", stage="load_model")
        return 2
    dataset_path = pathlib.Path(args.dataset).resolve(strict=False)
    if dataset_path in DENIED or (ROOT / "training" / "adapter").resolve() in dataset_path.parents:
        # Refused, and refused loudly. This is the second of two independent checks -- the API
        # refuses in `datasets.admit()` before it ever launches this process -- because a
        # single guard is a guard that a future caller can bypass by not going through the API.
        print("refusing a protected SyMoNeuRaL artefact as a dataset", file=sys.stderr)
        emit(event="error", kind="ProtectedArtefact", stage="load_dataset")
        return 3

    progress_file = pathlib.Path(args.progress_file) if args.progress_file else None
    started = time.time()
    stage = "load_dataset"

    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from transformers import (AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig,
                                  DataCollatorForSeq2Seq, Trainer, TrainerCallback,
                                  TrainingArguments)

        random.seed(args.seed)
        torch.manual_seed(args.seed)

        rows = []
        with dataset_path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.strip():
                    rows.append(json.loads(line))
        if args.max_examples:
            rows = rows[: args.max_examples]
        random.Random(args.seed).shuffle(rows)

        # The validation split the shipped trainer does not have. The repo manual is explicit:
        # hold out 5-10% BEFORE looking at training loss. Without it a loss curve is a report
        # on memorisation, which is why no figure from the existing adapter means anything.
        #
        # `--val-split 0` is honoured rather than floored, and the reinforcement preset uses it:
        # GRPO has no held-out loss to compute -- its objective is the reward, measured on the
        # model's own samples as they are drawn -- so holding back a tenth of the prompts would
        # spend training signal on an eval the method does not define.
        n_val = max(1, int(len(rows) * args.val_split)) if args.val_split > 0 and len(rows) > 4 else 0
        val_rows, train_rows = rows[:n_val], rows[n_val:]
        emit(event="start", rows=len(train_rows), val_rows=len(val_rows), seed=args.seed)

        # Reward functions are checked BEFORE the model is loaded, which is the whole point of
        # doing it here. `rewards.selfcheck()` runs every function over synthetic strings and
        # verifies the contract -- one float per completion, inside its published range. A reward
        # function that raises, or that returns 5.0 where the table promises 1.0 and therefore
        # silently dominates every other term, is a bug worth finding in the first second of a
        # run rather than the twentieth minute.
        #
        # Loaded by explicit path, not by import name. `sys.path` had this directory REMOVED at
        # the top of the file to stop `from datasets import Dataset` resolving to a sibling, and
        # that fix is what makes a plain `import rewards` fail here. Naming the file is the
        # honest consequence of a guard that is worth keeping.
        reward_plan = None
        if args.method == "reinforcement":
            stage = "check_rewards"
            import importlib.util
            spec = importlib.util.spec_from_file_location("_rf_rewards", HERE / "rewards.py")
            rewards_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(rewards_mod)
            problems = rewards_mod.selfcheck()
            if problems:
                print("reward self-check failed: " + "; ".join(problems), file=sys.stderr)
                emit(event="error", kind="RewardContractViolation", stage="check_rewards")
                return 4
            fields = sorted({k for row in train_rows[:200] for k in ("answer",) if row.get(k)})
            names = [n for n in args.rewards.split(",") if n]
            reward_plan = rewards_mod.resolve(names, available_fields=fields)
            emit(event="start", rewards=len(reward_plan["funcs"]))
            stage = "load_dataset"

        stage = "load_model"
        tok = AutoTokenizer.from_pretrained(args.model)
        if tok.pad_token is None:
            tok.pad_token = tok.eos_token

        def _encode(row: dict) -> dict:
            """Render with the model's own chat template, then mask everything but the answer.

            Carried forward verbatim from `training/train_lora.py`, and deliberately NOT
            replaced by trl's `assistant_only_loss`. That flag needs `{% generation %}` markers
            in the chat template so trl can find the assistant span; the stock Qwen2.5 template
            has none, so it would fail rather than silently mis-mask. The hand-rolled -100 mask
            is a workaround for a real gap, not legacy cruft.

            Why mask at all: training on the prompt teaches the model to predict questions,
            which dilutes the gradient that carries the behaviour being taught.
            """
            msgs = row["messages"]
            prompt = tok.apply_chat_template(msgs[:-1], tokenize=False, add_generation_prompt=True)
            answer = msgs[-1]["content"] + tok.eos_token
            p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
            a_ids = tok(answer, add_special_tokens=False)["input_ids"]
            ids = (p_ids + a_ids)[: args.max_length]
            labels = ([-100] * len(p_ids) + a_ids)[: args.max_length]
            return {"input_ids": ids, "labels": labels, "attention_mask": [1] * len(ids)}

        def _as_conversation(value):
            """A prompt as a conversation, so the model's own chat template gets applied.

            trl treats a plain string `prompt` column as the *standard* (non-conversational)
            format and feeds it to the model raw -- no chat template, no `<|im_start|>assistant`
            turn. On an instruct model that is a real quality bug rather than a formatting
            nicety: the policy is being sampled outside the format it was tuned in, so the
            completions are worse than the model is, and the reward curve measures that instead
            of what it claims to.
            """
            if isinstance(value, str):
                return [{"role": "user", "content": value}]
            return value

        dropped_long = 0
        if args.method == "sft":
            keep = ["input_ids", "labels", "attention_mask"]
            train_ds = Dataset.from_list(train_rows).map(
                _encode, remove_columns=[c for c in Dataset.from_list(train_rows).column_names
                                         if c not in keep])
            eval_ds = (Dataset.from_list(val_rows).map(
                _encode, remove_columns=[c for c in Dataset.from_list(val_rows).column_names
                                         if c not in keep]) if val_rows else None)

        elif args.method == "preference":
            # DPOTrainer tokenises the prompt/chosen/rejected columns itself, so there is no
            # `_encode` here and no hand-rolled mask: the objective is a comparison between two
            # completions, and trl builds both sides. Columns are passed through as authored.
            def _pair(row: dict) -> dict:
                return {"prompt": _as_conversation(row["prompt"]),
                        "chosen": _as_conversation(row["chosen"]),
                        "rejected": _as_conversation(row["rejected"])}

            train_ds = Dataset.from_list([_pair(r) for r in train_rows])
            eval_ds = Dataset.from_list([_pair(r) for r in val_rows]) if val_rows else None

        else:   # reinforcement
            # The prompt-length bound, enforced HERE because trl 1.10.0's `GRPOConfig` has no
            # `max_prompt_length` field -- a checked absence, not an oversight of ours. Over-long
            # prompts are DROPPED rather than truncated: a prompt cut off mid-sentence produces
            # completions that are bad for a reason that has nothing to do with the policy, and
            # those completions would then be scored and reinforced against. Dropping loses a
            # row; truncating poisons the gradient.
            #
            # The count is reported. The rows are not: no route, no log line and no error
            # message from this surface names a dataset row.
            def _prompt_ok(row: dict) -> bool:
                convo = _as_conversation(row["prompt"])
                text = tok.apply_chat_template(convo, tokenize=False, add_generation_prompt=True)
                return len(tok(text, add_special_tokens=False)["input_ids"]) <= args.max_length

            kept = []
            for row in train_rows:
                if _prompt_ok(row):
                    out_row = {"prompt": _as_conversation(row["prompt"])}
                    if row.get("answer") is not None:
                        out_row["answer"] = row["answer"]
                    kept.append(out_row)
                else:
                    dropped_long += 1
            if not kept:
                print("every prompt exceeded the prompt cap", file=sys.stderr)
                emit(event="error", kind="AllPromptsTooLong", stage="load_dataset")
                return 5
            if dropped_long:
                emit(event="start", dropped_long=dropped_long)
            train_rows = kept
            train_ds = Dataset.from_list(kept)
            # No eval dataset: GRPO defines no held-out loss. See the val_split note above.
            eval_ds = None

        model = AutoModelForCausalLM.from_pretrained(
            args.model,
            quantization_config=BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True,
            ),
            dtype=torch.bfloat16,
            device_map={"": 0},
        )
        # The KV cache is switched off for the two methods that only ever run forward-backward
        # over text they were given, and LEFT ON for the one that generates. A GRPO step samples
        # `num_generations` completions per prompt before it can compute a reward; doing that
        # without a cache re-runs attention over the whole prefix for every token, which turns
        # the sampling phase from the expensive part of a step into the entire step.
        #
        # Gradient checkpointing and the cache are not actually in conflict here: transformers
        # disables the cache inside a checkpointed training forward on its own and restores it
        # for `generate`. Forcing `use_cache = False` globally would leave generation slow with
        # nothing gained.
        model.config.use_cache = (args.method == "reinforcement")

        stage = "build_adapter"
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
        lora_cfg = LoraConfig(
            r=args.rank, lora_alpha=args.alpha, lora_dropout=args.dropout, bias="none",
            task_type="CAUSAL_LM",
            target_modules=[m for m in args.target_modules.split(",") if m],
        )
        init_adapter = args.init_adapter.strip()
        if init_adapter:
            # Continue from an existing adapter rather than a freshly initialised one.
            #
            # This is what makes the reinforcement method usable on this product at all. The
            # standard pipeline is supervised first, then RL on top of it: the shipped SymonChat
            # persona adapter IS the supervised stage, and starting a GRPO run from random
            # low-rank matrices would ask a reward function to re-derive the company voice from
            # scratch. A reward function cannot carry that, and the run would spend its whole
            # budget rediscovering what the corpus already taught.
            #
            # `is_trainable=True` is required and easy to miss: `PeftModel.from_pretrained`
            # loads adapters in INFERENCE mode by default, with `requires_grad=False` on every
            # LoRA weight. Without it this runs to completion, reports a loss, and saves an
            # adapter identical to the one it started from -- a silent no-op that looks like a
            # successful run. The trainable-parameter count emitted below is what catches it.
            #
            # The rank and target modules come from the loaded adapter, not from the preset: an
            # adapter's shape is fixed at the moment it was created. So a preset's `rank` is
            # ignored on this path, and the manifest records which one actually applied rather
            # than the one that was asked for.
            from peft import PeftModel
            model = PeftModel.from_pretrained(model, init_adapter, is_trainable=True)
        else:
            model = get_peft_model(model, lora_cfg)
        trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
        total = sum(p.numel() for p in model.parameters())
        emit(event="start", trainable=trainable, total_params=total)
        if init_adapter and trainable == 0:
            # Refused rather than run. A run with nothing trainable produces a copy of its input
            # and a plausible-looking log, which is the most expensive possible way to learn
            # that `is_trainable` was missed.
            print("the initial adapter loaded with no trainable parameters", file=sys.stderr)
            emit(event="error", kind="AdapterNotTrainable", stage="build_adapter")
            return 6

        stage = "train"
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()

        class Progress(TrainerCallback):
            """Emit a real reading per logging step. No smoothing, no interpolation.

            The VRAM figures are `torch.cuda.max_memory_allocated()` and
            `max_memory_reserved()` -- measured inside the process that is doing the
            allocating, which is the only place they can be measured honestly. `nvidia-smi`
            from outside would see this process's reservation plus everything else on the card.
            """

            def on_log(self, targs, state, control, logs=None, **kw):
                logs = logs or {}
                alloc = int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else 0
                reserved = int(torch.cuda.max_memory_reserved()) if torch.cuda.is_available() else 0
                # Whichever of the known metrics this trainer actually logged, under the
                # allowlisted name for each. The supervised path logs `loss`; GRPO logs `reward`
                # and `kl` and may not log a loss at all; DPO logs `rewards/chosen` and friends,
                # whose `/` would be dropped by `emit()` if it were not mapped here.
                #
                # An RL step is reported whenever ANY known metric is present, not only when a
                # `loss` key is. Keying the whole report off `loss` -- which is what this
                # callback used to do -- would leave a live GRPO run emitting nothing at all,
                # and the panel would show a running job with an empty curve.
                found = {out_key: logs[in_key] for in_key, out_key in _METRIC_KEYS.items()
                         if in_key in logs and isinstance(logs[in_key], (int, float))}
                if found:
                    payload = {
                        "event": "step", "step": state.global_step,
                        "total_steps": state.max_steps,
                        "epoch": round(float(state.epoch or 0), 4),
                        "elapsed_s": round(time.time() - started, 1),
                        "vram_alloc": alloc, "vram_reserved": reserved,
                        **found,
                    }
                    emit(**payload)
                    if progress_file:
                        _write_atomic(progress_file,
                                      {k: v for k, v in payload.items() if k != "event"})
                if "eval_loss" in logs:
                    emit(event="eval", step=state.global_step, val_loss=logs["eval_loss"])

        targs = dict(
            output_dir=str(pathlib.Path(args.out) / "checkpoints"),
            num_train_epochs=args.epochs,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=args.grad_accum,
            gradient_checkpointing=True,
            learning_rate=args.lr,
            lr_scheduler_type=args.scheduler,
            # Steps, never `warmup_ratio`: that argument is absent from transformers 5.15.0 and
            # trl 1.10.0 on this box, and code copied from older guides raises TypeError here.
            warmup_steps=max(1, int(0.05 * len(train_rows) * args.epochs / max(1, args.grad_accum))),
            logging_steps=1,
            save_strategy=args.save_strategy,
            bf16=True,
            optim="paged_adamw_8bit",
            seed=args.seed,
            report_to=[],
        )
        if args.max_steps:
            # `max_steps` overrides the epoch count outright, which is what makes a smoke test
            # a fixed handful of steps regardless of how large the dataset happens to be.
            targs["max_steps"] = args.max_steps
        if eval_ds is not None:
            targs["eval_strategy"] = "epoch" if not args.max_steps else "no"
            targs["per_device_eval_batch_size"] = 1

        if args.method == "sft":
            trainer = Trainer(
                model=model, train_dataset=train_ds, eval_dataset=eval_ds,
                data_collator=DataCollatorForSeq2Seq(tok, padding=True, label_pad_token_id=-100),
                args=TrainingArguments(**targs), callbacks=[Progress()],
            )

        elif args.method == "preference":
            stage = "load_reference"
            from trl import DPOConfig, DPOTrainer
            dpo = dict(targs)
            dpo["beta"] = args.beta
            dpo["max_length"] = args.max_length
            if args.loss_type:
                dpo["loss_type"] = args.loss_type
            if args.precompute_ref_log_probs:
                # Reference log-probabilities computed once, before the optimiser and its state
                # exist, then cached. This is what keeps the reference forward pass out of the
                # training peak on a card with no headroom -- see `registry.method_terms`.
                dpo["precompute_ref_log_probs"] = True
                dpo["precompute_ref_batch_size"] = 1
            trainer = DPOTrainer(
                model=model,
                # `ref_model=None` against a peft model is the whole trick: trl disables the
                # adapter to get the reference log-probabilities and re-enables it afterwards,
                # so the reference is the base weights already on the card. Passing a second
                # `AutoModelForCausalLM` here would load another 4-bit 7B and OOM immediately,
                # and it is the obvious thing to write.
                ref_model=None,
                args=DPOConfig(**dpo), train_dataset=train_ds, eval_dataset=eval_ds,
                processing_class=tok, callbacks=[Progress()],
            )
            stage = "train"

        else:   # reinforcement
            stage = "rollout"
            from trl import GRPOConfig, GRPOTrainer
            grpo = dict(targs)
            grpo.update(
                num_generations=args.num_generations,
                max_completion_length=args.max_completion_length,
                beta=args.beta,
                temperature=args.temperature,
                top_p=args.top_p,
                scale_rewards=args.scale_rewards,
                mask_truncated_completions=args.mask_truncated_completions,
                # Extra dataset columns must survive to reach the reward functions -- `answer`
                # is passed to `answer_match` as a keyword argument by trl. The inherited
                # default would strip any column the model's forward signature does not name,
                # which silently disables every dataset-dependent reward.
                remove_unused_columns=False,
                # Completions are written to the trainer's own logs for a human to read. The
                # reward curve alone is not a report on an RL run: a rising reward with worse
                # completions is reward hacking, and the completions are how it is spotted.
                log_completions=True,
                num_completions_to_print=2,
                use_cache=True,
                # On the CONFIG, not on the trainer: `GRPOTrainer.__init__` takes `reward_funcs`
                # but has no `reward_weights` parameter in trl 1.10.0, and passing it there is a
                # TypeError at construction. The weights are the relative pull of each reward
                # function in the sum, and `rewards.py` states each one with its reason.
                reward_weights=reward_plan["weights"],
            )
            if args.loss_type:
                grpo["loss_type"] = args.loss_type
            if args.rollout == "vllm":
                # Server mode only, and never a silent fallback: if the endpoint is not
                # reachable the run fails rather than quietly generating in-process at a
                # different speed and a different sampling implementation. Colocate mode is
                # refused by arithmetic in `presets.NOT_IN_V1`.
                grpo["use_vllm"] = True
                grpo["vllm_mode"] = "server"
                if args.vllm_base_url:
                    grpo["vllm_server_base_url"] = args.vllm_base_url
            trainer = GRPOTrainer(
                model=model, reward_funcs=reward_plan["funcs"],
                args=GRPOConfig(**grpo), train_dataset=train_ds,
                processing_class=tok, callbacks=[Progress()],
            )
            stage = "train"

        trainer.train()

        stage = "evaluate"
        val_loss = None
        if eval_ds is not None:
            metrics = trainer.evaluate()
            val_loss = metrics.get("eval_loss")
            emit(event="eval", step=trainer.state.global_step, val_loss=val_loss)

        stage = "save"
        out = pathlib.Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(str(out))
        tok.save_pretrained(str(out))

        peak_alloc = int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else 0
        peak_reserved = int(torch.cuda.max_memory_reserved()) if torch.cuda.is_available() else 0
        elapsed = time.time() - started

        # The run manifest. The shipped adapter has none -- no seed, no hyperparameters, no
        # results -- which is why it is not reproducible and why nothing about it can be
        # quoted. Every run from this surface writes one, beside its own weights.
        #
        # It records the DATASET'S SHAPE (name, row counts) and never its contents. It also
        # records the resolved path, which is fine here: the manifest sits beside the adapter
        # under run/, and no route in this package serves it.
        manifest = {
            "run": {"preset": args.preset, "model": args.model_id or args.model,
                    "method": args.method, "dataset_schema": args.dataset_schema,
                    "seed": args.seed, "started_at": started, "elapsed_s": round(elapsed, 1),
                    "elapsed_label": "measured"},
            # The method's own settings, recorded whatever the method -- an empty dict for a
            # supervised run rather than an absent key, so a reader never has to work out
            # whether a missing field means "not applicable" or "not recorded".
            "method_config": ({
                "beta": args.beta,
                "loss_type": args.loss_type or "trl default",
                "precompute_ref_log_probs": bool(args.precompute_ref_log_probs),
                "reference": ("peft-implicit: ref_model=None with the adapter disabled, so the "
                              "reference costs a forward pass and no weight bytes"),
            } if args.method == "preference" else {
                "num_generations": args.num_generations,
                "max_completion_length": args.max_completion_length,
                "prompt_cap_tokens": args.max_length,
                "prompts_dropped_over_cap": dropped_long,
                "beta": args.beta,
                "kl_penalty": ("off -- no reference forward pass, and no KL tether holding the "
                               "policy near behaviour learned from real examples"
                               if args.beta == 0 else f"on at beta={args.beta}"),
                "loss_type": args.loss_type or "trl default",
                "temperature": args.temperature,
                "top_p": args.top_p,
                "scale_rewards": args.scale_rewards,
                "rollout": args.rollout,
                "rewards": list(reward_plan["names"]) if reward_plan else [],
                "reward_weights": list(reward_plan["weights"]) if reward_plan else [],
                "rewards_refused": list(reward_plan["refused"]) if reward_plan else [],
                "reward_note": ("rules-based functions from rewards.py, every one verifiable by "
                                "reading the program. There is no reward model on this box. A "
                                "rising reward curve is evidence that THIS PROGRAM's score went "
                                "up -- it is not by itself evidence that the model got better, "
                                "and with beta=0 there is no structural guard against a reward "
                                "function's loophole being found and exploited"),
            } if args.method == "reinforcement" else {}),
            "initialised_from": (init_adapter or "a freshly initialised adapter"),
            "initialised_from_note": (
                ("continued from an existing adapter, so the rank and target modules are that "
                 "adapter's and NOT this preset's -- an adapter's shape is fixed when it is "
                 "created. Nothing was written back to it.")
                if init_adapter else
                ("started from random low-rank matrices. For the reinforcement method that is "
                 "usually the wrong choice: the standard pipeline is supervised first and RL on "
                 "top, so --init-adapter pointed at the persona adapter is the intended path.")),
            "hyperparameters": {
                "epochs": args.epochs, "max_steps": args.max_steps or None,
                "rank": args.rank, "lora_alpha": args.alpha, "lora_dropout": args.dropout,
                "learning_rate": args.lr, "lr_scheduler_type": args.scheduler,
                "max_length": args.max_length, "per_device_train_batch_size": 1,
                "gradient_accumulation_steps": args.grad_accum,
                "effective_batch": args.grad_accum,
                "target_modules": args.target_modules.split(","),
                "gradient_checkpointing": True, "bf16": True,
                "optim": "paged_adamw_8bit",
                "quantisation": "4-bit NF4 + double quantisation, bf16 compute",
                "warmup_steps": targs["warmup_steps"],
            },
            "dataset": {"name": dataset_path.name, "train_rows": len(train_rows),
                        "val_rows": len(val_rows), "label": "measured",
                        "note": "shape only; contents are never recorded in a manifest"},
            "results": {
                "trainable_params": trainable, "total_params": total,
                "trainable_pct": round(100.0 * trainable / total, 4) if total else None,
                "final_train_loss": trainer.state.log_history[-1].get("train_loss")
                                    if trainer.state.log_history else None,
                "val_loss": val_loss,
                "steps": trainer.state.global_step,
                "peak_vram_alloc_bytes": peak_alloc,
                "peak_vram_reserved_bytes": peak_reserved,
                "label": "measured",
                "note": ("peak VRAM read from torch inside this process. This retires the "
                         "projection for THIS model and THIS preset only -- scaling it to "
                         "another cell would be a projection wearing a measurement's label."),
            },
            "serving": ("this adapter is PEFT safetensors. The chat surface loads a GGUF "
                        "adapter, so it is not served until somebody converts it deliberately. "
                        "Nothing here promotes a run to the serving adapter."),
        }
        (out / "run-manifest.json").write_text(json.dumps(manifest, indent=2))

        # The measured-peaks ledger, keyed by the exact cell that was measured.
        if args.measured_file and peak_alloc:
            mf = pathlib.Path(args.measured_file)
            try:
                ledger = json.loads(mf.read_text())
            except (OSError, json.JSONDecodeError):
                ledger = {}
            ledger[f"{args.model_id or args.model}|{args.preset}"] = {
                "peak_alloc": peak_alloc, "peak_reserved": peak_reserved,
                "steps": trainer.state.global_step, "at": time.time(),
            }
            _write_atomic(mf, ledger)

        emit(event="done", peak_alloc=peak_alloc, peak_reserved=peak_reserved,
             elapsed_s=round(elapsed, 1), step=trainer.state.global_step)
        return 0

    except BaseException as exc:            # noqa: BLE001 -- every exit goes through _fail
        return _fail(stage, exc)


if __name__ == "__main__":
    raise SystemExit(main())
