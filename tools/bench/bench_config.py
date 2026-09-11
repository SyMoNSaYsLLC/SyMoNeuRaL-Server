#!/usr/bin/env python3
"""Sweep ENGINE CONFIGURATIONS for one model on this card. Find the argv, not the model.

Owner, 2026-09-11: *"no we have control of this we load the same and try different -ng -c
etc etc"*, following *"if we fine tune the oss and configure specifically to my hardware it
will run circles on qwen"*.

## What this measures that `bench_reasoning.py` does not

`bench_reasoning.py` holds the configuration fixed and varies the model. This does the
opposite: **one model, many argvs**, so the question it answers is *"what is the best this
box can do with these weights"* rather than *"which model is faster"*.

That matters because both models were previously measured on `-ngl 99 -c 8192`, a generic
argv chosen for neither of them. gpt-oss is a 32-expert MoE with 131,072 native context;
Qwen is a dense 7B run in production with a draft model and two slots. Neither was tuned.

## The four numbers per config, and why VRAM peak is one of them

| metric | how | why it is here |
|---|---|---|
| load_s | wall time until `/health` answers | a 40 s load is a config you will not use interactively |
| vram_peak_mib | `nvidia-smi` polled during the run | **the constraint.** A config that is 5% faster and does not leave room for the image stack is not faster, it is unusable |
| prefill_tok_s | engine `timings.prompt_per_second` | what `-b`/`-ub` move |
| gen_tok_s | engine `timings.predicted_per_second` | what everyone means by tok/s |

VRAM peak is sampled rather than computed, and it is sampled **during generation** rather
than after load, because the KV cache grows with the conversation and the peak is what
decides whether a second tenant fits. `backend/studio/docs/qlora-27b-measured.md` records the 27B
"fitting" with 1.17 GiB to spare and `registry.py` records that a run fitting by 0.9 GiB does
not fit -- its OOM is inside the noise.

## Configs are data, not code

`CONFIGS` below is a list of (name, extra argv, note). Adding an experiment is adding a row.
The sweep runs them one at a time, each in its own engine process, each holding the GPU lease
through the governor -- so a config that OOMs takes down its own run and nothing else, and
the next row still gets a clean card.

## What it does NOT do

* **It does not judge answers.** Configuration does not change what a model knows. The prompt
  set is short and fixed because it is a load generator here, not an evaluation.
* **It does not pick a winner for you.** It prints the table. A config that wins on tok/s and
  costs 3 GiB more VRAM is a trade-off with a context this script does not have.
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

ROOT = next(_p for _p in Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
ENGINE = ROOT / "symoneural-llm" / "build" / "bin" / "symoneural-llm"
GOV = ROOT / "scripts" / "gpu-governor.sh"

MODELS = {
    "gptoss": ROOT / "backend/models/staging/openai-gpt-oss-20b/symon-openai-20b.gguf",
    "qwen":   ROOT / "backend/models/llm/symon-1.0-7b-q4_k_m.gguf",
    "draft":  ROOT / "backend/models/llm/symon-1.0-draft-0.5b-q4_k_m.gguf",
}
PORT = 8099

# Short and fixed. This is a load generator, not an evaluation -- see the docstring.
PROMPTS = [
    "What is 2 + 2? Answer with the number only.",
    "In one sentence, what does a GPU do that a CPU does not?",
    "Explain in three sentences why quantising a model to 4 bits saves memory.",
]

#: (name, extra argv, note). Adding an experiment is adding a row.
#:
#: `-fa on` is first because flash attention is the single flag most likely to move both
#: numbers, and `auto` means the engine decides -- so "auto" is not a measurement of
#: anything, it is a measurement of whatever the engine chose today.
COMMON = ["-ngl", "99"]
CONFIGS = [
    ("baseline-c8192",      ["-c", "8192"],
     "what both models were measured on before -- generic, tuned for neither"),
    ("fa-on",               ["-c", "8192", "-fa", "on"],
     "flash attention forced on rather than left at auto"),
    ("fa-off",              ["-c", "8192", "-fa", "off"],
     "the control for fa-on; without it 'auto' hides which branch ran"),
    ("ub1024",              ["-c", "8192", "-fa", "on", "-ub", "1024"],
     "physical batch 1024 (default 512) -- prefill throughput"),
    ("ub2048-b4096",        ["-c", "8192", "-fa", "on", "-ub", "2048", "-b", "4096"],
     "wider still; costs VRAM for activations"),
    ("c32768",              ["-c", "32768", "-fa", "on"],
     "4x context -- what a real conversation needs"),
    ("c32768-kvq8",         ["-c", "32768", "-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0"],
     "same context with an 8-bit KV cache -- roughly half the KV VRAM"),
    ("c65536-kvq8",         ["-c", "65536", "-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0"],
     "production's context size, quantised KV"),
    ("c131072-kvq8",        ["-c", "131072", "-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0"],
     "gpt-oss NATIVE context. Expected to fail on qwen (32k trained)"),
]

#: MoE-only. Offloading experts to CPU trades generation speed for VRAM, and on a 16 GiB card
#: holding a 12.8 GiB MoE that trade is the whole question of whether a big context fits.
MOE_CONFIGS = [
    ("ncmoe4-c32768",  ["-c", "32768", "-fa", "on", "-ncmoe", "4"],
     "first 4 layers' experts on CPU -- frees VRAM, costs PCIe per token"),
    ("ncmoe8-c65536",  ["-c", "65536", "-fa", "on", "-ncmoe", "8"],
     "more offload, more context"),
]

#: Qwen-only. The production surface runs a draft model; this is whether that helps.
QWEN_CONFIGS = [
    ("draft-c8192", ["-c", "8192", "-fa", "on", "-md", str(MODELS["draft"]),
                     "-ngld", "99", "--spec-draft-n-max", "4"],
     "speculative decoding, as production runs it"),
    # `-fa off` and the draft model were each best SEPARATELY in the first sweep; nothing
    # tested them together, and "best of A" plus "best of B" is not "best of A+B".
    ("faoff-draft", ["-c", "8192", "-fa", "off", "-md", str(MODELS["draft"]),
                     "-ngld", "99", "--spec-draft-n-max", "4"],
     "the two best single wins combined -- untested until now"),
    ("faoff-draft-c32768", ["-c", "32768", "-fa", "off", "-md", str(MODELS["draft"]),
                            "-ngld", "99", "--spec-draft-n-max", "4"],
     "same, at a context a real conversation needs"),
    ("prod-shape",  ["-c", "65536", "-fa", "on", "-cb", "-np", "2",
                     "-md", str(MODELS["draft"]), "-ngld", "99", "--spec-draft-n-max", "4"],
     "production's actual shape minus the persona adapter"),
]


def alive(port: int, timeout: float = 2.0) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout).read()
        return True
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def ask(port: int, prompt: str, max_tokens: int) -> dict | None:
    body = {"model": "bench", "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "temperature": 0.7, "stream": False}
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions",
                                 method="POST", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return (json.loads(r.read().decode("utf-8", "replace")).get("timings") or {})
    except Exception as exc:                                            # noqa: BLE001
        print(f"      ! {type(exc).__name__}", file=sys.stderr)
        return None


class VramPoll(threading.Thread):
    """Sample total device memory every 250 ms and keep the maximum.

    A thread rather than a reading before and after: the peak is during generation, when the
    KV cache is full, and two point readings would miss it entirely.
    """

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


def run_config(model: Path, name: str, extra: list[str], note: str,
               max_tokens: int) -> dict:
    """One config, start to finish, on a card this function takes and gives back."""
    row = {"config": name, "note": note, "argv": " ".join(extra), "ok": False}

    got = subprocess.run([str(GOV), "acquire", "chat", "300", "--new-engine"],
                         env={**os.environ, "SYMONEURAL_OWNER_PID": str(os.getpid())},
                         capture_output=True, text=True, timeout=400)
    if got.returncode != 0:
        row["error"] = "governor refused the lease"
        return row

    poll = VramPoll()
    proc = None
    try:
        argv = [str(ENGINE), "-m", str(model), "--port", str(PORT), "--host", "127.0.0.1",
                "--jinja", *COMMON, *extra]
        t0 = time.time()
        proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        poll.start()
        up = False
        for _ in range(240):
            if alive(PORT):
                up = True
                break
            if proc.poll() is not None:
                break
            time.sleep(1)
        row["load_s"] = round(time.time() - t0, 1)

        if not up:
            err = (proc.stderr.read().decode("utf-8", "replace") if proc.stderr else "")
            # The reason matters more than the failure: OOM is a config that asked for too
            # much, which is a RESULT, not a broken run.
            row["error"] = ("out of memory" if "out of memory" in err.lower()
                            else f"did not start (rc={proc.returncode})")
            row["stderr_tail"] = err.strip().splitlines()[-3:] if err else []
            return row

        gens, prefills = [], []
        for p in PROMPTS:
            t = ask(PORT, p, max_tokens)
            if not t:
                continue
            if isinstance(t.get("predicted_per_second"), (int, float)):
                gens.append(t["predicted_per_second"])
            if isinstance(t.get("prompt_per_second"), (int, float)):
                prefills.append(t["prompt_per_second"])
        if gens:
            row.update(ok=True,
                       gen_tok_s=round(statistics.median(gens), 1),
                       prefill_tok_s=round(statistics.median(prefills), 1) if prefills else None)
        else:
            row["error"] = "started but answered nothing"
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("model", choices=sorted(k for k in MODELS if k != "draft"))
    ap.add_argument("--max-tokens", type=int, default=200)
    ap.add_argument("--out", default="")
    ap.add_argument("--only", default="", help="comma-separated config names")
    args = ap.parse_args()

    model = MODELS[args.model]
    if not model.exists():
        raise SystemExit(f"no weights at {model}")

    configs = list(CONFIGS)
    configs += MOE_CONFIGS if args.model == "gptoss" else QWEN_CONFIGS
    if args.only:
        want = {s.strip() for s in args.only.split(",")}
        configs = [c for c in configs if c[0] in want]

    print(f"  {model.name}  --  {len(configs)} configs\n")
    rows = []
    for name, extra, note in configs:
        print(f"  [{name}] {' '.join(extra)}")
        r = run_config(model, name, extra, note, args.max_tokens)
        rows.append(r)
        if r["ok"]:
            print(f"    load {r['load_s']:>5}s   peak {r['vram_peak_mib']:>6} MiB   "
                  f"prefill {r.get('prefill_tok_s'):>8}   gen {r['gen_tok_s']:>7} tok/s")
        else:
            print(f"    FAILED: {r.get('error')}   peak {r['vram_peak_mib']} MiB")

    out = ROOT / (args.out or f"review/bench/config-{args.model}-sweep.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"model": str(model), "rows": rows}, indent=2))

    print(f"\n  {'config':22s}{'load':>7}{'peak MiB':>10}{'prefill':>10}{'gen tok/s':>11}")
    for r in rows:
        if r["ok"]:
            print(f"  {r['config']:22s}{r['load_s']:>6}s{r['vram_peak_mib']:>10}"
                  f"{r.get('prefill_tok_s') or 0:>10}{r['gen_tok_s']:>11}")
        else:
            print(f"  {r['config']:22s}{'--':>7}{r['vram_peak_mib']:>10}    {r.get('error')}")
    print(f"\n  wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
