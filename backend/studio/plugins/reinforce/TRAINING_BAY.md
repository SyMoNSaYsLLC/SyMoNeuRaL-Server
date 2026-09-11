# SyMoNeuRaL Reinforce — the training bay

**Not to be confused with `README.md` in this same directory**, which documents the native CUDA
engine in `symoneural/`. Two different things share this package: the engine is hand-written CUDA
kernels compiled by NVRTC, and the training bay is the QLoRA tuning application described here.
They share a name and nothing else.

The bay is: `registry.py`, `presets.py`, `dataset_guard.py`, `rewards.py`, `rollout.py`,
`jobs.py`, `runner.py`, `routes.py`, `page.html`, `page.js`, and the two test suites
`test_reinforce.py` and `test_page.mjs`.

---

## What it does

Fine-tunes a model that is genuinely on this box, as a 4-bit low-rank adapter, on one RTX 5070 Ti
(15.92 GiB, Blackwell sm_120). Three objectives:

| Objective | Optimises | Dataset | Reference model | Generates? | Trainer |
|---|---|---|---|---|---|
| `sft` — imitation | likelihood of answers you supply | `messages` | no | no | `transformers.Trainer` |
| `preference` | the gap between a preferred and a rejected answer | `preference` | yes | no | `trl.DPOTrainer` |
| `reinforcement` | a reward on answers the model writes itself | `prompt` | only if `beta > 0` | **yes** | `trl.GRPOTrainer` |

**Only the third is reinforcement learning.** DPO optimises a preference objective in closed
form and never samples; it is usually filed under RLHF and it is not RL, and this package does not
call it that. `presets.METHODS[...]["is_rl"]` is the single source of that claim and a test asserts
exactly one method carries it.

The objective is **a property of the profile, not an independent choice.** `StartBody` has no
`method` field and the panel has no objective dropdown, because a request that paired a rank-16
chat profile with a preference objective would produce a configuration whose dataset schema and
hyperparameters contradict each other.

## The two objections that kept preference and RL out of v1, and how each was answered

`presets.NOT_IN_V1` and `docs/specs/qlora-upgrade.md` §5.4 both named DPO/GRPO as omitted, for two
stated reasons. Neither was wrong; both turned out to be answerable.

1. **"No VRAM for a reference model beside the policy."** True for a second set of weights, and
   there is never one. With peft, `ref_model=None` makes trl compute the reference pass by
   *disabling the adapter* on the model already resident — the reference **is** the base model,
   which is loaded either way. It costs a forward pass, not a copy. For DPO,
   `precompute_ref_log_probs=True` moves even that pass out of the training peak entirely,
   because it happens before the optimiser state exists.
2. **"No paired preference data."** Still true, and it is now a **stated precondition enforced by
   a schema check** rather than a reason to omit the method. `dataset_guard` refuses a chat file
   handed to a preference run, by name, with the shape it wanted — instead of failing inside a
   collator twenty minutes in while holding the card.

## "like what is in llama.cpp and vllm"

That is a question about **where completions come from**, and it has three different honest
answers. `rollout.py` is the whole argument; the short version:

- **`transformers`, in-process — the default and the only one that works here.** The model being
  trained generates with the adapter live, so it is on-policy by construction. Slow: no continuous
  batching, no paged attention.
- **vLLM — supported as an external server, refused as a co-tenant.** Colocate mode wants a second
  copy of the weights plus a pre-allocated KV pool; the training process alone projects near
  12 GiB of a ~14.2 GiB practical budget, and there is no value of `vllm_gpu_memory_utilization`
  that leaves both alive. Server mode is genuinely how RL is done at scale and needs a machine that
  is not this one. Configure with `SYMONEURAL_REINFORCE_VLLM_URL`; an unreachable endpoint **refuses the
  run** rather than falling back, because a silent fallback changes the sampling implementation
  without changing the label on the run.
- **llama.cpp — refused for rollouts, on correctness.** It is already built here and already fast,
  and it still cannot do this: `llama-server` holds a Q4_K_M GGUF of the *base* model and cannot
  carry an adapter that changes every optimiser step. Its completions and their log-probabilities
  would belong to a different model than the one taking the gradient — off-policy from step 1, and
  silently. It also cannot co-reside, since `train` holds the governor lock and is never evicted.

  **llama.cpp's real role here is the other end of the pipeline: it *serves* a GGUF LoRA.** That is
  what makes an adapter promotable, and it is why the trainer's PEFT output must be converted
  before chat can run it.

  The general form: *a fast generator that is not the policy is not a rollout engine — it is a
  different model's opinion.*

## Rewards

There is **no learned reward model**, and there will not be one on this card: it needs a second
network of comparable size resident beside the policy. What runs instead is a small set of rules
in `rewards.py` — stdlib only, so both interpreters can import it — each returning one float per
completion inside a published range, combined by weight.

The honest framing, which the panel repeats: **a rising reward is evidence that a program's score
went up.** It is not by itself evidence that the model improved. No human evaluation has been run
on this box and no quality claim is made anywhere in this package.

Rules-based rewards are auditable *and* gameable, and one of them is worth naming: `figure_labelling`
can be earned by labelling everything "measured", which is the precise dishonesty the labelling
rule exists to prevent. It is weighted below `pricing_refusal` for that reason and `beta` is
documented as the trade. That is a managed risk, not a solved problem.

**The rules are described; the patterns are never published.** How a behaviour is detected is
method rather than number — publish the numbers, keep the methods — and publishing the expression
a policy is scored against publishes the loophole. `rewards.offered()` carries
`patterns_published: False` and a test asserts no pattern leaks into the API response.

`resolve()` **refuses rather than silently dropping**: a reward needing a dataset column the file
does not have is named in the preflight response, because a run that quietly trained against fewer
functions than were configured would report a reward curve meaning something other than what the
panel says.

## The supervised → RL pipeline (`--init-adapter`)

The standard pipeline is **supervised first, reinforcement on top**. A reinforcement run started
from a freshly initialised adapter throws away the house voice and optimises a scoring function
against the raw base model, so `--init-adapter` exists and the panel tells an RL run that leaving
it empty is usually wrong.

`training/adapter/` — the shipped Symon adapter — is **allowed as a read-only starting point and
still denied as a dataset**. That asymmetry is deliberate: reading weights to continue training is
not serving a corpus over HTTP. Three guards make it safe:

- `PeftModel.from_pretrained(..., is_trainable=True)`, with a `trainable == 0` check that exits 6.
  Without it, peft loads adapters in inference mode, the run completes, reports a loss, and saves a
  copy of its input — a silent no-op that looks like a successful run.
- Output always goes to `run/reinforce/adapters/<job-id>`. **Nothing is ever written back** to the
  adapter that was named.
- Promotion to the serving adapter stays a deliberate manual act. A page reading "trained" while
  chat still ran the previous adapter would be a dishonest status.

## Cost model

`registry.plan_fit(..., method=, method_config=)` charges each objective its real terms:

- **reinforcement** — `rollout_kv_cache` + `rollout_group_activations` at effective batch
  `num_generations` over prompt+completion, plus `reference_forward` **only when `beta > 0`**.
  Logits are charged over the completion window only, per `grpo_trainer.py:2503`
  (`logits_to_keep = completion_ids.size(1)`) — ~0.87 GiB rather than ~2.61 GiB.
- **preference** — the *second* sequence only, since chosen/rejected are concatenated on the batch
  dimension (`dpo_trainer.py:356-359`) and the base plan already charges the first. The reference
  forward is charged **0 at peak** when `precompute_ref_log_probs` is set.

`num_generations` multiplies every activation term, which is why it — not the rank — is the first
rung on the RL ladder. Rank is the smallest term on an RL run's panel; offering it first would
point the operator at the wrong knob.

**None of this has been measured.** There is exactly one real peak behind this package's
arithmetic and it is a supervised run — the one that found the projection 2.03 GiB light and
corrected the 14B verdict. `plan_fit()` returns `method_accuracy` saying so in as many words, so
the RL terms cannot borrow the supervised measurement's error bar.

`GRPOConfig` has **no `max_prompt_length` field**, so the prompt cap is enforced in this package
before the card is taken; over-long prompts are dropped and counted (`dropped_long`), never
truncated and never named.

## The log protocol, and the failures that are silent

The runner prints `REINFORCE key=value` on stdout and `jobs.parse_log()` reads it through an
allowlist. Two failure modes here are **completely silent** and each has a test:

A third pair has the same shape and is the expensive one: **every keyword handed to `DPOConfig`
and `GRPOConfig` is checked against the installed trl**, by `TrlContractTests`, which reads the
dataclass fields out of `training/.venv` in a subprocess. A misspelled field is a `TypeError` at
stage `train` — *after* a governor acquire of up to 300 s and a 4-bit load of a 7B, having taken
the card from chat and image to get there. Preflight cannot see it, because preflight never
constructs a trl object. `reward_weights` is the proof it is not hypothetical: it reads as a
`GRPOTrainer` argument, it is not one, and only a source read caught it.

A fourth: `jobs.py` builds an argv and `runner.py` parses one, and neither imports the other. A
flag on one side only is argparse exit 2 on **stderr**, which `parse_log()` never reads — so the
panel shows a failed run with no kind and no stage. `ArgvContractTests` asserts the 36 flags agree.

A fifth, one layer later than construction and the most expensive of the set: **how trl *calls* a
reward function.** `grpo_trainer.py:1672` passes `prompts=`, `completions=`, `completion_ids=` and
then splats `reward_kwargs` — every surviving dataset column, which is why
`remove_unused_columns=False` is set, plus `trainer_state` and `log_metric` unconditionally. A
reward that does not absorb arbitrary keywords raises `TypeError` at the **first reward
computation**: inside the training loop, after the acquire, after the 4-bit load, after a group of
rollouts has already been generated and paid for. `RewardInvocationTests` asserts every offered
reward takes `**kwargs` and then calls each one with the exact keyword set trl uses, checking it
returns one finite-or-`None` value per completion — trl raises by name and count otherwise.

Values, as opposed to field names, are checked two ways because trl affords only two. `optim`,
`lr_scheduler_type` and the strategies are enum-validated, so every preset's real config is
**constructed** in the training venv and a bad value raises there. `loss_type`, `scale_rewards`
and `vllm_mode` are annotated plain `str` with no `Literal`, and `GRPOConfig(scale_rewards=
"banana")` raises nothing at all — verified — so those are checked against trl's own default and
the values its `help` metadata names. `vllm_mode` is the one that matters: it defaults to
`colocate`, the mode this package refuses by arithmetic.

- A metric key absent from `jobs._ALLOWED_KEYS` is **dropped**, so a live RL run shows an empty
  reward curve. trl logs names like `rewards/chosen`, and `/` is outside the value character class
  — `runner._METRIC_KEYS` maps them, and `MetricProtocolTests` asserts the two ends agree per key.
- An unrecognised `stage=` discards the **entire line, including `event=error`**, so a run failing
  in a stage one file knows about and the other does not reports nothing at all. `runner.STAGES`
  and `jobs._ENUM_VALUES["stage"]` are asserted equal.

Errors report an exception's **class name and stage only**, never its message: a tokeniser
traceback can carry a training example in it.

## Before you can train: the base weights live on Drive, by design

**The `symon-1.0-*` models and the `Qwen/*` catalogue rows are the same models at two
stages.** `symon-1.0-14b-q4_k_m` *is* `Qwen2.5-14B-Instruct`, converted and house-named;
`symon-1.0-27b-*` is `Qwen3.6-27B`. `backend/models/PROVENANCE.json` is the record, and the
catalogue now reads it — every GGUF row carries `upstream` and `same_model_as`, and the
upstream rows name the house model they became.

That matters because of where each stage is stored. The model-storage policy is:

> Local `backend/models/` — only canonical SyMoNeuRaL house-named runnable artifacts and
> required local metadata/state.
> Drive `Models/` — public/original upstream distributions **and conversion inputs**.

So the HF cache under `backend/models/hf/` holds **metadata only**: config, tokenizer and the
safetensors *filenames*, as symlinks whose blobs are on Drive. `du` reports 2.6 MB. That is
the policy executed correctly, **not damage** — broken symlinks are the shape
`huggingface_hub` leaves behind when blobs are removed.

**To train, fetch the base safetensors back from Drive `Models/` first.** That is a normal
pre-training step, not an incident. `jobs.preflight()` will refuse a model with
`present=False` rather than starting a download from an HTTP handler, and `scan_hf_cache()`
now says which state a row is in:

```
Qwen/Qwen2.5-7B-Instruct   present=False   same_model_as=symon-1.0-7b-q4_k_m
  OFFLOADED, not missing: 11 of 11 files in this snapshot are symlinks whose blobs are not
  on this box. ... To TRAIN, fetch the base safetensors back from Drive first; the runtime
  does not need them and works with Drive unavailable.
```

**The runtime does not need any of this**, and that is the point of the split: 37 GB of GGUF
inference weights are local and intact and `tools/lib/smoke.py` reports `model weights present
5/5`. Serving works with Drive unavailable; training is the occasional operation that reaches
for it.

**Written down because it was not, and the cost was real.** A commissioning pass on
2026-09-09 found `scan_hf_cache()` returning nothing, read the 2.6 MB cache and the broken
symlinks as lost training weights, and published it as a finding against the project's
standing objective. Every field it read was true. Nothing recorded that the two catalogue
rows were one model, or that an offloaded cache is the intended steady state.

## Running it

```bash
# The suites. 124 python assertions, 50 in a real browser. Six of the 124 read trl's real
# dataclasses out of `training/.venv` in a subprocess and SKIP if that venv is absent -- so
# "124 passed, 0 skipped" is a claim about a box that has it.
python3 backend/apps/studio/plugins/reinforce/test_reinforce.py

# The last FOUR of the 50 load the deployed `site/reinforce.html` rather than the `page.html`
# fragment, so generate it first or they fail on a file that is merely absent. They exist
# because `tools/build/build_reinforce.py` unwraps the fragment's `<section><div class="wrap">` and
# has to carry `id="reinforce"` through: every selector in the fragment's sheet is
# `#reinforce .rf-*`, so losing the id renders the panel UNSTYLED with all its text intact.
# No content assertion and no JS-error check can see that, which is why one reads a computed
# colour -- `.rf-lab-measured` must be rgb(127,215,164). Confirmed against a negative control:
# dropping the id fails exactly those two assertions and leaves the other 48 passing.
python3 tools/build/build_reinforce.py
node    backend/apps/studio/plugins/reinforce/test_page.mjs

# The surface is off unless BOTH are set. A never-evicted GPU route open to the world is a
# rack-wide denial of service costing one HTTP request.
export SYMONEURAL_REINFORCE_ENABLED=1
export SYMONEURAL_REINFORCE_TOKEN=...
export SYMONEURAL_REINFORCE_VLLM_URL=...      # optional; external rollout server, never localhost

# Everything touching the GPU goes through the governor, which always releases.
scripts/gpu-governor.sh with train -- <cmd>
```

Reads (`/models`, `/presets`, `/status`, `/datasets`) are open once enabled; **writes (`/start`,
`/stop`) always require the token**, in a header and never a URL — uvicorn logs the full request
line. A configuration that does not fit returns **501, not 500**: "this box cannot" is not
"broken".

## What is deliberately not offered

`presets.NOT_IN_V1`, each entry carrying its reason — an omission without a reason is a shrug, and
a test enforces >80 characters of it:

`full_fine_tuning`, `multi_gpu`, `reward_model_training`, `kto_and_online_dpo`,
`vllm_colocated_rollouts`, `llama_cpp_rollouts`.

`preference_tuning` is **no longer** in that list, and a test asserts it is absent.

## Standing constraints

- **`training/corpus.jsonl` and `training/build_dataset.py` are trade secret.** Never copy them
  into `site/`, never serve them from an endpoint, never quote them into a page or a commit
  message. No route here returns dataset contents and no error quotes a line — refusals report a
  line *number* and a category.
- `parse_log()` is an allowlist and must never gain a pass-through branch "just for debugging".
- Never call a bare `release` on the governor; always name the surface. `train` is never evicted.
- Every figure is labelled **measured**, **vendor** or **projected**. No decorative indicators —
  which includes charts: every series on the panel names the step window it was drawn from,
  because `/status` returns a tail of the log rather than the run's history.
- No `text-overflow:ellipsis`, anywhere. `test_page.mjs` reads computed styles and fails on one.

## State

- **The HTTP surface is mounted** at `/api/train`, beside the `tuner` include. It was not, for
  the whole of this package's life, while `routes.py` opened by asserting that it was — every
  route unreachable and the docstring saying otherwise. Mounting does not turn training on:
  shut, all seven routes answer **503**; open, `/presets` answers **200** and `/start` still
  answers **403** without the token. All four states were exercised, not reasoned about.
- **The rack unit is still hand-rolled** and deliberately left alone. `api.py` builds the `train`
  unit inline from `CHAT_ADAPTER.exists()` and points it at `/training.html`, while
  `reinforce.status()` returns the bay's real state and the `__init__` docstring names
  `Unit(**status())` as the contract. Swapping it belongs to whichever session owns
  `site/reinforce.html` — that file does not exist on this branch, so pointing the unit at it
  from here would be a dead link.
- The panel (`page.html` / `page.js`) is **staged**: no generator or deploy step consumes it, and
  it renders only under `test_page.mjs`. Publishing it is a separate decision.

`backend/server.py` on this branch is an **old copy** — it branched before several other sessions
landed their own mounts. Take the two lines by hand; do not merge this file wholesale.

The whole bay is also **untracked in the main checkout** — `git ls-files backend/apps/studio/plugins/reinforce`
returns only the CUDA engine's 62 files. It lives on the `worktree-reinforce-rl` branch.

No preference or reinforcement run has been executed on this box. Every RL number in this package
is arithmetic derived from the trl source with the source lines cited, labelled `projected`
everywhere it appears. The first RL run to finish retires that projection **for its own cell and
no other**.
