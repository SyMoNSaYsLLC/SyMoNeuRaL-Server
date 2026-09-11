"""The type scale in frontend/site/css/symoneural.css is enforceable, so enforce it.

frontend/site/css/symoneural.css carries a comment saying "EVERY font-size in this file references one
of these seven. Adding an eighth here, or writing a raw px size anywhere below, defeats
the point: the scale is meant to be enforceable, and it is checked by re-running the type
audit and counting the distinct sizes the DOM reports."

Re-running a browser type audit is a manual act that happens when someone remembers. This
parses the file instead, so the constraint holds on every commit rather than on every
review. It exists because the commit that added the depth-and-motion layer at the tail of
that file was working from a reference design whose display type is much larger than ours,
and reaching for a raw `font-size:56px` there is the single most likely way the scale gets
broken.

It also pins the specific invalid form that already bit this file once: twelve
declarations were written `font:600 12.5px/1 inherit`, and `inherit` is a CSS-wide keyword
rather than a font-family, so the entire shorthand was dropped and those elements silently
rendered at the UA's default control size. Any `font:` shorthand whose size part is not a
scale token now fails here.

Stdlib only, on purpose -- backend/ tests are collected by the main pytest run.
"""

import pathlib
import re

import pytest

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
CSS = ROOT / "frontend" / "site" / "css" / "symoneural.css"

# `var(--t3)`, optionally `!important`.
TOKEN = re.compile(r"^var\(--t[1-7]\)(\s*!important)?$")
# `clamp(var(--t3),3.4vw,var(--t1))` -- a fluid size is still expressed in scale tokens at
# both ends, which is what keeps the rendered range inside the scale.
CLAMP = re.compile(
    r"^clamp\(\s*var\(--t[1-7]\)\s*,[^,]+,\s*var\(--t[1-7]\)\s*\)(\s*!important)?$"
)


def _source():
    """The file with comments removed.

    Required, not cosmetic: the comments in this file quote font sizes as prose --
    `14.5px` and `Npx` both appear inside them -- so a scan of the raw text reports
    offenders that do not exist.
    """
    return re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)


def _ok(size: str) -> bool:
    size = size.strip()
    return bool(TOKEN.match(size) or CLAMP.match(size))


def test_the_scale_has_exactly_seven_steps():
    defined = sorted(set(re.findall(r"(--t[1-7])\s*:", _source())))
    assert defined == [f"--t{n}" for n in range(1, 8)]
    assert not re.search(r"--t[089]\s*:", _source()), "an eighth step was added to the scale"


def test_every_font_size_declaration_uses_a_scale_token():
    offenders = [v for v in re.findall(r"font-size\s*:([^;}]*)", _source()) if not _ok(v)]
    assert offenders == [], f"font-size values outside the scale: {offenders}"


def test_every_font_shorthand_sizes_itself_from_the_scale():
    # `font:inherit` is the whole shorthand as a CSS-wide keyword and is legal. It is the
    # only form without a size part.
    offenders = []
    for raw in re.findall(r"(?<![-\w])font\s*:([^;}]*)", _source()):
        value = raw.strip()
        if value in ("inherit", "initial", "unset", "revert"):
            continue
        # Strip an optional leading weight/style/variant run, then take the size, which
        # ends at the line-height slash or at the space before the family list.
        # `clamp\((?:[^()]|\([^()]*\))*\)` matches one level of nesting, which is what a
        # `clamp(var(--t6),1.02vw,var(--t4))` size part needs -- three nested var() calls
        # inside the clamp. A plain `[^)]*` stops at the first inner `)` and reports every
        # fluid shorthand in this file as an offender.
        m = re.match(
            r"^(?:[\w-]+\s+)*?(var\(--t[1-7]\)|clamp\((?:[^()]|\([^()]*\))*\))", value
        )
        if not m or not _ok(m.group(1)):
            offenders.append(value)
    assert offenders == [], f"font: shorthands not sized from the scale: {offenders}"


def test_no_font_shorthand_names_inherit_as_the_family():
    # The bug this file records: `font:600 12.5px/1 inherit` parses as invalid and is
    # dropped wholesale, which is why it went unnoticed.
    bad = [
        v.strip()
        for v in re.findall(r"(?<![-\w])font\s*:([^;}]*)", _source())
        if v.strip() != "inherit" and re.search(r"(^|[\s/])inherit\s*$", v)
    ]
    assert bad == [], f"`inherit` used as the font-family inside a shorthand: {bad}"


def test_no_raw_pixel_font_sizes_anywhere():
    raw = re.findall(r"font(?:-size)?\s*:[^;}]*?\b\d+(?:\.\d+)?px", _source())
    assert raw == [], f"raw px font sizes: {raw}"


@pytest.mark.parametrize(
    "token",
    ["--sf1", "--sfline", "--glass-blur", "--r-pill", "--ease", "--lift", "--el2", "--glow"],
)
def test_the_depth_layer_tokens_are_defined(token):
    # The depth layer's rules reference these; an undefined custom property does not error,
    # it silently drops the declaration that uses it, which is a look-and-feel regression
    # with no symptom at build time.
    assert re.search(re.escape(token) + r"\s*:", _source()), f"{token} is not defined"


def _reduced_motion_spans(src: str) -> list[tuple[int, int]]:
    """The [start, end) character ranges of every prefers-reduced-motion:no-preference block.

    Brace-matched rather than counted. The version of the guard below that this replaces
    asked whether the string "prefers-reduced-motion:no-preference" appeared ANYWHERE
    earlier in the file than the `animation:` declaration -- which two such blocks already
    do, near line 2930. So the check passed for every animation added after them whether it
    was guarded or not, and it would have passed for the news ticker's crawl, which is the
    one animation on this site that runs forever and is therefore the one that most needs
    the preference honoured. A test that cannot fail is not protecting anything.
    """
    spans, at = [], 0
    needle = "@media (prefers-reduced-motion:no-preference)"
    while True:
        i = src.find(needle, at)
        if i < 0:
            return spans
        open_brace = src.index("{", i)
        depth, j = 0, open_brace
        while j < len(src):
            if src[j] == "{":
                depth += 1
            elif src[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        spans.append((i, j))
        at = j


def test_every_added_animation_has_a_reduced_motion_path():
    src = _source()
    # `reveal` and `ring` are the two keyframes the depth layer added; `symonticker` is the
    # news bar's crawl. All three must be applied only from INSIDE a
    # prefers-reduced-motion:no-preference block, so a reader who has asked for less motion
    # gets the finished state and no animation at all. `symonticker` is the one that matters
    # most: a headline bar that slides text sideways forever is precisely what that
    # preference is set to stop, and the reduce branch turns the window into a scrollable
    # strip so no headline is lost along with the motion.
    spans = _reduced_motion_spans(src)
    assert spans, "no prefers-reduced-motion:no-preference block in the file at all"
    for name in ("reveal", "ring", "symonticker"):
        assert f"@keyframes {name}" in src, f"@keyframes {name} went missing"
        uses = list(re.finditer(r"animation\s*:[^;}]*\b" + name + r"\b[^;}]*", src))
        assert uses, f"@keyframes {name} is defined but never applied"
        for use in uses:
            inside = any(a < use.start() < b for a, b in spans)
            assert inside, f"`{use.group(0).strip()}` is not inside a reduced-motion guard"


def test_the_news_bar_is_namespaced_under_its_own_id():
    """Every `.sn-*` rule is scoped to `#symonsaynews`, and its two tokens exist.

    Not ceremony. This file has lost a bare class name to a later redefinition five times
    (`.bar` collapsed the site header to 7px, `.live` was a nav badge, `#console .sub`,
    `.cards .card`), and a news ticker brings in exactly the names most likely to collide:
    a lane, a run, an item, a head. So the invariant is structural rather than a review
    habit -- every selector in the ticker block either names the id or starts at `html`
    (the two layout-mode switches, which are on the root element by definition).

    The token check is the same argument as the depth-layer one above: an undefined custom
    property silently drops the declaration that uses it, so `--sn-h` going missing would
    give the bar a content height, let it cover the footer, and produce no build error.
    """
    # `_source()` strips comments, so the block is found by its first RULE rather than by
    # its banner -- the banner is a comment and is not in the string being scanned.
    src = _source()
    block = src[src.index("#symonsaynews"):]
    for token in ("--sn-h", "--sn-gap"):
        # Against the whole file: the tokens are declared on `:root` with the rest of the
        # site's tokens, which is ABOVE the first ticker rule and so outside `block`.
        assert re.search(re.escape(token) + r"\s*:", src), f"{token} is not defined"
    # Selectors are the text before each `{` that is not a declaration block or an at-rule.
    for sel in re.findall(r"(?m)^\s*([^@{}/\s][^{}]*?)\s*\{", block):
        sel = " ".join(sel.split())
        if ".sn-" not in sel:
            continue
        assert "#symonsaynews" in sel or sel.startswith("html"), \
            f"`{sel}` uses a bare sn- class outside the #symonsaynews namespace"


def test_the_news_bar_never_truncates_a_headline():
    """No `text-overflow` in the ticker block.

    CLAUDE.md: "Never use `text-overflow: ellipsis`... A truncated claim is a broken claim."
    A crawl has no excuse for it either -- the bar has infinite horizontal room by
    construction, so a long headline costs seconds, not pixels.
    """
    src = _source()
    block = src[src.index("#symonsaynews"):]
    assert "text-overflow" not in block
