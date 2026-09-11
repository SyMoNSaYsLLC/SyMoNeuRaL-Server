"""The HTTP surface. Mounted at `/api/sigils` by `api.py`; nothing here assumes that prefix.

A sigil is one small themed sticker: single subject, hard edges, **transparent background**.
The engine is the image surface's, the new part is the alpha channel, and the shape of this
module follows from two constraints that are not negotiable on this box.

**The card is held for a job, never for a process lifetime.** The render runs under
`scripts/gpu-governor.sh with sigil -- ...`, which releases on the way out even if the
engine crashes, and names its surface when it does. Everything after the render -- the
decode, the key, the despill, the encode, the write -- happens with the lock already given
back, in a worker thread. A CPU post-process that kept the next tenant off the GPU would be
the same mistake as holding the lock for residency instead of for work.

**No content policy lives here.** The operator's instruction is explicit: there are to be no
filters or safeguards on this project until he has decided himself what should pass. The
bounds in this file are structural -- one job at a time, a canvas the card can actually
decode, a time budget so a wedged engine cannot hold the queue forever -- and they exist to
stop the box falling over, not to stop a prompt. `PROMPT_GATE` below is a seam and is
`None`; it is left empty deliberately rather than filled in with a policy nobody asked for.

**Written for a phone app as much as for this website.** No session, no cookie, no CSRF, no
referer check: every field a client needs is in the response body. The response carries a
`schema` tag so a client can branch on it forever, and new fields may be added but existing
names and types do not change meaning.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import pathlib
import secrets
import tempfile
import time
from typing import Callable, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .lib import listen
from .apps import matte
from .apps import png
from .lib import render
from .lib import segment
from .lib import upload

log = logging.getLogger("symoneural.sigils")

router = APIRouter(tags=["sigils"])

#: An optional prompt gate, for the wiring engineer, and empty on purpose.
#:
#: `backend/server.py` applies one single condition to `/api/image` -- the intersection of a
#: child term and a sexual term, which is the one output that is illegal to produce -- and
#: nothing else. This surface reaches the same engine by a different route, so if that one
#: condition is wanted here too it is one line at the mount site:
#:
#:     sigils.router.PROMPT_GATE = denied
#:
#: It is left unset here rather than copied, because copying it would be this package
#: deciding a content question that belongs to the operator, and he has said plainly that he
#: sets those himself. Unset means every prompt reaches the engine.
PROMPT_GATE: Callable[[str], bool] | None = None

#: One sigil job at a time in this process. The governor is the real, cross-process mutex --
#: this only stops a single client from queueing a dozen renders inside one worker and
#: turning the lock wait into a thundering herd. It is a resource cap, not a rate limit.
_JOB = asyncio.Lock()
_inflight = 0

#: The last completed job, as a real reading for `/state` and for the rack detail line.
#: `None` until something has actually run: an unmeasured surface reports that it has no
#: measurement, it does not invent an encouraging one.
_last: dict | None = None

MAX_PROMPT_CHARS = 100_000

#: Themed starting points. These are prompt text and nothing more -- no hidden model, no
#: separate weights, no curation of what else may be asked for. The page shows them as
#: buttons because "what do I type" is the real first obstacle on a generative surface.
PACKS: dict[str, list[str]] = {
    "rack": ["a server rack with glowing status lights",
             "a single GPU card, three fans, seen head on",
             "a coiled network cable",
             "a cooling fan blade"],
    "raven": ["a raven perched, wings folded",
              "a raven in flight, wings wide",
              "a raven's head in profile"],
    "bench": ["a torque screwdriver",
              "a thermal paste syringe",
              "a power supply with braided cables",
              "a mechanical keyboard keycap"],
    "weather": ["a storm cloud with one lightning bolt",
                "a crescent moon",
                "a sun with sharp rays"],
}


class SigilRequest(BaseModel):
    """One sticker. Bounds are clamped rather than refused, except an oversized prompt."""
    model_config = ConfigDict(extra="ignore")
    prompt: str = Field(..., max_length=MAX_PROMPT_CHARS,
                        description="The subject, and only the subject. A fixed sticker "
                                    "suffix is appended; the composed prompt comes back in "
                                    "the response so you can see exactly what was sent.",
                        examples=["a raven perched, wings folded"])
    key: Literal["magenta", "green"] = Field(
        "magenta",
        description="The field colour the subject is drawn on and keyed out of. Magenta is "
                    "far from foliage; green is far from skin and warm tones. Neither wins "
                    "on every subject, which is why both are here.")
    steps: int = Field(4, ge=1, le=100,
                       description="This engine is distilled for four. More costs time.")
    size: int = Field(512, ge=256, le=1024, multiple_of=64,
                      description="Square edge in pixels, and the canvas of the returned "
                                  "PNG. Must be a multiple of 64: the decoder downsamples "
                                  "by 8 and the transformer patches by 2.")
    seed: int | None = Field(None, ge=0, le=2**31 - 1,
                             description="Omit for random. Supply to reproduce a sticker.")


@router.get("/packs", summary="Themed starting prompts")
async def packs() -> dict:
    """The presets the page offers. Text only -- nothing here constrains what may be asked."""
    return {"schema": "sigil/packs/v1", "packs": PACKS,
            "suffix": render.SUFFIX, "keys": sorted(matte.KEYS)}


@router.post("/render", summary="Render one sticker with a transparent background")
async def make(body: SigilRequest) -> dict:
    """Render, release the card, then key the field out and write an RGBA PNG.

    The returned `url` is served by the image surface's `/api/gen/<name>` route, so the file
    is named in that route's shape deliberately: it is an exact-match regex against an
    attacker-controlled path segment and inventing a new prefix would 404 every sticker.

    **The URL is ephemeral and the contract says so.** Renders in that directory are pruned
    to the newest sixty, so a client that wants to keep a sticker must keep the bytes, not
    the link. That is stated here rather than discovered by a user whose saved sticker
    turned into a 404.
    """
    global _inflight, _last

    subject = body.prompt.strip()
    if not subject:
        raise HTTPException(400, "Say what the sticker should be of.")
    if not render.weights_present():
        raise HTTPException(503, "The image engine is not installed on this box.")
    prompt = render.compose(subject, body.key)
    if PROMPT_GATE is not None and PROMPT_GATE(prompt):
        raise HTTPException(400, "That prompt was refused by the gate this box is running.")

    # secrets, not the clock: seeding from int(time.time()) gave every render inside the
    # same wall-clock second an identical "random" seed.
    seed = body.seed if body.seed is not None else secrets.randbelow(2**31 - 1)
    stamp = int(time.time() * 1000)
    # The intermediate is the raw render: a subject on a solid field, which is precisely the
    # image that must never be served. It is named outside /api/gen's regex so it cannot be
    # fetched even by guessing, kept outside the `gen-*` glob so it does not count against
    # the gallery's retention, and unlinked in `finally` whatever happens.
    raw = render.RENDERS / render.raw_name(stamp, seed)
    out = render.RENDERS / render.output_name(stamp, seed)

    async with _JOB:
        _inflight += 1
        try:
            try:
                rc, err, wait_s, render_s = await render.run(
                    render.build_argv(prompt, raw, seed, body.steps, body.size))
            except render.Busy as exc:
                raise HTTPException(
                    503, f"Something else is using the GPU right now: {exc}") from None
            if rc != 0 or not raw.is_file():
                log.error("sigil render failed rc=%s: %s", rc,
                          err.decode("utf-8", "replace")[-800:])
                raise HTTPException(500, "The render failed.")
            # The card is already back: `with` released it when the engine exited. Everything
            # below is CPU work and it runs in a thread, because a quarter of a second of
            # byte-plane arithmetic on the event loop stalls the live status socket.
            result = await asyncio.to_thread(
                _finish, raw, out, body.key,
                {"model": render.MODEL_NAME, "seed": seed, "steps": body.steps,
                 "size": body.size, "prompt": prompt})
        finally:
            _inflight -= 1
            raw.unlink(missing_ok=True)

    doc = {
        "schema": "sigil/result/v1",
        "url": f"/api/gen/{out.name}",
        "subject": subject,
        "prompt": prompt,
        "suffix": render.SUFFIX.format(key=body.key, hex=render.KEY_HEX[body.key]),
        "model": render.MODEL_NAME,
        "seed": seed,
        "steps": body.steps,
        "size": body.size,
        "bytes": result["bytes"],
        # Kept apart on purpose: `queued_seconds` is how long another tenant had the card,
        # `render_seconds` is what this box actually took, and `matte_seconds` is CPU work
        # done with the card already handed back. Their sum is the visitor's wait; none of
        # the three means what either of the others means.
        "queued_seconds": round(wait_s, 2),
        "render_seconds": round(render_s, 2),
        "matte_seconds": result["matte_seconds"],
        "note": "the url is ephemeral -- renders are pruned to the newest 60, so keep the "
                "bytes rather than the link",
        **result["stats"],
    }
    _last = {k: doc[k] for k in ("key", "size", "steps", "render_seconds", "matte_seconds",
                                 "transparent_fraction", "degenerate", "bytes")}
    _last["at"] = time.time()
    return doc


def _finish(raw: pathlib.Path, out: pathlib.Path, key: str, provenance: dict) -> dict:
    """Decode, key, encode, write. Synchronous on purpose -- the caller puts it in a thread."""
    width, height, planes = png.read(raw.read_bytes())
    return _matte_and_write(width, height, planes, out, key, provenance)


def _matte_and_write(width: int, height: int, planes: list[bytes], out: pathlib.Path,
                     key: str, provenance: dict) -> dict:
    """The half of `_finish` that does not care where the pixels came from.

    Split out so the cutout path -- which has no render behind it at all, only an upload --
    goes through the *same* matte, the same provenance chunks and the same encoder as a
    render does. Two code paths writing stickers would be two places for the alpha channel
    to be subtly different, and the whole surface is the alpha channel.
    """
    started = time.monotonic()
    rgba, stats = matte.cut(width, height, planes, key)
    stats["matte"] = "chroma"
    blob = _encode(width, height, rgba, key, provenance)
    out.write_bytes(blob)
    elapsed = time.monotonic() - started
    return {"bytes": len(blob), "matte_seconds": round(elapsed, 3), "stats": stats}


def _write_segmented(width: int, height: int, rgba: list[bytes], out: pathlib.Path,
                     key: str, provenance: dict, seg: dict) -> dict:
    """Encode an alpha channel that `segment.py` already produced.

    The pixels come back through this package's own encoder rather than being served as the
    worker wrote them, so a sticker carries the same `tEXt` provenance whichever matte made
    it. The extra decode and re-encode costs tens of milliseconds against a matte measured
    at ~1.3 s, and it buys one encoder with one set of tests instead of two.

    `stats` is deliberately shaped exactly like the chroma matte's, down to `degenerate`
    being computed the same way, so a client cannot tell the two apart by the shape of the
    response -- only by reading `matte`, which says outright which one ran.
    """
    started = time.monotonic()
    blob = _encode(width, height, rgba, key, provenance)
    out.write_bytes(blob)
    stats = {
        "key": key,
        "field_rgb": None,          # nothing was keyed, so there is no field to report
        "opaque_fraction": seg["opaque_fraction"],
        "transparent_fraction": seg["transparent_fraction"],
        "edge_pixels": None,
        "degenerate": seg["degenerate"],
        "matte": seg["model"],
    }
    return {"bytes": len(blob), "matte_seconds": round(time.monotonic() - started, 3),
            "stats": stats}


def _encode(width: int, height: int, rgba: list[bytes], key: str, provenance: dict) -> bytes:
    """Attach the provenance and encode. One encoder for every path that makes a sticker.

    Provenance rides in the file's metadata, not in its pixels. `tools/build_gallery.py`
    stamps a bar naming the model, size and seed onto homepage art; burning that into a
    sticker would deface the thing being made, so the same facts go into tEXt chunks
    instead and the sticker itself is untouched.

    Read with `.get`, and the keys are omitted rather than filled with a placeholder when
    they do not apply: a cutout has no model, no seed and no steps, because no model ran.
    Writing `Seed: 0` or `Model: none` into the metadata of a sticker that was never
    generated would be inventing provenance, which is the one thing this bar exists to
    prevent. An absent field says "this did not happen"; a zero says "it happened, and the
    answer was zero".
    """
    text = {
        "Software": "SyMoNeuRaL Sigils",
        "Canvas": f"{width}x{height}",
        "Key": key,
        # How the pixels came to exist: a render, a re-draw seeded by an upload, or an
        # upload with its background removed and nothing generated at all.
        "Mode": str(provenance.get("mode", "render")),
    }
    for field in ("Model", "Seed", "Steps", "Prompt", "Strength", "Source", "Matte"):
        value = provenance.get(field.lower())
        if value is not None:
            text[field] = str(value)
    return png.write_rgba(width, height, rgba, text)


class ImageRequest(BaseModel):
    """A picture in. Two modes, and they are different products -- see `mode`."""
    model_config = ConfigDict(extra="ignore")
    image_base64: str = Field(
        ..., description="The picture, base64-encoded. Anything ffmpeg decodes: JPEG, PNG, "
                         "HEIC, WebP, or one frame of a live photo. A data: URL prefix is "
                         "accepted and stripped.")
    mode: Literal["cutout", "redraw"] = Field(
        "cutout",
        description="`cutout` removes the background from YOUR picture -- no model runs, no "
                    "GPU, and what comes back is your own subject with an alpha channel. "
                    "`redraw` re-draws the subject as sticker artwork with the engine, "
                    "seeded by your picture; it is influenced by your photo, not traced "
                    "from it. `cutout` is the default because it is the one that returns "
                    "the thing you actually uploaded.")
    prompt: str = Field(
        "", max_length=MAX_PROMPT_CHARS,
        description="`redraw` only, and optional. Names the subject if you want to steer "
                    "it; leave empty and the upload is the only subject. Ignored by "
                    "`cutout`, which generates nothing.")
    strength: float = Field(
        upload.DEFAULT_STRENGTH, ge=0.2, le=upload.MAX_STRENGTH,
        description="`redraw` only: how far from your picture the engine may travel. The "
                    "ceiling is measured, not chosen -- at 0.85 two entirely different "
                    "uploads produced byte-identical output on this box, so above 0.80 the "
                    "picture you sent stops affecting the result.")
    key: Literal["magenta", "green"] = Field(
        "magenta",
        description="Recorded with the sticker for the audit trail. Note that neither mode "
                    "paints a field: the background being removed is the one your picture "
                    "or the re-draw actually has, measured off the border.")
    steps: int = Field(4, ge=1, le=100, description="`redraw` only.")
    size: int = Field(512, ge=256, le=1024, multiple_of=64,
                      description="The working edge in pixels. `cutout` keeps your aspect "
                                  "ratio and fits inside this box; `redraw` is square, "
                                  "because the engine renders at one geometry.")
    seed: int | None = Field(None, ge=0, le=2**31 - 1, description="`redraw` only.")


class AudioRequest(BaseModel):
    """Speech in. The words become the subject and go down the text path unchanged."""
    model_config = ConfigDict(extra="ignore")
    audio_base64: str = Field(
        ..., description="The recording, base64-encoded. Anything ffmpeg decodes: the "
                         "WebM/Opus a browser records, the m4a or caf an iPhone produces, "
                         "wav, mp3. A data: URL prefix is accepted and stripped.")
    key: Literal["magenta", "green"] = Field("magenta")
    steps: int = Field(4, ge=1, le=100)
    size: int = Field(512, ge=256, le=1024, multiple_of=64)
    seed: int | None = Field(None, ge=0, le=2**31 - 1)


def _decode_b64(raw: str, what: str) -> bytes:
    """Base64 in, bytes out, with the data: prefix a browser adds taken off.

    Base64 rather than multipart, and this is a deployment decision rather than a taste
    one: a route declaring `UploadFile` needs `python-multipart`, FastAPI raises at
    **route-definition time** when it is missing, and this repo's serving path is the
    system interpreter with `pip install` denied by policy. A missing package would
    therefore not break stickers, it would stop the entire API from starting -- on a box
    where only Garrett can run the restart and nobody can watch it fail. Base64 costs a
    third more bytes on the wire and cannot do that.
    """
    blob = raw.strip()
    if blob.startswith("data:"):
        _head, _sep, blob = blob.partition(",")
    try:
        return base64.b64decode(blob, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, f"that {what} was not valid base64") from None


@router.post("/from-image", summary="A sticker from a picture: background removed, or re-drawn")
async def from_image(body: ImageRequest) -> dict:
    """Two paths that share one matte and one encoder. The response says which one ran.

    **`cutout` never takes the GPU.** No model is loaded, no lock is acquired, and the whole
    job is the matte -- so it answers while another surface holds the card, the same way
    RavenCalc does. That is the reason it is the default as well as the reason it is fast.

    **`redraw` is honest about being a re-draw.** `mode` comes back in the response and goes
    into the PNG's metadata, because a client showing a user their own photo and a client
    showing them a generated picture of their photo owe the user different captions.
    """
    global _inflight, _last

    blob = _decode_b64(body.image_base64, "picture")
    if not blob:
        raise HTTPException(400, "That picture was empty.")

    stamp = int(time.time() * 1000)
    seed = body.seed if body.seed is not None else secrets.randbelow(2**31 - 1)
    out = render.RENDERS / render.output_name(stamp, seed)

    if body.mode == "cutout":
        started = time.monotonic()
        segment_s = None
        with tempfile.TemporaryDirectory() as tmp:
            norm = pathlib.Path(tmp) / "in.png"
            try:
                await upload.normalise(blob, norm, body.size, square=False)
            except upload.Undecodable as exc:
                raise HTTPException(400, str(exc)) from None

            provenance = {"mode": "cutout",
                          "source": "an uploaded picture, background removed"}
            result = None
            # Segmentation first, chroma key as the fallback -- and the fallback is real,
            # not decorative: a box without the venv still cuts stickers out, just less
            # well, and it says which one it used rather than pretending they are the same.
            #
            # This ordering is the opposite of the text path's on purpose. Where the
            # surface chose the background, a key is exact and costs ~40 ms. Where a
            # visitor chose it, a key cannot tell white fur from a light backdrop --
            # measured here: 88.75% transparent, `degenerate: false`, and holes through
            # the animal. So: key what we painted, segment what we did not.
            if segment.installed():
                cut = pathlib.Path(tmp) / "cut.png"
                try:
                    seg = await segment.cut_file(norm, cut)
                    segment_s = seg["seconds"]
                    width, height, planes = png.read(cut.read_bytes())
                    provenance["matte"] = seg["model"]
                    result = await asyncio.to_thread(
                        _write_segmented, width, height, planes, out, body.key,
                        provenance, seg)
                except segment.Unavailable as exc:
                    log.warning("cutout fell back to the chroma key: %s", exc)
            if result is None:
                width, height, planes = png.read(norm.read_bytes())
                provenance["matte"] = "chroma"
                # In a thread: the matte is tens of milliseconds of byte-plane arithmetic,
                # and on the event loop that stalls the live status socket the rack pushes
                # over.
                result = await asyncio.to_thread(
                    _matte_and_write, width, height, planes, out, body.key, provenance)
        doc = {
            "schema": "sigil/result/v1",
            "url": f"/api/gen/{out.name}",
            "mode": "cutout",
            "size": body.size,
            "width": width,
            "height": height,
            "bytes": result["bytes"],
            "decode_seconds": round(time.monotonic() - started - (segment_s or 0), 3),
            "segment_seconds": segment_s,
            "matte_seconds": result["matte_seconds"],
            # Stated rather than implied: nothing was *generated*, so there is no image
            # model, no seed and no render time to report. Reporting zeros would read as
            # measurements. The matte's own model, if one ran, is named in `matte`.
            "model": None,
            # False in the sense the rack cares about: no GPU lock was taken and no weights
            # went near the card. A segmentation model may well have run, on the CPU, and
            # `matte` in the stats names it -- so this is "the card was never touched",
            # not "no model was involved".
            "gpu": False,
            "note": "this is your own picture with its background removed -- nothing was "
                    "generated, and the card was never taken. the url is ephemeral: "
                    "renders are pruned to the newest 60, so keep the bytes not the link",
            **result["stats"],
        }
        _last = {"mode": "cutout", "size": body.size,
                 "matte_seconds": result["matte_seconds"],
                 "transparent_fraction": doc["transparent_fraction"],
                 "degenerate": doc["degenerate"], "bytes": doc["bytes"], "at": time.time()}
        return doc

    # ---- redraw ------------------------------------------------------------------
    if not render.weights_present():
        raise HTTPException(503, "The image engine is not installed on this box.")
    prompt = render.compose_redraw(body.prompt)
    if PROMPT_GATE is not None and PROMPT_GATE(prompt):
        raise HTTPException(400, "That prompt was refused by the gate this box is running.")
    raw = render.RENDERS / render.raw_name(stamp, seed)
    init = render.RENDERS / f"sigil-init-{stamp}-{seed}.png"

    async with _JOB:
        _inflight += 1
        try:
            try:
                await upload.normalise(blob, init, body.size, square=True)
            except upload.Undecodable as exc:
                raise HTTPException(400, str(exc)) from None
            try:
                rc, err, wait_s, render_s = await render.run(render.build_argv(
                    prompt, raw, seed, body.steps, body.size,
                    init=init, strength=body.strength))
            except render.Busy as exc:
                raise HTTPException(
                    503, f"Something else is using the GPU right now: {exc}") from None
            if rc != 0 or not raw.is_file():
                log.error("sigil redraw failed rc=%s: %s", rc,
                          err.decode("utf-8", "replace")[-800:])
                raise HTTPException(500, "The render failed.")
            provenance = {"model": render.MODEL_NAME, "seed": seed, "steps": body.steps,
                          "prompt": prompt, "strength": body.strength, "mode": "redraw",
                          "source": "seeded by an uploaded picture"}
            # Segmented, not keyed, and for the same reason the cutout path is: a re-draw
            # inherits its background from the upload rather than from a field this surface
            # asked for. Measured across 4, 8 and 12 steps at strengths 0.55-0.60, the
            # engine never painted the requested field -- the border came back grey every
            # time -- and one of the two test subjects came back as a photograph with a cast
            # shadow on a wall. A distance threshold has nothing to find there.
            result = None
            if segment.installed():
                with tempfile.TemporaryDirectory() as tmp:
                    cut = pathlib.Path(tmp) / "cut.png"
                    try:
                        seg = await segment.cut_file(raw, cut)
                        width, height, planes = png.read(cut.read_bytes())
                        provenance["matte"] = seg["model"]
                        result = await asyncio.to_thread(
                            _write_segmented, width, height, planes, out, body.key,
                            provenance, seg)
                        matte_seconds_extra = seg["seconds"]
                    except segment.Unavailable as exc:
                        log.warning("redraw fell back to the chroma key: %s", exc)
            if result is None:
                provenance["matte"] = "chroma"
                matte_seconds_extra = None
                result = await asyncio.to_thread(_finish, raw, out, body.key, provenance)
        finally:
            _inflight -= 1
            # Both intermediates go, whatever happened. The init is a copy of a visitor's
            # own photograph sitting in a directory the API serves out of; it is named
            # outside /api/gen's regex so it cannot be fetched, and it is not left there.
            raw.unlink(missing_ok=True)
            init.unlink(missing_ok=True)

    doc = {
        "schema": "sigil/result/v1",
        "url": f"/api/gen/{out.name}",
        "mode": "redraw",
        "prompt": prompt,
        "suffix": render.REDRAW_SUFFIX,
        "model": render.MODEL_NAME,
        "gpu": True,
        "seed": seed,
        "steps": body.steps,
        "strength": body.strength,
        "size": body.size,
        "bytes": result["bytes"],
        "queued_seconds": round(wait_s, 2),
        "render_seconds": round(render_s, 2),
        "matte_seconds": result["matte_seconds"],
        # Present only when a segmentation model ran. Kept apart from `matte_seconds`,
        # which is the encode, so neither figure absorbs the other's cost.
        "segment_seconds": matte_seconds_extra,
        # The honest caption for this mode, in the contract so a client cannot omit it by
        # accident. Measured on this box: at strength 0.85 the upload was ignored entirely,
        # and at 0.60 a photographic subject sometimes stays photographic rather than
        # becoming flat artwork -- so the background that gets keyed is whatever the
        # re-draw produced, and it does not always key cleanly. `degenerate` says when.
        "note": "a re-draw seeded by your picture, not a copy of it. the url is ephemeral "
                "-- renders are pruned to the newest 60, so keep the bytes not the link",
        **result["stats"],
    }
    _last = {"mode": "redraw", "size": body.size, "steps": body.steps,
             "render_seconds": doc["render_seconds"],
             "matte_seconds": result["matte_seconds"],
             "transparent_fraction": doc["transparent_fraction"],
             "degenerate": doc["degenerate"], "bytes": doc["bytes"], "at": time.time()}
    return doc


@router.post("/from-audio", summary="A sticker from speech: say what it should be of")
async def from_audio(body: AudioRequest) -> dict:
    """Transcribe on the CPU, then render exactly as a typed subject renders.

    **There is no audio-native model here and the response says so.** `path` comes back as
    "speech -> text -> the same render a typed subject gets", because a surface that took a
    voice and returned a picture could easily be read as listening to the voice. It is not:
    whisper.cpp turns the recording into words, and the words are the prompt.

    The transcription holds no GPU lock, so it overlaps whatever else has the card instead
    of queueing behind it. Measured on this box: 11 s of speech transcribed in 2.2 s on the
    CPU, against ~12 s for the render that follows -- so speech is not what makes a spoken
    sticker slow.
    """
    global _inflight, _last

    blob = _decode_b64(body.audio_base64, "recording")
    if not blob:
        raise HTTPException(400, "That recording was empty.")
    if not listen.installed():
        raise HTTPException(503, "Speech-to-text is not installed on this box.")
    if not render.weights_present():
        raise HTTPException(503, "The image engine is not installed on this box.")

    try:
        heard = await listen.transcribe(blob)
    except listen.Unheard:
        # 400, not 500, and worded as a fact about the recording rather than as a fault.
        # Whisper returns a marker for silence rather than nothing; rendering that marker
        # would have produced a confident sticker of the words "[BLANK_AUDIO]".
        raise HTTPException(400, "There was no speech in that recording.") from None
    except listen.Undecodable as exc:
        raise HTTPException(400, str(exc)) from None

    subject = heard["subject"]
    prompt = render.compose(subject, body.key)
    if PROMPT_GATE is not None and PROMPT_GATE(prompt):
        raise HTTPException(400, "That prompt was refused by the gate this box is running.")

    seed = body.seed if body.seed is not None else secrets.randbelow(2**31 - 1)
    stamp = int(time.time() * 1000)
    raw = render.RENDERS / render.raw_name(stamp, seed)
    out = render.RENDERS / render.output_name(stamp, seed)

    async with _JOB:
        _inflight += 1
        try:
            try:
                rc, err, wait_s, render_s = await render.run(
                    render.build_argv(prompt, raw, seed, body.steps, body.size))
            except render.Busy as exc:
                raise HTTPException(
                    503, f"Something else is using the GPU right now: {exc}") from None
            if rc != 0 or not raw.is_file():
                log.error("sigil audio render failed rc=%s: %s", rc,
                          err.decode("utf-8", "replace")[-800:])
                raise HTTPException(500, "The render failed.")
            result = await asyncio.to_thread(
                _finish, raw, out, body.key,
                {"model": render.MODEL_NAME, "seed": seed, "steps": body.steps,
                 "prompt": prompt, "mode": "speech"})
        finally:
            _inflight -= 1
            raw.unlink(missing_ok=True)

    doc = {
        "schema": "sigil/result/v1",
        "url": f"/api/gen/{out.name}",
        "mode": "speech",
        # What was heard comes back verbatim alongside what was rendered. A visitor whose
        # sticker is wrong needs to see whether the transcriber misheard them or the engine
        # drew the wrong thing, and those have different fixes.
        "heard": heard["transcript"],
        "subject": subject,
        "prompt": prompt,
        "suffix": render.SUFFIX.format(key=body.key, hex=render.KEY_HEX[body.key]),
        "model": render.MODEL_NAME,
        "asr_model": heard["model"],
        "path": heard["path"],
        "gpu": True,
        "seed": seed,
        "steps": body.steps,
        "size": body.size,
        "bytes": result["bytes"],
        "audio_seconds": heard["audio_seconds"],
        "decode_seconds": heard["decode_seconds"],
        # Kept separate from render_seconds on purpose: this one is CPU work that took no
        # lock, and adding it to the render time would report a GPU figure that is not one.
        "transcribe_seconds": heard["transcribe_seconds"],
        "queued_seconds": round(wait_s, 2),
        "render_seconds": round(render_s, 2),
        "matte_seconds": result["matte_seconds"],
        "note": "the url is ephemeral -- renders are pruned to the newest 60, so keep the "
                "bytes rather than the link",
        **result["stats"],
    }
    _last = {"mode": "speech", "size": body.size, "steps": body.steps,
             "transcribe_seconds": heard["transcribe_seconds"],
             "render_seconds": doc["render_seconds"],
             "matte_seconds": result["matte_seconds"],
             "transparent_fraction": doc["transparent_fraction"],
             "degenerate": doc["degenerate"], "bytes": doc["bytes"], "at": time.time()}
    return doc


@router.get("/state", summary="What this surface can do, and what it last did")
async def state() -> dict:
    """Real readings only.

    `installed` is the weights and the engine actually being on disk, not this module being
    importable. `last` is `null` until a sticker has genuinely been made here -- an empty
    measurement is reported as empty rather than filled in with a plausible number.
    """
    return {
        "schema": "sigil/state/v1",
        "installed": render.weights_present(),
        "surface": render.SURFACE,
        "busy": _inflight > 0,
        "keys": sorted(matte.KEYS),
        # Two mattes, and which one runs depends on who chose the background. Reported as
        # a pair rather than as one sentence, because a single string here was already
        # wrong the moment a photograph could be uploaded.
        "matte": {
            "generated": "chroma key, CPU, standard library only",
            "photographic": (f"{segment.DEFAULT_MODEL}, CPU, in its own venv"
                             if segment.installed()
                             else "chroma key -- segmentation is not installed, and it is "
                                  "measurably worse on photographs"),
            "rule": "key what the surface painted, segment what it did not",
        },
        # Three ways in, and each reports whether it can actually run rather than whether
        # its module imported. `cutout` is the only one that works with no weights at all,
        # which is why they are listed separately instead of behind one `installed` flag.
        "inputs": {
            "text": render.weights_present(),
            "image": upload.available(),
            "audio": listen.installed(),
        },
        "image": upload.state(),
        "audio": listen.state(),
        # Which matte a photograph gets. When this is not installed the surface still
        # works and says so -- `cutout` falls back to the chroma key, which is measurably
        # worse on photographs and is reported per sticker in `matte`.
        "segmentation": segment.state(),
        "last": _last,
    }


def status() -> dict:
    """The rack unit, as a plain dict. Called on every rack poll -- synchronous and cheap.

    Deliberately **not** built from `api.py`'s `Unit` model: importing it would put this
    module inside `api.py`'s import graph and outside the scope this module was built in.
    The keys match `Unit`'s fields so the wiring engineer can splat it in as
    `Unit(**sigils.status())`.

    The state is a reading, not a decoration:
      * `offline` when the engine or a weight file is missing -- the surface genuinely
        cannot work, and says so rather than showing an encouraging light;
      * `busy` while a render is actually in flight;
      * `ready` otherwise.
    It is never `ready` on the strength of the module importing.
    """
    # Deliberately still `offline` without the weights, even though `cutout` needs none and
    # would keep working. This is a `bus: gpu` unit on a rack about the GPU stack, and the
    # four states it may report have no value for "reduced". Reporting `ready` would hide a
    # missing engine to advertise one working mode, which is the worse of the two lies.
    # `GET /state` carries the real per-input breakdown, and that is where a client that
    # cares about cutouts should look.
    if not render.weights_present():
        state_, detail = "offline", "image engine not installed on this box"
    elif _inflight:
        state_, detail = "busy", "keying one sticker · the card is released before the matte"
    else:
        spoken = " · speech" if listen.installed() else ""
        state_, detail = "ready", (f"stickers from text, a photo{spoken} · real alpha "
                                   "channel, and the matte never takes the card")
    return {
        "id": "sigils",
        "label": "SyMoNeuRaL Sigils",
        "slot": "1U",
        "state": state_,
        "bus": "gpu",
        "href": "/sigils.html",
        "spec": "SymonImage F1 → chroma key → RGBA PNG",
        "detail": detail,
    }
