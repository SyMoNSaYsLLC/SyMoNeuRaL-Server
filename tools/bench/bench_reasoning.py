#!/usr/bin/env python3
"""Sweep gpt-oss reasoning_effort against Qwen, on this box, with the real numbers.

Owner, 2026-09-11: *"pretty sure the gpt adjust based off complexity of problem so make sure
to test on every level against qwen"*, and *"if we fine tune the oss and configure
specifically to my hardware it will run circles on qwen"*.

## The question this settles

The 2026-08-22 benchmark (`ops/docs/OPENAI-GPT-OSS-MIGRATION.md` §3d) found gpt-oss faster per
token (166.3 vs 147.6 tok/s) and **ten times more expensive per answer** -- 259 tokens for a
one-sentence reply against Qwen's 25, so 1.72 s wall clock against 0.21 s. It ran at ONE
reasoning setting and did not say which.

`reasoning_effort` is the direct lever on exactly that cost, and the chat template carries it
(`low` / `medium` / `high`, confirmed in `chat_template.jinja`). So the honest comparison is
not one number against one number: it is **three gpt-oss configurations against Qwen**, on the
same prompts, measured the same way.

## What is measured, and why wall clock leads

Per request, from the engine's own `timings` object -- not timed by this script, which would
be measuring the network and the JSON parser as well:

    predicted_n              tokens the model wrote      <- the August finding lives here
    predicted_per_second     generation rate
    prompt_per_second        prefill rate
    predicted_ms             generation wall time

**`predicted_n` is reported before `predicted_per_second` in every table this writes**, because
reading them the other way round is what makes a 13% rate win look like a victory next to a
10x token cost. A model that is faster per token and slower per answer is slower.

## Prompt set: complexity is the independent variable

The owner's hypothesis is that gpt-oss *"adjusts based off complexity of problem"*. That is
testable and it is the reason the prompts are graded rather than uniform: if the hypothesis
holds, the token cost gap should be small on HARD prompts (where reasoning earns its keep) and
large on TRIVIAL ones (where it is pure overhead). One prompt cannot show that shape.

## It DOES evict chat, and that is not optional

Measured 2026-09-11: the card is 16,303 MiB, Qwen holds 8,332 of it, and gpt-oss needs ~12.8
GiB of weights before any KV cache. **They cannot co-reside**, so measuring the candidate means
evicting the incumbent. Two consequences are designed around rather than hidden:

1. **Qwen is measured FIRST**, while it is still up. If the candidate then fails to start, the
   incumbent's numbers survive and the run is still worth something.
2. **The card is taken through `scripts/gpu-governor.sh acquire chat 300 --new-engine`**, not
   by killing the engine. Killing it frees the VRAM and leaves the governor's `resident`
   marker naming a dead pid -- the stale-marker case its boot-id stamp exists to catch.

   **`--new-engine` is load-bearing and the first run of this script proved it.** `chat` is
   the honest surface name -- this IS a chat engine, the same binary with different weights --
   but acquiring `chat` while `chat` was resident evicted *nothing*, because the governor
   compared surface NAMES and saw no tenant change. The candidate then died on arrival:

       ggml_backend_cuda_buffer_type_alloc_buffer: allocating 12036.68 MiB on device 0:
       cudaMalloc failed: out of memory

   The flag was added to the governor in `069f344d` for exactly this call: it says the caller
   is bringing its own engine, so a resident one goes even when the name matches. A surface
   name is not an identity.

**Chat is down from the eviction until the next request to `/api/chat`**, which restarts it.
Use `--qwen-only` to measure the incumbent without touching the card at all.

## What this script will not do

* **It does not judge answer quality.** It records the full text for a human to read. The
  August run found *both* models answered "What is SyMoNeuRaL?" wrongly, which measured
  fluency and not knowledge -- a scoring function here would have hidden that.
* **It does not promote anything.** Promotion is `--activate-candidate` in
  `scripts/model-staging/symoneural-model-stage.sh`, behind six gates, and it is a decision.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = next(_p for _p in Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
ENGINE = ROOT / "symoneural-llm" / "build" / "bin" / "symoneural-llm"
CANDIDATE = ROOT / "models/staging/openai-gpt-oss-20b/symon-openai-20b.gguf"
QWEN = ROOT / "models/llm/symon-1.0-7b-q4_k_m.gguf"

SMOKE_PORT = 8099            # never 8081: a candidate on the production port proves nothing
QWEN_PORT = 8081             # where production Qwen already listens

#: Graded by complexity ON PURPOSE. See the module docstring: the owner's hypothesis is about
#: how the model responds to difficulty, and a uniform prompt set cannot show that shape.
PROMPTS = [
    ("trivial", "Reply with exactly one short sentence: what colour is the sky on a clear day?"),
    ("trivial", "What is 2 + 2? Answer with the number only."),
    ("easy",    "In one sentence, what does a GPU do that a CPU does not?"),
    ("easy",    "Name three programming languages. List only."),
    ("medium",  "Explain in two sentences why quantising a model to 4 bits saves memory."),
    ("medium",  "A server has 16 GB of VRAM. A model needs 12.8 GB of weights and 3.9 GB of "
                "KV cache. Does it fit? Show the arithmetic."),
    ("hard",    "A 20B mixture-of-experts model activates 4 of 32 experts per token. A dense "
                "7B model activates all of its parameters. Which generates tokens faster on "
                "the same card, and why might the MoE still finish an answer slower?"),
    ("hard",    "Write a Python function that finds the longest palindromic substring in "
                "O(n) time. Explain the algorithm choice in one sentence after the code."),
]


def post(port: int, path: str, body: dict, timeout: float = 300.0) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", method="POST",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def alive(port: int, timeout: float = 2.0) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout).read()
        return True
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def ask(port: int, prompt: str, effort: str | None, max_tokens: int,
        seed: int = 20260911, temperature: float = 0.0) -> dict | None:
    """One request. Returns the engine's own timings plus the text, or None on failure.

    ## Why seed AND temperature=0

    The first three runs of this benchmark were not reproducible and the conclusion flipped
    between them: qwen 82.5 tokens vs gpt-oss 63 in one run, qwen 59.5 vs gpt-oss 75 in the
    next. Nothing about the models changed -- only the sampling. Token count drives wall
    clock, so wall clock inherited the noise, and a 26% difference at n=8 prompts sat well
    inside it.

    `seed` alone fixes sampling *within* one engine configuration. It does NOT guarantee
    identical output ACROSS configurations: `-fa on` vs `-fa off` and different batch shapes
    take different kernel paths, and tiny numeric differences compound into a different token
    once any two logits are close. Since this script's whole purpose is comparing different
    configurations, greedy decoding (`temperature=0`) is what actually removes the variance --
    it takes the argmax, so a numeric difference has to change the *ranking* of the top two
    tokens to change the output, not merely perturb a probability.

    Both are set. The seed matters if anyone raises the temperature; temperature=0 is what
    makes the default run comparable.

    **The cost, stated:** greedy is not how the surface serves. Production runs 0.7. So these
    numbers measure the models' relative cost under identical conditions, not the exact
    latency a user sees. `--temperature` raises it for anyone who wants the other question.
    """
    body: dict = {"model": "bench", "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": max_tokens, "temperature": temperature,
                  "seed": seed, "stream": False}
    if effort:
        # llama-server passes these through to the jinja template, which is where
        # reasoning_effort is consumed. Confirmed present in chat_template.jinja.
        body["chat_template_kwargs"] = {"reasoning_effort": effort}
    t0 = time.time()
    try:
        d = post(port, "/v1/chat/completions", body)
    except Exception as exc:                                            # noqa: BLE001
        print(f"      ! {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    wall = time.time() - t0
    t = d.get("timings") or {}
    msg = (d.get("choices") or [{}])[0].get("message") or {}
    return {
        "text": msg.get("content") or "",
        "reasoning": msg.get("reasoning_content") or "",
        "wall_s": round(wall, 3),
        # Read the token count before the rate. See the module docstring.
        "predicted_n": t.get("predicted_n"),
        "predicted_per_second": t.get("predicted_per_second"),
        "prompt_n": t.get("prompt_n"),
        "prompt_per_second": t.get("prompt_per_second"),
        "predicted_ms": t.get("predicted_ms"),
    }


def start_engine(model: Path, port: int, extra: list[str]) -> subprocess.Popen:
    # `-c 8192` only when the caller did not bring its own. A default that silently
    # overrides a measured config is how a tuned run quietly becomes an untuned one.
    argv = [str(ENGINE), "-m", str(model), "--port", str(port), "--host", "127.0.0.1",
            "-ngl", "99", *([] if "-c" in extra else ["-c", "8192"]), *extra]
    print(f"  starting {model.name} on :{port}")
    proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(180):
        if alive(port):
            print(f"  up after {_}s")
            return proc
        if proc.poll() is not None:
            raise SystemExit(f"engine exited {proc.returncode} before answering on :{port}")
        time.sleep(1)
    proc.terminate()
    raise SystemExit(f"engine did not answer on :{port} within 180s")


def run_isolated(model: Path, label: str, efforts, args,
                 extra: list[str] | None = None) -> list[dict]:
    """Take the card, start `model` on the smoke port, run the arms, always give it back.

    Factored out so the candidate and the incumbent go through byte-identical setup. Two
    copies of this sequence is how one arm quietly acquires a flag the other does not have,
    which is the exact defect this function exists to correct.
    """
    gov = str(ROOT / "scripts" / "gpu-governor.sh")
    # `--new-engine` is load-bearing: acquiring the resident surface used to evict nothing,
    # because the governor compared surface NAMES. See 069f344d.
    print(f"\n  acquiring the card for {model.name} (--new-engine)")
    got = subprocess.run([gov, "acquire", "chat", "300", "--new-engine"],
                         env={**os.environ, "SYMONEURAL_OWNER_PID": str(os.getpid())},
                         capture_output=True, text=True, timeout=400)
    if got.returncode != 0:
        raise SystemExit(f"governor refused the lease:\n{got.stdout}\n{got.stderr}")
    print("  lease held")

    rows: list[dict] = []
    proc = None
    try:
        proc = start_engine(model, SMOKE_PORT, ["--jinja", *(extra or [])])
        for effort in (efforts if efforts else [None]):
            name = f"{label} reasoning={effort}" if effort else label
            # `--repeat` exists to PROVE the seed worked rather than assume it. Two identical
            # passes inside one engine process must produce identical token counts; if they
            # do not, the seed is not controlling what it was supposed to and every
            # comparison built on it is noise wearing a decimal point.
            for pass_no in range(1, max(1, args.repeat) + 1):
                tag = name if args.repeat == 1 else f"{name} [pass {pass_no}]"
                rows += run_arm(tag, SMOKE_PORT, effort, args.max_tokens,
                                args.seed, args.temperature)
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
        subprocess.run([gov, "release", "chat"], capture_output=True, text=True, check=False)
        print("\n  engine stopped, lease released; the card is back")
    return rows


def run_arm(label: str, port: int, effort: str | None, max_tokens: int,
            seed: int = 20260911, temperature: float = 0.0) -> list[dict]:
    rows = []
    print(f"\n  [{label}]")
    for grade, prompt in PROMPTS:
        r = ask(port, prompt, effort, max_tokens, seed, temperature)
        if r is None:
            continue
        r["grade"], r["prompt"] = grade, prompt
        r["arm"] = label
        rows.append(r)
        print(f"    {grade:8s} {r['predicted_n'] or 0:5d} tok  "
              f"{r['predicted_per_second'] or 0:7.1f} tok/s  {r['wall_s']:6.2f}s")
    return rows


def summarise(rows: list[dict]) -> dict:
    """Per-arm and per-grade aggregates. Medians, because one slow request skews a mean."""
    def med(xs):
        xs = [x for x in xs if isinstance(x, (int, float))]
        return round(statistics.median(xs), 2) if xs else None
    out: dict = {}
    for arm in dict.fromkeys(r["arm"] for r in rows):
        a = [r for r in rows if r["arm"] == arm]
        out[arm] = {
            "requests": len(a),
            "median_tokens_written": med([r["predicted_n"] for r in a]),
            "total_tokens_written": sum(r["predicted_n"] or 0 for r in a),
            "median_tok_per_s": med([r["predicted_per_second"] for r in a]),
            "median_wall_s": med([r["wall_s"] for r in a]),
            "total_wall_s": round(sum(r["wall_s"] for r in a), 2),
            "by_grade": {g: {"median_tokens": med([r["predicted_n"] for r in a
                                                   if r["grade"] == g]),
                             "median_wall_s": med([r["wall_s"] for r in a if r["grade"] == g])}
                         for g in dict.fromkeys(r["grade"] for r in a)},
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--out", default="review/bench/gptoss-vs-qwen.json")
    ap.add_argument("--seed", type=int, default=20260911)
    ap.add_argument("--temperature", type=float, default=0.0,
                    help="0 = greedy = reproducible. Production serves 0.7.")
    ap.add_argument("--repeat", type=int, default=1,
                    help="run each arm N times; proves the seed actually made it reproducible")
    ap.add_argument("--best-configs", action="store_true",
                    help="run each model on the argv it won with (bench_config measurements)")
    ap.add_argument("--isolated-qwen", action="store_true",
                    help="run Qwen through the SAME isolated path as the candidate "
                         "(no draft model, no persona adapter, -c 8192) -- base vs base")
    ap.add_argument("--qwen-only", action="store_true",
                    help="measure the incumbent and stop; never touches the card")
    ap.add_argument("--skip-qwen", action="store_true",
                    help="gpt-oss arms only; useful when :8081 is busy serving")
    args = ap.parse_args()

    if not CANDIDATE.exists():
        raise SystemExit(f"candidate not converted yet: {CANDIDATE}")

    rows: list[dict] = []

    # Qwen FIRST, while it is still resident. gpt-oss needs ~12.8 GiB of weights and the card
    # has 16.3 GiB total with Qwen holding 8.3 -- they cannot co-reside, so measuring the
    # candidate means evicting the incumbent. Measuring the incumbent first means the
    # comparison survives even if the candidate fails to start.
    if not args.skip_qwen:
        if alive(QWEN_PORT):
            rows += run_arm("qwen (production :8081)", QWEN_PORT, None, args.max_tokens,
                            args.seed, args.temperature)
        else:
            print("  qwen not resident on :8081 and this script will not start it")

    if args.qwen_only:
        write_out(args, rows)
        return 0

    # ---- the fairness arm ------------------------------------------------------------
    #
    # The production Qwen arm above is NOT base-vs-base, and the difference is not small.
    # `api.py:1285-1319` starts it with:
    #
    #     -ngl 99  -c 65536  --no-warmup  -cb  -np 2
    #     -md <draft>  -ngld 99  --spec-draft-n-max N     <- speculative decoding
    #     --lora <persona adapter>                        <- changes what it writes
    #
    # gpt-oss ran on `-ngl 99 -c 8192 --jinja`: no draft model, no adapter, one slot. So the
    # first comparison was *production Qwen with two accelerators* against *bare gpt-oss*,
    # and reading it as an architecture comparison would credit gpt-oss's deficit to the
    # wrong cause. This arm runs Qwen through the SAME `start_engine` with the SAME argv.
    #
    # Both numbers are worth having and they answer different questions:
    #   production  what a user actually experiences today
    #   isolated    what the weights do, with nothing helping either side
    if args.isolated_qwen:
        if not QWEN.exists():
            raise SystemExit(f"qwen weights not found: {QWEN}")
        rows += run_isolated(QWEN, "qwen (isolated, same argv)", None, args)
        write_out(args, rows)
        return 0

    # ---- each model on the argv IT won with -----------------------------------------
    #
    # Measured by tools/bench/bench_config.py and tools/bench/bench_maxfit.py, 2026-09-11. Using one
    # shared argv was the right control for "which weights are faster" and the WRONG one
    # for "what can this box do", because the shared argv was tuned for neither model:
    #
    #   gpt-oss   -c 66560 -fa on     168.8 tok/s, peak 15,131 MiB, 1,172 MiB headroom.
    #                                 -fa off costs it 4.4x prefill (655 -> 148).
    #                                 -c 99328 also fits but leaves 462 MiB, under the
    #                                 governor's 1024 MiB drain floor -- the scheduler
    #                                 stops being able to tell a drained card from a full
    #                                 one, so the edge is real and deliberately not used.
    #   qwen      -c 32768 -fa off    145.4 tok/s with fa OFF -- the opposite of gpt-oss,
    #                                 and measured twice. The draft model HURTS here
    #                                 (143.4 with it, 145.4 without), which is why it is
    #                                 absent despite production running one.
    #
    # Context differs on purpose: 66,560 and 32,768 are each model's own usable ceiling
    # (gpt-oss trains to 131,072 but cannot fit it here; qwen trains to 32,768). Equalising
    # them would handicap whichever model has more to give.
    if args.best_configs:
        rows += run_isolated(QWEN, "qwen (best: -c 32768 -fa off)", None, args,
                             extra=["-c", "32768", "-fa", "off"])
        rows += run_isolated(CANDIDATE, "gpt-oss (best: -c 66560 -fa on)",
                             ["low", "medium"], args,
                             extra=["-c", "66560", "-fa", "on"])
        write_out(args, rows)
        return 0

    # Take the card through the GOVERNOR, not by killing the engine behind its back.
    # `acquire chat` takes the mutex and evicts whatever is resident, which is exactly the
    # eviction path `api.py` uses when an image render needs the card. Killing the process
    # directly would free the VRAM and leave the governor's `resident` marker naming a dead
    # pid -- the stale-marker case its boot-id stamp exists to catch.
    #
    # `chat` is the honest surface name: this IS a chat engine, the same binary with
    # different weights, so it matches `surface_pattern chat` and the governor can evict
    # THIS process later if something else needs the card. Acquiring under a name whose
    # pattern does not match our own process would make us un-evictable.
    # `--new-engine` is load-bearing and was added to the governor for this exact call.
    # Without it, `acquire chat` over a resident `chat` evicts NOTHING -- the surface names
    # match, so the governor sees no tenant change. That is what produced the cudaMalloc
    # failure on the first run of this script: 12.8 GiB of gpt-oss met 8.3 GiB of resident
    # Qwen on a 16.3 GiB card. See 069f344d.
    print("\n  acquiring the card (--new-engine: same surface, different process)")
    gov = str(ROOT / "scripts" / "gpu-governor.sh")
    got = subprocess.run([gov, "acquire", "chat", "300", "--new-engine"],
                         env={**os.environ, "SYMONEURAL_OWNER_PID": str(os.getpid())},
                         capture_output=True, text=True, timeout=400)
    if got.returncode != 0:
        raise SystemExit(f"governor refused the lease:\n{got.stdout}\n{got.stderr}")
    print("  lease held, incumbent evicted")

    # The lease is now held, so EVERYTHING after this point runs under try/finally.
    # It did not on the first run: `start_engine` raised SystemExit from outside the try,
    # the finally never ran, and the lock was left held by a process that had exited --
    # which is precisely what the release-in-finally comment below was written to prevent.
    proc = None
    try:
        proc = start_engine(CANDIDATE, SMOKE_PORT, ["--jinja"])
        for effort in ("low", "medium", "high"):
            rows += run_arm(f"gpt-oss reasoning={effort}", SMOKE_PORT, effort,
                            args.max_tokens, args.seed, args.temperature)
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
        # Release names itself: the governor refuses a release from a claimant that does not
        # hold the lock, after the API's shutdown hook once handed away a running fine-tune's
        # card with a bare `release`.
        subprocess.run([gov, "release", "chat"], capture_output=True, text=True, check=False)
        print("\n  candidate engine stopped, lease released; the card is back")
        print("  chat restarts on the next request to /api/chat")

    write_out(args, rows)
    return 0


def check_reproducible(rows: list[dict]) -> list[str]:
    """Compare repeated passes of the same arm. Returns a list of disagreements.

    This is the check that makes the seed a fact rather than an intention. It groups by
    (arm-without-pass-tag, prompt) and asserts every pass produced the same token count.
    """
    import re
    groups: dict[tuple, set] = {}
    for r in rows:
        base = re.sub(r" \[pass \d+\]$", "", r["arm"])
        groups.setdefault((base, r["prompt"]), set()).add(r["predicted_n"])
    bad = []
    for (arm, prompt), counts in groups.items():
        if len(counts) > 1:
            bad.append(f"{arm} | {prompt[:44]}... -> {sorted(counts)}")
    return bad


def write_out(args, rows: list[dict]) -> None:
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"measured_on": time.strftime("%Y-%m-%d %H:%M:%S"),
               "prompts": len(PROMPTS), "max_tokens": args.max_tokens,
               "summary": summarise(rows), "rows": rows,
               "read_this_first": ("tokens written is the column the August benchmark's "
                                   "conclusion turned on; read it before tok/s.")}
    bad = check_reproducible(rows)
    payload["reproducible"] = not bad
    payload["disagreements"] = bad
    out.write_text(json.dumps(payload, indent=2))
    if bad:
        print(f"\n  !! NOT REPRODUCIBLE -- {len(bad)} prompt(s) gave different token counts")
        for b in bad[:8]:
            print(f"     {b}")
        print("     every comparison below is inside this noise")
    elif any("[pass " in r["arm"] for r in rows):
        print("\n  reproducible: every repeated pass produced identical token counts")
    print(f"\n  wrote {out.relative_to(ROOT)}")
    for arm, s in payload["summary"].items():
        print(f"    {arm:30s} median {s['median_tokens_written']:>6} tok  "
              f"{s['median_tok_per_s']:>7} tok/s  {s['median_wall_s']:>6}s wall")


if __name__ == "__main__":
    sys.exit(main())
