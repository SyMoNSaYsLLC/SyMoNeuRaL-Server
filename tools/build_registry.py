#!/usr/bin/env python3
"""Pre-compute `run/registry.json` -- the model list `GET /api/studio/models` serves.

## Why this file exists at all

The route could scan the disk itself. `apps/studio/plugins/reinforce/registry.py` already does exactly that
and is stdlib-only precisely so the serving API can import it. But a scan walks the HF cache,
opens every `config.json`, and reads the key/value header out of every GGUF on the box, and
doing that inside a request handler puts a filesystem walk on the live network path. The
architecture rule for this stack is that the live path stays decoupled from the heavy Python:
the control plane's scans and database updates are background work, and the request handler
reads a file that background work already produced.

So the split is:

    this script (out-of-band, by hand or by timer)  ->  run/registry.json  ->  the route

The route never imports `registry`, never forks a process, never touches the network, and
never takes the GPU lock. It opens one file, re-validates it, and returns it.

## Every figure still carries its label

`registry.py`'s two rules -- *scan, never hardcode* and *derive, never look up* -- are not
weakened by writing the result to a file, because this script does the scanning. What it must
not do is invent the one figure the scan cannot produce.

**Latency.** Nothing on this box stores a per-model latency or a per-model token rate. The
`151 tok/s` figure that appears on the site is a string literal in `tools/build_console.py`;
the only timing-adjacent measurement persisted anywhere is `run/reinforce/measured-peaks.json`,
which is VRAM, not time. Copying the console's constant into a per-model row would relabel a
build-time literal as a reading taken of that model -- a projection wearing a measurement's
label, which is the specific dishonesty `.claude/CLAUDE.md` names.

So every row is emitted with `latency_ms: null`, `latency_label: null` and
`latency_measured_at: null`, and `_latency_for()` below is the single documented place where a
real reading gets wired in once something measures one. The field exists so the client's decode
path is stable; the value stays null until it is earned.

## Run it

    python3 tools/build_registry.py            # writes run/registry.json
    python3 tools/build_registry.py --print    # dump to stdout, write nothing

Deliberately NOT in the build list in `.claude/CLAUDE.md`. It writes nothing under `site/`, so
it is independent of the `build_cachebust.py` stamp ordering, and it describes what is on the
machine rather than what is on a page -- rebuilding the site does not change the answer, and
dropping a model into the cache does. Run it after `scripts/fetch-models.sh`, or on a timer.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
# `apps.studio.plugins.reinforce.registry` resolves the same way it does for the serving API, which puts
# `backend/` on the path and imports `apps.studio.plugins.reinforce`. Matching that import shape means this
# script and the API are looking at one module, not two copies with drifting behaviour.
sys.path.insert(0, str(ROOT / "backend"))

from apps.studio.plugins.reinforce import registry  # noqa: E402

OUT = ROOT / "run" / "registry.json"

# Bumped when the shape of a row changes, so a client reading a file written by an older
# revision of this script can tell rather than guess. The route echoes it back untouched.
SCHEMA = 1


def _latency_for(entry: registry.Entry) -> dict:
    """The latency slot. Null today, and honestly so.

    THIS IS THE HOOK. When something on this box actually times a model -- a bench harness
    writing `run/latency.json` keyed by model id, say -- read it here and return

        {"latency_ms": <the reading>, "latency_label": "measured",
         "latency_measured_at": <unix seconds of the run>}

    for the ids it covers, and keep returning the nulls below for every id it does not. Per
    `jobs.measured_peaks()`, a reading replaces the null for *that row only*; extrapolating one
    model's number onto another model's row is the thing the labelling rule forbids.

    Do not fill this from `tools/build_console.py`'s `151 tok/s`. That figure is real, but it
    was measured for one model at one quantisation and it lives in the generator as a literal;
    stamping it onto every row would state something about models it was never measured on.
    """
    return {"latency_ms": None, "latency_label": None, "latency_measured_at": None}


def _capabilities(entry: registry.Entry) -> list[str]:
    """What this model can actually be asked to do here, derived from the scan.

    Derived, never looked up -- same rule as the arithmetic in `registry.py`. Every string
    below is a consequence of something read off disk, so a model nobody anticipated still gets
    an honest list, and the list moves when the file on disk moves.
    """
    caps = []
    if entry.present:
        # A GGUF is what `llama.cpp` serves; an HF snapshot is what `transformers` loads. Both
        # can generate text, and that is the only capability either grants merely by existing.
        caps.append("text-generation")
    if entry.trainable:
        # `trainable` is registry.py's own verdict, and it is false for every GGUF because a
        # GGUF has no torch state dict for peft to attach to. Carrying `entry.reason` through
        # below is what turns "unsupported" into something an operator can act on.
        caps.append("fine-tune:qlora")
    if entry.kind == "gguf":
        caps.append("quantised")
    return caps


def rows() -> list[dict]:
    """One dict per model, in the picker's order (trainable first, then present, then id)."""
    out = []
    for e in registry.catalogue():
        row = {
            "id": e.id,
            "name": e.label,
            "kind": e.kind,                     # "hf" | "gguf"
            "path": e.path,                     # repo-relative -- never absolute, per registry.py
            "present": e.present,
            "capabilities": _capabilities(e),
            # `trainable` plus its reason. The reason is the half that makes a false value
            # useful: "GGUF has no torch state dict, so peft has no modules to attach to" tells
            # an operator to pick the other row instead of filing a bug.
            "trainable": e.trainable,
            "reason": e.reason,
            "bytes_on_disk": e.bytes_on_disk,
            "bytes_on_disk_label": "measured" if e.present else None,
            "quantisation": e.quantisation,
            "quantisation_label": e.quant_label,
            "parameters": (e.params or {}).get("total"),
            "parameters_label": (e.params or {}).get("label"),
        }
        row.update(_latency_for(e))
        out.append(row)
    return out


def build() -> dict:
    # `time.time()` rather than a formatted string: the reader should decide how to render it,
    # and a bare unix integer has no locale or timezone to get wrong in transit.
    import time
    return {
        "schema": SCHEMA,
        "generated_at": int(time.time()),
        "generated_by": "tools/build_registry.py",
        "models": rows(),
        "latency_note": ("latency is null on every row because nothing on this machine has "
                         "measured one yet. The field is present so the shape is stable; a "
                         "number will appear only when it has actually been measured."),
    }


def _write_atomic(path: pathlib.Path, payload: dict) -> None:
    """Same shape as `apps/studio/plugins/reinforce/runner.py:_write_atomic`, and for the same reason.

    The API may be reading this file on a request while this script is rewriting it. Without
    the rename a reader intermittently parses a truncated document; with it, a reader sees
    either the old file or the new one and never a half of either.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--print", dest="dump", action="store_true",
                    help="write nothing; dump the document to stdout")
    args = ap.parse_args()

    doc = build()
    if args.dump:
        print(json.dumps(doc, indent=2))
        return 0

    _write_atomic(OUT, doc)
    present = sum(1 for m in doc["models"] if m["present"])
    trainable = sum(1 for m in doc["models"] if m["trainable"])
    print(f"{OUT.relative_to(ROOT)}: {len(doc['models'])} models "
          f"({present} present, {trainable} trainable), latency null on all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
