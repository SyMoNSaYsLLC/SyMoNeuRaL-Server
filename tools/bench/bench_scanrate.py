#!/usr/bin/env python3
"""How many parameters can this GPU actually scan per second? The ceiling everything sits under.

Owner, 2026-09-11: *"we need a test to see how many actual parameters this gpu can scan in a
minute"*, and the insight behind it: *"why does every parameter have to be loaded? ... My
brain is not limited to reading parameters ... where the intelligence comes in is how i know
how to get to the answer or get to that area of the brain"*.

## Why this number is THE number on this box

Sampled at 10 Hz during a real generation: memory clock pinned at 14,001/14,001 MHz (100%),
power at 227/300 W (76%), temp 62 C. **Memory bandwidth is the binding constraint**, so
decode speed is not a question of FLOPs -- it is bytes read per second divided by bytes read
per token. A parameter is only "scanned" by being read out of VRAM.

So the scan rate is a property of the CARD, and every model's tok/s is that rate divided by
how many parameters that model insists on reading per token. Which makes the interesting
question the owner's one: **how few parameters can you get away with reading?**

## Two numbers, and the gap between them is the opportunity

* **ceiling** -- the best bytes/s any model achieved here. This is what the bus can do in
  practice, measured, not the spec sheet.
* **achieved** -- what each model actually gets. A model below the ceiling is leaving
  bandwidth unused, which is a software problem (gather patterns, kernel efficiency), not a
  hardware limit.

Measured 2026-09-11: dense Qwen models reach 719-729 GB/s. gpt-oss reaches 459 GB/s and
Qwen3-30B-A3B reaches 341 GB/s -- **the sparse models are the ones leaving bandwidth on the
floor**, because scattered expert reads do not stream like a dense matmul does.

That is the counter-intuitive result worth keeping: sparsity buys you fewer bytes to read,
then gives some of it back in worse read efficiency.

## Params per minute, and why quantisation is a multiplier on intelligence

Parameters are not bytes. At 4 bits a parameter costs half a byte, so the same bus scans
twice as many parameters per second as at 8 bits. This prints params/minute at each common
quantisation so the trade is explicit: **quantisation is not only a memory saving, it is
directly a scan-rate multiplier.**
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = next(_p for _p in Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
BENCH = ROOT / "review" / "bench"

#: bits per weight for the common GGUF schemes, effective (including scales/mins).
QUANTS = [("Q2_K", 2.6), ("Q3_K", 3.4), ("MXFP4", 4.25), ("Q4_K_M", 4.8),
          ("Q6_K", 6.6), ("Q8_0", 8.5), ("F16", 16.0)]


def load_rows() -> list[dict]:
    rows = []
    for f in sorted(BENCH.glob("ranking-*.json")):
        try:
            rows += [r for r in json.loads(f.read_text()).get("rows", []) if r.get("ok")]
        except (OSError, ValueError):
            continue
    return rows


def main() -> int:
    rows = load_rows()
    if not rows:
        print("  no ranking data in review/bench/ -- run tools/bench/bench_models.py first")
        return 1

    print("  ── what each model achieves ──\n")
    print(f"  {'model':20s}{'tok/s':>8}{'MiB/token':>11}{'GB/s':>8}{'params/min':>14}{'of ceiling':>12}")
    ceiling = max(r.get("achieved_gb_s") or 0 for r in rows)
    for r in sorted(rows, key=lambda r: -(r.get("achieved_gb_s") or 0)):
        gbs = r.get("achieved_gb_s") or 0
        # Parameters scanned per minute = active params per token x tokens per second x 60.
        ppm = (r.get("active") or 0) * (r.get("gen_tok_s") or 0) * 60
        print(f"  {r['label'][:19]:20s}{r.get('gen_tok_s',0):>8}"
              f"{r.get('bytes_per_token_mib',0):>11}{gbs:>8}"
              f"{ppm/1e12:>12.1f} T{100*gbs/ceiling:>11.0f}%")

    print(f"\n  ── the CARD's measured ceiling: {ceiling:.0f} GB/s ──")
    print(f"  (best any model achieved here; the spec sheet is not the measurement)\n")
    print(f"  {'quantisation':14s}{'bits/param':>12}{'params/second':>16}{'params/MINUTE':>16}")
    for name, bits in QUANTS:
        pps = ceiling * 1e9 / (bits / 8)
        print(f"  {name:14s}{bits:>12.2f}{pps/1e12:>14.2f} T{pps*60/1e12:>14.1f} T")

    print("\n  ── what that means for the owner's question ──")
    best = max(rows, key=lambda r: (r.get("active") or 0) * (r.get("gen_tok_s") or 0))
    ppm_best = (best.get("active") or 0) * (best.get("gen_tok_s") or 0) * 60
    print(f"  most parameters actually scanned per minute: {ppm_best/1e12:.1f} T  ({best['label']})")
    # Compared against the ceiling AT THAT MODEL'S OWN quantisation. Comparing a Q2 model's
    # parameter count against a Q4 ceiling is apples to oranges and produced a nonsense
    # negative "headroom" on the first run of this tool.
    bpt = (best.get("bytes_per_token_mib") or 0) * 2**20
    bits = (bpt * 8 / best["active"]) if best.get("active") else 4.8
    ceil_same = ceiling * 1e9 / (bits / 8) * 60
    print(f"  the bus could scan                          {ceil_same/1e12:.1f} T  "
          f"at this model's own {bits:.1f} bits/param")
    print(f"  bandwidth this model leaves unused           "
          f"{100*(1-(best.get('achieved_gb_s') or 0)/ceiling):.0f}%")
    print()
    print("  A parameter only counts as scanned when it is READ. Reading fewer of them per")
    print("  token -- MoE routing, contextual sparsity, hot/cold placement -- raises tokens")
    print("  per second WITHOUT needing a faster card. That is the whole fabric thesis, and")
    print("  the numbers above are the budget it would be spending.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
