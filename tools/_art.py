"""Shared markup for a render lifted out of site/art-*.png.

Three generators place these now -- the masthead, the rack, and the constellation on
/build.html -- and each was building the same anchor by hand with its own copy of the
prompt/seed/seconds lookup. One of those copies had already drifted.

Every render is a link to its own full-size file. That is not decoration: each PNG carries
a watermark strip naming the model, the quantisation, the resolution, the step count, the
seed and the wall-clock it took on this card. The click has to be obvious and it has to
work without JavaScript; ui.js upgrades it to an overlay, and with scripting off the link
still opens the PNG.

The strip alone was not enough. At the 268px a gutter render is shown at, a 12px strip is
four pixels tall -- the claim was least readable exactly where it was doing the most work.
Two things changed: the strip is now two rows of 20px (`tools/build_gallery.py`), and
`provenance()` prints the same facts as real HTML text beneath the image, which stays
crisp at every width and costs no image area. The burned-in strip is the copy that travels
with the file when someone downloads it; the text is the copy a visitor can read in place.

`dims()` reads the PNG rather than hardcoding its height. The height was written out as
`802` in two generators, and the watermark change made both wrong -- a stale height
attribute reserves the wrong aspect ratio and the page jumps as the images load.

`model_name()` lives here for the same reason the rest of this module does: the sidecar's
`model` string is printed in two places -- burned into the PNG bar by
`tools/build_gallery.py` and printed as HTML by `provenance()` below -- and a second copy
of the mapping is exactly the drift this file exists to prevent.
"""
from __future__ import annotations

import json
import pathlib

SITE = pathlib.Path(__file__).resolve().parent.parent / "site"

# Visible surfaces carry SyMoNeuRaL names only. The upstream attribution is consolidated on
# /credits.html, which is what actually satisfies Apache-2.0 §4 -- the notice has to be
# present in what we distribute, not repeated on every surface.
#
# This is a *prefix* map, not an equality test, and deliberately so. The sidecars on disk
# were written by an older API and still read "FLUX.1-schnell q4_k"; the API now writes
# "SymonImage F1 q4_k". Matching the prefix renames the old ones and passes the new ones
# through untouched, so both render identically without rewriting 18 JSON files.
#
# The quantisation suffix is never dropped. `q4_k` is not decoration: Apache-2.0 §4(b)
# requires stating that we modified the files, and quantising is that modification.
UPSTREAM = {"FLUX.1-schnell": "SymonImage F1"}


def model_name(raw: str) -> str:
    """The sidecar's model string, rendered under our own name."""
    for old, new in UPSTREAM.items():
        if raw.startswith(old):
            return new + raw[len(old):]
    return raw


def _sidecar(slug: str) -> dict:
    f = SITE / f"art-{slug}.json"
    return json.loads(f.read_text()) if f.is_file() else {}


def meta(slug: str) -> tuple[str, str, str]:
    """(prompt, seed, seconds) for a render, or empty strings if it has no sidecar."""
    d = _sidecar(slug)
    return d.get("prompt", ""), str(d.get("seed", "")), str(d.get("seconds", ""))


def dims(slug: str) -> tuple[int, int]:
    """The PNG's real (width, height), so the reserved box always matches the file.

    Read from the file rather than assumed: the watermark bar is part of the image, so
    changing it changes the height, and a hardcoded one silently mis-reserves the space.
    Falls back to a square if the render is missing, which is the shape without a bar.
    """
    f = SITE / f"art-{slug}.png"
    if not f.is_file():
        size = _sidecar(slug).get("size", 768)
        return size, size
    with f.open("rb") as fh:                       # PNG IHDR: width/height at bytes 16..24
        head = fh.read(24)
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def provenance(slug: str) -> str:
    """The watermark's own text, as readable HTML. Same facts, same order, same source."""
    d = _sidecar(slug)
    if not d:
        return ""
    return (f'{model_name(d.get("model", ""))} &middot; {d["size"]}&times;{d["size"]} &middot; '
            f'{d["steps"]} steps &middot; seed {d["seed"]} &middot; '
            f'{d["seconds"]}s on an RTX&nbsp;5070&nbsp;Ti')


def attrs(slug: str) -> str:
    """The href and data-* an <a class="art"> needs for the lightbox."""
    prompt, seed, secs = meta(slug)
    esc = prompt.replace('"', "&quot;")
    return (f'href="/art-{slug}.png" title="{esc}" data-prompt="{esc}" '
            f'data-seed="{seed}" data-secs="{secs}" '
            f'aria-label="Open the full render, watermark and all: {esc}"')


def gutter(slug: str, alt: str, question: str, rot: float = 0.0) -> str:
    """A render sized for a page gutter, with its provenance and the question it answers."""
    w, h = dims(slug)
    return f"""<a class="gart" {attrs(slug)} style="--rot:{rot}deg">
      <span class="gwrap">
        <img src="/art-{slug}.png" alt="{alt}, rendered by SyMoNeuRaL Image"
             loading="lazy" width="{w}" height="{h}">
        <span class="gzoom">Click to read the watermark</span>
      </span>
      <span class="gq">{question}</span>
      <span class="gprov">{provenance(slug)}</span>
    </a>"""
