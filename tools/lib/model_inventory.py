#!/usr/bin/env python3
"""Inventory every model-like asset on this box, and say what is not accounted for.

## Why this is a scan and not a list

`.claude/CLAUDE.md`'s standing rule is scan-never-hardcode, derive-never-look-up, every figure
labelled. A hand-written model list is a claim that rots the first time somebody drops a
`.safetensors` into `backend/models/`, and that is exactly what happened here: `PROVENANCE.json`
records 11 weights and there are 28 on disk. The 17 it does not know about are 78 GiB, and no
document noticed because no document was measuring.

So this reads three sources and cross-checks them:

    disk            -- what is actually there, with real byte counts
    PROVENANCE.json -- what we can say where it came from
    backend/server.py  -- which of them the running server actually loads

and the interesting output is the disagreement, not the agreement.

## Why it parses `api.py` instead of importing it

`api.py` builds a FastAPI app, reads the environment, and resolves governor paths at module
scope. Importing it to learn four filenames would run all of that, and in a tool that is meant
to be safe to run on a broken box. So the active set is read out of the source text, and
`backend/test_model_staging.py` asserts the patterns still match -- a structural assertion,
because a regex that silently stops matching would report "no active model" rather than fail.

Stdlib only, and no network. This tool downloads nothing, activates nothing, deletes nothing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = next(_p for _p in Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
MODELS = ROOT / "models"
MANIFEST = MODELS / "PROVENANCE.json"
API = ROOT / "backend" / "core" / "config.py"

# Every place a model path is chosen. Not just api.py: `voice/asr.py` picks the whisper model
# itself, and a first draft of this tool read only api.py and therefore reported the listen
# model as an idle component while the voice surface was loading it. One loader site missed is
# one active model misclassified, so the list is explicit and `test_model_staging.py` asserts each
# entry still parses to something.
LOADER_SITES = (
    ("backend/core/config.py", "api"),
    ("backend/voice/lib/asr.py", "voice"),
)
TRAINING = ROOT / "training"

# Extensions that make a file a weight rather than a note about one. `.bin` is here for
# whisper.cpp's format and `.onnx` for rembg's; neither is a torch pickle and the distinction
# does not matter to an inventory.
WEIGHT_EXT = {".safetensors", ".gguf", ".bin", ".onnx", ".pt", ".pth"}

# The HF cache is a cache: its layout IS its index (see PROVENANCE.json's note on why those
# directory names are not renamed), and counting blobs there would double-count models that
# are already listed by their house name.
SKIP_PARTS = ("/hf/", "/.cache/")

CLASSES = ("active-default", "candidate", "rollback", "component", "adapter",
           "runtime-dependency", "retired", "unknown-blocked")


def _skip(path: Path) -> bool:
    s = str(path)
    return any(part in s for part in SKIP_PARTS)


def active_from_source() -> dict[str, str]:
    """The paths the running surfaces actually load, read from source rather than imported.

    Returns `{relative-path: role}`. An empty result is a failure, not a finding -- see the
    module docstring on why this is asserted by a test rather than trusted.
    """
    found: dict[str, str] = {}

    api = ROOT / "backend" / "core" / "config.py"
    if api.is_file():
        text = api.read_text(encoding="utf-8", errors="replace")
        # CHAT_MODEL = MODELS / "llm" / "symon-1.0-7b-q4_k_m.gguf"
        for var, role in (("CHAT_MODEL", "chat"), ("DRAFT_MODEL", "chat-draft")):
            m = re.search(rf'^{var}\s*=\s*MODELS\s*/\s*"([^"]+)"\s*/\s*"([^"]+)"',
                          text, re.M)
            if m:
                found[f"{m.group(1)}/{m.group(2)}"] = role
        # "unet": MODELS / "image" / "symoneural-image-unet-q4_k.gguf",
        for m in re.finditer(r'"(\w+)":\s*MODELS\s*/\s*"([^"]+)"\s*/\s*"([^"]+)"', text):
            found[f"{m.group(2)}/{m.group(3)}"] = f"image-{m.group(1)}"

    asr = ROOT / "backend" / "voice" / "lib" / "asr.py"
    if asr.is_file():
        text = asr.read_text(encoding="utf-8", errors="replace")
        # ... / "backend" / "models" / "whisper" / "symoneural-listen-base-en.bin"
        m = re.search(r'"models"\s*/\s*"([^"]+)"\s*/\s*"([^"]+)"', text)
        if m:
            found[f"{m.group(1)}/{m.group(2)}"] = "asr"

    return found


# Kept as the old name so nothing that already calls it breaks; the behaviour widened.
active_from_api = active_from_source


def manifest_entries() -> dict[str, dict]:
    if not MANIFEST.is_file():
        return {}
    return {w["path"]: w for w in json.loads(MANIFEST.read_text(encoding="utf-8"))["weights"]}


def scan() -> dict:
    """Every weight-like file, joined to the manifest and to the active set."""
    man = manifest_entries()
    active = active_from_source()
    rows = []

    for p in sorted(MODELS.rglob("*")) if MODELS.is_dir() else []:
        if not p.is_file() or p.suffix not in WEIGHT_EXT or _skip(p):
            continue
        rel = str(p.relative_to(MODELS))
        entry = man.get(rel)
        licence_text = None
        if entry:
            licence_text = entry.get("license_text")
        rows.append({
            "path": rel,
            "bytes_on_disk": p.stat().st_size,
            "in_manifest": entry is not None,
            "upstream_repo": (entry or {}).get("upstream_repo"),
            "upstream_file": (entry or {}).get("upstream_file"),
            "license": (entry or {}).get("license"),
            "license_text": licence_text,
            "license_text_present": bool(licence_text)
                                    and (MODELS / licence_text).is_file(),
            "modified_by_us": (entry or {}).get("modified_by_us"),
            "role": active.get(rel) or (entry or {}).get("role"),
            "active_default": rel in active,
            "classification": _classify(rel, entry, rel in active),
        })

    # Adapters live outside backend/models on purpose -- they are training OUTPUT, and
    # `training/` is the protected tree. Recorded separately, never merged with base weights.
    adapters = []
    for p in sorted(TRAINING.rglob("adapter_model.safetensors")) if TRAINING.is_dir() else []:
        adapters.append({
            "path": str(p.relative_to(ROOT)),
            "bytes_on_disk": p.stat().st_size,
            "classification": "adapter",
            "protected": True,
        })

    return {"weights": rows, "adapters": adapters,
            "manifest_ghosts": sorted(r for r in man if not (MODELS / r).is_file())}


def _classify(rel: str, entry: dict | None, is_active: bool) -> str:
    """One label per asset, and `unknown-blocked` is the honest default.

    An unmanifested weight is not "probably fine" -- `docs/ops/LICENSE-AUDIT.md`'s vocabulary
    says an unrecorded licence is a blocker until provenance exists, because you cannot ship
    what you cannot describe. So no provenance means `unknown-blocked`, whatever the file is.
    """
    if entry is None:
        return "unknown-blocked"
    if is_active:
        return "active-default"
    # An image component named in the manifest but not loaded by api.py is still a component
    # of a bundle; an LLM tier that is not the active one is a rollback candidate.
    if rel.startswith("image/") or rel.startswith("vae/") or rel.startswith("clip"):
        return "component"
    if rel.startswith("llm/"):
        return "rollback"
    return "component"


def render(inv: dict) -> str:
    out: list[str] = []
    w = inv["weights"]
    known = [r for r in w if r["in_manifest"]]
    unknown = [r for r in w if not r["in_manifest"]]
    gib = lambda n: n / 2 ** 30                                        # noqa: E731

    out.append("SyMoNeuRaL ModelOps inventory")
    out.append("=" * 78)
    out.append(f"weight files on disk (excl. hf cache) : {len(w)}")
    out.append(f"  in PROVENANCE.json                  : {len(known):3}  "
               f"{gib(sum(r['bytes_on_disk'] for r in known)):8.2f} GiB")
    out.append(f"  NOT in PROVENANCE.json              : {len(unknown):3}  "
               f"{gib(sum(r['bytes_on_disk'] for r in unknown)):8.2f} GiB")
    out.append(f"manifest entries with no file on disk  : {len(inv['manifest_ghosts'])}")
    out.append(f"adapters (training/, protected)        : {len(inv['adapters'])}")
    out.append("")

    active = [r for r in w if r["active_default"]]
    out.append(f"-- ACTIVE DEFAULTS ({len(active)}) " + "-" * 50)
    for r in active:
        out.append(f"  {r['role']:14} {r['path']:52} {gib(r['bytes_on_disk']):7.2f} GiB")
    out.append("")

    gaps = [r for r in known if not r["license_text_present"]]
    out.append(f"-- MANIFESTED BUT NO LICENCE TEXT ON DISK ({len(gaps)}) " + "-" * 27)
    if not gaps:
        out.append("  none")
    for r in gaps:
        out.append(f"  {r['path']:52} {r['license'] or '?':14} "
                   f"upstream={r['upstream_repo']}")
    out.append("")

    out.append(f"-- UNKNOWN-BLOCKED: no provenance, no licence ({len(unknown)}) " + "-" * 22)
    for r in sorted(unknown, key=lambda x: -x["bytes_on_disk"]):
        out.append(f"  {gib(r['bytes_on_disk']):7.2f} GiB  {r['path']}")
    out.append("")
    out.append("Nothing was downloaded, activated, moved or deleted by this tool.")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true", help="emit the inventory as JSON")
    args = ap.parse_args(argv)
    inv = scan()
    if args.json:
        print(json.dumps(inv, indent=2, sort_keys=True))
    else:
        print(render(inv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
