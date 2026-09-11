"""Background removal for a photograph. **Runs inside `backend/sigils/.venv`, never
in the serving interpreter.**

    <root>/backend/sigils/.venv/bin/python cutout_worker.py <in.png> <out.png>
    -> {"ok": true, "seconds": 0.83, "model": "u2net", "transparent_fraction": 0.71}

This file is the far side of a subprocess boundary, and the boundary is the point. `rembg`
pulls in onnxruntime, numba, scikit-image and twenty-odd more packages; the serving
interpreter is a Debian install pinned to exactly the four things the API needs, and
`.claude/settings.local.json` denies `pip install` into it precisely so nothing grows there
by accident. `backend/asicminer/probe.py` established this shape -- venv on one side,
JSON on stdout, the API exec'ing it -- and this is the same pattern for the same reason.

## Why an ML matte exists here at all, when the chroma key already worked

They solve different problems and the difference was measured on this box, 2026-08-17.

The chroma key is excellent on a **generated** sticker, because the surface chooses the
background: the engine is asked for a flat field and the key removes exactly that. It is
unreliable on a **photograph**, because nobody chose the background. Measured: a photograph
of an orange tabby against a light grey studio backdrop, keyed on its border colour,
returned 88.75% transparent and `degenerate: false` -- and had holes punched through the
cat's white chest fur, its ear and a front leg, because light fur and a light backdrop are
the same colour to a distance threshold. The numbers all said success. The sticker was
ruined.

`docs/specs/sigils-spec.md` §3.6 anticipated exactly this and made the call in advance:
ship the colour key, keep rembg specified as the fallback, and choose between them **by
measurement rather than by taste**. This is that measurement arriving, so this is that
fallback.

## The licence is a gate, not a footnote

`u2net` is Apache-2.0 and is what this uses. **`bria-rmbg-2.0` is CC BY-NC 4.0 and must
never be selected here** -- it is the best-known model in rembg's list and it is
non-commercial, which disqualifies it for a company's product. The allowed set is pinned in
`ALLOWED` below rather than left to whatever string a caller passes.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

#: **The verified subset, not the permissive-looking one.** A model absent from this dict
#: cannot be selected, so a typo fails loudly instead of quietly running weights whose terms
#: nobody read. Every entry here was checked against upstream on 2026-08-17 and each is
#: recorded in `LICENSES.md` §2.
#:
#: Both are from `xuebinqin/U-2-Net`, whose repository `LICENSE` is Apache-2.0 (fetched and
#: read, not assumed) -- `u2netp` is the 4.4 MB variant of the same architecture from the
#: same repo and the same file.
ALLOWED = {
    "u2net": "Apache-2.0",
    "u2netp": "Apache-2.0",
}

#: Kept as a comment rather than deleted, because the next person will look at rembg's model
#: list and wonder why these are missing. They were checked and they did not pass:
#:
#:   bria-rmbg-2.0       **CC BY-NC 4.0.** Non-commercial, and the best-known model rembg
#:                       offers. Disqualified outright for a company's product.
#:   isnet-general-use   `xuebinqin/DIS` has **no LICENSE file** (404), and its README scopes
#:                       Apache-2.0 to "our code and evaluation metric" while pointing the
#:                       DIS5K *dataset* -- which is what these weights are trained on -- at a
#:                       separate terms-of-use PDF. Code terms are not weight terms.
#:   silueta             A third-party derivative (Kikedao/silueta.me) of U-2-Net with no
#:                       licensed source repository this box could locate.
#:
#: None of the three is asserted to be non-permissive. Two are simply **unverified**, and an
#: unverified claim inside a licence gate is worse than an absent one.


def main() -> int:
    if len(sys.argv) < 3:
        print(json.dumps({"ok": False, "error": "usage: cutout_worker.py <in.png> <out.png>"}))
        return 2
    src, dest = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    model = sys.argv[3] if len(sys.argv) > 3 else "u2net"
    if model not in ALLOWED:
        print(json.dumps({"ok": False,
                          "error": f"{model!r} is not in the permissively licensed set "
                                   f"{sorted(ALLOWED)}"}))
        return 2

    started = time.monotonic()
    try:
        from rembg import new_session, remove
        from PIL import Image
    except Exception as exc:                       # noqa: BLE001 -- reported, not raised
        print(json.dumps({"ok": False, "error": f"the cutout venv is incomplete: {exc}"}))
        return 1

    try:
        session = new_session(model)
        image = Image.open(src).convert("RGB")
        # alpha_matting refines the edge and costs seconds on a CPU. Off: a sticker edge is
        # supposed to be hard, and the measured cost is not worth a softness we then have to
        # explain. If it is ever wanted it belongs behind a flag with its own measurement.
        out = remove(image, session=session, post_process_mask=True)
        out = out.convert("RGBA")
        out.save(dest, "PNG")
        alpha = out.getchannel("A")
        n = out.width * out.height
        histogram = alpha.histogram()
        opaque = histogram[255]
        transparent = histogram[0]
    except Exception as exc:                       # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 1

    print(json.dumps({
        "ok": True,
        "seconds": round(time.monotonic() - started, 3),
        "model": model,
        "licence": ALLOWED[model],
        "width": out.width,
        "height": out.height,
        "transparent_fraction": round(transparent / n, 4),
        "opaque_fraction": round(opaque / n, 4),
        # Same meaning as the chroma matte's flag, computed the same way, so a client cannot
        # tell which matte ran by the shape of the answer -- only by the `matte` field that
        # says so outright.
        "degenerate": not (0.02 <= opaque / n <= 0.98),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
