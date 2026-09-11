#!/usr/bin/env python3
"""Render the homepage artwork on this machine, then watermark it with how it was made.

The band on the front page argues that a business can own its AI outright. Stock photos
would undercut that on the first scroll, so every image there is produced by the image
surface this site is selling -- same card, same weights, same four steps a visitor gets.

The watermark is not decoration or branding varnish: it prints the model, the size, the
step count and the seed. Anyone can paste that seed into /image.html and get the same
picture back. That is the whole argument of the site applied to its own artwork.

    python3 build_gallery.py              # render anything missing        (GPU)
    python3 build_gallery.py --force      # re-render everything           (GPU)
    python3 build_gallery.py --restamp    # redraw the watermark bar only  (no GPU)

`--restamp` exists because changing the watermark does not require regenerating the art.
The bar sits *below* the render, so the picture is exactly the top meta['size'] rows of
each file and cropping recovers it byte for byte; everything the bar prints is already in
the art-<slug>.json sidecar. Restyling all eighteen is a few seconds of CPU, takes no
governor lease, and cannot alter a single pixel of the artwork.

Writes site/art-<slug>.png and site/art-<slug>.json (the provenance the page prints).
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _art  # noqa: E402

# The generators live in tools/, so the repo root is one level up. This exact
# calculation has been wrong twice in this repo's history -- once when demo/ was
# flattened and once here -- and it fails *silently*, because the wrong parent is
# usually a directory that exists. Assert rather than trust it.
ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
assert (ROOT / "backend" / "server.py").is_file(), f"repo root not found at {ROOT}"
SITE = ROOT / "site"
API = "http://127.0.0.1:8800/api/image"
GEN = "http://127.0.0.1:8800/api/gen/"

# Seeds are pinned so a rebuild reproduces the same page rather than quietly redesigning
# it, and so the seed printed in the watermark stays true.
ART = [
    ("owns", 2517,
     "a lone server rack glowing green in a small dark office at night, warm desk lamp, "
     "clean product photography, deep blacks, emerald accent light"),
    ("cost", 8841,
     "a single graphics card resting on a workbench beside a coffee cup, macro shot, "
     "dark background, green circuit traces catching the light"),
    ("private", 4402,
     "a locked steel door inside a server room, dim corridor, green indicator lights, "
     "cinematic, moody, high contrast"),
    ("fast", 1195,
     "long exposure light trails flowing through a dark data centre aisle, emerald and "
     "teal streaks, abstract, minimal"),
    ("yours", 6730,
     "a hand holding a small labelled hard drive over a dark desk, shallow depth of "
     "field, green rim light, documentary photography"),
    ("build", 3364,
     "an engineer's desk covered in cables, a multimeter and an open server chassis, "
     "top down, dark tones, green accents"),
    ("gpu",      7714, "a single graphics card fan blade close up, macro, dark, teal rim light"),
    ("rack2",    9182, "three server units stacked, front panel LEDs, very dark room, green glow"),
    ("cable",    2296, "a bundle of network cables coiled on a dark surface, top down, minimal"),
    ("chip",     5527, "a silicon die under magnification, iridescent, dark field, abstract"),
    ("desk",     1840, "a laptop closed on a desk beside a small server tower, night, one lamp"),
    ("meter",    6635, "an analogue power meter needle at mid scale, dark instrument panel, amber"),
    ("vault",    3971, "a heavy safe door slightly ajar, dark room, thin green light spilling out"),
    ("map",      8408, "an abstract network graph of glowing nodes and thin lines, dark background"),
    ("box",      4153, "a plain cardboard shipping box on a dark floor, single overhead light"),
    ("token",    7062, "abstract streams of small glowing particles flowing left to right, dark"),
    ("hands",    2735, "two hands shaking over a desk with a server rack behind, warm dim light"),
    ("clock",    9540, "a wall clock in a dark server room, motion blurred second hand, green cast"),
]

# The bar is two rows of 20px mono. It used to be one row of 12px, which measured 704px
# of the 768px canvas -- so it could not be scaled up, only reflowed. And 12px on a render
# shown 268px wide in a page gutter is four pixels tall: the claim was unreadable exactly
# where it was doing the most work. Two rows at 20px reads at gutter size and costs 9% of
# the image; three or four rows read better still and cost 16% and 22%, which is the
# picture paying for its own caption. See `--restamp`: none of this needs the GPU.
FONT_PX = 20
PAD = 16          # above the first row and below the last
LEAD = 28         # baseline to baseline
FOOT = PAD * 2 + LEAD * 2 - (LEAD - FONT_PX)   # 80px, and site/_art.py must agree

MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"


def render(seed: int, prompt: str) -> tuple[bytes, dict]:
    body = json.dumps({"prompt": prompt, "steps": 4, "size": 768, "seed": seed}).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        meta = json.load(r)
    with urllib.request.urlopen(GEN + meta["url"].rsplit("/", 1)[-1], timeout=120) as r:
        return r.read(), meta


def rows(meta: dict) -> tuple[str, str]:
    """The two lines the bar prints, as one place both the PNG and the page can read.

    The model string goes through `_art.model_name()` -- the same map `_art.provenance()`
    uses for the HTML copy beneath the image -- so the burned-in caption and the readable
    one can never disagree about what drew the picture.
    """
    return (f"{_art.model_name(meta.get('model', ''))} · "
            f"{meta['size']}×{meta['size']} · {meta['steps']} steps",
            f"seed {meta['seed']} · {meta['seconds']}s on an RTX 5070 Ti")


def compose(art: Image.Image, meta: dict) -> Image.Image:
    """The render, with a bar printing exactly how it was produced."""
    w, h = art.size
    canvas = Image.new("RGB", (w, h + FOOT), "#0b0d0c")
    canvas.paste(art, (0, 0))
    d = ImageDraw.Draw(canvas)

    try:
        f = ImageFont.truetype(MONO, FONT_PX)
        fb = ImageFont.truetype(BOLD, FONT_PX)
    except OSError:                                    # font package missing
        f = fb = ImageFont.load_default()

    top, tail = rows(meta)
    d.line([(0, h), (w, h)], fill="#1d241f", width=1)
    d.text((13, h + PAD), "SyMoNeuRaL Image", font=fb, fill="#2ee08a")
    indent = 13 + int(d.textlength("SyMoNeuRaL Image", font=fb)) + FONT_PX

    # PIL does not wrap and does not clip: a string wider than the canvas is simply drawn
    # off the right edge and the tail of it is gone, with no error. That is the same data
    # loss the repo-wide ellipsis ban exists to prevent, so fail loudly instead. Renaming
    # the model shortened both rows, but the next rename might not.
    for x, line in ((indent, top), (13, tail)):
        over = x + d.textlength(line, font=f) - (w - 13)
        assert over <= 0, f"watermark row overflows the {w}px canvas by {over:.0f}px: {line!r}"

    d.text((indent, h + PAD), top, font=f, fill="#8d9b93")
    d.text((13, h + PAD + LEAD), tail, font=f, fill="#8d9b93")
    return canvas


def stamp(png: bytes, meta: dict, out: pathlib.Path) -> None:
    """Watermark a freshly rendered PNG."""
    compose(Image.open(_spool(png, out)).convert("RGB"), meta).save(out, "PNG", optimize=True)


def restamp(out: pathlib.Path, meta: dict) -> None:
    """Redraw the bar on an already-stamped PNG, without touching the GPU.

    The bar is drawn *below* the render rather than over it, so the art is exactly the top
    meta['size'] rows and cropping to them recovers it losslessly. Cropping to that height
    -- rather than to `height - FOOT` -- is what makes this idempotent: it discards whatever
    bar is present, of whatever height, so running it twice is the same as running it once.
    """
    im = Image.open(out).convert("RGB")
    side = meta["size"]
    assert im.height >= side, f"{out.name} is {im.height}px, shorter than the {side}px render"
    compose(im.crop((0, 0, im.width, side)), meta).save(out, "PNG", optimize=True)


def _spool(png: bytes, out: pathlib.Path) -> pathlib.Path:
    tmp = out.with_suffix(".raw")
    tmp.write_bytes(png)
    return tmp


def main() -> int:
    if "--restamp" in sys.argv:
        return main_restamp()
    force = "--force" in sys.argv
    made = 0
    for slug, seed, prompt in ART:
        out = SITE / f"art-{slug}.png"
        side = SITE / f"art-{slug}.json"
        if out.exists() and not force:
            print(f"  keep    art-{slug}.png")
            continue
        print(f"  render  art-{slug}.png (seed {seed}) ...", end="", flush=True)
        started = time.time()
        try:
            png, meta = render(seed, prompt)
        except urllib.error.URLError as e:
            print(f" FAILED: {e}")
            return 1
        stamp(png, meta, out)
        (SITE / f"art-{slug}.raw").unlink(missing_ok=True)
        side.write_text(json.dumps({**meta, "prompt": prompt, "slug": slug}, indent=2))
        print(f" {time.time() - started:.1f}s  ({meta['seconds']}s on the card)")
        made += 1
    print(f"\n{made} rendered, {len(ART) - made} kept")
    return 0


def main_restamp() -> int:
    """Redraw every bar from the sidecars. No API call, no card, no lease."""
    done = 0
    for slug, _seed, _prompt in ART:
        out, side = SITE / f"art-{slug}.png", SITE / f"art-{slug}.json"
        if not (out.is_file() and side.is_file()):
            print(f"  skip    art-{slug}: no PNG or no sidecar -- render it first")
            continue
        restamp(out, json.loads(side.read_text()))
        print(f"  restamp art-{slug}.png -> {Image.open(out).size[1]}px tall")
        done += 1
    print(f"\n{done} restamped, artwork untouched (bar is {FOOT}px)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
