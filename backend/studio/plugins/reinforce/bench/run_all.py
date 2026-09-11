#!/usr/bin/env python3
"""Run the whole benchmark suite.

    python -m bench.run_all [--quick] [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bench.suite import run_all  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quick", action="store_true",
                    help="smaller working sets; faster, less DRAM-representative")
    ap.add_argument("--json", type=Path, help="write results as JSON")
    args = ap.parse_args()

    results = run_all(quick=args.quick)
    if args.quick:
        print("\n  NOTE: --quick uses smaller working sets. Regime bands are "
              "calibrated for\n        full-size runs, where per-launch "
              "overhead is a smaller fraction of\n        each measurement. "
              "Out-of-band results below are advisory, not failures.")

    if args.json:
        args.json.write_text(json.dumps(
            [{"name": r.name, "metric": r.metric, "value": r.value,
              "unit": r.unit, "reference": r.reference, "ratio": r.ratio,
              "regime": r.regime, "healthy": r.healthy, "band": list(r.band),
              "note": r.note} for r in results], indent=2))
        print(f"\nwrote {args.json}")

    # Judge each result against the band for ITS OWN regime. A flat threshold
    # flags L2-resident and grid-capped benchmarks as regressions when they are
    # behaving exactly as designed.
    judged = [r for r in results if r.reference and r.regime not in ("info", "waived")]
    unhealthy = [r for r in judged if not r.healthy]

    print(f"\n{len(judged) - len(unhealthy)}/{len(judged)} benchmarks within "
          f"their regime band; {len(results) - len(judged)} informational.")
    if unhealthy:
        label = "Outside expected band (advisory -- quick mode)" if args.quick \
                else "Outside expected band"
        print(f"\n{label}:")
        for r in unhealthy:
            lo, hi = r.band
            print(f"  - {r.name}: {r.value:.2f} vs {r.reference:.2f} {r.unit} "
                  f"= {r.ratio:.2f}x, expected {lo:.2f}-{hi:.2f}x for "
                  f"regime '{r.regime}'")
    print()
    # Quick mode never fails the build; only a full-size run gates.
    return 1 if (unhealthy and not args.quick) else 0


if __name__ == "__main__":
    raise SystemExit(main())
