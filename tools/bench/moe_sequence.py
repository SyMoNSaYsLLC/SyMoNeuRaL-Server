#!/usr/bin/env python3
"""Capture MoE routing as SEQUENCES, then analyse it as P / I / D.

Owner, 2026-09-11: *"you are missing the first two parts of the equation (proportional and
integral), these you dont need ravencalc for we can use basic calculator to do this we need
ravencalc for the derivative 3rd part of the equation"*.

## Why the previous capture could not answer the question

`tools/bench/moe_capture.py` aggregated routing into per-layer counters and threw the ORDER away.
That makes it able to answer "how often does expert 17 fire" and unable to answer "given what
just happened, what fires next" -- which is the only question a prefetcher cares about.

It also produced near-uniform entropy (4.93 of a possible 5.00) on **72 routings per layer
across 32 experts -- about 2 observations per expert.** Entropy estimated from that few
samples is biased toward uniform regardless of the truth, so that number measured the sample
size, not the model. This tool keeps sequences and runs a much larger corpus.

## The three terms

| term | what it is here | maths | needs |
|---|---|---|---|
| **P** proportional | which experts this token chose | the top-k set itself | counting |
| **I** integral | accumulated usage over the sequence so far | running sum | counting |
| **D** derivative | how fast usage is SHIFTING | d(usage)/d(token) | RavenCalc |

P and I are descriptive: they say where routing has been. **D is the predictive term** -- a
positive derivative on expert e means e is being selected more often as the sequence
progresses, so e is a prefetch candidate before the router asks for it.

The payoff is measurable and was costed earlier: on this box's Gen3 x8 link, an expert miss
costs 1.91 ms. At a 5% miss rate the ceiling is 66 tok/s; at 1% it is 129 tok/s. **A
predictor does not have to be right, it has to be right often enough**, and the error is the
number that decides whether a bigger model is viable.

## What is stored

One row per (prompt, layer, token position): the k expert ids and their routing weights, in
order. Everything downstream is derived, so the capture never has to be repeated to ask a new
question of the same data.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = next(_p for _p in Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
EVALCB = ROOT / "symoneural-llm" / "build-evalcb" / "bin" / "llama-eval-callback"
GPTOSS = ROOT / "backend/models/staging/openai-gpt-oss-20b/symon-openai-20b.gguf"

# The trailing `= {...}` is the RESULT shape. A non-greedy match grabs the SOURCE shape out of
# `VIEW(ffn_moe_argsort-0{32, 4, ...})`, reads n_used as 32, finds no line with 32 numbers and
# silently reports zero routings. That bug cost a whole capture run.
HEAD = re.compile(r"ffn_moe_topk-(\d+)\s*=.*=\s*\{(\d+),\s*(\d+)")
NUMS = re.compile(r"-?\d+\.\d+")

DOMAINS = {
    "code": [open(ROOT/"backend/gpu.py").read()[:6000],
             open(ROOT/"backend/telemetry.py").read()[:6000],
             open(ROOT/"tools/bench/bench_models.py").read()[:6000]],
    "prose": [open(ROOT/"README.md").read()[:6000],
              open(ROOT/"ops/docs/MEASUREMENTS.md").read()[:6000],
              open(ROOT/"review/bench/README.md").read()[:6000]],
    "technical": [open(ROOT/"scripts/gpu-governor.sh").read()[:6000],
                  open(ROOT/"backend/fabric_core/expertcache.py").read()[:6000],
                  open(ROOT/"tools/bench/moe_sequence.py").read()[:6000]],
}


def parse_sequence(text: str) -> list[dict]:
    """[{layer, pos, experts:[...]}] in order. Ordering is the whole point of this tool."""
    out: list[dict] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = HEAD.search(lines[i])
        if not m:
            i += 1
            continue
        layer, n_used = int(m.group(1)), int(m.group(2))
        i += 1
        pos, depth = 0, 0
        while i < len(lines):
            ln = lines[i]
            depth += ln.count("[") - ln.count("]")
            vals = NUMS.findall(ln)
            if len(vals) >= n_used:
                out.append({"layer": layer, "pos": pos,
                            "experts": [int(float(v)) for v in vals[:n_used]]})
                pos += 1
            i += 1
            if depth <= 0 and "]" in ln:
                break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default=str(GPTOSS))
    ap.add_argument("--threads", type=int, default=18)
    ap.add_argument("--out", default="review/bench/moe-sequences.json")
    args = ap.parse_args()

    model = Path(args.model)
    if not model.exists():
        raise SystemExit(f"no model at {model}")
    if not EVALCB.exists():
        raise SystemExit(f"eval-callback not built at {EVALCB}")

    result = {"model": model.name, "domains": {}}
    grand = 0
    for dom, prompts in DOMAINS.items():
        seqs = []
        for n, pr in enumerate(prompts, 1):
            p = subprocess.run([str(EVALCB), "-m", str(model), "-p", pr, "-n", "1",
                                "-c", "8192", "-t", str(args.threads)],
                               capture_output=True, text=True, timeout=2400)
            rows = parse_sequence(p.stdout)
            seqs.append({"prompt": pr[:70], "rows": rows})
            grand += len(rows)
            print(f"  [{dom}] {n}/{len(prompts)}  {len(rows)} routings", flush=True)
        result["domains"][dom] = seqs

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result))
    print(f"\n  {grand} routings total -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
