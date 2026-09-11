"""Text to speech: the half that is NOT built, written so it reports that rather than faking it.

**Nothing on this box speaks.** Checked, not assumed: no `piper`, no `espeak-ng`, no `espeak`,
no `festival`, no `flite`, and the system interpreter has no `onnxruntime`, `torchaudio` or
`soundfile`. `arecord` is present; nothing that synthesises is.

**Piper was deliberately not installed.** `.claude/CLAUDE.md` reserves the serving interpreter
(`pip install` into it is denied in `.claude/settings.local.json` for a reason) and gives
anything that conflicts its own venv. Downloading a package *and* a voice model is a change to
the machine, and that is Garrett's to authorise rather than an agent's to slip into an
unattended queue. So this module does the one honest thing available to it: it looks for an
engine every time it is asked, and says exactly what is missing when there is none.

## Why this is not a stub

A `speak` route that returned a placeholder wav, or silence, or a 200 with an empty body,
would be the decorative-status-light bug in audio form -- indistinguishable from a working
one until somebody put on headphones. It returns 503 and names the command that fixes it.

## The command that closes it, and what to record when it is run

    cd backend/voice && python3 -m venv .venv && .venv/bin/pip install piper-tts
    # download a voice, then MEASURE, because the page may only print measured numbers:
    #   time .venv/bin/piper -m <voice>.onnx -f out.wav <<< "a one-sentence answer"
    # report: wall clock, peak RSS, and audio seconds produced per second of compute.

`.venv` lives beside this file because that is where `backend/asicminer/.venv` lives and
one convention beats two. (`backend/voice/docs/voice-spec.md` §3 first suggested `voice/.venv` at the
repo root; this is the corrected path and the spec now says so.)

Two things to settle in the same sitting, both cheap then and expensive later:

- **The voice model's licence goes in `models/licenses/`** like every other weight
  here. Piper's voices are not uniformly licensed -- check the specific voice; it does not
  inherit Piper's own terms.
- **`onnxruntime` is already in play on this box** -- `models/licenses/onnxruntime.
  LICENSE.txt` and `rembg`/`u2net` were recorded for the Stickers work (HANDOVER §5 item 13).
  Coordinate rather than adding a second copy of the same dependency under a different owner.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The venv this surface would use, by the same convention as apps/asicminer/.venv.
VENV_PIPER = HERE / ".venv" / "bin" / "piper"

# Engines worth looking for, most preferred first. Each is a real check against the box, so
# installing any one of them changes what `/api/voice/state` reports without a code change.
_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("piper", "the venv beside this module"),
    ("espeak-ng", "PATH"),
    ("espeak", "PATH"),
)

INSTALL_HINT = ("cd backend/voice && python3 -m venv .venv && "
                ".venv/bin/pip install piper-tts, then a voice model and its licence")


def engine() -> tuple[str, str] | None:
    """(name, path) of something that can speak, or None. Probed every call on purpose --
    a surface that cached "absent" at import time would still say no after an install."""
    if VENV_PIPER.is_file() and os.access(VENV_PIPER, os.X_OK):
        return "piper", str(VENV_PIPER)
    for name, _where in _CANDIDATES:
        found = shutil.which(name)
        if found:
            return name, found
    return None


def installed() -> bool:
    return engine() is not None


def state() -> dict:
    """What `/api/voice/state` publishes about this half. `measured` is absent from every
    field because there is nothing to measure yet, and that is the point."""
    found = engine()
    if found is None:
        return {
            "available": False,
            "engine": None,
            "problem": "no speech synthesiser is installed on this box",
            "install": INSTALL_HINT,
            # Said out loud so a reader does not go looking for a latency figure that a page
            # might have printed from a guess.
            "latency": "unmeasured — nothing that speaks is installed",
        }
    # Reached only after somebody installs an engine. It deliberately does NOT claim the
    # route works: whoever installs it writes `speak()` below and measures it first.
    return {
        "available": False,
        "engine": found[0],
        "problem": f"{found[0]} is installed at {found[1]} but no synthesis path is written "
                   f"yet — see this module's docstring",
        "install": None,
        "latency": "unmeasured",
    }
