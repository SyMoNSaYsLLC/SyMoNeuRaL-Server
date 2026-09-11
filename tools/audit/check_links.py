#!/usr/bin/env python3
"""Walk every link in `site/` and report the ones that resolve to nothing.

    python3 tools/audit/check_links.py          # exits 1 if anything is broken

Garrett asked for "verify all links are working", and a one-off walk answers that once.
This answers it every time, which matters here because eleven pages are generator-written:
a link breaks when a *generator* changes, long after anyone last looked at the HTML.

**Static on purpose.** It needs no API, no browser and no network, so it runs in a second and
can be put in front of a commit. What it therefore cannot check is whether an external URL is
alive; those are counted and skipped. `scripts/deploy.sh` has its own reference check over the
deployed webroot -- this one runs over the staging tree, before that.

Two false positives cost real time when this was first written, and both are guarded here:

* **`data-src="live"` is not a link.** A bare `(href|src)=` regex matches the tail of
  `data-src`, so the control board's `data-src="live"`/`"measured"`/`"projected"` and the
  miner's `data-src="emu"`/`"scan"` all reported as missing files. The lookbehind
  `(?<![-\\w])` is what makes it read attribute names rather than substrings.
* **A fragment is not part of a filename.** `/documentation.html#hardware` is not a file
  called `documentation.html#hardware`; it is a file plus an anchor, and BOTH halves have to
  be checked. Splitting on `#` and then asserting `id="hardware"` exists in the target file is
  what turns this from noise into the check that actually found the one real break: a
  `href="#rack"` in the masthead, on `/overview`, which has no `#rack` section since the page
  split -- and `/` 302s to `/overview`, so that dead button was on the page nearly every
  visitor sees. Fixed in `b5f4e4f`.

The only targets that are legitimately not files on disk are the four section paths (`/`,
`/overview`, `/livestack`, `/controlboard`, `/receipts`), `/docs`, `/openapi.json`, and
anything under `/api/*` -- all served by FastAPI rather than off the webroot. Adding a fifth
section means adding it to `ROUTES` here as well as to `ops/Caddyfile`, `tools/build/build_split.py`
and `backend/server.py`.

**The failure mode that costs the most is this one, so check `ROUTES` before believing a
BROKEN line.** A link to a path FastAPI serves and the webroot does not is reported broken here
even though it works in a browser, and the tempting repair -- "fix" the link -- breaks a link
that was right. That has not happened yet (the watch surface shipped as a file,
`site/streamer-watch.html`, and Reinforce as `site/reinforce.html`), but several sessions are
adding surfaces at once and any of them could add the first one. A BROKEN line naming a path
with no dot in it is that case until proven otherwise.
"""
from __future__ import annotations
import collections
import pathlib
import re
import sys

SITE = pathlib.Path(__file__).resolve().parent.parent / "site"
ROUTES = {"/", "/overview", "/livestack", "/controlboard", "/receipts",
          "/docs", "/openapi.json"}
SKIP = ("http://", "https://", "mailto:", "data:", "javascript:", "//")
LINK = re.compile(r'(?<![-\w])(?:href|src)\s*=\s*"([^"]+)"')


def has_id(html: str, ident: str) -> bool:
    return re.search(r'id\s*=\s*"%s"' % re.escape(ident), html) is not None


def main() -> int:
    pages = sorted(SITE.glob("*.html"))
    text = {p.name: p.read_text(errors="replace") for p in pages}
    refs: dict[str, list[str]] = collections.defaultdict(list)
    for p in pages:
        for m in LINK.finditer(text[p.name]):
            refs[m.group(1)].append(p.name)

    broken: list[tuple[str, str, str]] = []
    resolved = external = inpage = 0
    for target, where in sorted(refs.items()):
        t = target.split("?")[0]
        if t.startswith(SKIP):
            external += 1
            continue
        path, _, frag = t.partition("#")
        if not path:                       # an anchor into the page it is written on
            inpage += 1
            for w in sorted(set(where)):
                if frag and not has_id(text[w], frag):
                    broken.append((target, w, "no such id on that page"))
            continue
        if path.startswith("/api/") or path in ROUTES:
            resolved += 1
            continue
        name = path.lstrip("/")
        if not (SITE / name).exists():
            broken.append((target, ", ".join(sorted(set(where))), "no such file in site/"))
            continue
        if frag and name in text and not has_id(text[name], frag):
            broken.append((target, ", ".join(sorted(set(where))), f'{name} has no id="{frag}"'))
            continue
        resolved += 1

    total = sum(len(v) for v in refs.values())
    print(f"{len(pages)} pages, {total} links, {len(refs)} unique targets "
          f"({resolved} resolve, {external} external, {inpage} in-page)")
    for target, where, why in broken:
        print(f"  BROKEN  {target}\n          on {where} -- {why}")
    print("clean" if not broken else f"{len(broken)} broken")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
