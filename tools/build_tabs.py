#!/usr/bin/env python3
"""Front page as one screen of chrome with four tabbed panels.

    python3 tools/build_tabs.py        # site/index.html

Runs AFTER build_masthead / build_rack / build_console and BEFORE build_cachebust. It moves
nothing: it inserts a tab strip above the masthead and lets JavaScript show one panel at a
time. The sections stay exactly where the other generators put them, so this composes with
them instead of fighting them.

## What this does and does not claim

The **chrome** is one screen: header, tab strip and footer total 156px, and the active panel
gets everything else. A tall panel may still scroll inside itself, and saying otherwise
would be a lie the arithmetic refuses:

    1920x1080  ->  924px of panel, rack content  960px
    1440x900   ->  744px of panel, rack content 1009px
    1366x768   ->  612px of panel, rack content 1009px

There is no masthead left to reclaim in those numbers -- it is a panel now -- so no amount
of trimming closes a 265px gap at the commonest desktop height. What was wrong before was
never that the panel scrolled; it was that the panel was **330px** at 1440x900 and **48px**
at 1280x800, because the masthead was still stacked above it. Reading 1,009px of rack
through a 48px window is worse than scrolling, not better. A readable panel with a short
internal scroll is what claude.ai and ESPN actually do.

## Why the masthead is a panel rather than hidden

The obvious way to buy back its 373-727px is to hide the pitch column when the one-screen
layout is on. That is a **drop**, and `.claude/CLAUDE.md` is explicit: fold long content,
never trim it. Making the masthead the first panel is a fold -- it is still in the DOM, it
is still the default tab so it is still what a visitor lands on, and it costs the other
panels nothing.

## Why the gate starts at 1301px

`symoneural.css` restacks `.mh` at `max-width:1300px` from one row into two
(`"hero pitch"` over `"a1 a2"`), which is what took the masthead from 414px at 1440 to
**727px at 1280**. The first version of this gate opened at 1100px -- *inside* that reflow
band -- so every window between ~1100 and ~1300 turned no-scroll on at the exact width the
masthead was tallest. That was the 48px slit, and it shipped.

The gate now opens **above** the stacking point, so the one-screen layout only ever applies
to a layout that is not mid-reflow. This is the "two copies of a breakpoint drift" hazard in
`.claude/CLAUDE.md` with a third copy: the CSS stacking point at 1300px is now load-bearing
for a gate in a different file. Move one and you must move the other.

`min-height:740px` picks up 768px-tall laptops, which the old 780px floor excluded into a
3,438px scroll. Browser zoom shrinks the effective viewport, so at high zoom the query stops
matching and the page returns to scrolling on its own -- which is what someone who has
zoomed in needs. A no-scroll layout that survives zoom by clipping is an accessibility bug.

## Idempotency

Any existing strip and script are **removed before insertion** rather than substituted in
place. Substituting in place would have pinned the strip wherever a previous revision put
it -- below the masthead -- so the file would keep the old layout while this generator
reported success. Remove-then-insert means position is re-derived from the anchor every run.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
assert (ROOT / "backend" / "server.py").is_file(), f"repo root not found at {ROOT}"
SITE = ROOT / "site"

BEGIN = "<!-- BEGIN tabs (build_tabs.py) -->"
END = "<!-- END tabs -->"
JS_BEGIN = "<!-- BEGIN tabs-js (build_tabs.py) -->"
JS_END = "<!-- END tabs-js -->"

# The media query, in one place. The CSS copy in site/symoneural.css and the matchMedia call
# in SCRIPT below must both say exactly this.
GATE = "(min-width:1301px) and (min-height:740px)"

# id -> (tab label, description read by screen readers and shown on hover)
PANELS = [
    ("hero", "Overview", "What this machine is, and the argument"),
    ("rack", "Live stack", "The rack, reading its own sensors"),
    ("console", "Control board", "Instrument panel for the machine"),
    ("more", "Receipts", "Every claim, and what backs it"),
]


def strip() -> str:
    tabs = "\n".join(
        f'      <button type="button" class="ns-tab{" on" if i == 0 else ""}" '
        f'role="tab" id="nstab-{pid}" aria-controls="{pid}" '
        f'aria-selected="{"true" if i == 0 else "false"}" '
        f'data-panel="{pid}" title="{desc}">{label}</button>'
        for i, (pid, label, desc) in enumerate(PANELS)
    )
    return f"""{BEGIN}
<div class="ns-tabs" role="tablist" aria-label="Sections of this page">
  <div class="wrap ns-tabwrap">
{tabs}
    <span class="ns-tabnote">Nothing is hidden &mdash; every section is still here, one tab
      away.</span>
  </div>
</div>
{END}"""


SCRIPT = f"""{JS_BEGIN}
<script>
(function () {{
  'use strict';
  var strip = document.querySelector('.ns-tabs');
  if (!strip) return;
  var tabs = [].slice.call(strip.querySelectorAll('.ns-tab'));
  var ids = tabs.map(function (t) {{ return t.dataset.panel; }});

  // The one-screen layout is a CSS media query, so ASK THE BROWSER whether it is on rather
  // than re-deriving the breakpoint here. Two copies of a breakpoint drift, and the one in
  // JavaScript is always the one that gets forgotten.
  var mq = window.matchMedia('{GATE}');

  function applyLayout() {{
    // The class is what switches the CSS on. Adding it from JS rather than styling `html`
    // directly means a browser with JavaScript disabled never gets a clipped page -- it
    // scrolls, which is the safe way for this to fail.
    document.documentElement.classList.toggle('ns', mq.matches);
  }}

  function show(id) {{
    applyLayout();
    ids.forEach(function (p) {{
      var el = document.getElementById(p);
      if (!el) return;
      // Only hide when the one-screen layout is active. When the page scrolls normally
      // every section must be visible, or a phone visitor loses three quarters of the page.
      el.hidden = mq.matches && p !== id;
      if (el.hidden) el.scrollTop = 0;
    }});
    tabs.forEach(function (t) {{
      var on = t.dataset.panel === id;
      t.classList.toggle('on', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      t.tabIndex = on ? 0 : -1;
    }});
    if (mq.matches && location.hash !== '#' + id) {{
      history.replaceState(null, '', '#' + id);
    }}
  }}

  // Below the gate NOTHING is hidden, so switching a tab would move a highlight and change
  // nothing else -- a control that appears to do nothing, which is worse than no control.
  // There the strip is jump navigation instead, which is the only thing it can honestly be
  // when every section is already on the page.
  function pick(id) {{
    show(id);
    if (!mq.matches) {{
      var el = document.getElementById(id);
      if (el) el.scrollIntoView({{behavior: 'smooth', block: 'start'}});
    }}
  }}

  tabs.forEach(function (t) {{
    t.addEventListener('click', function () {{ pick(t.dataset.panel); }});
    // Left/right arrows move between tabs, which is what a tablist is expected to do.
    t.addEventListener('keydown', function (e) {{
      var i = tabs.indexOf(t), n = tabs.length, j = -1;
      if (e.key === 'ArrowRight') j = (i + 1) % n;
      if (e.key === 'ArrowLeft') j = (i - 1 + n) % n;
      if (j < 0) return;
      e.preventDefault();
      tabs[j].focus();
      pick(tabs[j].dataset.panel);
    }});
  }});

  // A link to #console from anywhere else must open that tab rather than scroll to a
  // section that is currently hidden.
  function fromHash() {{
    var want = (location.hash || '').replace(/^#/, '');
    show(ids.indexOf(want) >= 0 ? want : ids[0]);
  }}
  window.addEventListener('hashchange', fromHash);
  // When the layout flips -- resize, rotate, or the user zooms -- re-run so nothing is left
  // hidden on a page that has gone back to scrolling.
  mq.addEventListener ? mq.addEventListener('change', fromHash) : mq.addListener(fromHash);
  fromHash();
}})();
</script>
{JS_END}"""


def main() -> int:
    f = SITE / "index.html"
    html = f.read_text()

    missing = [pid for pid, _, _ in PANELS if f'id="{pid}"' not in html]
    if missing:
        print(f"  no element with id {missing} -- run build_masthead.py and build_rack.py first")
        return 1

    # ---- clear any previous strip and script, so position is re-derived every run rather
    #      than inherited from whatever revision wrote it last
    html = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n*", "", html, flags=re.S)
    html = re.sub(re.escape(JS_BEGIN) + r".*?" + re.escape(JS_END) + r"\n*", "", html, flags=re.S)

    # ---- the strip goes ABOVE the masthead, because the masthead is now a panel too
    anchor = "<!-- ===== MASTHEAD:BEGIN"
    if anchor not in html:
        print("  could not find the masthead block -- run build_masthead.py first")
        return 1
    html = html.replace(anchor, strip() + "\n\n" + anchor, 1)

    # ---- the script goes last, after the sections it controls exist
    html = html.replace("</body>", SCRIPT + "\n</body>", 1)

    f.write_text(html)
    print(f"  index.html: {len(PANELS)} tabs ({', '.join(p[0] for p in PANELS)}), gate {GATE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
