#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SyMonSays LLC. All rights reserved.
"""Run one fixed question set against any model+config. Save every prompt and response.

Owner, 2026-09-11: *"this is really smart to use the local model to find the answers lets
figure this out using the different models plus your expert levels, just make a QA folder in
review with the prompts and responses"*, and *"put against the gpt 20B using same
theory/code and then tested against all the QWENs using the same theory and code"*.

## Why this exists separately from the speed benchmarks

Everything measured today was speed, VRAM or context. **Not one number was about whether the
answers are any good.** That gap was named honestly in the model-choice argument and this
closes it: same prompts, same settings, every response written to disk for a human to read.

The comparison is only fair if the harness is identical across models, so configuration is an
argument, never a default buried in the code. Running the 120B, the 20B, the pruned variants
and the Qwens through this one entry point is the point.

## Recorded, not scored

No automatic grading. A scoring function would need a rubric nobody has written, and the
August run already demonstrated the failure mode -- gpt-oss and Qwen both answered "what is
SyMoNeuRaL" confidently and wrongly, which a similarity score would have rated highly.
Responses are written verbatim to `review/QA/` with their timings; judgement stays human.

Greedy and seeded, so re-running a model reproduces its answers and two models differ because
they differ rather than because they sampled differently.
"""
from __future__ import annotations

import argparse
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
QA = ROOT / "review" / "QA"
PORT = 8099

#: Fixed, graded, and chosen so a human can tell right from wrong at a glance. Two have
#: objectively checkable answers; the rest are judged by reading.
QUESTIONS = [
    ("arith",     "What is 2+2? Answer with the number only."),
    ("list",      "Name three colours."),
    ("code",      "Write a Python function that reverses a string. Code only."),
    ("reason",    "A server has 16 GB of VRAM. A model needs 12.8 GB of weights and 3.9 GB "
                  "of KV cache. Does it fit? Show the arithmetic."),
    ("explain",   "Explain in three sentences why memory bandwidth limits LLM decoding."),
    ("factual",   "What is the capital of Australia?"),
    ("trap",      "What is SyMoNeuRaL? If you do not know, say so."),
    ("instruct",  "List exactly two prime numbers greater than 100. Nothing else."),
]


def alive(t: float = 2.0) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=t).read()
        return True
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def ask(prompt: str, max_tokens: int, seed: int) -> dict:
    body = {"model": "qa", "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "temperature": 0.0, "seed": seed, "stream": False}
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
                                 method="POST", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as exc:                                            # noqa: BLE001
        return {"error": type(exc).__name__, "wall_s": round(time.time() - t0, 2)}
    m = (d.get("choices") or [{}])[0].get("message", {})
    t = d.get("timings") or {}
    return {"content": m.get("content") or "",
            # gpt-oss puts its chain of thought here. Kept because an empty `content` with a
            # long `reasoning_content` is the exact signature of a broken pruned model.
            "reasoning": (m.get("reasoning_content") or "")[:500],
            "tokens": t.get("predicted_n"), "tok_s": round(t.get("predicted_per_second") or 0, 2),
            "wall_s": round(time.time() - t0, 2)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--args", default="-fa on -c 8192",
                    help="engine argv held constant across the question set")
    ap.add_argument("--max-tokens", type=int, default=600)
    ap.add_argument("--seed", type=int, default=20260911)
    a = ap.parse_args()

    model = Path(a.model)
    if not model.exists():
        raise SystemExit(f"no model at {model}")
    QA.mkdir(parents=True, exist_ok=True)

    got = subprocess.run([str(GOV), "acquire", "chat", "300", "--new-engine"],
                         env={**os.environ, "SYMONEURAL_OWNER_PID": str(os.getpid())},
                         capture_output=True, text=True, timeout=400)
    if got.returncode != 0:
        raise SystemExit("governor refused the lease")

    proc, rows = None, []
    try:
        argv = [str(ENGINE), "-m", str(model), "--port", str(PORT), "--host", "127.0.0.1",
                "-ngl", "99", "--jinja", *a.args.split()]
        print(f"  {a.label}: {' '.join(a.args.split())}")
        proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(400):
            if alive():
                break
            if proc.poll() is not None:
                raise SystemExit(f"engine exited {proc.returncode}")
            time.sleep(1)
        else:
            raise SystemExit("engine never answered /health")

        for tag, q in QUESTIONS:
            r = ask(q, a.max_tokens, a.seed)
            rows.append({"tag": tag, "question": q, **r})
            head = (r.get("content") or r.get("error", "")).strip().replace("\n", " ")[:64]
            print(f"    {tag:9s} {r.get('tokens') or 0:>4} tok  "
                  f"{r.get('tok_s') or 0:>7} tok/s  {head}")
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
        subprocess.run([str(GOV), "release", "chat"], capture_output=True, text=True,
                       check=False)

    out = QA / f"{a.label}.json"
    out.write_text(json.dumps({"label": a.label, "model": model.name,
                               "engine_args": a.args, "seed": a.seed,
                               "answers": rows}, indent=2))
    md = QA / f"{a.label}.md"
    lines = [f"# QA — {a.label}", "",
             f"`{model.name}`  ·  `{a.args}`  ·  seed {a.seed}  ·  temperature 0", ""]
    for r in rows:
        lines += [f"## {r['tag']}", "", f"**Q:** {r['question']}", ""]
        if r.get("reasoning"):
            lines += ["<details><summary>reasoning channel</summary>", "",
                      "```", r["reasoning"][:500], "```", "", "</details>", ""]
        lines += ["**A:**", "", "```", (r.get("content") or f"[{r.get('error','empty')}]"), "```",
                  "", f"*{r.get('tokens')} tokens · {r.get('tok_s')} tok/s · {r.get('wall_s')}s*", ""]
    md.write_text("\n".join(lines))
    print(f"  wrote {out.relative_to(ROOT)} and {md.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
