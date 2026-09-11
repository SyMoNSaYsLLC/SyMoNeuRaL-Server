"""Every local asset URL on the site must resolve to a file that will be published.

290 of 855 did not. The site restructure moved pages under `pages/` and assets
under `assets/{brand,icons,art}/`, and the URLs in the HTML were never moved
with them. It stayed invisible for two compounding reasons:

  - `build_cachebust.py` stamps `src` and `href` but not `srcset`, and it can
    only stamp a link that resolves, so a broken one was silently "left alone".
  - the live webroot still held the pre-restructure flat layout, because
    `deploy.sh` had been publishing nothing at all. The old URLs worked against
    the old webroot, so nothing looked wrong.

The rules applied here are `deploy.sh`'s own: pages flatten to the webroot root,
and `css/`, `js/` and `assets/` keep their trees.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents
            if (p / "backend" / "server.py").is_file())
SITE = ROOT / "frontend" / "site"

# Served by FastAPI through Caddy rather than from disk. `deploy.sh` deliberately
# publishes no static copy: it would be shadowed by the proxy and only go stale.
PROXIED = {"/openapi.json"}

URL = re.compile(r'(?:src|href)="(/[^":]*?)"|srcset="([^"]*)"|url\((/[^)]*)\)')
HAS_EXTENSION = re.compile(r"\.[a-z0-9]{2,5}$")


def urls_in(page: Path) -> list[str]:
    """Every local URL a browser would fetch from this page, srcset included."""
    found: list[str] = []
    for m in URL.finditer(page.read_text(errors="replace")):
        if m.group(1):
            found.append(m.group(1))
        elif m.group(2):
            found += [c.strip().split()[0] for c in m.group(2).split(",") if c.strip()]
        elif m.group(3):
            found.append(m.group(3).strip("'\""))
    return [u.split("?")[0].split("#")[0] for u in found]


def publishes(url: str) -> bool:
    """deploy.sh's rules: pages flatten to `/`, asset directories keep their tree."""
    rel = url.lstrip("/")
    return (SITE / rel).is_file() or (SITE / "pages" / rel).is_file()


class EveryAssetUrlResolves(unittest.TestCase):
    def setUp(self):
        self.pages = sorted(SITE.rglob("*.html"))

    def test_the_site_has_pages_to_check(self):
        """A walk that finds nothing passes every test below it vacuously."""
        self.assertGreater(len(self.pages), 20)

    def test_no_page_links_a_file_that_will_not_be_published(self):
        broken = []
        for page in self.pages:
            for url in urls_in(page):
                if (not url.startswith("/") or url.startswith("//")
                        or url in PROXIED or not HAS_EXTENSION.search(url)):
                    continue
                if not publishes(url):
                    broken.append(f"{page.relative_to(ROOT)} -> {url}")
        self.assertEqual(broken, [], "links to files that do not exist:\n  "
                                     + "\n  ".join(sorted(set(broken))[:20]))

    def test_srcset_is_checked_too(self):
        """srcset is where this hid: build_cachebust does not stamp it, so a
        broken entry there produces no warning anywhere."""
        checked = [u for p in self.pages
                   for u in urls_in(p) if "mark-" in u or "-64.png" in u]
        self.assertTrue(checked, "the srcset walk found nothing to check")
        for url in checked:
            if url.startswith("/") and HAS_EXTENSION.search(url):
                self.assertTrue(publishes(url), url)

    def test_no_asset_is_referenced_at_the_webroot_root(self):
        """Every image and script lives under assets/, css/ or js/ now. A bare
        `/mark-32.png` is the pre-restructure layout, and it resolved against the
        stale webroot for as long as deploy.sh was publishing nothing."""
        bare = set()
        for page in self.pages:
            for url in urls_in(page):
                if (url.count("/") == 1 and HAS_EXTENSION.search(url)
                        and not url.endswith((".html", ".json", ".xml", ".ico"))):
                    bare.add(url)
        self.assertEqual(bare, set(), f"assets referenced at the root: {bare}")


class TheDeployerPreservesAssetDirectories(unittest.TestCase):
    """`deploy.sh` installed every asset directly into `$DST/$d/`, which kept the
    top level and flattened everything below it: `assets/brand/mark-32.png`
    landed at `/assets/mark-32.png` while 25 pages linked the full path. Its own
    comment already said the asset directories do not flatten; the code
    disagreed with the comment.
    """

    def setUp(self):
        self.script = (ROOT / "scripts" / "deploy.sh").read_text()

    def test_assets_are_installed_with_their_relative_path(self):
        self.assertIn('install -o www-data -g www-data -D -m 644 "$SRC/$rel" "$DST/$rel"',
                      self.script)

    def test_the_flattening_form_is_gone(self):
        self.assertNotIn('-exec install -o www-data -g www-data -m 644 {} "$DST/$d/"',
                         self.script)

    def test_there_are_assets_below_the_first_level_to_protect(self):
        """If this ever hits zero the test above is guarding nothing."""
        deep = [p for p in (SITE / "assets").rglob("*") if p.is_file()
                and len(p.relative_to(SITE / "assets").parts) > 1]
        self.assertGreater(len(deep), 50)


if __name__ == "__main__":
    unittest.main()
