"""SyMoNeuRaL Sigils -- small themed stickers with a real transparent background.

A sigil is a small drawn symbol that carries meaning, which is exactly what this makes: one
subject, hard edges, no scene, no ground shadow, no caption strip, and a genuine alpha
channel so it drops onto any background.

## Three ways in, and they are not the same product

| Input | Route | What happens | GPU |
|---|---|---|---|
| **text** | `POST /render` | the subject is drawn on a keyable field, then keyed | yes |
| **a picture** | `POST /from-image` `mode=cutout` | *your* picture, background removed | **no** |
| **a picture** | `POST /from-image` `mode=redraw` | re-drawn as artwork, seeded by yours | yes |
| **speech** | `POST /from-audio` | transcribed on the CPU, then the text path | yes |

`cutout` is the default image mode because it returns the thing that was uploaded. `redraw`
is offered next to it and labelled as a re-draw everywhere it appears -- in the response, in
the PNG metadata and on the page -- because two measured findings say it cannot be sold as a
copy of your photo:

* **At strength 0.85 the upload is ignored entirely.** Two completely different uploads,
  same seed and prompt, produced **byte-identical** PNGs (sha256 verified, 2026-08-17). The
  cap in `upload.MAX_STRENGTH` sits below that for this reason.
* **Where the upload does matter, the engine does not paint the field.** Across 4, 8 and 12
  steps at strengths 0.55-0.60 the border came back grey every time, never the requested
  magenta. So the background being removed is whatever the picture actually has, measured
  off the border -- which keys well on a plain backdrop and badly on a scene. `degenerate`
  in the response says which happened, per sticker.

**The speech path is ASR, not an audio-native model.** whisper.cpp turns a recording into
words and the words go down the same text path a typed subject goes down. It runs on the
CPU and takes no GPU lock, so it overlaps whatever holds the card rather than queueing
behind it -- RavenCalc's argument, applied to speech. Measured here: 11 s of audio
transcribed in 2.2 s, against ~12 s for the render after it.

## What it is, honestly

**A constrained variant of SyMoNeuRaL Image, not a second engine.** Same weights, same
binary, the image surface's proven flags, a fixed sticker suffix on the prompt and a smaller
canvas. One card of 15.92 GiB does not hold two weight sets, so a surface that loaded its
own would not be a feature, it would be an outage.

The part that is genuinely new is the fourth channel. The engine emits three and has no
alpha output at all, so the subject is rendered on a flat field colour and that field is
keyed out arithmetically here -- with hole-filling, despill and a one-pixel feather, in
`matte.py`, and with a PNG codec in `png.py` written on `zlib` and `struct` because this
package is standard library only.

## The rules it is built against

* **The card is held for a job, never for a process lifetime.** Renders go through
  `scripts/gpu-governor.sh with sigil -- ...`, which releases even on a crash and names its
  surface when it does. The matte, the encode and the write all happen after the release.
* **A surface name is also a `case` in the governor's `evict()`.** Add
  `sigil) pkill -f 'bin/symoneural-diffuse' ;;` beside the `image)` arm in the same commit that first writes
  `sigil` into `run/resident`; without it the name falls to `*)`, which takes chat down as
  collateral. See `render.py`.
* **No content policy.** The bounds here are structural -- one job at a time, a canvas the
  card can decode, a time budget. `routes.PROMPT_GATE` is a seam and is deliberately unset.
* **Output is API output.** It lands in `backend/output/` and comes back as
  `/api/gen/<name>`, in that route's exact filename shape, never in `site/`.
* **No watermark bar.** `tools/build/build_gallery.py` stamps the model, size and seed into the
  pixels of homepage art; on a sticker that is a caption burned into the artwork. The same
  facts ride in the PNG's `tEXt` chunks instead, so provenance survives without defacing
  anything.

## Wiring

    import sigils
    app.include_router(sigils.router, prefix="/api/sigils", tags=["sigils"])
    Unit(**sigils.status())        # in the /api/status unit list

`status()` returns the keys of `api.py`'s `Unit` model as a plain dict, on purpose: this
package must not import the application it plugs into.
"""
from __future__ import annotations

from .router import PACKS, router, status
from .lib.render import MODEL_NAME, REDRAW_SUFFIX, SUFFIX, SURFACE

__all__ = ["router", "status", "PACKS", "SUFFIX", "REDRAW_SUFFIX", "SURFACE", "MODEL_NAME"]
