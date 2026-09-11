"""A picture in, a sticker out. The image half of SyMoNeuRaL Stickers.

There are two honest ways to turn a photograph into a sticker and they are different
products, so this module offers both and the response says which one ran.

## `cutout` -- the photograph itself, with its background removed

No GPU, no diffusion, no model. The picture is decoded, its background is keyed off the
border colour the way a render's field is, and what comes back is *the original subject*
with an alpha channel. Measured cost is the matte alone -- tens of milliseconds. It works
when the background is reasonably plain, which is what a phone photo against a wall or a
product shot on a table already is, and it fails on a busy scene. **It says when it
failed**: `degenerate` is returned, computed from the opaque fraction, so a caller can tell
a real cut from a keyed-everything or a keyed-nothing without looking at the pixels.

## `redraw` -- the subject re-drawn as sticker artwork

img2img: the upload seeds the render and the sticker suffix pushes it toward flat, outlined
artwork. This is *not* a traced copy and the page must not imply it is -- it is a picture
influenced by yours.

**The strength ceiling here is a measured finding, not a guess.** Measured on this box
2026-08-17 at 768x768, four steps, seed 777, one prompt naming no subject, two completely
different uploads:

    strength 0.85  ->  the two outputs were BYTE-IDENTICAL (sha256 match)
    strength 0.60  ->  the two outputs differed, and each tracked its own upload

At 0.85 the upload contributes nothing: the same sticker comes back whatever you send. A
mode called "image to sticker" that ignores the image is a lie, so `MAX_STRENGTH` is capped
below it and the cap carries this reason. `symoneural-diffuse` also quantises img2img to
`int(steps * strength)` denoise steps, which is why 0.55 and 0.70 produced identical output
at four steps -- both round to two. Strength is therefore a coarse dial at low step counts,
and that is a property of the engine rather than of this code.

## Why ffmpeg decodes the upload and PIL does not

This package is standard-library-only on the Python side -- `png.py` is a PNG codec written
on `zlib` and `struct` for exactly that reason. A phone sends HEIC, JPEG or WebP and none of
those is decodable from the standard library. ffmpeg is already a hard dependency of this
surface's audio half and of the tuner, so the decode goes through it rather than adding an
imaging library to the serving interpreter, which `.claude/settings.local.json` denies
installing into anyway.
"""
from __future__ import annotations

import asyncio
import pathlib
import shutil
import tempfile
import time

from . import png

#: A phone photo is a few megabytes; a 48MP HEIC is more. Structural, like the audio cap:
#: this bounds what one request can make the box decode, not what may be asked for.
MAX_IMAGE_BYTES = 40 * 1024 * 1024
FFMPEG_TIMEOUT_S = 120

#: See the module docstring. Above this the engine stops using the upload at all, measured.
MAX_STRENGTH = 0.80
DEFAULT_STRENGTH = 0.60


class Undecodable(RuntimeError):
    """ffmpeg could not read the upload as a picture."""


def available() -> bool:
    return shutil.which("ffmpeg") is not None


async def _spawn(argv: list[str], timeout: float) -> tuple[int, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    try:
        _out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode or 0, err or b""


async def normalise(blob: bytes, dest: pathlib.Path, size: int, *, square: bool) -> None:
    """Decode any picture ffmpeg reads into an RGB24 PNG at the working size.

    `square` is the difference between the two modes and it is not cosmetic:

    * **redraw needs a square** -- `symoneural-diffuse` renders at one geometry, and the decoder
      downsamples by 8 while the transformer patches by 2, so the side must be a multiple
      of 64. The padding is white and it does not matter, because the engine repaints it.
    * **cutout must NOT be padded.** Padding invents a border in a colour the photograph
      does not contain, and the matte measures the field *off the border*. Pad a photo shot
      against dark grey with white and the key finds white, removes the padding, and leaves
      the actual grey background fully opaque -- a cut that fails while every intermediate
      step reports success. The aspect ratio is kept instead; nothing requires a sticker to
      be square.
    """
    if len(blob) > MAX_IMAGE_BYTES:
        raise Undecodable(
            f"that picture is larger than the {MAX_IMAGE_BYTES // (1 << 20)} MB cap")
    if not available():
        raise Undecodable("image decoding is not installed on this box")
    with tempfile.NamedTemporaryFile(suffix=".upload", delete=False) as raw:
        raw.write(blob)
        src = pathlib.Path(raw.name)
    if square:
        vf = (f"scale={size}:{size}:force_original_aspect_ratio=decrease,"
              f"pad={size}:{size}:(ow-iw)/2:(oh-ih)/2:color=white")
    else:
        # decrease-only: a small upload is not enlarged into softness it never had.
        vf = f"scale={size}:{size}:force_original_aspect_ratio=decrease"
    try:
        rc, err = await _spawn([
            "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
            "-i", str(src),
            "-frames:v", "1",          # an animated GIF or a live photo is one sticker
            "-vf", vf,
            "-pix_fmt", "rgb24",
            "-c:v", "png", "-f", "image2", "-y", str(dest),
        ], FFMPEG_TIMEOUT_S)
    finally:
        src.unlink(missing_ok=True)
    if rc != 0 or not dest.is_file() or dest.stat().st_size < 64:
        raise Undecodable(err.decode("utf-8", "replace").strip()[-300:]
                          or "ffmpeg could not read that picture")


async def prepare(blob: bytes, size: int, *, square: bool) -> tuple[int, int, list[bytes], float]:
    """Normalise and decode, returning (width, height, planes, seconds).

    ffmpeg writes a PNG and `png.read` reads it back. That round trip through a file looks
    wasteful and is deliberate: it means one PNG decoder is used everywhere in this package,
    the one with tests, rather than trusting a second path to agree with it about geometry.
    """
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        norm = pathlib.Path(tmp) / "in.png"
        await normalise(blob, norm, size, square=square)
        width, height, planes = png.read(norm.read_bytes())
    return width, height, planes, time.monotonic() - started


def state() -> dict:
    """Real readings, and the measured reason for the strength cap."""
    return {
        "modes": ["cutout", "redraw"],
        "ffmpeg": available(),
        "max_bytes": MAX_IMAGE_BYTES,
        "default_strength": DEFAULT_STRENGTH,
        "max_strength": MAX_STRENGTH,
        "strength_note": "measured on this box: at 0.85 two different uploads gave "
                         "byte-identical output, so above 0.80 the upload stops mattering",
    }
