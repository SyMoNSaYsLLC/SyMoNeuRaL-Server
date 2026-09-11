"""Playlist cover art, drawn here rather than fetched.

`pipeline` calls `render_cover(name, prompt)` and uploads the result where the connector supports
it. Pillow if it is installed and nothing if it is not -- the DJ must not fail to create a playlist
because a drawing library is missing, so every path returns bytes or None and none of them raise.

Deliberately not the image agent. Generating cover art there would take the GPU turnstile for a
picture nobody asked for, in the middle of a job whose point is the tracklist.

SPDX-License-Identifier: GPL-2.0-or-later
"""
from __future__ import annotations

import hashlib
import io
import logging

log = logging.getLogger(__name__)

#: The brand accent, and a deep companion. The same #2ee08a the icons and the windows use.
ACCENT = (46, 224, 138)
DEEP = (10, 45, 32)


def _hue_for(text: str) -> tuple[int, int, int]:
    """A stable colour per playlist name, biased green so a set still looks like ours.

    Stable matters: regenerating the same playlist must not produce a different cover, or the art
    becomes noise instead of a way to recognise it in a list.
    """
    digest = hashlib.sha256(text.encode()).digest()
    return (
        max(12, min(80, DEEP[0] + digest[0] % 40)),
        max(40, min(200, DEEP[1] + digest[1] % 120)),
        max(24, min(140, DEEP[2] + digest[2] % 90)),
    )


def render_cover(name: str, prompt: str = "", size: int = 640) -> bytes | None:
    """A JPEG for the playlist, or None. Never raises."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        log.info("no Pillow — playlists get the service's default cover")
        return None

    try:
        image = Image.new("RGB", (size, size), _hue_for(name or prompt or "symoneural"))
        draw = ImageDraw.Draw(image)

        # Bar heights come from the name's digest: a spectrum that is identical every time for
        # one playlist and different between playlists.
        digest = hashlib.sha256((name + prompt).encode()).digest()
        bars = 24
        width = size / bars
        for i in range(bars):
            height = (digest[i % len(digest)] / 255.0) * (size * 0.55) + size * 0.05
            x0 = i * width
            draw.rectangle([x0 + width * 0.18, size - height,
                            x0 + width * 0.82, size - size * 0.10],
                           fill=ACCENT if i % 3 else (255, 255, 255))

        buffer = io.BytesIO()
        # JPEG and under 256 KiB: Spotify's cover upload rejects anything larger, and quality 85
        # at 640px lands well inside that.
        image.save(buffer, format="JPEG", quality=85)
        data = buffer.getvalue()
        return data if len(data) < 256 * 1024 else None
    except Exception as exc:                                    # noqa: BLE001
        log.warning("cover render failed, continuing without one: %s", exc)
        return None
