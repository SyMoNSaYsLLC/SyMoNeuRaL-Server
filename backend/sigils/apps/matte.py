"""Make the fourth channel. Standard library only.

The image engine returns three channels. A sticker needs four, and nothing in the render
path can produce the fourth: `symoneural-diffuse --help` on the built binary has `--mask` as an *input*
for inpainting and no alpha, RGBA or transparency output of any kind. So the subject is
drawn on a flat, saturated field that a sticker will never legitimately contain, and this
module keys that field out arithmetically.

Why a colour key rather than a segmentation model: a segmentation model is an ML runtime,
and the serving interpreter has deliberately never had one -- no torch, no ONNX. It would
also be a second GPU tenant on a card that already serialises chat against image. A sticker
is the easy case for a colour key besides: hard-edged, one subject, no hair, no glass, no
depth of field, which are exactly the cases that defeat keying.

Four things that are easy to leave out and are not optional:

1. **Holes.** A subject may legitimately contain the key colour -- an eye, a highlight, a
   gap between an arm and a body. Thresholding alone punches a hole straight through it.
   Only key-coloured regions **connected to the frame edge** are background. That is done
   here by run-length labelling each row and unioning runs that overlap the row above, which
   fills interior holes as a property of the algorithm rather than as a second pass.
2. **Despill.** Pixels at the subject's edge pick up the field colour, and it is invisible
   until the sticker lands on a white message bubble and wears a coloured halo. Despill runs
   in straight (non-premultiplied) colour, before alpha is attached.
3. **A feather, but a small one.** One or two pixels of ramp. A sticker's edge is supposed
   to be hard; a soft edge just looks like a bad cut-out.
4. **Saying when it failed.** `subject_fraction` and `degenerate` are returned and reported
   rather than being smoothed over. A keyed sticker that came out as a solid square is a PNG
   that decodes perfectly and is worthless, and no test that merely decodes it will notice.

Performance strategy, since this is interpreted python: everything that can be phrased as a
whole-plane operation is (`bytes.translate`, big-integer bitwise ops, slice assignment --
all C loops), and the interpreted work is confined to the run-length pass, which visits a
few thousand runs rather than a quarter of a million pixels, and to the edge band, which is
the subject's perimeter rather than its area.
"""
from __future__ import annotations

#: The fields the surface may ask for. Both are offered rather than one being assumed
#: correct: film uses green because it is far from skin and warm tones, but a sticker of a
#: frog or a leaf is a real request, and magenta is far from foliage while sitting close to
#: lips, tongues and anything pink. Neither wins on every subject.
#:
#: **These are what the prompt asks for, not what gets keyed.** See `sample_field`.
KEYS: dict[str, tuple[int, int, int]] = {
    "magenta": (0xFF, 0x00, 0xFF),
    "green": (0x00, 0xFF, 0x00),
}

#: How far a channel may sit from the key value and still count as field. Wide enough to
#: absorb the render's dithering across a flat area, narrow enough that a genuinely
#: magenta subject is not eaten.
TOLERANCE = 78

#: Alpha ramp, in sum-of-absolute-channel-distance from the key colour (0..765). At or
#: below `NEAR` a band pixel is field; at or above `FAR` it is subject; between, it ramps.
NEAR = 60
FAR = 200

#: How far the edge band reaches into the subject, in pixels. Despill and feather apply
#: here and nowhere else, which is what stops a magenta hat being desaturated.
BAND = 2

#: Pixels of subject thrown away at the boundary before anything else happens -- a
#: "choke", in the compositing sense.
#:
#: The outermost ring of the subject is not subject: it is subject and field mixed by the
#: renderer's own anti-aliasing, and no arithmetic can unmix it without knowing the mixing
#: fraction. Measured on a real render (2026-08-17): a sticker's white outline came back
#: (255, 215, 246) against a field of (244, 9, 107), which is white with roughly 15% of the
#: field in it, and it read as a pink halo the moment the sticker was put on a light
#: background. One pixel is the standard answer and costs a 512px sticker nothing visible;
#: more would start eating thin strokes.
CHOKE = 1


def _plane_and(planes: list[bytes], n: int) -> bytes:
    """Bitwise AND of several equal-length planes, without an interpreted loop."""
    acc = int.from_bytes(planes[0], "big")
    for p in planes[1:]:
        acc &= int.from_bytes(p, "big")
    return acc.to_bytes(n, "big")


def _table(centre: int, tol: int) -> bytes:
    return bytes(0xFF if abs(i - centre) <= tol else 0x00 for i in range(256))


def key_mask(planes: list[bytes], key: tuple[int, int, int], n: int,
             tol: int = TOLERANCE) -> bytes:
    """0xFF where the pixel is within `tol` of the key colour on every channel."""
    return _plane_and([planes[c].translate(_table(key[c], tol)) for c in range(3)], n)


def sample_field(planes: list[bytes], width: int, height: int) -> tuple[int, int, int]:
    """Measure the field colour off the render's own border instead of assuming it.

    **This is the correction that made the surface work at all, and it is a measurement,
    not a preference.** The prompt asks for a flat `#FF00FF` field. Rendered on this box on
    2026-08-17, the engine drew that field as **(248, 1, 96)** -- a hot pink, 159 counts
    away from the blue channel it was asked for -- consistently across every subject, and a
    key against the *requested* colour therefore matched nothing at all: sixteen renders
    came back with `transparent_fraction` 0.0. A diffusion model is suggestible, not
    obedient, and the field it actually paints is the field that has to be keyed.

    So: take the frame's four edges, bucket them coarsely, and average the most common
    bucket. The mode survives a subject that runs off the edge -- it only fails if the
    border has no dominant colour at all, which means the engine ignored the constraint,
    and that shows up honestly as `degenerate` rather than as a quietly bad cut.
    """
    r, g, b = planes[0], planes[1], planes[2]
    idx: list[int] = []
    idx.extend(range(0, width))                                  # top row
    idx.extend(range((height - 1) * width, height * width))      # bottom row
    for y in range(height):
        idx.append(y * width)                                    # left column
        idx.append(y * width + width - 1)                        # right column
    buckets: dict[tuple[int, int, int], list[int]] = {}
    for i in idx:
        bucket = (r[i] >> 4, g[i] >> 4, b[i] >> 4)
        acc = buckets.get(bucket)
        if acc is None:
            buckets[bucket] = [r[i], g[i], b[i], 1]
        else:
            acc[0] += r[i]
            acc[1] += g[i]
            acc[2] += b[i]
            acc[3] += 1
    best = max(buckets.values(), key=lambda acc: acc[3])
    count = best[3]
    return (best[0] // count, best[1] // count, best[2] // count)


def border_components(mask: bytes, width: int, height: int) -> bytearray:
    """Keep only the key-coloured regions that touch the frame edge.

    Run-length labelling with union-find. Each row is scanned for runs of key colour with
    `bytes.find`, which is a C scan, so the interpreted work is proportional to the number
    of runs -- a few per row on a sticker -- and not to the pixel count. Runs that overlap a
    run in the row above are unioned (4-connectivity); a run touching any frame edge marks
    its component as background.

    An enclosed region of key colour therefore never reaches the border and stays opaque,
    which is the hole-filling step, obtained for free rather than bolted on.
    """
    parent: list[int] = []
    edge: list[bool] = []

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
            edge[ra] = edge[ra] or edge[rb]

    rows: list[list[tuple[int, int, int]]] = []
    prev: list[tuple[int, int, int]] = []
    for y in range(height):
        row = mask[y * width:(y + 1) * width]
        cur: list[tuple[int, int, int]] = []
        i = 0
        while True:
            start = row.find(b"\xff", i)
            if start < 0:
                break
            stop = row.find(b"\x00", start)
            if stop < 0:
                stop = width
            label = len(parent)
            parent.append(label)
            edge.append(y == 0 or y == height - 1 or start == 0 or stop == width)
            for pstart, pstop, plabel in prev:
                if pstart < stop and start < pstop:
                    union(plabel, label)
                elif pstart >= stop:
                    break
            cur.append((start, stop, label))
            i = stop
        rows.append(cur)
        prev = cur

    background = bytearray(width * height)
    for y, cur in enumerate(rows):
        base = y * width
        for start, stop, label in cur:
            if edge[find(label)]:
                background[base + start:base + stop] = b"\xff" * (stop - start)
    return background


def channel_split(key: tuple[int, int, int]) -> tuple[list[int], list[int]]:
    """Which channels the field holds high, and which it holds low.

    Worked out from the colour that was actually painted rather than the one that was asked
    for, and against the field's own range rather than a fixed midpoint. That matters: the
    field measured (244, 9, 107) here, and against a midpoint of 128 the blue channel reads
    as *low* -- so a pink halo, which is exactly red and blue lifted together, would not be
    recognised as spill at all. Against 40% of the field's own span it reads as high, which
    it plainly is: 107 against a green channel of 9.
    """
    lo, hi = min(key), max(key)
    cut_at = lo + (hi - lo) * 0.4
    high = [c for c in range(3) if key[c] > cut_at]
    low = [c for c in range(3) if key[c] <= cut_at]
    return high, low


def _dilate(plane: bytes, width: int, n: int, steps: int) -> bytes:
    """Grow a 0x00/0xFF plane by `steps` pixels, four-connected.

    Done as big-integer shifts: one byte is one pixel, so a shift by 8 moves a column and a
    shift by `width * 8` moves a row. Wrapping at the row ends is accepted -- the band this
    produces is only used to choose which pixels get despilled, and two stray pixels at the
    far edge of a row cost nothing.
    """
    value = int.from_bytes(plane, "big")
    limit = (1 << (n * 8)) - 1
    rowbits = width * 8
    for _ in range(steps):
        value = (value | (value << 8) | (value >> 8)
                 | (value << rowbits) | (value >> rowbits)) & limit
    return value.to_bytes(n, "big")


def cut(width: int, height: int, planes: list[bytes], key_name: str = "magenta",
        field: tuple[int, int, int] | None = None) -> tuple[list[bytes], dict]:
    """Key `planes` (R, G, B) against the field colour and return (R, G, B, A) plus stats.

    `key_name` is what the *prompt* asked for and is carried through to the stats so a
    client can tell one run from another. `field` is what was actually painted; leave it
    `None` and it is measured off the border by `sample_field`, which is what any real
    render needs.
    """
    if key_name not in KEYS:
        raise ValueError(f"unknown key colour {key_name!r}")
    n = width * height
    if any(len(p) != n for p in planes[:3]):
        raise ValueError("plane size does not match the stated geometry")
    key = field if field is not None else sample_field(planes, width, height)

    mask = key_mask(planes, key, n)
    background = border_components(mask, width, height)
    limit = (1 << (n * 8)) - 1

    # Choke: the outermost ring of subject is mixed with the field and is discarded rather
    # than corrected. See CHOKE.
    if CHOKE:
        background = bytearray(_dilate(bytes(background), width, n, CHOKE))

    # Opaque everywhere the background component is not. Inverting a plane is one
    # complement on a big integer.
    alpha = bytearray((int.from_bytes(bytes(background), "big") ^ limit).to_bytes(n, "big"))

    red, green, blue = (bytearray(planes[0]), bytearray(planes[1]), bytearray(planes[2]))

    # The edge band: subject-side pixels within BAND of the field. Despill and feather touch
    # these and nothing else.
    grown = _dilate(bytes(background), width, n, BAND)
    band = (int.from_bytes(grown, "big") & ~int.from_bytes(bytes(background), "big")
            & limit).to_bytes(n, "big")

    high, low = channel_split(key)
    chans = (red, green, blue)
    kr, kg, kb = key

    banded = 0
    i = band.find(b"\xff")
    while i >= 0:
        banded += 1
        r, g, b = red[i], green[i], blue[i]
        dist = abs(r - kr) + abs(g - kg) + abs(b - kb)
        # --- despill, in straight colour, before alpha is attached -------------
        # The colour-difference measure: how far the *weakest* of the field's strong
        # channels sits above the strongest of its weak ones. It is self-limiting, which is
        # why it needs no scaling factor. A white outline tinted by a pink field trips it;
        # a subject that is merely warm does not, because a red-orange lifts one of the
        # field's strong channels and leaves the other where it was.
        #
        # An earlier version scaled this by distance from the field colour instead, and
        # that was measured wrong on a real render: the white outline is 356 counts from
        # the field, so the scaling switched the correction off at exactly the pixels
        # wearing the halo.
        if high and low:
            spill = min(chans[c][i] for c in high) - max(chans[c][i] for c in low)
            if spill > 0:
                for c in high:
                    chans[c][i] = max(0, chans[c][i] - spill)
                r, g, b = red[i], green[i], blue[i]
        # --- feather: ramp alpha by distance from the field colour -------------
        if dist <= NEAR:
            alpha[i] = 0
        elif dist < FAR:
            alpha[i] = ((dist - NEAR) * 255) // (FAR - NEAR)
        i = band.find(b"\xff", i + 1)

    opaque = alpha.count(255)
    stats = {
        "key": key_name,
        # What the engine actually painted, per render. Reported rather than assumed: the
        # gap between this and the requested colour is the single most useful diagnostic
        # this surface produces, and hiding it would hide the reason a cut went wrong.
        "field_rgb": list(key),
        "opaque_fraction": round(opaque / n, 4),
        "transparent_fraction": round((n - opaque) / n, 4),
        "edge_pixels": banded,
        # A sticker that is almost all subject means the key found nothing; one that is
        # almost all background means it ate the subject. Either way the number is
        # reported rather than hidden, because both failures produce a PNG that decodes.
        "degenerate": not (0.02 <= opaque / n <= 0.98),
    }
    return [bytes(red), bytes(green), bytes(blue), bytes(alpha)], stats
