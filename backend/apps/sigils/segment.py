"""The serving side of the photograph matte. Execs `cutout_worker.py` in its own venv.

Nothing in this module imports rembg, onnxruntime or numpy. It builds a command line, runs
it, and reads one JSON object off stdout -- exactly the boundary
`backend/apps/asicminer/probe.py` established, and for the same reason: the serving
interpreter is pinned and must not grow an ML runtime.

## Which matte runs where, and why it is not one answer

    text  ->  chroma key   the surface CHOSE the background, so keying it is exact and
                           costs ~40 ms. Segmentation here would be slower and no better.
    photo ->  u2net        NOBODY chose the background. A distance threshold cannot tell a
                           white chest from a light grey backdrop, and measured on this box
                           it did not: the keyed cat came back 88.75% transparent with
                           `degenerate: false` and holes through its fur.

Stated as one line: **key what we painted, segment what we did not.**

Measured on this box 2026-08-17, i9-10900KF, wall-clock for the whole subprocess including
interpreter start and the 168 MB model load -- which is what a request actually waits for,
not an inference time with the setup deducted:

    steady state   1.25 s, 1.28 s, 1.33 s   over HTTP, three consecutive requests
    direct         1.286 s, 1.302 s, 1.335 s   the worker called straight from a shell
    FIRST run      **32.9 s**, measured once, immediately after an API restart

**The cold figure is real and is recorded rather than dropped as an outlier.** Every
request spawns a fresh interpreter and re-reads the weights, so the steady-state number
depends entirely on the file being in the OS page cache; the first read after a reboot is
not, and it costs what it costs. A page that quoted 1.3 s without this would be quoting a
warm-cache figure as if it were the guarantee.

Worth doing if it ever matters, and deliberately not done here: warm the session at API
startup, or keep one worker resident. Both trade memory and boot time for a one-off that
happens once per reboot, and neither is worth changing the serving path's boot for until
somebody actually complains about it.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
assert (ROOT / "scripts" / "gpu-governor.sh").is_file(), (
    f"{ROOT / 'scripts' / 'gpu-governor.sh'} is not a file. Either that script is "
    f"missing, or ROOT is wrong (computed {ROOT}). Same wording as api.py:58 and the "
    "same reason: commissioning moved the script aside and the old message blamed the "
    "root, which was the one thing that was correct."
)

VENV_PY = ROOT / "backend" / "apps" / "sigils" / ".venv" / "bin" / "python"
WORKER = pathlib.Path(__file__).resolve().parent / "cutout_worker.py"
#: Where `scripts/fetch-cutout.sh` puts the weights. Passed as `U2NET_HOME` so rembg loads
#: from disk instead of reaching for the network mid-request, which is its default and is
#: the wrong behaviour inside a serving path.
WEIGHTS = ROOT / "backend" / "models" / "rembg"
DEFAULT_MODEL = "u2net"

#: Generous against a measured ~1.3 s. A cold page cache after a reboot is the realistic
#: worst case, not a hung process.
TIMEOUT_S = 120


class Unavailable(RuntimeError):
    """The venv or the weights are not installed. The caller falls back to the chroma key."""


def model_file(name: str = DEFAULT_MODEL) -> pathlib.Path:
    return WEIGHTS / f"{name}.onnx"


def installed(name: str = DEFAULT_MODEL) -> bool:
    """Binary and weights genuinely on disk. Never reports available on an import."""
    return VENV_PY.is_file() and WORKER.is_file() and model_file(name).is_file()


async def cut_file(src: pathlib.Path, dest: pathlib.Path,
                   model: str = DEFAULT_MODEL) -> dict:
    """Segment `src` into an RGBA PNG at `dest`. Returns the worker's stats.

    Raises `Unavailable` when it is not installed, so the caller can fall through to the
    chroma key rather than failing the request: a box without the venv still makes stickers,
    just with the matte that does not need it.
    """
    if not installed(model):
        raise Unavailable("the cutout venv or its weights are not installed on this box")
    env = {**os.environ, "U2NET_HOME": str(WEIGHTS),
           # onnxruntime otherwise takes every core it can see. This runs beside a render
           # and a live status socket, so it is bounded rather than left to grab the box.
           "OMP_NUM_THREADS": str(min(8, os.cpu_count() or 4))}
    proc = await asyncio.create_subprocess_exec(
        str(VENV_PY), str(WORKER), str(src), str(dest), model,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT_S)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        proc.kill()
        await proc.wait()
        raise
    try:
        # The worker prints exactly one JSON object. Anything else -- a warning from a
        # dependency, a traceback -- is read as failure rather than parsed hopefully.
        doc = json.loads((out or b"").decode("utf-8", "replace").strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise Unavailable(
            f"the cutout worker returned nothing usable: "
            f"{(err or out or b'').decode('utf-8', 'replace')[-300:]}") from None
    if not doc.get("ok"):
        raise Unavailable(str(doc.get("error", "the cutout worker failed")))
    return doc


def state() -> dict:
    return {
        "installed": installed(),
        "model": DEFAULT_MODEL if model_file().is_file() else None,
        # Two licences, not one, because the engine and the weights are separate artefacts
        # with separate terms and a single "Apache-2.0" here would be quietly wrong about
        # rembg. Both texts are fetched to `backend/models/licenses/`; see LICENSES.md §2-3.
        "licence": {"model": "Apache-2.0 (U^2-Net, upstream repo)",
                    "engine": "MIT (rembg, onnxruntime)"},
        "engine": "rembg + onnxruntime, CPU, in its own venv -- never takes the GPU lock",
        # Both numbers, because one of them without the other is misleading. The steady
        # figure holds once the weights are in the page cache; the first call after a
        # reboot re-reads 168 MB and was measured once at 32.9 s.
        "seconds_measured": "1.25-1.33 s steady state, i9-10900KF, 2026-08-17",
        "seconds_first_call": "32.9 s once, cold page cache after an API restart",
    }
