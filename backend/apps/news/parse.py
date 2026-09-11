"""One parser for both feed formats, using stdlib `xml.etree` only.

There is no `feedparser` here and there is not going to be: CLAUDE.md forbids installing into
the system interpreter, which is the serving path, and a news ticker is not a good enough
reason for a venv in that path. So this module does the one job a feed library does that we
actually need -- get titles, links and timestamps out of two dialects -- and nothing else.

The two dialects, and why one function handles both:

  RSS 2.0    `<rss><channel><item><title><link><pubDate>`      -- no namespace, link is text
  Atom 1.0   `<feed><entry><title><link href><updated>`        -- namespaced, link is an attr

Everything else about them is close enough that branching on `item` vs `entry` and on where
the URL lives is the whole difference. arXiv's RSS carries `<dc:date>` instead of `<pubDate>`,
which is the third case and the reason `_when` takes a list of candidates.

On safety: stdlib `ElementTree` does not expand external entities and does not fetch DTDs, so
the billion-laughs and XXE classes do not apply to it the way they do to `lxml`. What it does
do is raise `ParseError` on malformed input, which is why `parse_feed` is called inside a
per-source `try` in `collect.py` -- one publisher serving a truncated document costs one
source in one pass, not the pass.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import NamedTuple
from xml.etree import ElementTree
from urllib.parse import urlsplit

ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/elements/1.1/}"

# Bing declares its extension namespace as the query URL it was called with, so the URI is
# different on every request and cannot be matched literally. The local name is all there is
# to go on, which is why `_bing_source` searches by suffix.
_BING_SOURCE_LOCAL = "}Source"

# Feeds put markup in titles: HuggingFace uses `<b>`, arXiv puts LaTeX in there, and a few
# wrap the whole thing in CDATA that resolves to HTML. The ticker renders as text, so tags
# come out here rather than being escaped downstream and shown as literal angle brackets.
_TAG = re.compile(r"<[^>]{0,200}>")
_WS = re.compile(r"\s+")
# HuggingFace's blog feed escapes markdown in titles, so `LFM2.5 Q4_0` arrives as
# `LFM2.5 Q4\_0`. Only a backslash before punctuation is removed -- a lone backslash in a
# path or a code fragment is content and stays.
_MD_ESCAPE = re.compile(r"\\([_*`~\[\]()#+.!-])")

# Google News formats every title as "Headline - Publisher" and Bing does the same with an
# en-dash. Splitting it lets the chip carry the publisher instead of saying "Google News",
# which is closer to true: Google did not write the story.
_PUBLISHER = re.compile(r"\s+[-–—]\s+([^-–—]{2,40})$")


class Item(NamedTuple):
    title: str
    url: str
    source: str        # who to credit on the chip
    topic: str
    at: float          # epoch seconds, or 0.0 when the feed gave no usable date
    weight: float      # carried from the source, consumed by rank.py


def clean(text: str | None) -> str:
    """Feed text -> one line of plain text. Entities resolved, tags gone, runs collapsed."""
    if not text:
        return ""
    # Unescape first: a title may arrive as `&lt;b&gt;Qwen&lt;/b&gt;`, where the tags only
    # become tags after unescaping, so stripping first would miss them.
    return _WS.sub(" ", _MD_ESCAPE.sub(r"\1", _TAG.sub(" ", html.unescape(text)))).strip()


def _when(el: ElementTree.Element) -> float:
    """Best available timestamp as epoch seconds, or 0.0.

    0.0 rather than "now": rank.py scores on recency, and defaulting a dateless item to now
    would float undated items to the top of a live ticker. An item that cannot say when it
    happened should not be presented as the newest thing on the page.
    """
    for tag in ("pubDate", "published", "updated", f"{ATOM}published", f"{ATOM}updated",
                f"{DC}date", "date"):
        node = el.find(tag)
        raw = (node.text or "").strip() if node is not None else ""
        if not raw:
            continue
        for attempt in (_rfc822, _iso8601):
            got = attempt(raw)
            if got:
                return got
    return 0.0


def _rfc822(raw: str) -> float | None:
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    # A date with no zone is not an error in RFC 822, and `.timestamp()` would read it as
    # local time. UTC is the honest reading for a feed of unknown origin.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _iso8601(raw: str) -> float | None:
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _https(url: str) -> str:
    """Upgrade `http://` to `https://`, but only for a host this package itself fetched.

    Bing News' RSS links every result through `http://www.bing.com/news/apiclick.aspx?...`
    -- plaintext, on a feed we just read over TLS from that same host. Serving that link to a
    browser on an https page is a mixed-content warning, and dropping it costs the whole Bing
    arm.

    So the upgrade is allowed for exactly the hosts in `feeds.HOSTS`, because this package has
    demonstrated within the same pass that each of them speaks https -- it fetched the feed
    that way. For any other host it is still a guess, and the guess is not made: `parse_feed`
    drops the item instead.
    """
    if url.startswith("http://"):
        from . import feeds
        candidate = "https://" + url[len("http://"):]
        if urlsplit(candidate).hostname in feeds.HOSTS:
            return candidate
    return url


def _url(el: ElementTree.Element) -> str:
    """The item's link, from whichever of the four places a feed put it."""
    for tag in ("link", f"{ATOM}link"):
        for node in el.findall(tag):
            href = (node.get("href") or "").strip()
            rel = node.get("rel") or "alternate"
            if href and rel == "alternate":
                return _https(href)
            text = (node.text or "").strip()
            if text:
                return _https(text)
    # arXiv's RSS puts the canonical URL in <guid> and hnrss uses <comments>; guid is the one
    # that is reliably a link rather than an opaque id, and only when it looks like one.
    guid = el.find("guid")
    raw = (guid.text or "").strip() if guid is not None else ""
    return _https(raw) if raw.startswith("https://") or raw.startswith("http://") else ""


def _credit(title: str, url: str, fallback: str) -> tuple[str, str]:
    """(title, source). Splits "Headline - Publisher" for the search feeds.

    Only applied when `fallback` is a search feed's name, and only when the tail looks like a
    publisher rather than part of the sentence -- a headline ending in "- and that is the
    problem" would otherwise lose its ending and gain a nonsense chip.
    """
    m = _PUBLISHER.search(title)
    if not m:
        host = urlsplit(url).hostname or ""
        return title, (host[4:] if host.startswith("www.") else host) or fallback
    tail = m.group(1).strip()
    if " " in tail and len(tail.split()) > 4:
        return title, fallback          # a clause, not a masthead
    return title[:m.start()].strip(), tail


def _bing_source(el: ElementTree.Element) -> str:
    """The publisher from Bing's `<News:Source>`, or "" when the feed has no such element."""
    for child in el:
        if child.tag.endswith(_BING_SOURCE_LOCAL):
            return clean(child.text)[:40]
    return ""


def parse_feed(body: str, source: str, topic: str, weight: float,
               credit_from_title: bool = False) -> list[Item]:
    """Parse one RSS or Atom document into Items. Raises ParseError on malformed XML.

    `credit_from_title` is set for the search arm only: "Google News" is the finder, not the
    publisher, so those titles get split and the publisher becomes the chip.
    """
    root = ElementTree.fromstring(body)
    nodes = root.findall(".//item") or root.findall(f".//{ATOM}entry")
    out: list[Item] = []
    for node in nodes:
        title_el = node.find("title")
        if title_el is None:
            title_el = node.find(f"{ATOM}title")
        title = clean(title_el.text if title_el is not None else "")
        url = _url(node)
        if not title or not url.startswith("https://"):
            # http:// links are dropped rather than upgraded. A ticker that hands a visitor
            # a plaintext link is a mixed-content warning on an https page, and guessing that
            # the https version exists is a guess.
            continue
        credit = source
        if credit_from_title:
            # Bing states the publisher outright; Google News does not, so its title has to
            # be split. Reading the element when it exists is strictly better than inferring
            # from punctuation, and it is why "CNBC on MSN" comes out intact.
            declared = _bing_source(node)
            title, inferred = _credit(title, url, source)
            credit = declared or inferred
        out.append(Item(title=title, url=url, source=credit, topic=topic,
                        at=_when(node), weight=weight))
    return out
