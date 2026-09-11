#!/usr/bin/env python3
"""Capture which experts a MoE model routes to, per layer, per domain. The map before the cut.

Owner, 2026-09-11: *"we need to build a visulizer so we can identify first where these things
are and then expert prune. You have to load the game to save the game"*, following
*"when you slice the 20b do you know what areas or specialities are in those"*.

## The question this answers, and the one it does not

**Answers:** for each layer, which of the 32 experts fire, how often, and *does that differ by
domain*. That is the map.

**Does not answer:** what an expert "is". Experts have no labels -- the GGUF carries
`expert_count: 32` and nothing else. Any name attached to expert 17 would be invented. What
can be said honestly is "expert 17 fires on 31% of code tokens and 2% of prose tokens", and
that is a measurement rather than a story.

## Why this must be domain-separated

Pruning by overall frequency on a general corpus is the dangerous version. If three of the
experts that look cold overall are the ones that fire on code tokens, cutting them yields a
model that chats fine and cannot program -- discovered later, on a real task, with no obvious
cause. So the corpus is split by domain and the histograms are compared, never pooled.

The domains here mirror the channels this project actually serves (Chat, Coder, Studio,
Remix), because those are what the model has to keep being able to do.

## Marginals are not enough, and the tool records both

4-of-32 routing means every token picks a COMBINATION. Two experts can each look infrequent
and still always co-fire on the cases that matter. So co-occurrence pairs are counted
alongside per-expert counts: pruning on marginals alone would miss that structure.

## How the data is obtained

`llama-eval-callback` (built at `symoneural-llm/build-evalcb/`) dumps every named graph tensor
during evaluation. `cb(selected_experts, "ffn_moe_topk", il)` in `src/llama-graph.cpp` means
the routing decision is already a named tensor -- so **no engine patch is needed**, which is
why this route was chosen over modifying llama.cpp.

The dump is CPU-only and verbose (~29k lines for a four-token prompt), so prompts are short
and the parser is streaming.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = next(_p for _p in Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
EVALCB = ROOT / "symoneural-llm" / "build-evalcb" / "bin" / "llama-eval-callback"
GPTOSS = ROOT / "backend/models/staging/openai-gpt-oss-20b/symon-openai-20b.gguf"

#: Mirrors the channels this project serves. See the module docstring on why pooling is wrong.
DOMAINS = {
    "code":   ["def quicksort(arr):\n    if len(arr) <= 1:\n        return arr",
               "SELECT user_id, COUNT(*) FROM orders GROUP BY user_id HAVING COUNT(*) > 5;",
               "class Governor:\n    def acquire(self, surface: str) -> bool:"],
    "prose":  ["The evening light fell across the harbour, and the boats",
               "In considering the question of free will, one must first",
               "She had never seen the city from this angle before, and"],
    "math":   ["Prove that the square root of 2 is irrational. Let us suppose",
               "The derivative of x^3 + 2x with respect to x is",
               "If a matrix A is invertible then its determinant is"],
    "technical": ["Memory bandwidth limits transformer decoding because every",
                  "The GPU governor serialises surfaces so that two weight sets",
                  "Flash attention reduces HBM traffic by tiling the softmax"],
}

#: `ffn_moe_topk-<layer> = (i32) VIEW(ffn_moe_argsort-0{32, 4, ...}) = {4, 4, 1, 1}`
#:
#: The trailing `= {...}` is the RESULT shape and is the one wanted. A non-greedy `.*?`
#: matched the SOURCE shape inside `VIEW(...{32, 4...})` instead, read n_used as 32, then
#: found no line carrying 32 numbers and silently counted zero routings. Greedy `.*` walks
#: to the last `= {` on the line, which is the result.
HEAD = re.compile(r"ffn_moe_topk-(\d+)\s*=.*=\s*\{(\d+),\s*(\d+)")
NUMS = re.compile(r"-?\d+\.\d+")


def parse(text: str) -> tuple[dict, dict]:
    """(per-layer expert counts, per-layer co-occurrence pairs). Streaming over the dump."""
    counts: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
    pairs: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = HEAD.search(lines[i])
        if not m:
            i += 1
            continue
        layer, n_used = int(m.group(1)), int(m.group(2))
        i += 1
        # Each subsequent bracketed row is one token's expert list, until the block closes.
        depth = 0
        while i < len(lines):
            ln = lines[i]
            depth += ln.count("[") - ln.count("]")
            vals = NUMS.findall(ln)
            if len(vals) >= n_used:
                picked = [int(float(v)) for v in vals[:n_used]]
                counts[layer].update(picked)
                for a in range(len(picked)):
                    for b in range(a + 1, len(picked)):
                        pairs[layer][tuple(sorted((picked[a], picked[b])))] += 1
            i += 1
            if depth <= 0 and "]" in ln:
                break
    return counts, pairs


def run_prompt(model: Path, prompt: str, threads: int) -> str:
    p = subprocess.run([str(EVALCB), "-m", str(model), "-p", prompt, "-n", "1",
                        "-c", "512", "-t", str(threads)],
                       capture_output=True, text=True, timeout=1800)
    return p.stdout


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default=str(GPTOSS))
    ap.add_argument("--threads", type=int, default=16)
    ap.add_argument("--out", default="review/bench/moe-routing.json")
    ap.add_argument("--domains", default="", help="comma separated subset")
    args = ap.parse_args()

    model = Path(args.model)
    if not model.exists():
        raise SystemExit(f"no model at {model}")
    if not EVALCB.exists():
        raise SystemExit(f"eval-callback not built at {EVALCB}")

    want = set(args.domains.split(",")) if args.domains else set(DOMAINS)
    result: dict = {"model": model.name, "domains": {}}

    for dom, prompts in DOMAINS.items():
        if dom not in want:
            continue
        tot: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
        tot_pairs: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
        for n, pr in enumerate(prompts, 1):
            print(f"  [{dom}] prompt {n}/{len(prompts)}", flush=True)
            counts, pairs = parse(run_prompt(model, pr, args.threads))
            for l, c in counts.items():
                tot[l].update(c)
            for l, c in pairs.items():
                tot_pairs[l].update(c)
        result["domains"][dom] = {
            "layers": {str(l): {str(e): n for e, n in sorted(c.items())}
                       for l, c in sorted(tot.items())},
            "pairs": {str(l): {f"{a}-{b}": n for (a, b), n in c.most_common(40)}
                      for l, c in sorted(tot_pairs.items())},
            "total_routings": sum(sum(c.values()) for c in tot.values()),
        }
        got = result["domains"][dom]
        print(f"    {len(got['layers'])} layers, {got['total_routings']} routings")

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    print(f"\n  wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
