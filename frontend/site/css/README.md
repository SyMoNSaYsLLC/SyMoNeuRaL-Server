# `frontend/site/css/` — the stylesheet

`symoneural.css` is the site. The rest are page-scoped additions, and each should be asking
itself whether it belongs in the main file instead.

## What to know before editing

**The one-screen fold sets `overflow:hidden` on html and body** above `1301px × 740px`, and
the active panel is the only thing that scrolls. `min-height: 0` on a flex child is
load-bearing there: without it the child refuses to shrink below its content and the page
scrolls after all.

`js/fit.js` measures each panel and zooms it down to fit, with a floor below which the panel
gets its scrollbar back rather than becoming unreadable. If a panel is clipped at 100% zoom,
that is a layout the fold cannot fit, not a missing rule.

`tests/site/test_site_css.py` asserts one stylesheet and no orphan rules.
