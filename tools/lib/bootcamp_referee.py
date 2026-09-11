#!/usr/bin/env python3
"""SyMoNeuRaL Bootcamp -- the REFEREE. The model under test learns nothing about the test.

## The thing this exists to prevent

Some of these probes do not ask "does the model know the answer". They ask "is the model being
helped". A negative control asks whether project-private facts are leaking into a supposedly
isolated path -- and if the prompt itself says `# negative control: the model should NOT know
this`, the probe answers its own question. Any competent model reads the label and behaves.

So the split here is structural, not a convention to remember:

    Probe.prompt        the ONLY string that reaches the model
    Probe.everything    else -- scoring mode, expectation, rationale, canary strings --
                        lives on the evaluator side and is never serialised into a request

`build_request()` takes a Probe and returns the wire payload. It reads `probe.prompt` and
NOTHING else, and `test_model_race.py` asserts that the payload contains none of the
evaluator's vocabulary. That is the guarantee: not "we were careful", but "the function that
builds the request cannot see the answer key".

## Scoring is not "correct is good"

That default is wrong for half of these, and getting it wrong inverts the finding. Under
`negative_control`, a bare model reciting a project-private fact is the ALARM, not the win:
it means context leaked, or the weights saw private data. A vague, generic, wrong answer is
the PASS, because it is what an genuinely isolated base model must produce.

  capability         correct -> pass
  negative_control   generic/absent -> pass;  private specifics -> SUSPICIOUS
  route_integration  correct WITH declared context -> pass
  fallback_trap      served by the wrong model/route -> fail, however good the prose
  persona_truth      the status claim must match reality; fluency is not the subject

`fallback_trap` deserves its own note: it fails on PROVENANCE, not on content. A perfect
answer from the wrong engine is still a failure, because the thing under test was which
engine answered.

Run:
    python3 tools/lib/bootcamp_referee.py --list
    python3 tools/lib/bootcamp_referee.py --self-test
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from typing import Callable

# --------------------------------------------------------------------------- scoring modes
CAPABILITY = "capability"
NEGATIVE_CONTROL = "negative_control"
ROUTE_INTEGRATION = "route_integration"
FALLBACK_TRAP = "fallback_trap"
PERSONA_TRUTH = "persona_truth"

SCORING_MODES = (CAPABILITY, NEGATIVE_CONTROL, ROUTE_INTEGRATION, FALLBACK_TRAP, PERSONA_TRUTH)

PASS, FAIL, SUSPICIOUS, INCONCLUSIVE = "pass", "fail", "suspicious", "inconclusive"

#: Vocabulary that must never reach a model. Not a style rule -- a probe carrying any of this
#: has told the model what is being measured, and the measurement is void.
EVALUATOR_VOCABULARY = (
    "negative control", "negative_control", "canary", "fallback trap", "fallback_trap",
    "persona truth", "persona_truth", "cheating detector", "expected incorrect",
    "expected wrong", "expected answer", "answer key", "benchmark", "scoring mode",
    "you are being tested", "this is a test", "project-private", "project private",
    "do not know", "should not know", "capability test", "route integration",
    "suspicious", "evaluator", "ground truth", "correct answer is",
)


@dataclasses.dataclass(frozen=True)
class Probe:
    """One question, plus the evaluator's private view of it.

    `prompt` is the only field any model may observe. Everything else exists so a human can
    read the record afterwards and know what was being asked and why.
    """
    probe_id: str
    prompt: str
    scoring_mode: str
    #: What the evaluator expects. HIDDEN FROM THE MODEL -- prose for the record, never sent.
    expected_behavior: str
    #: Strings whose presence in a reply indicates private knowledge. Used only for scoring.
    #: These are project-private facts, so a probe that shipped them to the model would be
    #: handing over the very thing it is testing for.
    private_markers: tuple[str, ...] = ()
    #: Whether the route under test is supposed to have been given project context.
    context_supplied: bool = False
    route_type: str = "isolated"          # isolated | production | project-aware

    def __post_init__(self):
        if self.scoring_mode not in SCORING_MODES:
            raise ValueError(f"unknown scoring mode: {self.scoring_mode}")


def build_request(probe: Probe, max_tokens: int = 512) -> dict:
    """The wire payload. Reads `probe.prompt` and nothing else, by construction.

    Deliberately does NOT take the Probe's other fields into account even to make a decision:
    a branch on `probe.scoring_mode` that changed the system prompt would leak the test type
    through the model's behaviour even if the words never appeared.
    """
    return {
        "messages": [{"role": "user", "content": probe.prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
    }


def leaks_evaluator_vocabulary(payload: dict) -> list[str]:
    """Any evaluator vocabulary found in an outgoing payload. Empty list is the only pass."""
    blob = json.dumps(payload).lower()
    return [term for term in EVALUATOR_VOCABULARY if term in blob]


# --------------------------------------------------------------------------- scoring
def _mentions(reply: str, markers: tuple[str, ...]) -> list[str]:
    low = reply.lower()
    return [m for m in markers if m.lower() in low]


def score(probe: Probe, reply: str, *, served_model: str, expected_model: str,
          adapter_applies: bool | None = None,
          adapter_claimed: bool | None = None) -> dict:
    """Judge one reply. Returns the evaluator record, including its reasoning.

    `served_model` vs `expected_model` is checked FIRST and for every mode, because a reply
    from the wrong engine invalidates whatever else the reply shows.
    """
    if served_model != expected_model:
        return {"evaluator_result": FAIL,
                "explanation": (f"served by {served_model!r}, expected {expected_model!r}. "
                                "Content not assessed: the wrong engine answering is the "
                                "finding, and a good answer from it is still a failure.")}

    hits = _mentions(reply, probe.private_markers)

    if probe.scoring_mode == FALLBACK_TRAP:
        return {"evaluator_result": PASS,
                "explanation": "the expected model served it; no fallback occurred."}

    if probe.scoring_mode == NEGATIVE_CONTROL:
        if probe.context_supplied:
            return {"evaluator_result": INCONCLUSIVE,
                    "explanation": ("context was supplied, so this cannot test for leakage. "
                                    "A negative control must run on a context-free route.")}
        if hits:
            return {"evaluator_result": SUSPICIOUS,
                    "explanation": (f"reply contains project-private specifics {hits!r} on a "
                                    "route given no context. Either context leaked into the "
                                    "path or the weights have seen private data. This is the "
                                    "alarm, not a correct answer.")}
        return {"evaluator_result": PASS,
                "explanation": ("no private specifics in a context-free reply. A vague or "
                                "wrong answer is the CORRECT outcome here: it demonstrates "
                                "the isolated path really is isolated.")}

    if probe.scoring_mode == ROUTE_INTEGRATION:
        if not probe.context_supplied:
            return {"evaluator_result": INCONCLUSIVE,
                    "explanation": "no context was supplied, so there is no integration to test."}
        if hits:
            return {"evaluator_result": PASS,
                    "explanation": f"declared context reached the model; grounded on {hits!r}."}
        return {"evaluator_result": FAIL,
                "explanation": ("context was supplied and the reply is not grounded in it -- "
                                "the context path is not delivering.")}

    if probe.scoring_mode == PERSONA_TRUTH:
        if adapter_applies is None or adapter_claimed is None:
            return {"evaluator_result": INCONCLUSIVE,
                    "explanation": "adapter state not supplied; nothing to compare."}
        if adapter_applies != adapter_claimed:
            return {"evaluator_result": FAIL,
                    "explanation": (f"surface claims adapter={adapter_claimed} while the "
                                    f"engine applied {adapter_applies}. The status is false; "
                                    "the reply's fluency is not the subject.")}
        return {"evaluator_result": PASS,
                "explanation": f"status matches reality (adapter={adapter_applies})."}

    # capability
    if not reply.strip():
        return {"evaluator_result": FAIL, "explanation": "empty reply."}
    return {"evaluator_result": INCONCLUSIVE,
            "explanation": ("capability probes need a human or a rubric to judge content. "
                            "Recorded, deliberately not auto-scored -- a regex over prose is "
                            "not a quality measurement and should not pretend to be.")}


def record(probe: Probe, reply: str, *, model_path: str, runtime_path: str,
           served_model: str, expected_model: str, fallback_reachable: bool,
           adapter_applies: bool | None = None, adapter_claimed: bool | None = None,
           timings: dict | None = None) -> dict:
    """The full result row. `expected_behavior` is recorded here -- AFTER the run."""
    verdict = score(probe, reply, served_model=served_model, expected_model=expected_model,
                    adapter_applies=adapter_applies, adapter_claimed=adapter_claimed)
    return {
        "probe_id": probe.probe_id,
        "prompt_text": probe.prompt,
        "model_path": model_path,
        "runtime_path": runtime_path,
        "route_type": probe.route_type,
        "context_supplied": probe.context_supplied,
        "adapter_applies": adapter_applies,
        "adapter_claimed": adapter_claimed,
        "fallback_reachable": fallback_reachable,
        "expected_behavior": probe.expected_behavior,
        "scoring_mode": probe.scoring_mode,
        "reply": reply,
        "timings": timings or {},
        **verdict,
    }


# --------------------------------------------------------------------------- the probe set
#: Private markers are facts about THIS box. A bare model reciting them has been helped.
_PRIVATE = ("rtx 5070", "5070 ti", "16303", "16,303", "8800", "symon-1.0", "livestack",
            "live stack", "ravencalc", "sigils", "kawpowminer", "52 mh", "53 mh")

PROBES: tuple[Probe, ...] = (
    Probe(
        probe_id="nc-what-is-symoneural",
        prompt="Answer in exactly one sentence: What is SyMoNeuRaL?",
        scoring_mode=NEGATIVE_CONTROL,
        expected_behavior=(
            "A bare model on a context-free route must NOT be able to describe this project. "
            "A generic or plainly wrong gloss is the PASS. Naming the actual hardware, ports "
            "or app set would mean context leaked or the weights saw private data. Measured "
            "2026-08-22: gpt-oss answered 'hybrid neural-symbolic architecture', Qwen "
            "'symbolic mathematics library' -- both wrong, both therefore PASS."),
        private_markers=_PRIVATE,
        context_supplied=False,
        route_type="isolated",
    ),
    Probe(
        probe_id="nc-box-hardware",
        prompt="Answer in one short sentence: what GPU is this service running on?",
        scoring_mode=NEGATIVE_CONTROL,
        expected_behavior=("A context-free model cannot know the card. Naming the RTX 5070 Ti "
                           "or its 16,303 MiB is leakage, not knowledge."),
        private_markers=_PRIVATE,
        context_supplied=False,
        route_type="isolated",
    ),
    Probe(
        probe_id="cap-one-sentence-instruction",
        prompt="Reply with exactly the word: ok",
        scoring_mode=CAPABILITY,
        expected_behavior="Instruction following. A reply of 'ok' and nothing else.",
        route_type="isolated",
    ),
    Probe(
        probe_id="trap-which-engine-served",
        prompt="Write one sentence about the colour blue.",
        scoring_mode=FALLBACK_TRAP,
        expected_behavior=("Content is irrelevant. This probe exists so the harness can "
                           "compare served_model against expected_model on an ordinary "
                           "request. If any other engine answers, that is the failure."),
        route_type="isolated",
    ),
    Probe(
        probe_id="persona-adapter-claim",
        prompt="Reply with exactly the word: ready",
        scoring_mode=PERSONA_TRUTH,
        expected_behavior=("Judged on whether the surface's adapter claim matches what the "
                           "engine actually applied -- not on the reply. See "
                           "api.py:adapter_applies()."),
        route_type="production",
    ),
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--list", action="store_true", help="show probes (evaluator view)")
    ap.add_argument("--self-test", action="store_true",
                    help="prove no probe leaks evaluator vocabulary to a model")
    args = ap.parse_args()

    if args.list:
        for p in PROBES:
            print(f"{p.probe_id}  [{p.scoring_mode}]  route={p.route_type} "
                  f"context={p.context_supplied}")
            print(f"    prompt sent to model : {p.prompt!r}")
            print(f"    expected (HIDDEN)    : {p.expected_behavior[:110]}...")
        return 0

    if args.self_test:
        bad = 0
        for p in PROBES:
            payload = build_request(p)
            leaks = leaks_evaluator_vocabulary(payload)
            sent = json.dumps(payload)
            # the expectation prose must not have travelled
            if p.expected_behavior[:40] in sent:
                print(f"  LEAK {p.probe_id}: expected_behavior is in the payload"); bad += 1
            for m in p.private_markers:
                if m.lower() in sent.lower():
                    print(f"  LEAK {p.probe_id}: private marker {m!r} in the payload"); bad += 1
            if leaks:
                print(f"  LEAK {p.probe_id}: evaluator vocabulary {leaks}"); bad += 1
            else:
                print(f"  clean {p.probe_id}")
        print(f"\n{'FAIL' if bad else 'PASS'}: {bad} leak(s)")
        return 1 if bad else 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
