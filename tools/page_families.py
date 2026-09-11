"""The page family of every public page. ONE authored source.

A page's family decides how much width its layout is given: `--max` is 1120px for prose and
wider for a dashboard, a workspace or a workbench. Handshake 6.1 established the families by
measurement and set them from `site/shell.js`; 6.2 moves the authority into static markup so
the layout does not depend on JavaScript having run.

## Why this is a module and not a map in each place that needs one

The families were about to exist in four places at once -- the generators that emit the
markup, the hand-authored pages that carry it, `site/shell.js`, and the test that checks it.
Four hand-maintained copies of one fact is the failure `backend/ROSTER.md` was written
about, arriving in the frontend.

So: this file is the authored source. The generators IMPORT it and emit `data-family` from it.
`site/shell.js` no longer carries a map at all -- it reads the static attribute and only
supplies a fallback when one is genuinely absent. The test READS this map and verifies the
rendered pages agree with it, rather than restating the pairs a second time.

It is a module and not JSON so the reasoning below travels with the data.

## The four families, and why prose is not one of them

    workbench   an input, its settings, and an output canvas      image, remix, sigils
    workspace   a persistent surface you work inside              chat, coder, ravencalc, ...
    dashboard   many readings compared at a glance                the section pages, miner, ...
    docs        a documentation surface                           documentation.html

A page with no entry here gets NO `data-family` and keeps the 1120px prose width. That is
deliberate and is the substance of the rule rather than an omission: `index`, `account`,
`credits` and `build` are things to read, and a 1,700px line of prose is harder to read, not
easier. A map whose default was "wider" would have widened them by forgetting them.

`streamer-watch.html` is also deliberately absent: it has no site header at all, which is why
`site/shell.js` returns early on it.
"""

from __future__ import annotations

#: page filename (as written into `site/`) -> family. The keys are FILENAMES, not routes,
#: because that is what a generator knows about the file it is writing. `site/shell.js` maps
#: routes to the same families for the pages that also answer at an extensionless address.
FAMILIES: dict[str, str] = {
    # ---- workbench: input, settings, output canvas ------------------------------------
    "image.html": "workbench",
    "remix.html": "workbench",
    "sigils.html": "workbench",
    # ---- workspace: a surface you work inside ------------------------------------------
    "chat.html": "workspace",
    "coder.html": "workspace",
    "ravencalc.html": "workspace",
    "project.html": "workspace",
    "studio.html": "workspace",
    "exp.html": "workspace",
    "reinforce.html": "workspace",
    "live.html": "workspace",
    "streamer.html": "workspace",
    # ---- dashboard: many readings at once ----------------------------------------------
    "miner.html": "dashboard",
    "gateway.html": "dashboard",
    "overview.html": "dashboard",
    "livestack.html": "dashboard",
    "controlboard.html": "dashboard",
    "receipts.html": "dashboard",
    # ---- documentation -----------------------------------------------------------------
    "documentation.html": "docs",
}

#: Pages that deliberately carry NO family, with the reason. Named explicitly rather than left
#: to omission, so a page missing from both dicts is an unclassified page and fails a test
#: instead of silently taking the prose default.
NO_FAMILY: dict[str, str] = {
    "index.html": "the front page is prose and a launcher; bounded measure is correct",
    "account.html": "prose",
    "credits.html": "prose; long attribution lists read better at a bounded measure",
    "build.html": "prose",
    "training.html": "the manual; already carries its own <main> and is not a shell page",
    "streamer-watch.html": "no site header at all; site/shell.js returns early on it",
    "share-dispatchos.html": "no site header; served behind the door",
}


def family_of(filename: str) -> str | None:
    """The family for a page filename, or None when it deliberately has none.

    Raises on a filename in neither dict. That is the point: a new page must be classified,
    and an unclassified one is the ambiguity this module exists to remove.
    """
    if filename in FAMILIES:
        return FAMILIES[filename]
    if filename in NO_FAMILY:
        return None
    raise KeyError(
        f"{filename} is in neither FAMILIES nor NO_FAMILY in tools/page_families.py. "
        "Classify it: a page with no family silently keeps the 1120px prose width, which "
        "is right for prose and wrong for a workspace.")


def attribute(filename: str) -> str:
    """The `data-family` attribute text for a page, or an empty string when it has none.

    Returned with a leading space so it can be concatenated straight into `<html lang="en">`
    without the caller having to think about spacing.
    """
    fam = family_of(filename)
    return f' data-family="{fam}"' if fam else ""
