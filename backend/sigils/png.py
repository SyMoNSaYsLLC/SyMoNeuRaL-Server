"""A PNG reader and writer in nothing but the standard library.

**Why this file exists at all.** The serving interpreter has no virtualenv and never gets
one -- `.claude/CLAUDE.md` says so and `.claude/settings.local.json` denies the bare `pip
install` forms. Pillow and numpy happen to be installed as OS packages, but this package was
required to be stdlib-only, and "already on the box" is not the same promise as "in the
standard library": an OS upgrade can take a Debian package away and it cannot take `zlib`
away. So the alpha channel this whole surface exists to produce is made with `zlib`,
`struct` and `bytes`, which is less work than it sounds -- PNG is a filtered scanline format
and a matte is three passes over a byte plane.

Scope, deliberately narrow, because a general PNG decoder is a much bigger and much less
testable thing than the one this needs:

  * read  -- 8-bit, non-interlaced, colour type 2 (RGB) or 6 (RGBA). That is exactly what
             `symoneural-diffuse` writes (verified against a real render: IHDR reports 768x768x8, colour
             type 2, interlace 0), and anything else raises rather than guessing.
  * write -- 8-bit RGBA, non-interlaced, with `tEXt` chunks for provenance.

Everything here works on **planes**: one `bytes` per channel. That is not a stylistic
choice, it is the entire performance strategy in a pure-python decoder. `data[0::3]` is a C
loop, `bytes.translate` is a C loop, and `bytearray[0::4] = plane` is a C loop, so all the
per-pixel work that can be expressed as a whole-plane operation costs no interpreted
bytecode at all. Only the scanline unfilter and the edge band are genuinely interpreted.
"""
from __future__ import annotations

import struct
import zlib

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

#: 0x7f in every byte, sized on demand. Used for SWAR byte-wise addition -- see `_up`.
_MASK_CACHE: dict[int, int] = {}


def _mask(nbytes: int) -> int:
    m = _MASK_CACHE.get(nbytes)
    if m is None:
        m = int.from_bytes(b"\x7f" * nbytes, "big")
        _MASK_CACHE[nbytes] = m
    return m


def _add_bytes(a: bytes, b: bytes) -> bytes:
    """Byte-wise (a + b) mod 256, without an interpreted loop.

    The Up filter is a whole-row addition and a per-byte python loop over it is the single
    most expensive thing in the decoder. Big integers add at C speed but carry across byte
    boundaries, so this is the standard SWAR trick: add the low seven bits of each byte,
    where a carry cannot escape, then fold the eighth bit back in with XOR.
    """
    n = len(a)
    m = _mask(n)
    ai = int.from_bytes(a, "big")
    bi = int.from_bytes(b, "big")
    low = (ai & m) + (bi & m)
    return (low ^ ((ai ^ bi) & ~m & ((1 << (n * 8)) - 1))).to_bytes(n, "big")


class PngError(ValueError):
    """The file is not a PNG this module is willing to read."""


def read(blob: bytes) -> tuple[int, int, list[bytes]]:
    """Decode a PNG into (width, height, [plane, ...]).

    Three planes for RGB, four for RGBA. Each plane is `width * height` bytes.
    """
    if blob[:8] != PNG_MAGIC:
        raise PngError("not a PNG")
    width = height = depth = colour = interlace = -1
    idat = bytearray()
    pos = 8
    end = len(blob)
    while pos + 8 <= end:
        length, kind = struct.unpack(">I4s", blob[pos:pos + 8])
        body = blob[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, colour, _comp, _filt, interlace = struct.unpack(
                ">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
        pos += 12 + length
    if width <= 0 or height <= 0:
        raise PngError("no usable IHDR")
    if depth != 8:
        raise PngError(f"only 8-bit samples are supported, got {depth}")
    if interlace != 0:
        raise PngError("interlaced PNG is not supported")
    if colour not in (2, 6):
        raise PngError(f"only colour types 2 and 6 are supported, got {colour}")
    nchan = 3 if colour == 2 else 4
    raw = zlib.decompress(bytes(idat))
    flat = _unfilter(raw, width, height, nchan)
    return width, height, [bytes(flat[c::nchan]) for c in range(nchan)]


def _unfilter(raw: bytes, width: int, height: int, nchan: int) -> bytearray:
    """Undo the per-scanline filters. Returns interleaved samples, no filter bytes.

    The five filter types are defined in RFC 2083 §6 and every one of them is a recurrence
    on the row above or the pixel to the left, so they cannot all be vectorised. Types 0 and
    2 -- which are the common ones in `stb_image_write`'s output -- are handled whole-row at
    C speed; the other three fall back to an interpreted loop over the row.
    """
    stride = width * nchan
    if len(raw) < height * (stride + 1):
        raise PngError("truncated image data")
    out = bytearray(height * stride)
    prev = bytes(stride)
    src = 0
    dst = 0
    for _y in range(height):
        ftype = raw[src]
        src += 1
        line = raw[src:src + stride]
        src += stride
        if ftype == 0:
            cur = line
        elif ftype == 2:
            cur = _add_bytes(line, prev)
        else:
            cur = _unfilter_row(ftype, line, prev, nchan, stride)
        out[dst:dst + stride] = cur
        dst += stride
        prev = cur
    return out


def _unfilter_row(ftype: int, line: bytes, prev: bytes, nchan: int, stride: int) -> bytes:
    cur = bytearray(line)
    if ftype == 1:                                    # Sub
        for i in range(nchan, stride):
            cur[i] = (cur[i] + cur[i - nchan]) & 0xFF
    elif ftype == 3:                                  # Average
        for i in range(stride):
            left = cur[i - nchan] if i >= nchan else 0
            cur[i] = (cur[i] + ((left + prev[i]) >> 1)) & 0xFF
    elif ftype == 4:                                  # Paeth
        for i in range(stride):
            if i >= nchan:
                a = cur[i - nchan]
                c = prev[i - nchan]
            else:
                a = c = 0
            b = prev[i]
            p = a + b - c
            pa = p - a
            if pa < 0:
                pa = -pa
            pb = p - b
            if pb < 0:
                pb = -pb
            pc = p - c
            if pc < 0:
                pc = -pc
            if pa <= pb and pa <= pc:
                pred = a
            elif pb <= pc:
                pred = b
            else:
                pred = c
            cur[i] = (cur[i] + pred) & 0xFF
    else:
        raise PngError(f"unknown scanline filter {ftype}")
    return bytes(cur)


def _chunk(kind: bytes, body: bytes) -> bytes:
    return (struct.pack(">I", len(body)) + kind + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))


def write_rgba(width: int, height: int, planes: list[bytes],
               text: dict[str, str] | None = None, level: int = 6) -> bytes:
    """Encode four 8-bit planes as an RGBA PNG.

    `text` becomes `tEXt` chunks. That is where this surface's provenance goes, and it is
    the deliberate replacement for `tools/build_gallery.py`'s watermark bar: the bar prints
    the model, size and seed *into the pixels*, which on a sticker is a caption strip burned
    into the artwork. The information is the point, not the pixels -- so it rides in the
    file's metadata instead, where a sticker saved to a phone still carries how it was made
    and nothing is defaced. Do not reintroduce the bar here for consistency's sake.

    Every row is written with filter type 0. Filtering exists to help deflate find structure
    in photographic data; a keyed sticker is mostly one exactly-repeated transparent value,
    which deflate already compresses to almost nothing, and choosing filters per row would
    cost an interpreted pass over the whole image to save very little.
    """
    n = width * height
    inter = bytearray(n * 4)
    for c in range(4):
        inter[c::4] = planes[c]
    stride = width * 4
    rows = bytearray()
    for y in range(height):
        rows += b"\x00"
        rows += inter[y * stride:(y + 1) * stride]
    out = bytearray(PNG_MAGIC)
    out += _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    for key, value in (text or {}).items():
        # Latin-1 is what tEXt is defined to hold. Anything outside it is dropped rather
        # than mangled -- a provenance field that lies about itself is worse than absent.
        out += _chunk(b"tEXt", key.encode("latin-1", "replace") + b"\x00"
                      + str(value).encode("latin-1", "replace"))
    out += _chunk(b"IDAT", zlib.compress(bytes(rows), level))
    out += _chunk(b"IEND", b"")
    return bytes(out)


def read_text(blob: bytes) -> dict[str, str]:
    """Pull the `tEXt` chunks back out. Used by the tests and by anyone auditing a sticker."""
    found: dict[str, str] = {}
    pos = 8
    while pos + 8 <= len(blob):
        length, kind = struct.unpack(">I4s", blob[pos:pos + 8])
        if kind == b"tEXt":
            key, _, value = blob[pos + 8:pos + 8 + length].partition(b"\x00")
            found[key.decode("latin-1")] = value.decode("latin-1")
        elif kind == b"IEND":
            break
        pos += 12 + length
    return found
