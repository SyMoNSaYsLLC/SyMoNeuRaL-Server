#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SyMonSays LLC. All rights reserved.
# PROPRIETARY AND CONFIDENTIAL. Not for distribution. See docs/ops/EXPORTS.md.
"""Slice experts out of a MoE GGUF. Fewer parameters, same active count, same speed.

Owner, 2026-09-11: *"I think we have proven 7B parameters is perfect for my GPU so adjust the
gpt to be 7B"*, after correctly pushing back on my claim that quantisation could not do it.
**They were right and I was wrong**: quantisation cannot reduce parameter COUNT, but expert
pruning can, and gpt-oss is unusually suited to it because 91.4% of its parameters are experts.

## The arithmetic this implements

Measured off the 20B's own tensors:

    total              20.91 B params
    expert weights     19.12 B   (91.4%)  <- the prunable mass
    dense              1.80 B    (8.6%)   <- embeddings, attention, router, norms; NOT prunable

    experts kept   total params   file ~GB   active/token
              32        20.9 B      11.1       4.19 B
              16        11.4 B       6.0       4.19 B
               8         6.6 B       3.5       4.19 B   <- the "7B gpt-oss"
               4         4.2 B       2.2       4.19 B

**Active parameters per token do not change** -- routing still selects 4 -- so generation
speed is roughly unchanged. What is bought is VRAM: ~3.5 GB instead of ~11 GB, which on a
16.3 GB card is the entire constraint. It leaves room for Studio and image to co-reside with
chat, which plain gpt-oss-20b does not.

## Why this is safe to implement and unsafe to do blindly

**Safe to implement.** GGUF stores `ffn_{gate,up,down}_exps.weight` as `(2880, 2880, 32)`
where the expert index is the SLOWEST-varying dimension. Each expert is therefore a
contiguous byte range, and slicing is a byte-range copy that works for MXFP4 without
understanding its block format. The router (`ffn_gate_inp.weight` `(2880, 32)` and its bias
`(32,)`) is sliced to match, and `expert_count` is rewritten.

**Unsafe to do blindly.** Which experts to keep is a measurement, not a default. Pruning the
wrong ones yields a model that chats fine and cannot program, discovered later on a real task
with no obvious cause. `--keep-from` takes a routing capture (`tools/moe_sequence.py`) and
selects per layer by observed usage **per domain**, so no domain's experts are silently lost.
`--keep-first` exists only for smoke-testing the mechanics and is documented as wrong.

## What this does NOT claim

The pruned model is **not** equivalent to the original. Removing 24 of 32 experts removes
capacity the model was trained with, and the router's learned distribution no longer matches
the experts present. Quality must be measured after, not assumed. This tool produces a
candidate for evaluation; it does not produce a promotion.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "symoneural-llm" / "gguf-py"))

import numpy as np                                                    # noqa: E402
from gguf import GGUFReader, GGUFWriter                               # noqa: E402

EXPERT_TAG = "_exps"
ROUTER_TAGS = ("ffn_gate_inp",)


def choose_experts(capture: Path | None, n_layers: int, n_expert: int,
                   keep: int) -> dict[int, list[int]]:
    """Per layer, which expert indices to keep. Union across domains, never pooled counts.

    Taking the union of each domain's top experts rather than the top of pooled counts is the
    whole safety property: a domain that contributes few tokens still gets its experts kept.
    """
    if capture is None:
        # Mechanics-only. Documented as WRONG for any real use.
        return {l: list(range(keep)) for l in range(n_layers)}

    d = json.loads(capture.read_text())
    per_layer_domain: dict[int, dict[str, collections.Counter]] = collections.defaultdict(
        lambda: collections.defaultdict(collections.Counter))
    for dom, seqs in d["domains"].items():
        for s in seqs:
            for row in s["rows"]:
                per_layer_domain[row["layer"]][dom].update(row["experts"])

    out: dict[int, list[int]] = {}
    for l in range(n_layers):
        doms = per_layer_domain.get(l, {})
        if not doms:
            out[l] = list(range(keep))
            continue
        # Round-robin across domains so each contributes its hottest before any contributes
        # its second. Equal voice regardless of how many tokens a domain supplied.
        ranked = {dom: [e for e, _ in c.most_common()] for dom, c in doms.items()}
        chosen: list[int] = []
        i = 0
        while len(chosen) < keep and any(i < len(v) for v in ranked.values()):
            for dom in sorted(ranked):
                if len(chosen) >= keep:
                    break
                if i < len(ranked[dom]) and ranked[dom][i] not in chosen:
                    chosen.append(ranked[dom][i])
            i += 1
        for e in range(n_expert):                       # pad if a layer was under-observed
            if len(chosen) >= keep:
                break
            if e not in chosen:
                chosen.append(e)
        out[l] = sorted(chosen[:keep])
    return out


def layer_of(name: str) -> int | None:
    parts = name.split(".")
    if len(parts) > 1 and parts[0] == "blk" and parts[1].isdigit():
        return int(parts[1])
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--keep", type=int, required=True, help="experts to keep per layer")
    ap.add_argument("--keep-from", default="", help="routing capture JSON (STRONGLY advised)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src = Path(args.src)
    r = GGUFReader(src)

    def field(k):
        v = r.get_field(k)
        return v.contents() if v else None

    arch = field("general.architecture")
    n_expert = field(f"{arch}.expert_count")
    n_used = field(f"{arch}.expert_used_count")
    n_layers = field(f"{arch}.block_count")
    if not n_expert:
        raise SystemExit(f"{src.name} is not a MoE model (no expert_count)")
    if args.keep >= n_expert:
        raise SystemExit(f"--keep {args.keep} must be < expert_count {n_expert}")
    if args.keep < n_used:
        raise SystemExit(f"--keep {args.keep} must be >= expert_used_count {n_used}: "
                         f"the router selects {n_used} every token and cannot select from fewer")

    cap = Path(args.keep_from) if args.keep_from else None
    if cap is None:
        print("  WARNING: no --keep-from. Keeping experts 0..k by index, which is arbitrary\n"
              "           and will damage the model. Use this only to test the mechanics.")
    keepmap = choose_experts(cap, n_layers, n_expert, args.keep)

    print(f"  {src.name}: {arch}, {n_layers} layers, {n_expert} experts, {n_used} used/token")
    print(f"  keeping {args.keep}/{n_expert} per layer"
          f"{' from ' + cap.name if cap else ''}")
    sample = keepmap.get(0, [])
    print(f"  layer 0 keeps: {sample}")

    kept_bytes = dropped_bytes = 0
    plan = []
    for t in r.tensors:
        l = layer_of(t.name)
        is_expert = EXPERT_TAG in t.name
        is_router = any(tag in t.name for tag in ROUTER_TAGS)
        if (is_expert or is_router) and l is not None:
            # Expert index is the SLOWEST-varying dim, so it is the LAST entry of shape.
            if int(t.shape[-1]) != n_expert:
                plan.append((t, None)); kept_bytes += t.n_bytes; continue
            plan.append((t, keepmap[l]))
            kept_bytes += t.n_bytes * args.keep // n_expert
            dropped_bytes += t.n_bytes - t.n_bytes * args.keep // n_expert
        else:
            plan.append((t, None)); kept_bytes += t.n_bytes

    print(f"  tensor bytes: keep {kept_bytes/2**30:.2f} GiB, drop {dropped_bytes/2**30:.2f} GiB")
    if args.dry_run:
        print("  --dry-run: nothing written")
        return 0

    w = GGUFWriter(args.dst, arch)
    for f in r.fields.values():
        k = f.name
        if k in ("GGUF.tensor_count", "GGUF.kv_count") or k.startswith("GGUF."):
            continue
        try:
            val = f.contents()
        except Exception:                                              # noqa: BLE001
            continue
        if k == f"{arch}.expert_count":
            val = args.keep                                            # the whole point
        if k == "general.name":
            val = f"{val} (pruned to {args.keep}/{n_expert} experts)"
        try:
            w.add_key_value(k, val, f.types[0])
        except Exception:                                              # noqa: BLE001
            continue

    # `raw_shape` must be the BYTE shape in numpy order, not the logical shape.
    #
    # The reader hands back logical (2880, 2880, 32) as numpy (32, 2880, 1530) uint8 for
    # MXFP4 -- 2880 elements / 32 per block x 17 bytes = 1530 bytes per row. Two consequences:
    # the expert index is numpy AXIS 0, so `data[idx]` slices experts correctly; and the
    # writer's quant_shape_from_byte_shape() needs shape[-1] to be bytes-per-row, so passing
    # the logical shape makes it reject 2880 as "not a multiple of MXFP4 type size (17)".
    for t, keep_list in plan:
        data = t.data
        if keep_list is not None:
            idx = np.array(keep_list, dtype=np.int64)
            data = np.ascontiguousarray(data[idx])
        w.add_tensor(t.name, data, raw_shape=data.shape, raw_dtype=t.tensor_type)

    w.write_header_to_file()
    w.write_kv_data_to_file()
    w.write_tensors_to_file(progress=True)
    w.close()
    out = Path(args.dst)
    print(f"\n  wrote {out} -- {out.stat().st_size/2**30:.2f} GiB")
    print("  QUALITY IS NOT ASSUMED. Benchmark and evaluate before any promotion.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
