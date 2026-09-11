#!/usr/bin/env python3
"""Rank every GGUF on this box for THIS card. Bandwidth-bound, so bytes/token decides.

Owner, 2026-09-11: *"i just want to make sure i have the best option for gpt oss, qwen or
any other LLM"*, with 1.5 hours to test as many as wanted.

## The measurement that reframed all of this

Sampled at 10 Hz during a real 900-token generation (`review/bench/BOTTLENECK-20260911.md`):

    mem clock   14,001 / 14,001 MHz   100%   <- PINNED
    gpu util            93%
    sm clock            93%
    power        227 / 300 W           76%
    temp                62 C

**Memory clock is at its ceiling and power has 73 W spare.** This card is memory-BANDWIDTH
bound on decode, not compute bound and not power bound. Three consequences drive this script:

1. **Time per token scales with BYTES READ per token**, not with parameter count and not with
   FLOPs. So the ranking column is tok/s, and the explanatory column is bytes/token.
2. **Sparse (MoE) beats dense at equal size**, because only the active experts are read.
3. **Raising the power limit buys nothing.** The overclock module (`apps/overclock.py`) is
   real and its +5% is real, and it cannot help this workload. Recorded so nobody re-runs it
   hoping.

## What is measured per model

| column | source | why |
|---|---|---|
| gen tok/s | engine `timings.predicted_per_second` | the answer |
| prefill tok/s | engine `timings.prompt_per_second` | how fast it reads a prompt |
| vram peak | `nvidia-smi` sampled at 4 Hz during generation | the constraint |
| total / active params | GGUF tensor shapes, expert counts | explains the tok/s |
| bytes/token | file size x (active/total) | the bandwidth-bound predictor |
| GB/s achieved | bytes/token x tok/s | how close to the bus ceiling |

`GB/s achieved` is the honest efficiency number and the one that says whether a model is
leaving throughput on the table: two models reading the same bytes should hit the same GB/s,
and one that does not has an access-pattern problem rather than a size problem.

## Seeded and greedy

`temperature=0`, fixed seed. Three earlier runs of the sibling benchmark disagreed with each
other because sampling noise moved token counts by 26%, which is larger than any effect being
measured. Greedy removes it. The cost is that production serves at 0.7, so these are relative
costs under identical conditions, not user-visible latencies.
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
GGUF_PY = ROOT / "symoneural-llm" / "gguf-py"
VENV_PY = ROOT / "training" / ".venv" / "bin" / "python3"
PORT = 8099
SAFETY_MIB = 1024                       # the governor's own drain floor

PROMPTS = [
    ("short", "What is 2 + 2? Answer with the number only."),
    ("mid",   "In three sentences, explain why memory bandwidth limits LLM decoding."),
    ("long",  "Write a detailed technical explanation of how paged attention works in a "
              "modern inference server, including the memory layout. At least 400 words."),
]


def gguf_facts(path: Path) -> dict:
    """Params, active params and architecture, read from the file itself."""
    code = f'''
import json, numpy as np
from gguf import GGUFReader
r = GGUFReader({str(path)!r})
def f(k):
    v = r.get_field(k)
    return v.contents() if v else None
arch = f("general.architecture")
ne, nu = f(f"{{arch}}.expert_count"), f(f"{{arch}}.expert_used_count")
dense = sparse = 0
for t in r.tensors:
    n = int(np.prod(t.shape))
    if "_exps" in t.name: sparse += n
    else: dense += n
total = dense + sparse
active = dense + (sparse * (nu / ne) if ne else 0)
print(json.dumps({{"arch": arch, "total": total, "active": active,
                  "n_expert": ne, "n_expert_used": nu,
                  "ctx_train": f(f"{{arch}}.context_length"),
                  "file_type": f("general.file_type"),
                  "name": f("general.name")}}))
'''
    try:
        p = subprocess.run([str(VENV_PY), "-c", code], capture_output=True, text=True,
                           timeout=180, env={**os.environ, "PYTHONPATH": str(GGUF_PY)})
        return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception as exc:                                            # noqa: BLE001
        return {"error": f"{type(exc).__name__}"}


def alive(t: float = 2.0) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=t).read()
        return True
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def ask(prompt: str, max_tokens: int, seed: int) -> dict | None:
    body = {"model": "b", "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "temperature": 0.0, "seed": seed, "stream": False}
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
                                 method="POST", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return (json.loads(r.read().decode("utf-8", "replace")).get("timings") or {})
    except Exception:                                                   # noqa: BLE001
        return None


class Poll(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True); self.peak = 0; self._s = threading.Event()

    def run(self):
        while not self._s.is_set():
            try:
                p = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                                    "--format=csv,noheader,nounits"],
                                   capture_output=True, text=True, timeout=5)
                self.peak = max(self.peak, int(p.stdout.strip().splitlines()[0]))
            except Exception:                                           # noqa: BLE001
                pass
            self._s.wait(0.25)

    def stop(self) -> int:
        self._s.set(); self.join(timeout=5); return self.peak


def bench(path: Path, label: str, ctx: int, extra: list[str], max_tokens: int,
          seed: int) -> dict:
    facts = gguf_facts(path)
    size_b = path.stat().st_size
    row = {"label": label, "file": path.name, "size_gib": round(size_b / 2**30, 2),
           **facts, "ctx": ctx, "extra": " ".join(extra), "ok": False}

    got = subprocess.run([str(GOV), "acquire", "chat", "300", "--new-engine"],
                         env={**os.environ, "SYMONEURAL_OWNER_PID": str(os.getpid())},
                         capture_output=True, text=True, timeout=400)
    if got.returncode != 0:
        row["error"] = "governor refused the lease"; return row

    poll, proc = Poll(), None
    try:
        argv = [str(ENGINE), "-m", str(path), "--port", str(PORT), "--host", "127.0.0.1",
                "--jinja", "-ngl", "99", "-c", str(ctx), *extra]
        t0 = time.time()
        proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        poll.start()
        up = False
        for _ in range(300):
            if alive(): up = True; break
            if proc.poll() is not None: break
            time.sleep(1)
        row["load_s"] = round(time.time() - t0, 1)
        if not up:
            err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
            row["error"] = ("OOM" if "out of memory" in err.lower()
                            else f"did not start (rc={proc.returncode})")
            return row

        gens, pres = [], []
        for _tag, p in PROMPTS:
            t = ask(p, max_tokens, seed)
            if not t: continue
            if isinstance(t.get("predicted_per_second"), (int, float)):
                gens.append(t["predicted_per_second"])
            if isinstance(t.get("prompt_per_second"), (int, float)):
                pres.append(t["prompt_per_second"])
        if not gens:
            row["error"] = "started but answered nothing"; return row

        tps = statistics.median(gens)
        row.update(ok=True, gen_tok_s=round(tps, 1),
                   prefill_tok_s=round(statistics.median(pres), 1) if pres else None)
        # The bandwidth-bound explanation. Bytes read per token is the file scaled by the
        # fraction of the model a token actually touches -- for a dense model that is 1.0.
        if facts.get("total"):
            frac = facts["active"] / facts["total"]
            bpt = size_b * frac
            row["active_frac"] = round(frac, 4)
            row["bytes_per_token_mib"] = round(bpt / 2**20, 1)
            row["achieved_gb_s"] = round(bpt * tps / 1e9, 1)
        return row
    finally:
        row["vram_peak_mib"] = poll.stop()
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=30)
            except subprocess.TimeoutExpired: proc.kill()
        subprocess.run([str(GOV), "release", "chat"], capture_output=True, text=True,
                       check=False)
        time.sleep(2)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--models", required=True,
                    help="label=path[:ctx][:extra] , comma separated")
    ap.add_argument("--max-tokens", type=int, default=400)
    ap.add_argument("--seed", type=int, default=20260911)
    ap.add_argument("--out", default="review/bench/model-ranking.json")
    args = ap.parse_args()

    specs = []
    for chunk in args.models.split(","):
        chunk = chunk.strip()
        if not chunk: continue
        label, _, rest = chunk.partition("=")
        parts = rest.split(":")
        path = Path(parts[0])
        if not path.is_absolute(): path = ROOT / path
        ctx = int(parts[1]) if len(parts) > 1 and parts[1] else 8192
        extra = parts[2].split() if len(parts) > 2 and parts[2] else ["-fa", "on"]
        specs.append((label, path, ctx, extra))

    rows = []
    for label, path, ctx, extra in specs:
        if not path.exists():
            print(f"  [{label}] MISSING {path}"); continue
        print(f"  [{label}] {path.name}  -c {ctx} {' '.join(extra)}")
        r = bench(path, label, ctx, extra, args.max_tokens, args.seed)
        rows.append(r)
        if r["ok"]:
            print(f"    {r['gen_tok_s']:>7} tok/s   peak {r['vram_peak_mib']:>6} MiB   "
                  f"{r.get('bytes_per_token_mib','?'):>7} MiB/tok   "
                  f"{r.get('achieved_gb_s','?'):>6} GB/s   "
                  f"active {r.get('active_frac','?')}")
        else:
            print(f"    FAILED: {r.get('error')}")

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rows": rows}, indent=2))
    ok = sorted((r for r in rows if r["ok"]), key=lambda r: -r["gen_tok_s"])
    print(f"\n  {'model':22s}{'tok/s':>8}{'VRAM':>8}{'MiB/tok':>9}{'GB/s':>7}{'params':>13}{'active':>12}")
    for r in ok:
        print(f"  {r['label'][:21]:22s}{r['gen_tok_s']:>8}{r['vram_peak_mib']:>8}"
              f"{r.get('bytes_per_token_mib',0):>9}{r.get('achieved_gb_s',0):>7}"
              f"{r.get('total',0)/1e9:>12.1f}B{r.get('active',0)/1e9:>11.2f}B")
    print(f"\n  wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
