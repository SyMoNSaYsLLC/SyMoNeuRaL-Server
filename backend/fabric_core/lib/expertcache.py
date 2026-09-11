# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SyMonSays LLC. All rights reserved.
#
# SyMoNeuRaL Adaptive Fabric -- Residency Manager / Transfer Policy.
# PROPRIETARY AND CONFIDENTIAL. Not for distribution. See ops/registry/EXPORTS.md.
"""Expert residency simulation: can a small VRAM cache serve a model too big for the card?

Owner, 2026-09-11: *"see if you can get that gpt oss 120B loaded by using this proprietary
software"*, and *"Make sure this is symoneural proprietary"*.

## The question, with the numbers that make it precise

gpt-oss-120b Q2_K is 58.27 GB. Measured decomposition, using the 91.4% expert fraction read
off the 20B's own tensors:

    dense weights        5.01 GB   -> fits VRAM
    expert weights      53.26 GB   -> must live in the 88 GB of system RAM
    one expert          11.84 MiB
    experts per token      144     (4 of 128, x 36 layers)
    bytes per token      1704 MiB  if nothing is cached

At the measured Gen3 x8 host-to-device rate of 6.93 GB/s (`performance/results/P1.6`), moving
1704 MiB per token costs **258 ms -- 3.9 tok/s.** Unusable.

After the dense weights and the governor's 1024 MiB drain floor, **10,148 MiB of VRAM is free
for an expert cache: 857 of 4,608 experts, or 18.6%.**

So the whole question is one number:

    **can 18.6% residency deliver a high enough hit rate?**

    hit  0%  ->   3.9 tok/s        hit 90%  ->  38.8 tok/s
    hit 50%  ->   7.8 tok/s        hit 95%  ->  77.6 tok/s
    hit 80%  ->  19.4 tok/s        hit 98%  -> 193.9 tok/s

## Why static frequency is the wrong policy, and what this measures instead

Marginal expert frequency on the 20B came out nearly uniform -- top-16 of 32 covered only
~61%. If residency were chosen by global frequency, 18.6% capacity would serve well under
half the routings and the answer would be no.

But a cache is not a static selection. It exploits **temporal locality**: consecutive tokens
tend to reuse experts, and routing concentrates sharply with depth (measured: layer 0 spreads
across 26 experts, layer 20 across 14, with top-8 covering 85%). LRU over a real routing
sequence can therefore beat frequency-based residency by a wide margin.

This module replays **captured routing sequences** (`tools/bench/moe_sequence.py`) through several
residency policies and reports the hit rate each achieves. It is a simulation over real
routing decisions, not a model of one -- the sequences came out of the actual router.

## Policies compared

| policy | rule | why it is here |
|---|---|---|
| `oracle` | keep the experts this sequence will use most | the ceiling; unimplementable, bounds the rest |
| `lru` | evict least recently used | the standard baseline |
| `lfu` | evict least frequently used | better when usage is stable |
| `static_top` | preload globally hottest, never evict | what frequency-based pruning would give |
| `layer_aware` | budget per layer by that layer's concentration | **ours** -- deep layers are narrow, early ones wide |

`layer_aware` is the first place fabric-specific policy enters: a uniform per-layer budget
wastes capacity on deep layers that need little and starves early layers that need much.
"""
from __future__ import annotations

import collections
import json
from dataclasses import dataclass, field
from pathlib import Path

ROOT = next(_p for _p in Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())


@dataclass
class CacheResult:
    policy: str
    capacity: int
    hits: int = 0
    misses: int = 0
    bytes_moved: int = 0

    @property
    def hit_rate(self) -> float:
        t = self.hits + self.misses
        return self.hits / t if t else 0.0

    def as_dict(self) -> dict:
        return {"policy": self.policy, "capacity": self.capacity,
                "hits": self.hits, "misses": self.misses,
                "hit_rate": round(self.hit_rate, 4)}


def _key(layer: int, expert: int) -> tuple[int, int]:
    """An expert is identified by (layer, index). The same index in two layers is two
    different tensors -- conflating them would report a hit that cannot happen."""
    return (layer, expert)


def simulate(seq: list[dict], capacity: int, policy: str,
             n_experts: int = 32, n_layers: int = 24) -> CacheResult:
    """Replay one routing sequence through a residency policy of `capacity` experts."""
    r = CacheResult(policy=policy, capacity=capacity)

    if policy == "oracle":
        # Keep whatever this very sequence uses most. Unimplementable in production -- it
        # needs the future -- and that is the point: it bounds every real policy.
        freq = collections.Counter(_key(row["layer"], e)
                                   for row in seq for e in row["experts"])
        resident = {k for k, _ in freq.most_common(capacity)}
        for row in seq:
            for e in row["experts"]:
                if _key(row["layer"], e) in resident:
                    r.hits += 1
                else:
                    r.misses += 1
        return r

    if policy == "static_top":
        # Global frequency, chosen ONCE and never revised: what expert pruning would leave.
        freq = collections.Counter(_key(row["layer"], e)
                                   for row in seq[:len(seq) // 4] for e in row["experts"])
        resident = {k for k, _ in freq.most_common(capacity)}
        for row in seq[len(seq) // 4:]:
            for e in row["experts"]:
                if _key(row["layer"], e) in resident:
                    r.hits += 1
                else:
                    r.misses += 1
        return r

    if policy == "layer_aware":
        # OURS. Give each layer a share of capacity proportional to how many distinct experts
        # it actually uses, then run LRU inside each layer's own budget. A flat per-layer
        # split wastes capacity on deep layers (14 experts used) and starves early ones (26).
        used = collections.defaultdict(set)
        for row in seq:
            used[row["layer"]].update(row["experts"])
        total_distinct = sum(len(v) for v in used.values()) or 1
        budget = {l: max(1, round(capacity * len(v) / total_distinct))
                  for l, v in used.items()}
        per_layer: dict[int, collections.OrderedDict] = collections.defaultdict(
            collections.OrderedDict)
        for row in seq:
            l = row["layer"]
            cache = per_layer[l]
            cap = budget.get(l, 1)
            for e in row["experts"]:
                if e in cache:
                    cache.move_to_end(e); r.hits += 1
                else:
                    r.misses += 1
                    cache[e] = True
                    if len(cache) > cap:
                        cache.popitem(last=False)
        return r

    # lru / lfu over one global cache
    cache: collections.OrderedDict = collections.OrderedDict()
    freq: collections.Counter = collections.Counter()
    for row in seq:
        for e in row["experts"]:
            k = _key(row["layer"], e)
            freq[k] += 1
            if k in cache:
                cache.move_to_end(k); r.hits += 1
                continue
            r.misses += 1
            cache[k] = True
            if len(cache) > capacity:
                if policy == "lfu":
                    victim = min(cache, key=lambda x: freq[x])
                    cache.pop(victim)
                else:
                    cache.popitem(last=False)
    return r


def load_sequences(path: Path) -> dict[str, list[dict]]:
    """Flatten the capture into one ordered routing list per domain."""
    d = json.loads(path.read_text())
    out: dict[str, list[dict]] = {}
    for dom, seqs in d["domains"].items():
        rows: list[dict] = []
        for s in seqs:
            rows.extend(s["rows"])
        out[dom] = rows
    return out
