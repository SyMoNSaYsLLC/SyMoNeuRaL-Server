#!/usr/bin/env python3
"""Measure what the disabled drafter is costing: speculative decoding A/B.

`tools/bench/bench_llm.py` found that the production argv asks for speculative decoding
and does not get it -- `api.py:1333-1335` passes `-md`, `-ngld 99` and
`--spec-draft-n-max 2`, and both engine slots report `speculative: false`, because
this engine build defaults `speculative.types` to `{ NONE }` (`common/common.h:370`)
and only `--spec-type` (`common/arg.cpp:4154`) selects a method. That is a finding
about configuration. It does not say what the fix would be worth, and "it should be
faster" is not a number.

So this measures both sides. Two SCRATCH engine instances, one with the production
draft flags exactly as they are and one with `--spec-type draft-simple` added,
identical in every other respect, on the same workloads.

    python3 tools/bench/bench_llm_spec_ab.py

WHAT THIS TOUCHES. It spawns engines and it stops them. Deliberately bounded:

* **Never port 8081.** `LLAMA_PORT` is fixed at 8081 in `api.py` and `llama_up()`
  only probes `/health`, so an instance there would silently become what the
  production chat surface proxies to, carrying this script's argv instead of
  production's -- and would be indistinguishable in a later report. Scratch
  instances take 8-prefixed high ports and are killed in a `finally`.
* **`-c 4096 -np 1`, not production's `-c 65536 -np 2`.** Not a shortcut: two 7B
  instances at production context do not fit on a 16 GB card beside the resident
  one, and an OOM mid-run measures the allocator. The pair are identical to each
  other, which is what an A/B needs; neither is production's throughput, which is
  what `bench_llm.py` measures.
* Nothing is written outside the given output path. No config, no service, no repo
  file, no production process.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "symoneural-llm" / "build" / "bin" / "symoneural-llm"
CHAT = ROOT / "backend" / "models" / "llm" / "symon-1.0-7b-q4_k_m.gguf"
DRAFT = ROOT / "backend" / "models" / "llm" / "symon-1.0-draft-0.5b-q4_k_m.gguf"
ADAPTER = ROOT / "training" / "adapter" / "symoneural-lora.gguf"

#: Deliberately not 8081. See the module docstring.
PORT_OFF, PORT_ON = 18081, 18082

PROSE = ("Explain, in several paragraphs, why generating one token on a consumer "
         "GPU is limited by memory bandwidth rather than by arithmetic.")
FILLER = ("The card holds the weights and the cache in the same memory, so every "
          "token generated must read the whole of both. ")
N_PREDICT = 256


def workloads(ctx: int) -> list[tuple[str, str]]:
    """The prompts, plus one that only exists when the context is big enough to fill.

    `prose-at-depth` is here because a comparison run on an empty context answers a
    narrower question than it looks like it answers. Speculative decoding spends
    memory bandwidth -- the drafter's own cache, and a verification batch -- and
    bandwidth is exactly what a full KV cache is already competing for. The
    throughput report's fill curve measures decode falling from 117 to 92 tok/s
    between an empty context and 31K of it, so a drafting decision taken at zero
    depth may simply not hold at the depth a real conversation runs at.
    """
    rows = [
        ("counting", "Count from 1 to 400. Output only the numbers, comma separated."),
        ("prose", PROSE),
        ("code", "Write a Python function that streams a file in fixed-size chunks and "
                 "returns its SHA-256, with a docstring and error handling."),
    ]
    if ctx >= 8192:
        # ~70% of the slot in filler, leaving room for the 256-token reply. Sized in
        # characters at roughly 4.7 per token, the ratio the throughput tool measured
        # on this same filler; a little under is harmless here, over would be refused.
        target_tokens = int(ctx * 0.70)
        prefix = FILLER * max(1, round(target_tokens * 4.7 / len(FILLER)))
        rows.append(("prose-at-depth", prefix + "\n\n" + PROSE))
    return rows


DEFAULT_CTX = 4096


def base_argv(port: int, ctx: int = DEFAULT_CTX) -> list[str]:
    """Production's flags, minus the context/slot sizing the card cannot double.

    One slot rather than production's two, and a context the caller chooses: the
    sides run sequentially, so the ceiling is one scratch instance beside the
    resident production engine, not two.
    """
    return [str(ENGINE), "-m", str(CHAT), "-ngl", "99",
            "--host", "127.0.0.1", "--port", str(port),
            "-c", str(ctx), "--no-warmup", "-cb", "-np", "1",
            "-md", str(DRAFT), "-ngld", "99", "--spec-draft-n-max", "2",
            "--lora", str(ADAPTER)]


def wait_up(port: int, timeout: int = 180) -> bool:
    for _ in range(timeout):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def measure(port: int, repeats: int, temperature: float, ctx: int) -> dict:
    props = json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{port}/props", timeout=10).read())
    slots = json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{port}/slots", timeout=10).read())
    out: dict = {
        "n_ctx_slot": props.get("default_generation_settings", {}).get("n_ctx"),
        "speculative_active": any(s.get("speculative") for s in slots),
        "speculative_types": props.get("default_generation_settings", {})
                                  .get("params", {}).get("speculative.types"),
        "regimes": {}}
    for key, prompt in workloads(ctx):
        rates, prompt_tokens = [], None
        for i in range(repeats):
            body = json.dumps({
                "model": "symoneural", "messages": [{"role": "user", "content": prompt}],
                "max_tokens": N_PREDICT, "temperature": temperature, "seed": 1000 + i,
                "ignore_eos": True, "timings_per_token": True, "stream": False}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/chat/completions", data=body,
                headers={"Content-Type": "application/json"})
            r = json.loads(urllib.request.urlopen(req, timeout=600).read())
            t = r["timings"]
            rates.append(t["predicted_per_second"])
            # `usage.prompt_tokens`, NOT `timings.prompt_n`. The slot caches the
            # prompt between repeats of an identical request, so `prompt_n` -- which
            # counts tokens newly *evaluated* -- reads 1 on every repeat after the
            # first. The depth probe then reported its 11,000-token prefix as "1
            # tokens of filler" while the decode rate it produced (105.7 against
            # 116.8 at zero depth) proved the cache was in fact full.
            prompt_tokens = r.get("usage", {}).get("prompt_tokens") or t.get("prompt_n")
        out["regimes"][key] = {
            "mean": round(sum(rates) / len(rates), 2),
            "min": round(min(rates), 2), "max": round(max(rates), 2),
            # Recorded so `prose-at-depth` can be shown at the depth it actually
            # reached rather than the depth it aimed at.
            "prompt_tokens": prompt_tokens,
            "samples": [round(r, 2) for r in rates]}
    return out


def run_side(label: str, port: int, extra: list[str], repeats: int,
             temperature: float, ctx: int) -> dict:
    argv = base_argv(port, ctx) + extra
    print(f"[{label}] starting scratch engine on {port}...", file=sys.stderr)
    # New process group so the `finally` below kills the engine and any child it
    # forked, rather than orphaning one that keeps 5 GB of the card.
    proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        if not wait_up(port):
            return {"label": label, "argv": " ".join(argv),
                    "error": f"did not come up on {port}"}
        print(f"[{label}] measuring...", file=sys.stderr)
        return {"label": label, "argv": " ".join(argv), "port": port,
                **measure(port, repeats, temperature, ctx)}
    finally:
        print(f"[{label}] stopping scratch engine {proc.pid}", file=sys.stderr)
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=30)
        except Exception:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass


def vram() -> str:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return "unknown"
    return subprocess.run([exe, "--query-gpu=memory.used,memory.total",
                           "--format=csv,noheader"],
                          capture_output=True, text=True).stdout.strip()


def markdown(d: dict) -> str:
    off, on = d["spec_off"], d["spec_on"]
    L = [f"# Speculative decoding A/B — measured {d['measured_at']}", "",
         f"Commit: `{d['head']}`  ",
         f"Scratch instances at `-c {d['ctx']} -np 1`, one per side, run sequentially, "
         f"production flags otherwise. **Neither figure is production throughput** — "
         f"production runs `-c 65536 -np 2`; see the throughput report for that. What "
         f"this pair establishes is the *difference* the missing flag makes.  ",
         f"GPU at start: {d['vram_before']} — the resident production engine is "
         f"included in that.", ""]
    if off.get("error") or on.get("error"):
        L += ["## Did not complete", "",
              f"- spec-off: `{off.get('error', 'ok')}`",
              f"- spec-on: `{on.get('error', 'ok')}`", ""]
        return "\n".join(L)

    # `default_generation_settings.params["speculative.types"]` reads `none` on BOTH
    # sides, because it is the per-request default a caller may override -- not the
    # server's configuration. Reported next to a slot saying `speculative: true` it
    # looks like a contradiction and is only a mislabelled field, so the slot state
    # is the column that decides, and the other is named for what it is.
    L += ["| Side | `--spec-type` | slot state (authoritative) | per-request default |",
          "|---|---|---|---|",
          f"| production flags as-is | *(absent)* | "
          f"`speculative: {str(off['speculative_active']).lower()}` | "
          f"`{off['speculative_types']}` |",
          f"| plus `--spec-type draft-simple` | `draft-simple` | "
          f"`speculative: {str(on['speculative_active']).lower()}` | "
          f"`{on['speculative_types']}` |", "",
          "| Regime | prompt tokens | as-is tok/s | with `--spec-type` tok/s | change |",
          "|---|---|---|---|---|"]
    deltas = {}
    for key, _ in workloads(d["ctx"]):
        a, b = off["regimes"][key]["mean"], on["regimes"][key]["mean"]
        deltas[key] = (b - a) / a * 100
        L.append(f"| `{key}` | {off['regimes'][key].get('prompt_tokens') or '?'} "
                 f"| {a} | **{b}** | {deltas[key]:+.1f}% |")
    L.append("")

    # The verdict, stated rather than left to be inferred from the first row. An
    # earlier revision of this report printed the three numbers and stopped, and the
    # top row -- counting, the most draftable workload there is -- reads +38% and
    # invites the conclusion that a one-word flag was left off by mistake. The prose
    # rows say otherwise, and prose is the workload the chat surface actually serves.
    losers = [k for k, v in deltas.items() if v < -2]
    winners = [k for k, v in deltas.items() if v > 2]
    L += ["## What this means", ""]
    if losers and winners:
        L += [f"**Enabling `--spec-type draft-simple` is a trade, not a repair.** It "
              f"gains on {', '.join('`' + k + '`' for k in winners)} and *loses* on "
              f"{', '.join('`' + k + '`' for k in losers)}. Ordinary prose is the "
              f"closest of these regimes to what the chat surface actually serves, so "
              f"the top row of that table is the least representative number in it. "
              f"Drafting spends memory bandwidth on tokens the 7B then rejects; where "
              f"the output is predictable that bet pays, and where it is not, the "
              f"wasted verification is a straight loss. Turning the flag on would be a "
              f"decision about which workload to favour — it is not a defect fix, and "
              f"the measurement does not make the choice.", ""]
    elif winners and not losers:
        L += [f"`--spec-type draft-simple` gained on "
              f"{', '.join('`' + k + '`' for k in winners)} and cost nothing measurable "
              f"on the rest, at this context size.", ""]
    elif losers and not winners:
        L += [f"`--spec-type draft-simple` lost on "
              f"{', '.join('`' + k + '`' for k in losers)} and gained nowhere. The "
              f"absent flag is not costing throughput at this context size.", ""]
    else:
        L += ["No regime moved by more than 2% either way, which is inside the spread "
              "this bench measures between identical samples.", ""]

    if "prose-at-depth" in deltas:
        depth = off["regimes"]["prose-at-depth"]
        L += [f"`prose-at-depth` is the same prose prompt behind "
              f"{depth.get('prompt_tokens') or '?'} tokens of context, which is what "
              f"tests whether the trade survives a full cache rather than an empty "
              f"one. **It survives:** {deltas['prose-at-depth']:+.1f}% at depth "
              f"against {deltas['prose']:+.1f}% at zero depth. The depth itself costs "
              f"throughput on both sides — {depth['mean']} tok/s here against "
              f"{off['regimes']['prose']['mean']} at zero depth with the same flags — "
              f"which is the fill-curve effect in the throughput report, not the flag."
              if deltas["prose-at-depth"] < -2 else
              f"`prose-at-depth` is the same prose prompt behind "
              f"{depth.get('prompt_tokens') or '?'} tokens of context: it moved "
              f"{deltas['prose-at-depth']:+.1f}% against {deltas['prose']:+.1f}% at "
              f"zero depth, so the zero-depth result does **not** carry to a full "
              f"cache.", ""]
    else:
        L += [f"Run at `-c {d['ctx']}`, which is too small to hold a depth probe, so "
              f"whether this trade holds once the cache is full is **untested here**.",
              ""]

    L += ["## The argv of each side, in full", "",
          f"```\n{off['argv']}\n```", "", f"```\n{on['argv']}\n```", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--ctx", type=int, default=DEFAULT_CTX,
                    help="per-slot context for BOTH scratch sides. 8192 or more adds "
                         "the prose-at-depth probe. The sides run sequentially, so the "
                         "ceiling is one scratch instance beside the resident "
                         "production engine, not two")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    for p in (ENGINE, CHAT, DRAFT):
        if not p.exists():
            print(f"missing: {p}", file=sys.stderr)
            return 2

    d = {"measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "head": subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                capture_output=True, text=True).stdout.strip(),
         "vram_before": vram(), "repeats": args.repeats, "ctx": args.ctx,
         "temperature": args.temperature}
    d["spec_off"] = run_side("spec-off", PORT_OFF, [], args.repeats,
                             args.temperature, args.ctx)
    d["spec_on"] = run_side("spec-on", PORT_ON, ["--spec-type", "draft-simple"],
                            args.repeats, args.temperature, args.ctx)
    d["vram_after"] = vram()

    stem = Path(args.out) if args.out else (
        ROOT / "review" / f"MEASURED-{datetime.now(timezone.utc):%Y-%m-%d}-spec-decode-ab")
    stem.parent.mkdir(parents=True, exist_ok=True)
    stem.with_suffix(".json").write_text(json.dumps(d, indent=2) + "\n")
    stem.with_suffix(".md").write_text(markdown(d))
    print(f"wrote {stem.with_suffix('.json')}\nwrote {stem.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
