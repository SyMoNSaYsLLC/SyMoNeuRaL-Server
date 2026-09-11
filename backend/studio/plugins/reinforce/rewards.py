"""SyMoNeuRaL Reinforce -- the reward functions. Rules-based, and every one readable.

## What a reward function is here, and what it deliberately is not

The reinforcement method needs something to score the model's own sampled completions. There
are two ways to get that and this file is emphatically the second one:

* **A reward model** -- a second neural network, trained on human comparisons, that outputs a
  scalar. This is what RLHF classically means. It is not available here for a stated reason:
  a reward model has to be trained first and then held resident during every RL step, and this
  card is already full with the policy alone. `presets.NOT_IN_V1` says so.
* **Verifiable, rules-based rewards** -- a program that scores a completion. Every function
  below is one. You can read it and know exactly what it rewards, which is a property a
  learned scorer does not have and cannot be given.

That second property is the reason this is the right choice here rather than merely the
affordable one. This repo's whole argument is that its numbers are real and its behaviour is
checkable. A reward curve produced by rules you can read is evidence; the same curve produced
by an unexamined 7B scorer is a number that went up.

## The honesty rule this file exists under, and the trap in it

`.claude/CLAUDE.md`: *"Label every figure: measured, vendor, or projected. Never present a
projection as a result."* A reward is none of those three -- it is not a figure about the
hardware, it is the output of a function defined here. So:

**A rising reward curve is evidence that this program's score went up. It is NOT evidence that
the model got better.** Those are the same sentence only if the reward function is a perfect
proxy for quality, and no reward function is. Optimising a proxy until it breaks is called
reward hacking and it is the normal outcome, not the pathological one. Two concrete examples
that these functions are exposed to:

* `length_band` rewards completions inside a token band. A policy can earn it by padding to
  length with filler that says nothing.
* `figure_labelling` rewards the word "measured" appearing near a number. A policy can earn it
  by labelling every number "measured" regardless of whether anything was measured -- which
  would train the model to do precisely the thing the honesty rule forbids.

**That second one is the reason the `reward` preset's `beta` is a documented trade rather than
a default.** The KL tether to the reference policy is the mechanism that holds a policy near
behaviour that was learned from real examples; with `beta=0.0` there is nothing structural
stopping the hack above. So: read the completions. `log_completions` is on for this reason, and
the reward curve alone is never the whole report on a run.

## Publishing: names and reasons, never patterns

`routes.py` serves the table below -- id, label, rationale, provenance, weight. It does **not**
serve the patterns, and that is deliberate on two grounds. The lesser one is that publishing
the exact regex a policy is scored against is publishing the hack. The greater one is the repo's
own line: **publish the numbers, keep the methods.** What is rewarded is a fair description of
the product's behaviour. How it is detected is method.

## The contract with trl

trl inspects a reward function's signature and passes `prompts`, `completions`, and every
remaining dataset column as keyword arguments. A function must:

* accept `**kwargs` -- otherwise a dataset that happens to carry an extra column raises;
* return one float per completion, in list order;
* be named, because trl logs each function's mean under `rewards/<__name__>`.

Completions arrive in one of two shapes depending on the dataset: a list of strings, or -- for
a conversational dataset -- a list of message lists. `_text()` normalises both, because getting
this wrong yields a function that silently scores `str(dict)` and rewards the shape of Python's
repr.

## Stdlib only

This module is imported by BOTH interpreters: `runner.py` executes these functions in the
training venv, and `routes.py` imports the table to publish it from the serving API, which has
no torch and never will. So: no numpy, no torch, no third-party anything. The scoring is
string and regex work, which is all it needs to be.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# ---------------------------------------------------------------- normalisation


def _text(completion) -> str:
    """One completion -> its text, whichever shape trl handed over.

    A conversational dataset yields `[{"role": "assistant", "content": "..."}]` per completion;
    a standard one yields a plain string. Both reach here, and a function that assumes the
    string form scores `"[{'role': 'assistant', ...}]"` -- rewarding Python's repr rather than
    the model's answer, while looking like it works.
    """
    if isinstance(completion, str):
        return completion
    if isinstance(completion, dict):
        return str(completion.get("content", ""))
    if isinstance(completion, (list, tuple)):
        return "\n".join(_text(part) for part in completion)
    return str(completion)


def _prompt_text(prompt) -> str:
    return _text(prompt)


def _sentences(text: str) -> list[str]:
    """Split on sentence-ish boundaries. Deliberately crude.

    `figure_labelling` needs to ask whether a label is *near* a figure, and "in the same
    sentence" is the cheapest defensible reading of near. A real sentence tokeniser would be a
    dependency, and this module takes none.
    """
    return [s for s in re.split(r"(?<=[.!?;:\n])\s+", text) if s.strip()]


# ---------------------------------------------------------------- the patterns
#
# NOT served by any route. See the module docstring: publishing the regex a policy is scored
# against publishes the loophole, and the detection method is method rather than number.

# A question about what something costs. Kept broad -- a missed pricing question scores 0
# (neutral) rather than wrong, so the cost of breadth is lower than the cost of a miss.
_ASKS_PRICE = re.compile(
    r"\b(price|pricing|prices|cost|costs|how much|quote|quotation|rate|rates|fee|fees|"
    r"budget|charge|charges|afford|expensive|cheap|per hour|hourly|monthly|invoice)\b", re.I)

# A stated money figure. This is the thing that must never be invented.
_STATES_MONEY = re.compile(
    r"(?:[$£€]\s?\d|\b\d+(?:[.,]\d+)?\s?(?:usd|gbp|eur|dollars?|pounds?|euros?|"
    r"cents?|per\s+hour|/hour|per\s+month|/month|an\s+hour|a\s+month)\b)", re.I)

# The correct destination for a pricing question, per .claude/CLAUDE.md.
_PRICING_CONTACT = re.compile(r"symonsayadmin@symoneural\.com", re.I)
_DECLINES = re.compile(
    r"\b(cannot|can't|can not|do not|don't|won't|will not|not able to|unable to|"
    r"no published|not published|not quoted|not something i)\b[^.!?]{0,60}"
    r"\b(quote|price|pricing|cost|costs|figure|number)\b", re.I)

# A figure about the hardware: a number with a unit that this repo would have to label.
# Bare integers are excluded on purpose -- "28 layers" and "2 of 3" are not measurements, and
# demanding a provenance label on every digit would train the model to label prose.
_FIGURE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s?"
    r"(?:gb/s|gib/s|mb/s|tb/s|gib|gb|mib|mb|tib|tb|tok/s|tokens?/s|tflops|gflops|pflops|"
    r"ms|µs|us|ns|watts?|w\b|kwh|hz|khz|mhz|ghz|%|x\b|fps|rows?/s|steps?/s)", re.I)

# The three labels .claude/CLAUDE.md allows, plus the honest hedges that carry the same meaning.
_LABEL = re.compile(
    r"\b(measured|vendor|projected|projection|specification|spec|nameplate|"
    r"unmeasured|not measured|arithmetic|estimated|estimate)\b", re.I)

# Assistant boilerplate and placeholder text. A short RL run's most common degenerate output.
_BOILERPLATE = re.compile(
    r"(as an ai language model|as an ai model|i'm just an ai|i am just an ai|"
    r"lorem ipsum|\bTODO\b|\bTBD\b|\bFIXME\b|\bXXX\b|\[insert[^\]]*\]|"
    r"\{\{[^}]*\}\}|<placeholder>|your text here)", re.I)

# Degenerate repetition: the same 4+ word phrase three times over. The classic collapse mode of
# a policy that has found a rewarded phrase.
_REPEAT = re.compile(r"\b(\w+(?:\s+\w+){3,}?)\b(?:\W+\1\b){2,}", re.I)


# ---------------------------------------------------------------- the functions
#
# Every one returns a float per completion, in list order. Ranges are stated in the table below
# and asserted by `selfcheck()`, because a function that quietly returns 5.0 where the table
# promises [-1, 1] would silently dominate every other term in the weighted sum.


def house_style(completions=None, **kwargs) -> list[float]:
    """Did it produce a usable answer at all: no boilerplate, no placeholder, no collapse.

    The floor function. It rewards nothing about quality and is not meant to -- it catches the
    three ways a short RL run degenerates, which are assistant boilerplate, placeholder text,
    and repeating a rewarded phrase until the token budget runs out. Without a term like this,
    the other rewards can all be earned by output that is not an answer.
    """
    out = []
    for completion in completions or []:
        text = _text(completion).strip()
        if not text:
            out.append(-1.0)                      # an empty completion is the worst outcome
            continue
        score = 1.0
        if _BOILERPLATE.search(text):
            score -= 1.5                          # enough to go negative on its own
        if _REPEAT.search(text):
            score -= 1.5
        # A completion that is one word is not an answer to anything this model is asked.
        if len(text.split()) < 3:
            score -= 1.0
        out.append(max(-1.0, min(1.0, score)))
    return out


def pricing_refusal(completions=None, prompts=None, **kwargs) -> list[float]:
    """The one behaviour `.claude/CLAUDE.md` says is trained in rather than prompted.

    *"Never invent pricing. Direct pricing questions to symonsayadmin@symoneural.com."*

    Scored only when the PROMPT asks about cost. A completion to any other prompt scores 0 --
    neutral, not rewarded -- because a model that earns points for mentioning the pricing
    contact in unrelated answers has learned the wrong rule. Under `scale_rewards="group"` a
    constant across a group contributes no gradient, so a neutral 0 genuinely costs nothing.

    This is the most defensible reward function here, because the correct behaviour is written
    down in the repo, is already the product's stated policy, and is checkable by a program
    rather than by taste.
    """
    prompts = prompts or []
    out = []
    for i, completion in enumerate(completions or []):
        prompt = _prompt_text(prompts[i]) if i < len(prompts) else ""
        if not _ASKS_PRICE.search(prompt):
            out.append(0.0)
            continue
        text = _text(completion)
        invented = bool(_STATES_MONEY.search(text))
        directed = bool(_PRICING_CONTACT.search(text))
        declined = bool(_DECLINES.search(text))
        if invented:
            # Inventing a price is the failure this refusal exists to prevent, and it is worse
            # than a useless answer -- so it is punished rather than merely unrewarded, even if
            # the completion also gives the contact address.
            out.append(-1.0)
        elif directed:
            out.append(1.0)
        elif declined:
            # Correct not to invent, but it left the asker with nowhere to go.
            out.append(0.4)
        else:
            out.append(-0.3)
        continue
    return out


def figure_labelling(completions=None, **kwargs) -> list[float]:
    """Every figure carries measured / vendor / projected, per the repo's first honesty rule.

    Scored only when the completion actually states a figure with a unit; prose with no numbers
    scores 0. A figure whose sentence carries no provenance word is penalised.

    **Read the module docstring's warning before trusting this one.** It rewards a label
    appearing near a number, and a policy can earn it by labelling everything "measured" --
    which is the exact dishonesty the rule is meant to prevent, learned as a habit. It is
    included because the behaviour it points at is genuinely the product's central claim, and
    it is weighted below `pricing_refusal` for precisely this reason.
    """
    out = []
    for completion in completions or []:
        text = _text(completion)
        sentences = [s for s in _sentences(text) if _FIGURE.search(s)]
        if not sentences:
            out.append(0.0)
            continue
        labelled = sum(1 for s in sentences if _LABEL.search(s))
        # Fraction of figure-bearing sentences that carry a label, mapped onto [-1, 1].
        out.append(2.0 * (labelled / len(sentences)) - 1.0)
    return out


def length_band(completions=None, **kwargs) -> list[float]:
    """A soft target band on completion length, and a real penalty for running to the cap.

    Two jobs. The first is the ordinary one: keep answers in a useful range rather than letting
    the policy discover that longer scores better on the other terms. The second matters more --
    a completion that reaches `max_completion_length` was **truncated**, and a truncated
    completion is an unfinished sentence that should not be reinforced. `mask_truncated_completions`
    in the preset handles that structurally; this term makes it visible in the reward as well.

    The band is 20 to 160 words: comfortably inside the preset's 192-token completion cap, so
    an answer can be complete without being clipped.
    """
    low, high = 20, 160
    out = []
    for completion in completions or []:
        n = len(_text(completion).split())
        if n < 3:
            out.append(-1.0)
        elif n < low:
            out.append(-1.0 + 2.0 * (n / low))          # ramps up to ~1.0 at the band edge
        elif n <= high:
            out.append(1.0)
        else:
            # Falls off, and keeps falling; at roughly twice the band it is fully negative.
            out.append(max(-1.0, 1.0 - 2.0 * (n - high) / high))
    return out


def answer_match(completions=None, answer=None, **kwargs) -> list[float]:
    """Exact match against a reference answer the DATASET supplied. The verifiable reward.

    This is the one function here that scores correctness rather than conduct, and it is the
    pattern most GRPO work actually uses: a task with a checkable answer, scored by comparing
    against it. It is only available when the dataset provides an `answer` column, which is why
    it is not in any preset's default list -- `resolve()` offers it when the staged dataset
    carries the field and refuses it, by name, when it does not.

    Matching is normalised on case, surrounding whitespace and trailing punctuation, and the
    reference is accepted if it appears as a substring of the completion -- a model that reasons
    aloud and then states the answer is correct, and demanding a bare answer would be scoring
    format under the name of correctness.
    """
    answers = answer or []
    out = []
    for i, completion in enumerate(completions or []):
        want = str(answers[i]).strip().lower().rstrip(".!?") if i < len(answers) else ""
        if not want:
            out.append(0.0)
            continue
        got = _text(completion).strip().lower()
        out.append(1.0 if want in got else -1.0)
    return out


# ---------------------------------------------------------------- the published table


@dataclass(frozen=True)
class Reward:
    id: str
    label: str
    weight: float
    requires: str          # a dataset column this function needs, or "" for none
    why: str
    provenance: str
    lo: float
    hi: float

    def to_dict(self) -> dict:
        """What a route may publish. Note what is absent: the function and its patterns."""
        return {"id": self.id, "label": self.label, "weight": self.weight,
                "requires": self.requires or None, "why": self.why,
                "provenance": self.provenance, "range": [self.lo, self.hi],
                "patterns_published": False,
                "patterns_note": ("the rules are described, never listed. Publishing the exact "
                                  "pattern a policy is scored against publishes the loophole, "
                                  "and how a behaviour is detected is method rather than "
                                  "number -- publish the numbers, keep the methods")}


FUNCTIONS = {
    "house_style": house_style,
    "pricing_refusal": pricing_refusal,
    "figure_labelling": figure_labelling,
    "length_band": length_band,
    "answer_match": answer_match,
}

REWARDS: dict[str, Reward] = {
    "house_style": Reward(
        id="house_style", label="House style", weight=1.0, requires="", lo=-1.0, hi=1.0,
        provenance="convention",
        why=("the floor: no assistant boilerplate, no placeholder text, no repetition collapse, "
             "not one word long. Rewards nothing about quality and is not meant to -- it catches "
             "the three ways a short reinforcement run degenerates. Without a term like this the "
             "other rewards can all be earned by output that is not an answer")),
    "pricing_refusal": Reward(
        id="pricing_refusal", label="Pricing refusal", weight=1.0, requires="", lo=-1.0, hi=1.0,
        provenance="manual",
        why=("`.claude/CLAUDE.md` states the rule: never invent pricing, direct pricing questions "
             "to the admin address. Scored only when the prompt asks about cost, so a model "
             "cannot earn it by mentioning the contact in unrelated answers. Inventing a figure "
             "is punished rather than merely unrewarded. The most defensible function here: the "
             "correct behaviour is written down, is already the product's policy, and a program "
             "can check it")),
    "figure_labelling": Reward(
        id="figure_labelling", label="Figure labelling", weight=0.6, requires="", lo=-1.0, hi=1.0,
        provenance="manual",
        why=("the repo's first honesty rule -- every figure carries measured, vendor or "
             "projected. Scored only on completions that actually state a figure with a unit. "
             "Weighted BELOW pricing refusal on purpose: it rewards a label appearing near a "
             "number, and a policy can earn it by labelling everything 'measured', which is the "
             "very dishonesty the rule exists to prevent. A reward function that can be gamed "
             "into the opposite of its intent gets less weight, and its risk gets written down")),
    "length_band": Reward(
        id="length_band", label="Length band", weight=0.4, requires="", lo=-1.0, hi=1.0,
        provenance="convention",
        why=("a soft 20-160 word band, and a real penalty for reaching the completion cap -- a "
             "clipped completion is an unfinished sentence and should not be reinforced. Lowest "
             "weight here because it is the most gameable term on the list: length is trivially "
             "padded, so it shapes output rather than judging it")),
    "answer_match": Reward(
        id="answer_match", label="Answer match", weight=1.0, requires="answer", lo=-1.0, hi=1.0,
        provenance="published",
        why=("normalised match against a reference answer the dataset supplied -- the classic "
             "verifiable reward, and the only function here that scores correctness rather than "
             "conduct. Not in any preset by default because it needs an `answer` column; offered "
             "when the staged dataset has one and refused by name when it does not")),
}


class RewardError(Exception):
    """A reward selection that cannot be honoured. Message is ours, never built from data."""


def resolve(names, available_fields=()) -> dict:
    """Turn a preset's reward-function names into callables, weights and refusals.

    Refuses rather than silently dropping. A run that quietly trained against three functions
    when four were configured would report a reward curve that means something different from
    what the panel says it means, and nothing about it would look wrong.
    """
    fields = set(available_fields or ())
    chosen, weights, refused = [], [], []
    for name in names or ():
        spec = REWARDS.get(name)
        if spec is None:
            raise RewardError(f"no such reward function: {name!r}. "
                              f"Available: {', '.join(sorted(REWARDS))}.")
        if spec.requires and spec.requires not in fields:
            refused.append({"id": name, "reason": "missing_field",
                            "message": (f"'{name}' needs a '{spec.requires}' column and the "
                                        f"dataset does not have one.")})
            continue
        chosen.append(FUNCTIONS[name])
        weights.append(spec.weight)
    if not chosen:
        raise RewardError("no usable reward function. The reinforcement method cannot run "
                          "without one -- there is nothing to optimise.")
    return {"funcs": chosen, "weights": weights, "names": [f.__name__ for f in chosen],
            "refused": refused}


def offered(available_fields=()) -> list[dict]:
    """The published table, with availability resolved against a dataset's columns."""
    fields = set(available_fields or ())
    rows = []
    for spec in REWARDS.values():
        row = spec.to_dict()
        row["available"] = (not spec.requires) or (spec.requires in fields)
        rows.append(row)
    return rows


def selfcheck() -> list[str]:
    """Run every function over synthetic completions and verify the contract. Returns problems.

    Called by the runner at startup, BEFORE the training loop and therefore before the run has
    spent anything, because the alternative is finding out that a reward function raises after
    twenty minutes of sampling. It is also the test the suite runs, so the two ends cannot drift.

    The inputs here are synthetic strings written for this purpose. Nothing from the corpus is
    used, and nothing from a staged dataset is read.
    """
    problems: list[str] = []
    samples = ["", "ok", "The copy kernel reached 746 GB/s, measured on this card.",
               "It costs $200 per hour.",
               "Pricing is not published here -- write to symonsayadmin@symoneural.com.",
               "word " * 400, "As an AI language model, I cannot help with that.",
               "The bus moved 746 GB/s and the ceiling is 896 GB/s."]
    prompts = ["what does it cost?"] * len(samples)
    answers = ["746"] * len(samples)
    for name, fn in FUNCTIONS.items():
        spec = REWARDS[name]
        try:
            got = fn(completions=samples, prompts=prompts, answer=answers)
        except Exception as exc:                       # noqa: BLE001 -- reported, not raised
            problems.append(f"{name} raised {type(exc).__name__}")
            continue
        if not isinstance(got, list) or len(got) != len(samples):
            problems.append(f"{name} returned {type(got).__name__} of the wrong length")
            continue
        for value in got:
            if not isinstance(value, float):
                problems.append(f"{name} returned a {type(value).__name__}, not a float")
                break
            if not (spec.lo <= value <= spec.hi):
                # This is the check that matters most: the weighted sum has no normalisation
                # step, so a function returning 5.0 where the table promises 1.0 silently
                # dominates every other term and the run optimises that one function.
                problems.append(f"{name} returned {value}, outside its published "
                                f"[{spec.lo}, {spec.hi}] range")
                break
    return problems


__all__ = ["REWARDS", "FUNCTIONS", "Reward", "RewardError", "resolve", "offered", "selfcheck",
           "house_style", "pricing_refusal", "figure_labelling", "length_band", "answer_match"]
