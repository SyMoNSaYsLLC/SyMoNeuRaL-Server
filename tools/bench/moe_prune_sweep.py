#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SyMonSays LLC. All rights reserved.
# PROPRIETARY AND CONFIDENTIAL. Not for distribution. See ops/registry/EXPORTS.md.
"""Prune to every expert count and find where the model breaks. The PROPORTIONAL term.

Owner, 2026-09-11: *"where we pruned 8/32 experts we should start at 1 and add an expert
throughout the testing for the proportional"*.

## Why the floor is 4 and not 1

`expert_used_count` is 4: the router selects four experts for every token. A model with three
experts cannot satisfy its own routing, so the sweep starts at 4. That is a property of the
file, not a choice.

## What is already known, and what this fills in

Measured 2026-09-11 with `tools/bench/moe_prune.py`:

    32 experts  12.85 GiB  original   -> "4"                        35 tok   COHERENT
    16 experts   8.10 GiB  pruned     -> "4", "Red, Blue, Green"    54 tok   COHERENT
     8 experts   5.73 GiB  pruned     -> '' , loops in reasoning    400 tok  BROKEN

**Active parameters, and therefore speed, are unchanged at every setting** -- routing still
picks 4. 165.8 tok/s pruned against 166.2 original. What changes is total parameters and VRAM:
6,320 MiB at 8 experts against 13,800 at 32.

So the cliff is between 8 and 16 and this walks every step to find it.

## The failure mode being detected

A broken pruned model does not error. It **loops in the reasoning channel and never emits a
final answer** -- `content` stays empty while `reasoning_content` repeats itself and burns the
whole token budget. So the health check is not "did it respond" but "did it produce non-empty
content within a sane token count", and the token count is itself a signal: the original
answers "what is 2+2" in 35 tokens, so 400 means it never terminated.

## What this measures and what it cannot

Measures: does the model still terminate and answer, at each expert count, on a fixed prompt
set. That is a floor test, not an evaluation -- a model can pass it and still be much worse at
real work. **Nothing here licenses a promotion.** It finds the boundary worth evaluating
properly.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = next(_p for _p in Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
ENGINE = ROOT / "symoneural-llm" / "build" / "bin" / "symoneural-llm"
GOV = ROOT / "scripts" / "gpu-governor.sh"
VENV = ROOT / "training" / ".venv" / "bin" / "python3"
SRC = ROOT / "models/staging/openai-gpt-oss-20b/symon-openai-20b.gguf"
CAPTURE = ROOT / "review/bench/moe-sequences.json"
WORK = ROOT / "models/staging/prune-sweep"
PORT = 8099

# Short factual prompts the original answers in under 60 tokens. A model that needs 400 has
# failed to terminate, which is the failure mode being looked for.
PROBES = [
    ("arith", "What is 2+2? Answer with the number only.", "4"),
    ("list",  "Name three colours.", None),
    ("code",  "Write a one-line Python expression that reverses the string s.", None),
]


def alive(t: float = 2.0) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=t).read()
        return True
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def ask(prompt: str, max_tokens: int = 400) -> dict:
    body = {"model": "b", "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "temperature": 0.0, "seed": 1, "stream": False}
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
                                 method="POST", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as exc:                                            # noqa: BLE001
        return {"error": type(exc).__name__}
    m = (d.get("choices") or [{}])[0].get("message", {})
    t = d.get("timings") or {}
    return {"content": (m.get("content") or "").strip(),
            "reasoning": (m.get("reasoning_content") or "")[:200],
            "tokens": t.get("predicted_n"),
            "tok_s": round(t.get("predicted_per_second") or 0, 1)}


def evaluate(model: Path) -> dict:
    got = subprocess.run([str(GOV), "acquire", "chat", "300", "--new-engine"],
                         env={**os.environ, "SYMONEURAL_OWNER_PID": str(os.getpid())},
                         capture_output=True, text=True, timeout=400)
    if got.returncode != 0:
        return {"error": "lease refused"}
    proc = None
    try:
        proc = subprocess.Popen(
            [str(ENGINE), "-m", str(model), "--port", str(PORT), "--host", "127.0.0.1",
             "-ngl", "99", "-c", "8192", "-fa", "on", "--jinja"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(180):
            if alive():
                break
            if proc.poll() is not None:
                return {"error": f"engine exited {proc.returncode}"}
            time.sleep(1)
        else:
            return {"error": "never answered /health"}

        probes, ok = {}, 0
        for tag, prompt, expect in PROBES:
            r = ask(prompt)
            # Coherent = produced non-empty content AND terminated well inside the budget.
            good = bool(r.get("content")) and (r.get("tokens") or 999) < 350
            if expect:
                good = good and expect in r.get("content", "")
            probes[tag] = {**r, "pass": good}
            ok += bool(good)
        return {"probes": probes, "passed": ok, "of": len(PROBES),
                "tok_s": probes.get("arith", {}).get("tok_s")}
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
        subprocess.run([str(GOV), "release", "chat"], capture_output=True, text=True,
                       check=False)
        time.sleep(2)


def main() -> int:
    lo = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    hi = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    WORK.mkdir(parents=True, exist_ok=True)
    rows = []
    for keep in range(lo, hi + 1):
        dst = WORK / f"e{keep:02d}.gguf"
        if not dst.exists():
            p = subprocess.run(
                [str(VENV), str(ROOT / "tools" / "bench" / "moe_prune.py"), "--keep", str(keep),
                 "--src", str(SRC), "--dst", str(dst), "--keep-from", str(CAPTURE)],
                capture_output=True, text=True, timeout=3600)
            if p.returncode != 0:
                rows.append({"keep": keep, "error": "prune failed"})
                print(f"  e{keep:02d}  PRUNE FAILED")
                continue
        size = dst.stat().st_size / 2**30
        res = evaluate(dst)
        row = {"keep": keep, "gib": round(size, 2), **res}
        rows.append(row)
        verdict = (f"{res.get('passed')}/{res.get('of')}" if "passed" in res
                   else res.get("error", "?"))
        print(f"  e{keep:02d}  {size:5.2f} GiB  probes {verdict:>6}  "
              f"{res.get('tok_s') or '-'} tok/s", flush=True)
        # Keep only the boundary artefacts; a full sweep is ~180 GiB otherwise.
        if row.get("passed", 0) == 0 and keep > lo:
            dst.unlink(missing_ok=True)

    out = ROOT / "review/bench/prune-sweep.json"
    out.write_text(json.dumps({"rows": rows}, indent=2))
    print(f"\n  wrote {out.relative_to(ROOT)}")
    good = [r["keep"] for r in rows if r.get("passed") == r.get("of")]
    if good:
        print(f"  smallest fully-coherent expert count: {min(good)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
