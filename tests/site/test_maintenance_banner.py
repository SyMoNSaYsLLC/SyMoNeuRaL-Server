"""The maintenance banner appears where it was asked for, and nowhere near the customer.

Task #107. Garrett, 2026-08-26: *"Maintenance banner would be great for the symoneural
portion and we will be 100% powering dispatch through symoneural domain"*.

**The failure worth catching is not a missing banner, it is a leaked one.** Dispatch is
served from the same origin as the rest of symoneural.com, so the page Donnie is about to be
emailed is one bad path match away from telling him the thing he is being sold is down. That
is what `test_dispatch_never_carries_the_banner` and `test_dispatch_page_does_not_load_ui_js`
are for, and they are the two that matter.

**The second failure is a banner over something that works.** This project's standing rule is
that every LED and gauge reflects a real reading, and a banner is a much larger claim than an
LED. A surface that answers correctly and is labelled down is as false as a dead one labelled
ready -- so `test_no_ready_surface_is_labelled_down` fails if a page that reads `ready` on the
rack ever appears on the list. It uses a recorded reading rather than calling the live API:
this suite must pass with the network down and with the API stopped, and a test that silently
turns into a no-op when a fetch fails is worse than no test. The reading it compares against
is the one `docs/ops/MAINTENANCE-SURFACES.md` was written from, and refreshing it is a
deliberate edit in both places.

**One list, two files, asserted equal.** The list lives in `site/ui.js` because that is what
the browser executes, and in `docs/ops/MAINTENANCE-SURFACES.md` because that is where the
reason for each entry is written down. `test_list_matches_the_document` is what stops those
two from drifting -- which they would, because taking a surface off maintenance is exactly the
moment somebody edits one file and considers the job done.
"""
from __future__ import annotations

import pathlib
import re
import unittest

REPO = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
UI_JS = REPO / "site" / "ui.js"
DOC = REPO / "docs" / "ops" / "MAINTENANCE-SURFACES.md"
SITE = REPO / "site"

#: The rack reading `docs/ops/MAINTENANCE-SURFACES.md` was written from, read from
#: `GET /api/status` at 08:23 EDT on 2026-08-26 and pasted here rather than fetched. Frozen on
#: purpose: see the module docstring. `train` is the rack's id for Reinforce.
RACK_AT_2026_08_26 = {
    "chat": "offline", "image": "offline", "remix": "offline", "ravencalc": "ready",
    "train": "offline", "miner": "offline", "streamer": "ready", "coder": "ready",
    "project": "ready", "sigils": "offline", "studio": "offline", "exp": "queued",
    "live": "ready",
}

#: Which page each rack unit is reached at. Only units with a page can be on the list at all.
UNIT_PAGE = {
    "chat": "/chat.html", "image": "/image.html", "remix": "/remix.html",
    "ravencalc": "/ravencalc.html", "train": "/reinforce.html", "miner": "/miner.html",
    "streamer": "/streamer.html", "coder": "/coder.html", "project": "/project.html",
    "sigils": "/sigils.html", "studio": "/studio.html", "exp": "/exp.html",
    "live": "/live.html",
}

DISPATCH_PATHS = {"/demo/dispatchos", "/share-dispatchos.html"}


def ui_js_list() -> list[str]:
    """The DOWN array out of `site/ui.js`, parsed rather than grepped.

    Parsed because a substring search over a 400-line file cannot tell an entry in the array
    from the same path mentioned in a comment three lines above it -- and this file's comments
    name several of these paths while explaining why they are or are not listed.
    """
    src = UI_JS.read_text(encoding="utf-8")
    m = re.search(r"var\s+DOWN\s*=\s*\[(.*?)\]", src, re.S)
    assert m, "site/ui.js no longer declares a DOWN array; the banner block was removed or renamed"
    return re.findall(r"'([^']+)'", m.group(1))


def doc_list() -> list[str]:
    """The paths in the document's table, taken from the first column of `| `/x` |` rows."""
    rows = re.findall(r"^\|\s*`(/[^`]*)`\s*\|", DOC.read_text(encoding="utf-8"), re.M)
    assert rows, "docs/ops/MAINTENANCE-SURFACES.md has no table rows to read"
    return rows


class MaintenanceBannerTests(unittest.TestCase):

    def test_banner_exists(self):
        src = UI_JS.read_text(encoding="utf-8")
        self.assertIn("maintenance", src.lower())
        # The class is assigned as a property, not written into markup, so this asserts on
        # the assignment. `.maint` is what the stylesheet the block injects actually targets,
        # so losing the class is losing the styling while the element still appears.
        self.assertRegex(src, r"className\s*=\s*['\"]maint['\"]",
                         "the banner element lost its class; the stylesheet it writes targets .maint")
        self.assertIn(".maint{", src,
                      "the banner no longer injects its own stylesheet")
        self.assertTrue(ui_js_list(), "the DOWN list is empty -- the banner shows nowhere")

    def test_list_matches_the_document(self):
        """Every listed path is documented, and every documented path is listed.

        Compared as sets of the extensionless form, because the site answers on both spellings
        and `ui.js` lists both while the document names one per row.
        """
        def bare(p: str) -> str:
            return p[:-5] if p.endswith(".html") else p

        in_js = {bare(p) for p in ui_js_list()}
        in_doc = {bare(p) for p in doc_list()}
        self.assertEqual(
            in_js, in_doc,
            "site/ui.js and docs/ops/MAINTENANCE-SURFACES.md disagree about which surfaces "
            "are down. Only in ui.js: %s. Only in the document: %s."
            % (sorted(in_js - in_doc), sorted(in_doc - in_js)))

    def test_no_ready_surface_is_labelled_down(self):
        listed = set(ui_js_list())
        for unit, state in RACK_AT_2026_08_26.items():
            if state != "ready":
                continue
            page = UNIT_PAGE[unit]
            self.assertNotIn(
                page, listed,
                f"{page} is on the maintenance list, but the rack reads {unit}=ready. A "
                f"surface that works and is labelled down is as false as a dead one labelled "
                f"ready. Re-read /api/status and update the document if this has changed.")

    def test_dispatch_never_carries_the_banner(self):
        listed = set(ui_js_list())
        for path in DISPATCH_PATHS:
            self.assertNotIn(
                path, listed,
                f"{path} is on the maintenance list. That is the customer surface; Donnie is "
                f"being sent that URL.")

    def test_dispatch_page_does_not_load_ui_js(self):
        """Structural safety, not just absence from a list.

        The preview page carries no `ui.js`, so the banner cannot reach it even if somebody
        adds its path to DOWN by accident. That is a property worth holding on to rather than
        rediscovering, so it is asserted -- it stays true only until someone adds a script tag.
        """
        preview = SITE / "share-dispatchos.html"
        self.assertTrue(preview.is_file(), "the customer preview page has gone missing")
        self.assertNotIn("ui.js", preview.read_text(encoding="utf-8"),
                         "share-dispatchos.html now loads ui.js, so the maintenance banner can "
                         "reach the customer preview. Either remove the script tag or make the "
                         "banner opt-in.")

    def test_every_listed_page_exists(self):
        """A banner aimed at a page that is not there protects nobody and hides a typo."""
        for path in ui_js_list():
            if not path.endswith(".html"):
                continue                      # routed names like /livestack have no file
            self.assertTrue((SITE / path.lstrip("/")).is_file(),
                            f"{path} is on the maintenance list but site{path} does not exist")


if __name__ == "__main__":
    unittest.main()
