"""Tests for the Sigils surface. Standard library `unittest`, no fixtures, no network.

    python3 -m unittest discover -s backend/sigils -t backend -v
    python3 backend/sigils/test_sigils.py

What is worth testing here is not "does it run" -- that is what the browser test and a real
render prove. It is the handful of properties that fail *silently*:

* a PNG decoder that gets one scanline filter wrong produces a picture that still decodes;
* a matte that punches holes through the subject produces a sticker that still decodes;
* a filename one character out of `/api/gen/{name}`'s regex 404s on every request;
* a bare `release` gives away a lock this surface does not hold, which has already cost
  this repo a running fine-tune;
* a `status()` that reports `ready` because the module imported is a decorative indicator,
  which is the one thing this site's rules forbid outright.

Every check here was confirmed to fail when the thing it guards was reverted -- the log of
that is in the task report, not in a comment, because a comment claiming a test works is
exactly the sort of assertion this project does not accept.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import re
import struct
import sys
import unittest
import zlib


from sigils.apps import matte, png
from sigils import sigils as routes
from sigils.lib import render

#: The exact regex `backend/server.py:1788` matches an attacker-controlled path segment
#: against before serving a render. Copied here rather than imported, because importing
#: `api` from a plug-in would invert the dependency -- but it is a contract, so if that
#: line changes this test is meant to fail.
GEN_RE = re.compile(r"gen-\d{13}-\d{1,10}\.png")


def encode_rgb(width: int, height: int, rows: list[bytes], ftype: int) -> bytes:
    """Build an RGB PNG using one specific scanline filter, so the decoder can be checked
    against every filter type rather than against whichever ones a sample file happens to
    use. Filter maths is RFC 2083 §6."""
    raw = bytearray()
    prev = bytes(width * 3)
    for row in rows:
        raw.append(ftype)
        if ftype == 0:
            raw += row
        elif ftype == 1:
            raw += bytes((row[i] - (row[i - 3] if i >= 3 else 0)) & 0xFF
                         for i in range(len(row)))
        elif ftype == 2:
            raw += bytes((row[i] - prev[i]) & 0xFF for i in range(len(row)))
        elif ftype == 3:
            raw += bytes((row[i] - (((row[i - 3] if i >= 3 else 0) + prev[i]) >> 1)) & 0xFF
                         for i in range(len(row)))
        elif ftype == 4:
            out = bytearray()
            for i in range(len(row)):
                a = row[i - 3] if i >= 3 else 0
                b = prev[i]
                c = prev[i - 3] if i >= 3 else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                out.append((row[i] - pred) & 0xFF)
            raw += out
        prev = row

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

    return (png.PNG_MAGIC
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw)))
            + chunk(b"IEND", b""))


def field_with_subject(width: int, height: int, key: tuple[int, int, int],
                       subject: tuple[int, int, int] = (20, 160, 90),
                       hole: bool = True) -> list[bytes]:
    """Three planes: a flat field, a rectangular subject, and optionally a patch of field
    colour *inside* the subject -- the case a plain threshold punches a hole through."""
    n = width * height
    planes = [bytearray(bytes([key[c]]) * n) for c in range(3)]
    for y in range(height // 4, 3 * height // 4):
        for x in range(width // 4, 3 * width // 4):
            for c in range(3):
                planes[c][y * width + x] = subject[c]
    if hole:
        for y in range(height // 2, height // 2 + 4):
            for x in range(width // 2, width // 2 + 4):
                for c in range(3):
                    planes[c][y * width + x] = key[c]
    return [bytes(p) for p in planes]


class TestPng(unittest.TestCase):
    def test_every_scanline_filter_decodes_identically(self) -> None:
        width, height = 9, 5
        rows = [b"".join(bytes(((x * 7 + y * 13) % 256, (x * 3) % 256, (y * 29) % 256))
                         for x in range(width)) for y in range(height)]
        want = None
        for ftype in range(5):
            w, h, planes = png.read(encode_rgb(width, height, rows, ftype))
            self.assertEqual((w, h), (width, height))
            if want is None:
                want = planes
                # and it really is the source image, not merely self-consistent
                self.assertEqual(bytes(planes[0][x] for x in range(width)),
                                 bytes(rows[0][c] for c in range(0, width * 3, 3)))
            self.assertEqual(planes, want, f"filter {ftype} decoded differently")

    def test_rgba_roundtrip_and_text_chunks(self) -> None:
        width, height = 6, 4
        planes = [bytes(range(width * height)), bytes([7]) * 24,
                  bytes([9]) * 24, bytes([255, 0] * 12)]
        blob = png.write_rgba(width, height, planes, {"Seed": "42", "Key": "magenta"})
        w, h, back = png.read(blob)
        self.assertEqual((w, h), (width, height))
        self.assertEqual(back, planes)
        self.assertEqual(png.read_text(blob), {"Seed": "42", "Key": "magenta"})

    def test_refuses_what_it_cannot_read(self) -> None:
        with self.assertRaises(png.PngError):
            png.read(b"not a png at all")


class TestMatte(unittest.TestCase):
    def test_field_goes_transparent_and_subject_stays(self) -> None:
        w = h = 32
        planes = field_with_subject(w, h, matte.KEYS["magenta"], hole=False)
        rgba, stats = matte.cut(w, h, planes, "magenta")
        alpha = rgba[3]
        self.assertEqual(alpha[0], 0, "the corner of the field is not transparent")
        self.assertEqual(alpha[(h // 2) * w + w // 2], 255, "the subject is not opaque")
        self.assertFalse(stats["degenerate"])
        self.assertGreater(stats["transparent_fraction"], 0.5)

    def test_key_colour_inside_the_subject_is_not_a_hole(self) -> None:
        """The whole reason for the connected-component pass. A threshold alone cuts here."""
        w = h = 32
        planes = field_with_subject(w, h, matte.KEYS["magenta"], hole=True)
        rgba, _ = matte.cut(w, h, planes, "magenta")
        self.assertEqual(rgba[3][(h // 2) * w + w // 2], 255,
                         "an enclosed patch of field colour was cut out of the subject")

    def test_both_key_colours_work(self) -> None:
        w = h = 24
        for name in ("magenta", "green"):
            planes = field_with_subject(w, h, matte.KEYS[name], subject=(200, 40, 40),
                                        hole=False)
            rgba, stats = matte.cut(w, h, planes, name)
            self.assertEqual(rgba[3][0], 0, name)
            self.assertEqual(rgba[3][(h // 2) * w + w // 2], 255, name)
            self.assertEqual(stats["key"], name)

    @staticmethod
    def _block(colour: tuple[int, int, int], w: int, h: int,
               span: range) -> list[bytes]:
        """A magenta field with one solid square of `colour` in it."""
        key = matte.KEYS["magenta"]
        planes = [bytearray(bytes([key[c]]) * (w * h)) for c in range(3)]
        for y in span:
            for x in span:
                for c in range(3):
                    planes[c][y * w + x] = colour[c]
        return [bytes(p) for p in planes]

    def test_despill_pulls_the_field_colour_out_of_the_edge(self) -> None:
        """A subject pixel near a magenta field picks the field up. On a white message
        bubble that reads as a coloured halo, so it is removed in straight colour.

        **This asserts on the first pixel that is actually visible, and that is the whole
        subtlety.** `CHOKE = 1` discards the outermost ring of subject rather than
        correcting it, because that ring is a blend of subject and field and no arithmetic
        recovers what was mixed. So the literal corner of the block is left at its input
        colour *and given alpha 0* -- untouched RGB under a transparent alpha cannot show a
        halo, so there is nothing there to fix. The despill applies one pixel further in,
        which is where the first pixel a viewer can see lives.

        An earlier revision of this test asserted on the choked corner and read as an
        off-by-one in the despill threshold (`230 not less than 230`). It was not: the
        despill was never reached for that pixel by design. Measured on this input, the
        first opaque pixel goes 230 -> 105 on red, which is the full correction. The fix
        was to assert on the pixel that can carry a halo, not to move the threshold.

        The opaque index is derived from `CHOKE` rather than written as a literal `5`, so
        the next change to the choke depth moves this test with the code instead of turning
        it red on a pixel that has become background.
        """
        w = h = 16
        # Heavy magenta spill: red and blue lifted together, close enough to the field to be
        # plainly contamination, far enough from it on green not to be keyed out as field.
        planes = self._block((230, 100, 225), w, h, range(4, 12))
        rgba, _ = matte.cut(w, h, planes, "magenta")

        choked = 4 * w + 4                 # the outermost ring: discarded, not corrected
        self.assertEqual(rgba[3][choked], 0,
                         "the choked ring must be transparent -- that is why its RGB stands")

        edge = 4 + matte.CHOKE             # the first opaque pixel, inside the edge band
        i = edge * w + edge
        self.assertGreater(rgba[3][i], 0, "this pixel must be visible for the test to mean anything")
        self.assertLess(rgba[0][i], 230, "red was not despilled at the edge")
        self.assertLess(rgba[2][i], 225, "blue was not despilled at the edge")
        self.assertEqual(rgba[1][i], 100, "the non-key channel must not be touched")

    def test_a_merely_warm_subject_is_not_despilled(self) -> None:
        """The case an unscaled despill ruins, and it gets its own render deliberately.

        A red-orange lifts *one* of the field's strong channels and leaves the other where
        it was, so the colour-difference measure comes out negative and the correction never
        fires. Asserted on its own image rather than as a second block in the spill test,
        because in one image the warm block sat entirely inside the choked ring: it was
        transparent, its RGB was untouched for that reason rather than for the right one,
        and the assertion passed while testing nothing.

        Verified by deleting the `if spill > 0:` guard in `matte.cut`: this pixel then moves
        to (220, 90, 90), so it is genuinely inside the band and the assertion is not passing
        by sitting somewhere the correction never reaches.
        """
        w = h = 16
        planes = self._block((190, 90, 60), w, h, range(4, 12))
        rgba, _ = matte.cut(w, h, planes, "magenta")
        edge = 4 + matte.CHOKE
        i = edge * w + edge
        self.assertGreater(rgba[3][i], 0, "this pixel must be visible for the test to mean anything")
        self.assertEqual((rgba[0][i], rgba[1][i], rgba[2][i]), (190, 90, 60),
                         "a warm subject colour was desaturated as if it were spill")

    def test_a_solid_field_is_reported_degenerate(self) -> None:
        """The failure that decodes perfectly: nothing but background. It must be visible in
        the response, not smoothed over."""
        w = h = 16
        planes = [bytes([c]) * (w * h) for c in matte.KEYS["magenta"]]
        _, stats = matte.cut(w, h, planes, "magenta")
        self.assertTrue(stats["degenerate"])
        self.assertEqual(stats["opaque_fraction"], 0.0)

    def test_geometry_must_match(self) -> None:
        with self.assertRaises(ValueError):
            matte.cut(8, 8, [b"\x00" * 10] * 3, "magenta")
        with self.assertRaises(ValueError):
            matte.cut(2, 2, [b"\x00" * 4] * 3, "chartreuse")


class TestGovernor(unittest.TestCase):
    def test_release_always_names_the_surface(self) -> None:
        self.assertEqual(render.release_argv()[-2:], ["release", render.SURFACE])

    def test_no_bare_release_anywhere_in_the_package(self) -> None:
        """`release` with no surface name is the call that destroyed a fine-tune's lock."""
        here = pathlib.Path(render.__file__).parent
        for path in sorted(here.glob("*.py")):
            if path.name.startswith("test_"):
                continue
            text = path.read_text()
            for hit in re.finditer(r'"release"', text):
                tail = text[hit.end():hit.end() + 40]
                self.assertRegex(tail, r"SURFACE|surface",
                                 f"{path.name} may issue an unnamed release")

    def test_acquire_names_the_surface_and_carries_a_timeout(self) -> None:
        argv = render.acquire_argv(42)
        self.assertEqual(argv[1:], ["acquire", render.SURFACE, "42"])

    def test_the_engine_is_not_run_through_the_with_wrapper(self) -> None:
        """Measured 2026-08-17: `gpu-governor.sh with sigil -- <path>/symoneural-diffuse` is SIGTERMed
        by its own eviction, because `evict()`'s image arm is `pkill -f 'bin/symoneural-diffuse'` and
        `pkill -f` matches the wrapper's own command line. The engine argv must therefore
        never be handed to the `with` form."""
        source = pathlib.Path(render.__file__).read_text()
        code = source.split('"""', 2)[-1]          # skip the module docstring
        self.assertNotIn('"with"', code)

    def test_engine_argv_keeps_the_image_surface_flags(self) -> None:
        argv = render.build_argv("a raven", pathlib.Path("/tmp/x.png"), 7, 4, 512)
        for flag in ("--cfg-scale", "--sampling-method", "--backend", "--vae-tiling",
                     "--diffusion-fa"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--backend") + 1], "te=cpu")
        self.assertEqual(argv[argv.index("-W") + 1], "512")
        self.assertEqual(argv[argv.index("--seed") + 1], "7")

    def test_release_happens_even_when_the_engine_fails(self) -> None:
        calls: list[list[str]] = []

        async def fake(argv, timeout, env=None):
            calls.append(list(argv))
            if "acquire" in argv:
                return 0, b""
            if "release" in argv:
                return 0, b""
            return 1, b"engine exploded"

        original = render._spawn
        render._spawn = fake
        try:
            rc, err, _wait, _took = asyncio.run(render.run(["/nonexistent/engine"]))
        finally:
            render._spawn = original
        self.assertEqual(rc, 1)
        self.assertIn(b"exploded", err)
        self.assertIn("acquire", calls[0])
        self.assertEqual(calls[-1][-2:], ["release", render.SURFACE])

    def test_a_lost_acquire_is_reported_and_not_rendered_through(self) -> None:
        async def fake(argv, timeout, env=None):
            if "acquire" in argv:
                return 1, b"TIMED OUT behind 'train'"
            raise AssertionError("the engine ran without the card")

        original = render._spawn
        render._spawn = fake
        try:
            with self.assertRaises(render.Busy):
                asyncio.run(render.run(["/nonexistent/engine"]))
        finally:
            render._spawn = original


class TestSurface(unittest.TestCase):
    UNIT_KEYS = {"id", "label", "slot", "state", "bus", "href", "spec", "detail"}

    def test_status_has_exactly_the_unit_fields(self) -> None:
        self.assertEqual(set(routes.status()), self.UNIT_KEYS)

    def test_status_is_offline_without_the_engine(self) -> None:
        """Never `ready` on the strength of the module importing."""
        original = render.DIFFUSE_ENGINE
        render.DIFFUSE_ENGINE = pathlib.Path("/nonexistent/symoneural-diffuse")
        try:
            unit = routes.status()
        finally:
            render.DIFFUSE_ENGINE = original
        self.assertEqual(unit["state"], "offline")
        self.assertIn("not installed", unit["detail"])

    def test_the_page_and_the_bus_are_real(self) -> None:
        unit = routes.status()
        self.assertEqual(unit["bus"], "gpu")
        self.assertEqual(unit["href"], "/sigils.html")
        self.assertEqual(unit["label"], "SyMoNeuRaL Sigils")

    def test_no_upstream_model_names_reach_the_surface(self) -> None:
        """Branding: the site uses SyMoNeuRaL product names. The upstream identities are a
        licence matter for LICENSES.md, not page or API copy."""
        blob = " ".join([str(routes.status()), render.MODEL_NAME, render.SUFFIX,
                         str(routes.PACKS)]).lower()
        for banned in ("flux", "qwen", "qlora", "stable diffusion", "schnell"):
            self.assertNotIn(banned, blob)

    def test_the_prompt_gate_is_unset(self) -> None:
        """No content policy ships in this package. The operator sets those himself."""
        self.assertIsNone(routes.PROMPT_GATE)

    def test_the_suffix_names_the_field_colour(self) -> None:
        for name, hexcode in render.KEY_HEX.items():
            composed = render.compose("a raven", name)
            self.assertIn(f"#{hexcode}", composed)
            self.assertTrue(composed.startswith("a raven,"))

    def test_delivered_filename_matches_the_route_that_serves_it(self) -> None:
        name = render.output_name(1786975636925, 1867341583)
        self.assertRegex(name, GEN_RE)
        # ...and the intermediate deliberately does not: it is the subject still sitting on
        # its field colour, and it must not be fetchable even by guessing.
        self.assertNotRegex(render.raw_name(1786975636925, 1867341583), GEN_RE)

    def test_a_whole_sticker_end_to_end_without_a_gpu(self) -> None:
        """Drive the route with the engine replaced by a synthetic render. Asserts the two
        things a decode-only check would pass anyway: the PNG carries real transparency, and
        the raw field render does not survive on disk."""
        w = h = 256
        planes = field_with_subject(w, h, matte.KEYS["magenta"])
        blob = encode_rgb(w, h, [b"".join(bytes((planes[0][y * w + x], planes[1][y * w + x],
                                                 planes[2][y * w + x]))
                                          for x in range(w)) for y in range(h)], 0)
        written: dict[str, pathlib.Path] = {}

        async def fake(argv, timeout, env=None):
            if "acquire" in argv or "release" in argv:
                return 0, b""
            out = pathlib.Path(argv[argv.index("-o") + 1])
            out.write_bytes(blob)
            written["raw"] = out
            return 0, b""

        original_spawn, original_present = render._spawn, render.weights_present
        render._spawn = fake
        render.weights_present = lambda: True
        try:
            doc = asyncio.run(routes.make(routes.SigilRequest(
                prompt="a raven perched", seed=99, size=256)))
        finally:
            render._spawn, render.weights_present = original_spawn, original_present
            (render.RENDERS / doc["url"].rsplit("/", 1)[-1]).unlink(missing_ok=True)

        self.assertEqual(doc["schema"], "sigil/result/v1")
        self.assertRegex(doc["url"], r"^/api/gen/" + GEN_RE.pattern + "$")
        self.assertGreater(doc["transparent_fraction"], 0.0)
        self.assertFalse(doc["degenerate"])
        self.assertIn("ephemeral", doc["note"])
        self.assertFalse(written["raw"].exists(),
                         "the raw field render was left on disk")


class TestMountedAndMetered(unittest.TestCase):
    """`backend/server.py` is read as source, not imported.

    Importing the serving module from inside a plug-in inverts the dependency -- api.py
    imports this package -- and would also execute the whole app at test time. Both of the
    facts asserted here are single lines in that file, and both have already been wrong.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.api_py = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file()) / "api.py"
        cls.tree = ast.parse(cls.api_py.read_text())

    def _include_call(self) -> ast.Call:
        """The `app.include_router(sigils.router, ...)` call node, or fail saying so."""
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "include_router"):
                continue
            first = node.args[0]
            if (isinstance(first, ast.Attribute) and first.attr == "router"
                    and isinstance(first.value, ast.Name) and first.value.id == "sigils"):
                return node
        self.fail(f"{self.api_py} never calls include_router on the sigils router")

    def test_the_surface_is_mounted(self):
        """The defect this whole surface shipped with.

        `site/sigils.html` was live and reachable while api.py contained no occurrence of
        the string 'sigil' anywhere in it, so every route the page called answered 404. The
        page looked finished; nothing behind it was connected.
        """
        self.assertIn("sigils", self.api_py.read_text(),
                      "api.py does not mention the sigils app at all")
        self._include_call()

    def test_the_rate_lane_is_actually_spent_from(self):
        """Listing a surface in _RATE_SUGGESTED builds its buckets. It does not spend them.

        Half of this was already true and was worse than being openly unmetered: with the
        name listed but no dependency wired, `SYMONEURAL_RATE_SIGIL=20/300` would be read, parsed,
        validated and turned into two live RateLimiter objects that nothing ever consulted
        -- so an operator who set it would believe a cap was in force when none was. This
        is the surface that spends the GPU and the one aimed at a phone app, so an
        imaginary limit is exactly the wrong thing to have.
        """
        src = self.api_py.read_text()
        self.assertIn('"sigil"', src, "no sigil lane in _RATE_SUGGESTED")

        call = self._include_call()
        deps = [kw for kw in call.keywords if kw.arg == "dependencies"]
        self.assertTrue(
            deps, "the sigils router is mounted with no dependencies= at all, so the "
                  "sigil rate lane is built and never consulted")
        # Depends(throttled_for("sigil")) -- assert on the surface name too, because
        # throttling this router against someone else's budget would still parse.
        wired = ast.dump(deps[0].value)
        self.assertIn("throttled_for", wired, f"dependencies= does not throttle: {wired}")
        self.assertIn("'sigil'", wired,
                      f"dependencies= throttles against the wrong surface: {wired}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
