"""One outbound GET, with the three limits that make it safe to run on a public box.

The gateway's `chain.probe` is the shape being copied -- blocking `urllib` called from
`asyncio.to_thread`, never raising past the refresher, returning a reading or an error. What
this adds over that is host discipline, because the gateway talks to one operator-configured
node and this package talks to third-party hosts it does not control.

  1. HOST. The host of every URL is checked against `feeds.HOSTS` before the socket opens.
     `feeds.HOSTS` is derived from the literal source and template tuples, so there is no way
     to reach a host that is not written down in `feeds.py`.

  2. REDIRECTS. `urllib` follows redirects by default, which means the host that was
     validated is not necessarily the host that answered -- GitHub 301s
     `comfyanonymous/ComfyUI` to `Comfy-Org/ComfyUI` today, and the next project to move will
     not tell us either. `_HostCheckedRedirect` re-runs the check on every hop, so a redirect
     off-list raises instead of being quietly followed.

  3. SIZE. `developer.nvidia.com/blog/feed` was 739 KB on 2026-08-20 and nothing promises it
     will not be 739 MB tomorrow. The read is capped and an over-cap body is discarded whole
     rather than truncated, because a truncated XML document is a parse error dressed up as
     data.
"""
from __future__ import annotations

import gzip
import urllib.request
from urllib.parse import urlsplit

from . import feeds

# 4 MiB. Five times the largest feed measured here, which leaves room for a feed to grow
# without leaving room for a feed to exhaust the box.
MAX_BYTES = 4 * 1024 * 1024

# Per request. A whole pass is sequential inside one worker thread, so this is what bounds
# the pass: sources plus searches, times this, is the worst case.
TIMEOUT_S = 12.0

# Identifying, contactable, and true. A publisher who wants to block this can, and one who
# wants to ask about it has an address -- `symonsayadmin@` is where CLAUDE.md points public
# questions.
USER_AGENT = ("symoneural-news/1.0 (+https://symoneural.com; "
              "symonsayadmin@symoneural.com)")


class HostNotAllowed(Exception):
    """A URL, or a redirect target, whose host is not in feeds.HOSTS."""


def check_host(url: str) -> str:
    """Return the host of `url`, or raise HostNotAllowed.

    Called before connecting and again on every redirect hop. It is a module-level function
    rather than an inline check because it is the one property in this package that is about
    security rather than correctness, and a test should be able to call the thing it tests.
    """
    parts = urlsplit(url)
    if parts.scheme != "https":
        # Every URL in feeds.py is https, so a plaintext hop is a downgrade worth refusing on
        # its own account, before the host is even considered.
        raise HostNotAllowed(f"{parts.scheme!r} is not https: {url!r}")
    host = parts.hostname
    if not host or host not in feeds.HOSTS:
        raise HostNotAllowed(
            f"{host!r} is not one of the {len(feeds.HOSTS)} hosts named in feeds.py")
    return host


class _HostCheckedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_host(newurl)          # raises, which aborts the whole fetch
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_HostCheckedRedirect)


def get(url: str, timeout: float = TIMEOUT_S) -> str:
    """Fetch `url` and return the body as text. Raises on anything that is not a body.

    Raising rather than returning an error string is deliberate. The caller is `collect.py`,
    which has to decide per source what a failure means, and a function that returned `""`
    for "empty feed", "404" and "host refused" alike would make that decision impossible.
    `refresh_once` is where exceptions stop.
    """
    check_host(url)
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
        "Accept-Encoding": "gzip",
    })
    with _opener.open(req, timeout=timeout) as resp:
        raw = resp.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError(f"body exceeds {MAX_BYTES} bytes; discarded whole")
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        # `errors="replace"` rather than `strict`: a single bad byte in a 739 KB feed should
        # cost one glyph in one headline, not the whole source for that pass.
        return raw.decode(resp.headers.get_content_charset() or "utf-8", "replace")
