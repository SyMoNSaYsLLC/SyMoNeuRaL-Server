"""A service that reports a real reading, or says it cannot.

The module form: no class, no decorator, just a module-level `apply`. This is what the loader's
`use: apps.studio.plugins.exp.plugins.gpu` resolves to.

It is here because every other example in this directory is synthetic, and a plugin runtime
whose examples all invent their data teaches the wrong habit. This one shells out to
`nvidia-smi` and to `scripts/gpu-governor.sh status`, and when either is absent it returns
`available: False` rather than a plausible number. CLAUDE.md's rule -- no decorative readings,
where there is no measurement show nothing -- applies inside a plugin exactly as it does on a
page.

It takes no GPU lease. Reading VRAM is not using the card, and a plugin that acquires the mutex
for the lifetime of a mount is the exact failure that file warns about.

`vram()` reports every card as a row in `gpus`, and a field `nvidia-smi` could not read comes
back as `None` rather than a zero. A box with two cards is a box with two rows; collapsing it to
the first would put one card's VRAM on the page as though it were the whole machine's. This box
has one card, so that path is exercised by the tests in `test_exp.py` and not by the hardware.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

name = "gpu"
schema = {"timeout": (float, 3.0)}

_ROOT = pathlib.Path(__file__).resolve().parents[4]      # .../Symoneural


def _int_or_none(text: str) -> int | None:
    """`[N/A]` is nvidia-smi saying it could not read that field.

    It happens on a card in a bad state and on one whose driver does not report the field. It is
    not a zero, and it is not a reason to raise out of a method whose whole contract is to report
    what it has: the reading is absent, so `None` goes on the wire and the page shows no figure
    rather than a plausible one.
    """
    try:
        return int(text)
    except ValueError:
        return None


class GPU:
    def __init__(self, timeout: float) -> None:
        self.timeout = timeout

    def vram(self) -> dict:
        smi = shutil.which("nvidia-smi")
        if smi is None:
            return {"available": False, "reason": "nvidia-smi not on PATH"}
        try:
            out = subprocess.run(
                [smi, "--query-gpu=index,memory.used,memory.total,name",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=self.timeout, check=True).stdout
        except (subprocess.SubprocessError, OSError) as exc:
            return {"available": False, "reason": str(exc)}
        # One row per card, and every card is reported. `name` is queried last and the split is
        # bounded at three commas, because a product name can contain one -- "Tesla V100-SXM2,
        # 16GB" is real, and an unbounded split turned it into an unpacking error. Empty output
        # used to raise `IndexError` off `splitlines()[0]`; it now falls through to the
        # not-parseable branch below, which is what the module docstring promises.
        cards = []
        for line in out.strip().splitlines():
            parts = [part.strip() for part in line.split(",", 3)]
            if len(parts) != 4:
                continue
            index, used, total, model = parts
            cards.append({"index": _int_or_none(index), "used_mib": _int_or_none(used),
                          "total_mib": _int_or_none(total), "model": model})
        if not cards:
            return {"available": False,
                    "reason": f"nvidia-smi returned nothing parseable: {out.strip()!r}"}
        return {"available": True, "count": len(cards), "gpus": cards, "source": "measured"}

    def lease(self) -> dict:
        governor = _ROOT / "scripts" / "gpu-governor.sh"
        if not governor.exists():
            return {"available": False, "reason": f"no governor at {governor}"}
        try:
            out = subprocess.run([str(governor), "status"], capture_output=True, text=True,
                                 timeout=self.timeout)
        except (subprocess.SubprocessError, OSError) as exc:
            return {"available": False, "reason": str(exc)}
        return {"available": True, "text": out.stdout.strip(), "rc": out.returncode}


def apply(ctx, config):
    ctx.provide("gpu", GPU(config["timeout"]))
