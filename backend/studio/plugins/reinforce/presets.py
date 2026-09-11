"""SyMoNeuRaL Reinforce -- the predetermined tuning methods.

The owner's second complaint: no *"predetermined professional tuning methods"*. Four named
profiles live here. They are named for the job they do, not for their rank, because a rank is
not a decision an operator can make and "Voice" is.

## Why presets rather than a settings page

A settings page that exposes every knob is not a tuning method; it is a form. The value of a
preset is that somebody already spent the run finding out which combination works, and every
value below carries a **`why`** and a **`provenance`** field saying where it came from. If a
value has no defensible source it does not belong in a preset.

## Provenance vocabulary, and why none of these says "measured"

`.claude/CLAUDE.md` allows exactly three labels for a figure: measured on this machine,
vendor specification, or projected arithmetic. Hyperparameters are not figures of that kind,
so they carry a fourth vocabulary describing where the *choice* came from:

* `published` -- somebody else's paper or a library default (QLoRA, peft, TAO)
* `manual` -- `frontend/site/docs/symoneural-manual.md`, Playbook 04, written on this box
* `as-shipped` -- what the existing trainer already does, unvalidated
* `hardware` -- forced by one 16 GiB card, not chosen
* `convention` -- a ratio kept fixed so one knob stays one knob
* `measured` -- used for exactly one entry, `warmup_steps`, because the reason for expressing
  warmup in steps is a fact checked against the installed library on this box:
  `warmup_ratio` is absent from transformers 5.15.0.

**No quality claim appears here and none may be added without a run behind it.** Nothing about
training quality or throughput has ever been measured on this box: one adapter exists, from an
unlogged run with no validation split. So there is no "this preset scores better" field, and
the VRAM figures are projected until `jobs.measured_peaks()` has a real reading for that exact
(model x preset) pair.

## Three methods, not one -- and how the two objections to RL were actually answered

This file used to end with a section titled *"what is deliberately absent"*, and the thing it
named was preference tuning. Both of its reasons have now been answered rather than argued
with, so the presets exist:

* *"it needs a reference model resident beside the policy on a card with no headroom."* It does
  not. Under peft the reference policy **is** the base model with the adapter switched off:
  `ref_model=None` alongside a `peft_config` makes trl disable the adapter for the reference
  forward pass and re-enable it afterwards. The reference costs **zero extra weight bytes** --
  it costs one extra forward pass. `backend/studio/docs/qlora-upgrade.md` §5.4 spotted this itself
  ("on 4-bit that is achievable by disabling the adapter rather than loading twice") and then
  deferred it anyway.
* *"it needs paired preference data, which does not exist here."* Correct, and it still does not
  exist -- so the surface does not invent any. What changed is that `dataset_guard.py` now
  admits three dataset **schemas** and every preset declares which one it needs. A preference
  preset with no preference file staged is refused at preflight, by name, with the schema it
  wanted. The data problem is now a stated precondition instead of a reason to omit a method.

The three methods:

| method | trainer | what it optimises | dataset schema |
|---|---|---|---|
| `sft` | `Trainer` | next-token likelihood of the answer you wrote | `messages` |
| `preference` | `DPOTrainer` | the margin between an answer you preferred and one you did not | `preference` |
| `reinforcement` | `GRPOTrainer` | a reward computed over the model's own sampled output | `prompt` |

**Only the third is reinforcement learning in the ordinary sense**, and the distinction is
worth keeping straight rather than selling: DPO is a closed-form supervised surrogate for
RLHF's objective with no sampling loop and no reward function, and calling it RL is the kind of
overstatement this repo does not make. GRPO samples `num_generations` completions per prompt,
scores each with a reward function, and uses the group's mean as its own baseline -- no learned
value head, no critic, which is precisely why it fits on one card.

## Where the rollout comes from -- the llama.cpp and vLLM question, answered honestly

A GRPO step must generate before it can learn, and *what generates* is the whole performance
story. Three backends were considered and the honest answer differs for each. `rollout.py`
holds the detail and the refusals; the short version:

* **`transformers` in-process** -- the default and the only one that works on this box today.
  On-policy by construction: the sampling model *is* the model being trained, adapter live.
* **vLLM** -- supported as configuration (`use_vllm`, `vllm_mode="server"`,
  `vllm_server_base_url`), because a remote rollout server is genuinely how this is done at
  scale. It is **not installed here** and colocate mode cannot fit beside a 4-bit 7B on 15.92
  GiB. So it is offered as a reachable-or-refused external endpoint, never as a silent
  fallback.
* **llama.cpp** -- deliberately **not** a rollout backend, and this is a correctness argument
  rather than an effort one. `llama-server` on this box holds a Q4_K_M GGUF of the *base*
  model; it has no way to carry the adapter that is being trained, so every completion it
  returned would be off-policy from step 1 and the logprobs would belong to a different model
  than the one taking the gradient. It also cannot co-reside: `train` holds the governor lock
  and never yields, and 4.36 GiB of GGUF plus a ~12 GiB training process does not fit on a
  15.92 GiB card. What llama.cpp does contribute is real and unchanged -- it *serves* a GGUF
  LoRA, which is the promotion step at the other end of the pipeline.

## What is still deliberately absent

`NOT_IN_V1` below, and it is shorter than it was. KTO, reward-model training and PPO are named
there with a reason each. A greyed-out tab would be a decorative control, which is the same
dishonesty as a decorative status light.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

from . import registry

# The seven `nn.Linear` leaves in a Qwen2-family decoder layer, and the only seven there are.
# peft's `all-linear` shorthand resolves to exactly this set on this architecture (it excludes
# lm_head by design), so offering both would be two spellings of one thing -- a knob that does
# nothing, which an operator would burn a run discovering. The explicit list is used because
# it is readable in a run manifest and it survives peft changing its mind about `all-linear`.
ALL_SEVEN = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")
ATTENTION_ONLY = ("q_proj", "v_proj")

# Fixed across every preset, because the hardware decides them rather than the operator.
SHARED = {
    "quantisation": {"value": "4-bit NF4 + double quantisation, bf16 compute",
                     "provenance": "published",
                     "why": ("4-bit low-rank adaptation is not a cost optimisation on this box, "
                             "it is the only thing that makes a 7B trainable here at all -- "
                             "full fine-tuning of 7.6B parameters needs roughly 8x this card")},
    "gradient_checkpointing": {"value": True, "provenance": "hardware",
                               "why": ("mandatory at 7B on 16 GiB: without it the stored "
                                       "activations alone exceed the budget. Not offered as a "
                                       "choice because there is no configuration here where "
                                       "turning it off fits")},
    "bf16": {"value": True, "provenance": "hardware",
             "why": "Blackwell sm_120; bf16 compute is native and fp16 loss scaling is avoidable"},
    "optim": {"value": "paged_adamw_8bit", "provenance": "published",
              "why": ("QLoRA's paged optimiser. Two bytes of moment state per trainable "
                      "parameter instead of eight, and the paging is what stops an allocator "
                      "spike from OOMing a card with no headroom")},
    "lora_dropout": {"value": 0.05, "provenance": "published",
                     "why": "peft's common default; also what the existing trainer uses"},
    "bias": {"value": "none", "provenance": "published",
             "why": "training biases adds parameters that carry almost no adaptation"},
    "per_device_train_batch_size": {"value": 1, "provenance": "hardware",
                                    "why": ("batch is the term that multiplies the activation "
                                            "cost, and the activation cost is dominated by a "
                                            "152k-wide logit tensor. Batch 2 at seq 1024 adds "
                                            "roughly a gibibyte for nothing that gradient "
                                            "accumulation cannot buy more cheaply")},
    "warmup": {"value": "expressed in steps, never warmup_ratio", "provenance": "measured",
               "why": ("checked against the installed transformers 5.15.0 and trl 1.10.0 on "
                       "this box: `warmup_ratio` is absent from both TrainingArguments and "
                       "SFTConfig. Code copied from older guides raises TypeError here")},
    "loss_masking": {"value": "assistant turn only, hand-rolled -100 mask",
                     "provenance": "as-shipped",
                     "why": ("training on the prompt teaches the model to predict questions. "
                             "trl's `assistant_only_loss` is NOT a drop-in replacement on this "
                             "model: it needs {% generation %} markers in the chat template and "
                             "the stock Qwen2.5 template has none, so it would fail rather than "
                             "silently mis-mask. The hand-rolled mask is a workaround for a real "
                             "gap, not legacy cruft")},
    "seed": {"value": 20260817, "provenance": "convention",
             "why": ("the shipped adapter is not reproducible -- no seed was set and no run "
                     "config was written beside the weights. Every run from this surface writes "
                     "a manifest with its seed")},
}


# ---------------------------------------------------------------- the method dimension
#
# A method is the *objective*: what quantity a run is moving. It decides which trl trainer is
# constructed, which dataset schema is required, and which metrics mean anything -- an RL run
# reporting a `loss` curve and no reward curve is a panel that looks alive and says nothing.
#
# Kept as data rather than as branches so that one table drives the runner's dispatch, the
# preflight's cost model, the dataset guard's schema check and the page's metric labels. Four
# copies of this knowledge would drift, and the one that drifts silently is the page.
METHODS = {
    "sft": {
        "id": "sft",
        "label": "Supervised",
        "trainer": "transformers.Trainer",
        "dataset_schema": "messages",
        "optimises": ("next-token likelihood of the answer you wrote, with the prompt masked "
                      "out of the loss"),
        "is_rl": False,
        "needs_reference": False,
        "samples": False,
        "metrics": ("loss", "val_loss"),
        "why": ("the right method when you can write the answer you want. It is also the only "
                "one of the three that has ever been run on this box"),
    },
    "preference": {
        "id": "preference",
        "label": "Preference (DPO)",
        "trainer": "trl.DPOTrainer",
        "dataset_schema": "preference",
        "optimises": ("the log-probability margin between a completion you preferred and one "
                      "you rejected, against a frozen reference policy"),
        "is_rl": False,
        "needs_reference": True,
        "samples": False,
        "metrics": ("loss", "rewards_chosen", "rewards_rejected", "rewards_margin",
                    "rewards_accuracy"),
        "why": ("the right method when you can rank two answers but cannot write the ideal one. "
                "NOT reinforcement learning: there is no sampling loop and no reward function, "
                "and its 'rewards/*' metrics are implicit log-ratios rather than a reward "
                "signal. Calling it RL would be an overstatement"),
    },
    "reinforcement": {
        "id": "reinforcement",
        "label": "Reinforcement (GRPO)",
        "trainer": "trl.GRPOTrainer",
        "dataset_schema": "prompt",
        "optimises": ("a reward computed over the model's OWN sampled completions, advantage-"
                      "normalised within each group of samples for one prompt"),
        "is_rl": True,
        "needs_reference": True,       # only when beta > 0; the preset says which
        "samples": True,
        "metrics": ("reward", "reward_std", "kl", "completion_len", "clip_ratio", "entropy"),
        "why": ("the only method here that is reinforcement learning in the ordinary sense. "
                "Group-relative: the group mean is the baseline, so there is no learned value "
                "head and no critic network -- which is exactly why it fits on one card at all"),
    },
}


@dataclass
class Preset:
    id: str
    label: str
    when: str                       # when this preset is the right one
    epochs: float
    rank: int
    lora_alpha: int
    target_modules: tuple[str, ...]
    learning_rate: float
    lr_scheduler_type: str
    max_length: int
    gradient_accumulation_steps: int
    val_split: float
    save_strategy: str
    max_examples: int = 0           # 0 means the whole dataset
    max_steps: int = 0              # 0 means run the epochs out
    # The objective. Defaults to `sft` so that every pre-existing preset keeps its exact
    # meaning and no caller has to be updated to keep working.
    method: str = "sft"
    # Method-specific settings, nested rather than hung off this dataclass as a dozen
    # `num_generations: int | None` fields. Flattening them would put `beta=None` and
    # `num_generations=None` in every SFT preset's `to_dict()` and force `fit_table()` to
    # guess which of them apply -- nulls in both directions, which is how a UI ends up
    # rendering a knob that does nothing.
    method_config: dict = field(default_factory=dict)
    rationale: dict = field(default_factory=dict)

    @property
    def effective_batch(self) -> int:
        return self.gradient_accumulation_steps      # per-device batch is 1 on this card

    @property
    def dataset_schema(self) -> str:
        """Which dataset shape this preset requires. Derived from the method, never stored.

        Storing it per preset would let a preset declare `method="preference"` and
        `dataset_schema="messages"`, which is a configuration that cannot work and would be
        discovered at step 0 after the card had been acquired.
        """
        return METHODS[self.method]["dataset_schema"]

    @property
    def is_rl(self) -> bool:
        return bool(METHODS[self.method]["is_rl"])

    def to_dict(self) -> dict:
        d = asdict(self)
        d["target_modules"] = list(self.target_modules)
        d["effective_batch"] = self.effective_batch
        d["dataset_schema"] = self.dataset_schema
        d["is_rl"] = self.is_rl
        d["method_label"] = METHODS[self.method]["label"]
        d["trainer"] = METHODS[self.method]["trainer"]
        d["metrics"] = list(METHODS[self.method]["metrics"])
        return d


PRESETS: dict[str, Preset] = {}


def _add(p: Preset) -> None:
    PRESETS[p.id] = p


_add(Preset(
    id="smoke",
    label="Smoke",
    when=("Prove the pipeline runs end to end before spending an hour on it. Not a training "
          "method -- a test of one. Nothing it produces should be served."),
    epochs=1.0, rank=8, lora_alpha=16, target_modules=ATTENTION_ONLY,
    learning_rate=2e-4, lr_scheduler_type="cosine", max_length=512,
    gradient_accumulation_steps=4, val_split=0.1, save_strategy="no",
    max_examples=32, max_steps=8,
    rationale={
        "rank": ("8 -- the bottom of the manual's 8-32 band. This preset is not trying to "
                 "learn anything, it is trying to finish. (provenance: manual)"),
        "target_modules": ("q,v only. The existing trainer's docstring is explicit that "
                           "attention-only adapters pick up style but are worse at absorbing "
                           "facts -- which is exactly why it is the right choice here and the "
                           "wrong one everywhere else. (provenance: as-shipped)"),
        "max_steps": ("8. A capped step count is what makes this a smoke test rather than a "
                      "short run: it reaches the optimiser, the backward pass and the peak "
                      "allocation, then stops. (provenance: convention)"),
        "base_model": ("defaults to the 7B, which is the only model on this box in a trainable "
                       "format. Defaulting the fastest-feedback preset to a smaller base would "
                       "gate it behind a download, which is backwards for a preset whose job is "
                       "to fail fast. (provenance: hardware)"),
        "learning_rate": "2e-4 -- top of the manual's 1e-4 to 3e-4 band. (provenance: manual)",
    },
))

_add(Preset(
    id="voice",
    label="Voice",
    when=("Teach style, persona and refusals -- behaviour rather than facts. This is the "
          "profile that produced the adapter the chat surface serves."),
    epochs=3.0, rank=16, lora_alpha=32, target_modules=ALL_SEVEN,
    learning_rate=1e-4, lr_scheduler_type="cosine", max_length=1024,
    gradient_accumulation_steps=16, val_split=0.1, save_strategy="epoch",
    rationale={
        "rank": ("16 with alpha 32. The most-cited low-rank configuration, and it arrives here "
                 "three times independently: the existing trainer, this repo's own Playbook 04, "
                 "and NVIDIA TAO's preflight defaults. (provenance: published + manual)"),
        "alpha": ("2x rank, held as a fixed ratio so that rank is genuinely the single knob it "
                  "appears to be. (provenance: convention)"),
        "learning_rate": ("1e-4 -- the low end of the band, because behaviour is learned from a "
                          "small number of examples repeated, and a high rate on a small corpus "
                          "overwrites more than it teaches. (provenance: as-shipped)"),
        "epochs": ("3. The manual's stated priority order is data quality > learning rate > "
                   "epochs (1-3, watch val loss) > rank. Three epochs is the top of that band "
                   "and is where the validation split earns its keep. (provenance: manual)"),
        "effective_batch": ("16, reached as batch 1 x 16 accumulation. This CHANGES the existing "
                            "trainer, which uses 8. The manual's snippet targets 16 (as 2 x 8); "
                            "batch must stay at 1 on this card, so the accumulation carries it. "
                            "(provenance: manual)"),
        "val_split": ("10%. The manual says to hold out 5-10% BEFORE looking at training loss. "
                      "The shipped trainer does not do this, which is why no loss curve on this "
                      "box means anything yet. (provenance: manual)"),
    },
))

_add(Preset(
    id="recall",
    label="Recall",
    when=("Absorb domain vocabulary and facts the base model does not have. Product names, "
          "part numbers, procedures -- content, not character."),
    epochs=2.0, rank=32, lora_alpha=64, target_modules=ALL_SEVEN,
    learning_rate=2e-4, lr_scheduler_type="cosine", max_length=1024,
    gradient_accumulation_steps=16, val_split=0.1, save_strategy="epoch",
    rationale={
        "rank": ("32 -- the top of the manual's 8-32 band, for the case the manual says rank "
                 "actually matters for. Roughly doubles the trainable parameters against Voice "
                 "over the identical module set. (provenance: manual)"),
        "why_not_more_modules": ("Rank is what separates Recall from Voice, NOT module coverage. "
                                 "There is no larger module set to escalate to: the seven are "
                                 "every linear leaf in the decoder layer. A preset advertising "
                                 "'more coverage' would be a knob that does nothing. "
                                 "(provenance: published)"),
        "trainable_pct": ("lands at roughly 1.06% of the base at r=32 on a 7B, just outside the "
                          "0.1-1% band TAO's error playbook uses to catch an over-broad target "
                          "list. Here it is deliberate and the module list is exactly right, so "
                          "the preflight flags it rather than refusing. (provenance: published)"),
        "epochs": ("2. Facts need fewer passes than character does, and a third pass on a small "
                   "corpus at rank 32 is where memorisation stops being recall. (provenance: manual)"),
        "learning_rate": "2e-4 -- the manual's own snippet value. (provenance: manual)",
    },
))

_add(Preset(
    id="longform",
    label="Long-form",
    when=("Documents longer than a chat turn: manuals, transcripts, incident logs. Anything "
          "where the answer depends on context that will not fit in 1024 tokens."),
    epochs=2.0, rank=16, lora_alpha=32, target_modules=ALL_SEVEN,
    learning_rate=1e-4, lr_scheduler_type="cosine", max_length=2048,
    gradient_accumulation_steps=8, val_split=0.1, save_strategy="epoch",
    rationale={
        "max_length": ("2048, and this is a VRAM decision rather than a model limit -- the base "
                       "supports 32,768 tokens of context. Doubling the sequence roughly doubles "
                       "the activation term, and on a 152k-vocabulary model that term is "
                       "dominated by the logit tensor: seq 2048 costs about 1.78 GiB of logits "
                       "alone. This is the preset closest to the ceiling. (provenance: manual)"),
        "gradient_accumulation_steps": ("8 rather than 16, so that a doubled sequence length does "
                                        "not also double the wall-clock per optimiser step. "
                                        "(provenance: convention)"),
        "rank": ("16, not 32. At seq 2048 the headroom belongs to activations, and rank is the "
                 "cheapest thing to give back. (provenance: hardware)"),
    },
))


_add(Preset(
    id="prefer",
    label="Preference",
    when=("You can rank two answers but cannot write the ideal one. Needs a `preference` "
          "dataset: prompt, chosen, rejected. Teaches which of two candidates to prefer, "
          "which is a different and often easier authoring job than writing the target."),
    epochs=1.0, rank=16, lora_alpha=32, target_modules=ALL_SEVEN,
    learning_rate=5e-6, lr_scheduler_type="cosine", max_length=1024,
    gradient_accumulation_steps=16, val_split=0.1, save_strategy="epoch",
    method="preference",
    method_config={
        "beta": 0.1,
        "loss_type": "sigmoid",
        "precompute_ref_log_probs": True,
        "reference": "peft-implicit",
    },
    rationale={
        "learning_rate": ("5e-6 -- roughly TWENTY TIMES lower than the SFT presets, and this is "
                          "the single value most likely to be 'corrected' by somebody copying "
                          "1e-4 across from Voice. DPO optimises a log-ratio against a frozen "
                          "reference; at an SFT learning rate the policy leaves the reference's "
                          "neighbourhood in a few steps and the objective stops meaning what it "
                          "says. The published DPO range is 5e-7 to 5e-6 for full fine-tuning "
                          "and the top of that band is the right starting point for a low-rank "
                          "adapter, which moves less per step. (provenance: published)"),
        "beta": ("0.1 -- the DPO paper's own default and trl's. It is the strength of the KL "
                 "tether to the reference: lower drifts further and overfits the preference "
                 "pairs, higher barely moves. (provenance: published)"),
        "reference_model": ("`ref_model=None` with a `peft_config`, which makes trl use THIS "
                           "model with the adapter disabled as the reference. Zero extra weight "
                           "bytes -- the reference costs one forward pass, not a second 4-bit "
                           "7B. This is the objection that kept DPO out of v1, and it was always "
                           "answerable. (provenance: published)"),
        "precompute_ref_log_probs": ("True. The reference log-probabilities are computed in a "
                                     "pass over the dataset BEFORE the optimiser and its state "
                                     "exist, then cached and the reference forward is never run "
                                     "again. It trades wall-clock and a little host memory for "
                                     "peak VRAM, and peak VRAM is the binding constraint on this "
                                     "card. (provenance: published)"),
        "epochs": ("1. Preference data is small and DPO is famously quick to overfit it -- the "
                   "accuracy metric hits the ceiling while the margin keeps growing, which is "
                   "memorisation, not preference. (provenance: published)"),
        "max_length": ("1024 total, and note this is DPO's `max_length`, which covers prompt AND "
                       "completion together. Every example is scored TWICE (chosen and rejected), "
                       "so the activation term is charged at twice the sequence count -- see "
                       "`registry.plan_fit`. (provenance: hardware)"),
    },
))

_add(Preset(
    id="reward",
    label="Reward",
    when=("Reinforcement learning proper. You cannot write the answer and cannot rank pairs, but "
          "you CAN write a program that scores an answer. Needs a `prompt` dataset. The model "
          "samples its own completions, they are scored, and the gradient follows the score."),
    epochs=1.0, rank=16, lora_alpha=32, target_modules=ALL_SEVEN,
    learning_rate=1e-6, lr_scheduler_type="constant_with_warmup", max_length=384,
    gradient_accumulation_steps=8, val_split=0.0, save_strategy="epoch",
    method="reinforcement",
    method_config={
        "num_generations": 4,
        "max_completion_length": 192,
        "beta": 0.0,
        "loss_type": "dapo",
        "temperature": 1.0,
        "top_p": 1.0,
        "scale_rewards": "group",
        "mask_truncated_completions": True,
        "rewards": ("house_style", "pricing_refusal", "figure_labelling", "length_band"),
        "rollout": "transformers",
    },
    rationale={
        "learning_rate": ("1e-6, lower again than the preference preset. A policy-gradient step "
                          "is computed from four samples of one prompt, which is a far noisier "
                          "estimate than a supervised token target; the published RLHF and GRPO "
                          "recipes sit at 1e-6 to 5e-6 for exactly that reason. (provenance: "
                          "published)"),
        "num_generations": ("4. This is the knob that decides whether GRPO works and whether it "
                            "fits, and it is a genuine trade rather than a default. The advantage "
                            "of a completion is its reward minus the GROUP MEAN, so the group is "
                            "the baseline -- at 2 the baseline is one other sample and the "
                            "variance is enormous; published work uses 8 to 64. 4 is the largest "
                            "value that leaves headroom here, because every term in the training "
                            "forward pass is multiplied by it, including the 152k-wide logit "
                            "tensor. It is the first rung on this method's OOM ladder and the "
                            "preflight says so. (provenance: hardware)"),
        "beta": ("0.0, which switches the KL penalty and the reference forward pass OFF "
                 "entirely. Deliberate, and a real trade: the reference is what stops the policy "
                 "drifting into reward hacking, and without it a reward function with a "
                 "loophole will be found and exploited. It is off because the reference forward "
                 "at four completions per prompt is the term this card cannot afford, and "
                 "because recent GRPO work (DAPO, Dr. GRPO) reports that dropping KL is fine "
                 "for short runs on a well-specified reward. Raise it to 0.04 if you see the "
                 "reward climb while the completions get worse -- that IS reward hacking, and "
                 "the KL term is the thing that answers it. (provenance: published)"),
        "loss_type": ("`dapo` -- token-level normalisation rather than sequence-level. The "
                      "original GRPO loss averages per sequence, which weights a 10-token "
                      "completion the same as a 250-token one and biases the policy toward "
                      "length. (provenance: published)"),
        "scale_rewards": ("`group` -- divide the advantage by the group's own reward standard "
                          "deviation. When every sample in a group scores identically the "
                          "advantage is zero and the prompt contributes no gradient, which is "
                          "correct: a prompt every sample gets right teaches nothing. "
                          "(provenance: published)"),
        "max_completion_length": ("192 tokens. Short, and it is a VRAM decision: the generation "
                                  "KV cache and the training logit tensor are both charged at "
                                  "num_generations x this length. A task needing longer answers "
                                  "needs a smaller num_generations to pay for it. (provenance: "
                                  "hardware)"),
        "max_length": ("384, and on THIS method that number is the PROMPT cap, not the whole "
                       "sequence -- the completion is `max_completion_length` on top of it. The "
                       "supervised and preference presets use `max_length` for prompt and answer "
                       "together, so the same field means two different things across methods, "
                       "which is worth knowing before copying a value between them. The bound is "
                       "enforced by this package before the card is taken, because trl 1.10.0's "
                       "`GRPOConfig` has no `max_prompt_length` field at all -- a checked "
                       "absence -- and an over-long prompt would otherwise fail at step 0 after "
                       "a governor acquire. (provenance: hardware)"),
        "verdict": ("this preset costs out as TIGHT on the 7B, not as a comfortable fit, and it "
                    "is shipped that way deliberately rather than shrunk until the word changed. "
                    "384/192 at four generations projects ~1.7 GiB of headroom -- more than the "
                    "Long-form supervised preset already ships with. The alternative was 128-token "
                    "completions, which reads as 'fits' and is too short to be worth reinforcing. "
                    "Treat an OOM here as expected rather than as a fault, and take the first "
                    "rung of the ladder the preflight offers. (provenance: hardware)"),
        "temperature": ("1.0, not lower. Sampling IS the exploration -- at temperature 0.2 the "
                        "four completions in a group are near-identical, their reward standard "
                        "deviation collapses, and with `scale_rewards=group` the advantage goes "
                        "to zero and the run learns nothing while looking perfectly healthy. "
                        "(provenance: published)"),
        "val_split": ("0.0, and this one is a departure from every other preset here. There is "
                      "no held-out loss to compute: the RL objective is the reward, and the "
                      "reward is measured on the model's own samples as they are drawn. Holding "
                      "back 10% of the prompts would cost a tenth of the training signal to "
                      "produce an eval that GRPO does not define. The honest eval for an RL run "
                      "is the reward curve plus a human reading the completions. (provenance: "
                      "convention)"),
        "rewards": ("four rules-based functions from `rewards.py`, every one verifiable by "
                    "program. There is NO reward model on this box and no learned scorer -- a "
                    "reward model is itself a trained network and would need the VRAM the policy "
                    "is using. (provenance: manual)"),
    },
))

_add(Preset(
    id="probe",
    label="Reward probe",
    when=("Prove the reinforcement path runs end to end before spending an hour on it. The RL "
          "equivalent of Smoke, and it exists for the same reason: the GRPO path reaches a "
          "sampling loop and a reward function that the supervised path never touches, so "
          "Smoke passing says nothing about whether this works. Nothing it produces should be "
          "served."),
    epochs=1.0, rank=8, lora_alpha=16, target_modules=ATTENTION_ONLY,
    learning_rate=1e-6, lr_scheduler_type="constant", max_length=384,
    gradient_accumulation_steps=2, val_split=0.0, save_strategy="no",
    max_examples=16, max_steps=6,
    method="reinforcement",
    method_config={
        "num_generations": 2,
        "max_completion_length": 96,
        "beta": 0.0,
        "loss_type": "dapo",
        "temperature": 1.0,
        "top_p": 1.0,
        "scale_rewards": "group",
        "mask_truncated_completions": True,
        "rewards": ("house_style", "length_band"),
        "rollout": "transformers",
    },
    rationale={
        "num_generations": ("2 -- the minimum GRPO accepts, because a group of one has no "
                            "baseline to be relative to. At 2 the advantage estimate is close to "
                            "worthless, which is fine: this preset is not trying to learn, it is "
                            "trying to reach the reward function and the optimiser and stop. "
                            "(provenance: convention)"),
        "max_steps": ("6. Enough to sample, score, back-propagate and hit the peak allocation. "
                      "(provenance: convention)"),
        "rewards": ("two of the four, so a failure inside a reward function is easy to localise. "
                    "(provenance: convention)"),
        "val_split": ("0.0, for the same reason the Reward preset gives: GRPO's objective is the "
                      "reward measured on its own samples, so there is no held-out loss to "
                      "compute and a split would spend training signal on an eval the method "
                      "does not define. (provenance: convention)"),
    },
))


# Named in the UI as text, not built as a disabled control.
NOT_IN_V1 = {
    "reward_model_training": (
        "Training a reward MODEL is not offered. `trl.RewardTrainer` is installed, so this is a "
        "deliberate omission: a reward model is a second network that has to be trained first and "
        "then held resident during every RL step to score completions, and this card is already "
        "full with the policy alone. The `reward` preset scores completions with rules-based "
        "functions from `rewards.py` instead -- every one of them verifiable by reading the "
        "program, which is a property a learned scorer does not have."),
    "kto_and_online_dpo": (
        "KTO is installed and not offered; online DPO and PPO are not installed at all -- "
        "`trl 1.10.0` on this box ships neither `PPOTrainer` nor `OnlineDPOTrainer`, which is a "
        "checked fact and not an assumption. KTO wants unpaired binary feedback, which is a third "
        "dataset schema for a method that does not do anything the two offered methods do not "
        "already cover. If a use case appears, it is a small addition to `METHODS` and the guard."),
    "vllm_colocated_rollouts": (
        "vLLM in colocate mode -- the rollout engine sharing this process's card -- is refused by "
        "arithmetic rather than by policy. vLLM pre-allocates a KV cache block pool sized by "
        "`vllm_gpu_memory_utilization` on top of a second full copy of the weights, and the "
        "training process already projects near 12 GiB of a 14.2 GiB practical budget. Server mode "
        "against an endpoint on ANOTHER machine is supported and preflighted; see `rollout.py`."),
    "llama_cpp_rollouts": (
        "llama.cpp is not a rollout backend, and the reason is correctness before effort. "
        "`llama-server` here holds a Q4_K_M GGUF of the BASE model and has no way to carry the "
        "adapter being trained, so its completions and their logprobs would belong to a different "
        "model than the one taking the gradient -- off-policy from step 1, silently. It also "
        "cannot co-reside: `train` holds the governor lock and never yields. llama.cpp's real job "
        "in this pipeline is the other end -- it SERVES a GGUF LoRA, which is what makes an "
        "adapter promotable."),
    "full_fine_tuning": (
        "Full fine-tuning is not offered at any model size. 7.6B parameters under AdamW needs "
        "weights, gradients and two optimiser moments -- about 113 GiB at fp32, and mixed "
        "precision with an fp32 master copy lands in the same place. Against a ~14.2 GiB budget "
        "the shortfall is roughly 8x. This is a capability this box does not have, not a feature "
        "that has not been built."),
    "multi_gpu": (
        "No FSDP, no ZeRO-3, no tensor parallelism. One card, no NVLink. Optimiser offload to "
        "host memory is not a rescue either: this host is capped at PCIe Gen 3 x8, which turns a "
        "VRAM problem into a wall-clock one."),
}


def fit_table(model_id: str = "Qwen/Qwen2.5-7B-Instruct",
              free_bytes: int | None = None) -> list[dict]:
    """Every preset costed against one model. The picker's whole argument in one table.

    Returns one row per preset with the itemised projection from `registry.plan_fit`. Rows for
    a model that is not on this box still compute -- the arithmetic only needs the architecture,
    and refusing to show the cost of a model you cannot yet run is exactly the information an
    operator needs to decide whether to fetch it.
    """
    entry = registry.find(model_id)
    if entry is None or entry.arch is None:
        return []
    arch = registry.Arch(**entry.arch)
    rows = []
    for p in PRESETS.values():
        # `method` and `method_config` are passed through, and this is load-bearing rather than
        # tidy. A GRPO row costed with the supervised cost model would understate its peak by
        # the whole rollout term -- num_generations x the 152k-wide logit tensor, which is the
        # largest single term in an RL run -- and publish the understatement labelled
        # `projected`, as though the arithmetic had been done. A wrong number wearing an honest
        # label is worse than no number.
        plan = registry.plan_fit(
            arch, rank=p.rank, target_modules=p.target_modules, seq_len=p.max_length,
            batch=1, gradient_checkpointing=True, free_bytes=free_bytes,
            method=p.method, method_config=p.method_config)
        rows.append({"preset": p.id, "label": p.label, "model": entry.id,
                     "model_trainable": entry.trainable, "method": p.method,
                     "method_label": METHODS[p.method]["label"],
                     "dataset_schema": p.dataset_schema, "is_rl": p.is_rl,
                     "plan": plan})
    return rows
