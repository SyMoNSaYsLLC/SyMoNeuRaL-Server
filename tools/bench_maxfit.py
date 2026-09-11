#!/usr/bin/env python3
"""Push a parameter until the card refuses, step back to the last that fits, measure THERE.

Owner, 2026-09-11: *"you get the models you adjust parameters until you overshoot the vram
then back it back just barely under then run the test"*.

## Why the previous sweep was the wrong shape

`bench_config.py` ran a hand-written list of configurations. Every one of them was a guess,
and a guess cannot find an edge -- it can only tell you about the points somebody thought of.
The question is not *"is -c 32768 good"*, it is **"what is the most this card will hold"**,
and the only honest way to answer that is to go until it breaks.

So this **binary-searches the failure boundary**. It deliberately overshoots, records the
value that failed and why, and then benchmarks at the largest value that actually loaded and
generated.

## "Loads" is not "fits", and this distinguishes them

A config can allocate its weights and its KV cache and still die on the first long
generation, because the compute buffers grow with the batch. So a candidate is only accepted
when it **loads AND answers a real generation**, not when `/health` returns 200.

That distinction is the one `docs/specs/qlora-27b-measured.md` records the hard way: the 27B
"fitting with 1.17 GiB to spare" and `registry.py`'s rule that **a run that fits by 0.9 GiB
does not fit -- its OOM is inside the noise.**

## Two answers, not one, because "just barely under" has a cost

The search reports both and refuses to collapse them:

* **`max_fit`** -- the largest value that loaded and generated. The edge.
* **`recommended`** -- the largest value that also leaves `SAFETY_MIB` of headroom.

`SAFETY_MIB` defaults to 1024, matching the governor's `DRAIN_FLOOR_MIB`. Below that floor
the governor cannot tell a drained card from an occupied one, so a config that peaks into it
is one that makes the *scheduler* unreliable even when the model itself is fine. Running at
`max_fit` is a legitimate choice for a single-tenant box; it is not the default, and the
number is printed so it is a choice rather than an accident.

## One parameter at a time

Searching two parameters at once finds a point on a surface, not an edge, and cannot say
which of the two bought the win. `--param` picks the axis; run it again for the next one.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "symoneural-llm" / "build" / "bin" / "symoneural-llm"
GOV = ROOT / "scripts" / "gpu-governor.sh"
PORT = 8099

MODELS = {
    "gptoss": ROOT / "backend/models/staging/openai-gpt-oss-20b/symon-openai-20b.gguf",
    "qwen":   ROOT / "backend/models/llm/symon-1.0-7b-q4_k_m.gguf",
    "qwen3-30b-a3b": ROOT / ("backend/models/staging/candidates/qwen3-30b-a3b/"
                             "Qwen3-30B-A3B-Instruct-2507-UD-Q3_K_XL.gguf"),
    "qwen3-14b": ROOT / "backend/models/staging/candidates/qwen3-14b/Qwen_Qwen3-14B-Q4_K_M.gguf",
    "qwen3-30b-q2": ROOT / ("backend/models/staging/candidates/qwen3-30b-a3b-q2/"
                            "Qwen3-30B-A3B-Instruct-2507-Q2_K_L.gguf"),
}

#: The governor's own drain floor. Below this it cannot distinguish a drained card from an
#: occupied one, so peaking into it breaks the scheduler, not just the model.
SAFETY_MIB = 1024

#: Long enough to grow the KV cache and the compute buffers. A config that loads and answers
#: "4" has not been tested -- the peak is during a real generation.
PROBE_PROMPT = ("Write a detailed technical explanation of how paged attention works in a "
                "modern inference server, including the memory layout.")

PARAMS = {
    # name: (flag, lo, hi, step_floor) -- hi is deliberately absurd; the search finds the edge
    "ctx":    ("-c",   2048, 262144, 1024),
    "ubatch": ("-ub",   128,  16384,   64),
    "batch":  ("-b",    512,  65536,  256),
}


def card_total_mib() -> int:
    p = subprocess.run(["nvidia-smi", "--query-gpu=memory.total",
                        "--format=csv,noheader,nounits"], capture_output=True, text=True)
    return int(p.stdout.strip().splitlines()[0])


def alive(timeout: float = 2.0) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=timeout).read()
        return True
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def generate(max_tokens: int) -> dict | None:
    body = {"model": "b", "messages": [{"role": "user", "content": PROBE_PROMPT}],
            "max_tokens": max_tokens, "temperature": 0.7, "stream": False}
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
                                 method="POST", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return (json.loads(r.read().decode("utf-8", "replace")).get("timings") or {})
    except Exception:                                                   # noqa: BLE001
        return None


class VramPoll(threading.Thread):
    """Peak device memory, sampled. The peak is DURING generation; endpoints would miss it."""

    def __init__(self):
        super().__init__(daemon=True)
        self.peak = 0
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            try:
                p = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                                    "--format=csv,noheader,nounits"],
                                   capture_output=True, text=True, timeout=5)
                self.peak = max(self.peak, int(p.stdout.strip().splitlines()[0]))
            except Exception:                                           # noqa: BLE001
                pass
            self._stop.wait(0.25)

    def stop(self) -> int:
        self._stop.set()
        self.join(timeout=5)
        return self.peak


def try_value(model: Path, base: list[str], flag: str, value: int,
              max_tokens: int) -> dict:
    """Load at `value`, then GENERATE. Both must succeed for this to count as fitting."""
    row = {"value": value, "fits": False, "vram_peak_mib": 0}
    got = subprocess.run([str(GOV), "acquire", "chat", "300", "--new-engine"],
                         env={**os.environ, "SYMONEURAL_OWNER_PID": str(os.getpid())},
                         capture_output=True, text=True, timeout=400)
    if got.returncode != 0:
        row["error"] = "governor refused the lease"
        return row

    poll, proc = VramPoll(), None
    try:
        argv = [str(ENGINE), "-m", str(model), "--port", str(PORT), "--host", "127.0.0.1",
                "--jinja", "-ngl", "99", *base, flag, str(value)]
        proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        poll.start()
        up = False
        for _ in range(300):
            if alive():
                up = True
                break
            if proc.poll() is not None:
                break
            time.sleep(1)
        if not up:
            err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
            row["error"] = ("OOM at load" if "out of memory" in err.lower()
                            else f"did not start (rc={proc.returncode})")
            return row

        # The half that matters. Loading is not fitting.
        t = generate(max_tokens)
        if not t or not isinstance(t.get("predicted_per_second"), (int, float)):
            row["error"] = "loaded but generation failed -- compute buffers did not fit"
            return row
        row.update(fits=True,
                   gen_tok_s=round(t["predicted_per_second"], 1),
                   prefill_tok_s=round(t.get("prompt_per_second") or 0, 1),
                   predicted_n=t.get("predicted_n"))
        return row
    finally:
        row["vram_peak_mib"] = poll.stop()
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
        subprocess.run([str(GOV), "release", "chat"], capture_output=True, text=True,
                       check=False)
        time.sleep(2)


def search(model: Path, base: list[str], flag: str, lo: int, hi: int, floor: int,
           max_tokens: int) -> tuple[list[dict], dict | None]:
    """Binary search the largest value that loads AND generates. Every probe is recorded."""
    tried: list[dict] = []
    best: dict | None = None
    print(f"    probing {flag} in [{lo}, {hi}]")
    while hi - lo > floor:
        mid = ((lo + hi) // 2 // floor) * floor
        if mid <= lo:
            break
        r = try_value(model, base, flag, mid, max_tokens)
        tried.append(r)
        if r["fits"]:
            print(f"      {flag} {mid:>7}  FITS   peak {r['vram_peak_mib']:>6} MiB   "
                  f"gen {r['gen_tok_s']:>6} tok/s")
            best, lo = r, mid
        else:
            print(f"      {flag} {mid:>7}  FAILS  {r.get('error')}")
            hi = mid
    return tried, best


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("model", choices=sorted(MODELS))
    ap.add_argument("--param", default="ctx", choices=sorted(PARAMS))
    ap.add_argument("--base", default="-fa on",
                    help="fixed argv held constant during the search")
    ap.add_argument("--max-tokens", type=int, default=400)
    ap.add_argument("--safety-mib", type=int, default=SAFETY_MIB)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    model = MODELS[args.model]
    if not model.exists():
        raise SystemExit(f"no weights at {model}")
    flag, lo, hi, floor = PARAMS[args.param]
    base = args.base.split()
    total = card_total_mib()

    print(f"  {model.name}")
    print(f"  card {total} MiB   searching {args.param} ({flag})   base: {args.base}")
    print(f"  a candidate must LOAD and GENERATE {args.max_tokens} tokens to count\n")

    tried, best = search(model, base, flag, lo, hi, floor, args.max_tokens)

    fitting = [r for r in tried if r["fits"]]
    max_fit = max(fitting, key=lambda r: r["value"]) if fitting else None
    # `recommended` keeps the governor's drain floor clear. See the module docstring.
    safe = [r for r in fitting if total - r["vram_peak_mib"] >= args.safety_mib]
    recommended = max(safe, key=lambda r: r["value"]) if safe else None

    result = {"model": str(model), "param": args.param, "flag": flag, "base": args.base,
              "card_total_mib": total, "safety_mib": args.safety_mib,
              "probes": tried, "max_fit": max_fit, "recommended": recommended}
    out = ROOT / (args.out or f"review/bench/maxfit-{args.model}-{args.param}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))

    print(f"\n  ── result ──")
    if max_fit:
        head = total - max_fit["vram_peak_mib"]
        print(f"  max_fit      {flag} {max_fit['value']}   peak {max_fit['vram_peak_mib']} MiB"
              f"   headroom {head} MiB   gen {max_fit['gen_tok_s']} tok/s")
        if head < args.safety_mib:
            print(f"               ^ BELOW the {args.safety_mib} MiB governor drain floor: the "
                  f"scheduler cannot tell a drained card from an occupied one here")
    else:
        print("  max_fit      NOTHING in range loaded and generated")
    if recommended:
        print(f"  recommended  {flag} {recommended['value']}   peak "
              f"{recommended['vram_peak_mib']} MiB   headroom "
              f"{total - recommended['vram_peak_mib']} MiB   gen {recommended['gen_tok_s']} tok/s")
    else:
        print(f"  recommended  none -- every fitting config peaks within {args.safety_mib} MiB "
              f"of the card")
    print(f"\n  wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
