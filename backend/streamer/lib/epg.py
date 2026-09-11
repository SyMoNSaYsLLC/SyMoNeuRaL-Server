"""Electronic programme guide for the Streamer. Two sources, one shape out.

A provider exposes its guide twice, and the two are not interchangeable:

    player_api.php?action=get_short_epg&stream_id=N&limit=K   one channel, JSON, base64 titles
    xmltv.php?username=&password=                             the whole account, XMLTV

`get_short_epg` is a few hundred bytes and answers in one round trip per channel. `xmltv.php`
is one round trip for everything and, on the account this was measured against, **31 MB for
10,124 channels** -- fine as a background load, far too slow to block a grid that only needs
now-and-next for the twenty rows a visitor can actually see. So the grid uses the per-channel
call with a small amount of concurrency, and the whole-account XMLTV is a separate route for
callers that want the day ahead.

**Times come back as epoch seconds and nothing else.** Both sources also carry a formatted
local string (`"2026-08-17 14:00:00"`) in the panel's timezone, which is not the visitor's and
is not labelled -- rendering that directly is how a guide ends up confidently three hours wrong.
`get_short_epg` supplies `start_timestamp`/`stop_timestamp`, XMLTV supplies an explicit offset
(`20260817140000 +0100`); both are unambiguous and both are converted here. A row this module
cannot place on the clock is dropped rather than guessed at, and `dropped` says how many.

**Titles are base64, except when they are not.** The Xtream spec says `title` and `description`
are base64; real panels ship both, sometimes in the same response. `_maybe_b64` decodes only
when the result is plausible text, so a panel that sends plain titles is not turned into mojibake
by a decoder that insisted.

**Credentials.** Same contract as the rest of this package: they arrive in a POST body, are used
to build a URL, and are never logged. Every error message from here goes through the creds'
`Scrubber` before it can reach a response, because a panel error page routinely echoes the
password back.
"""
from __future__ import annotations

import base64
import binascii
import io
import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from ..lib import safefetch
from .safefetch import BlockedURL, FetchError, Policy, ResponseTooLarge
from .xtream import XtreamCreds, api_url, panel_base

__all__ = ["EpgError", "EpgTooLarge", "Programme", "short_epg", "xmltv_epg", "now_next"]

#: How many programmes one `get_short_epg` call asks for. Four is now, next, and two after that
#: -- enough for a grid row three hours wide, which is what the guide draws. Asking for more is
#: not free: the panel serialises every row and the grid multiplies it by the number of visible
#: channels.
DEFAULT_LIMIT = 4

#: Hard ceiling on `limit`, so a crafted request cannot turn one grid load into a full-day dump
#: for every channel at once. Panels themselves cap somewhere around here.
MAX_LIMIT = 24

#: XMLTV `start`/`stop`: 14 digits, then an optional signed offset. Both halves are needed --
#: `20260817140000` alone is a wall-clock time in an unstated zone, which is exactly the thing
#: this module refuses to guess at.
_XMLTV_TIME = re.compile(r"^\s*(\d{14})(?:\s*([+-]\d{4}))?\s*$")


class EpgError(Exception):
    """A guide-level failure. The message never contains a credential."""


class EpgTooLarge(EpgError):
    """The guide document was over the caller's `Policy.max_bytes`.

    Distinguished for the same reason `xtream.XtreamTooLarge` is: a size refusal is this box's
    decision, and reporting it as "your provider has no guide" sends the visitor to argue with
    the wrong party. `Policy.max_bytes` defaults to 0 (uncapped), so this only fires for a
    caller that asked for a ceiling.
    """


@dataclass(frozen=True)
class Programme:
    """One row of guide, on the clock and in the visitor's language.

    `start`/`stop` are epoch seconds UTC. `stop` may equal `start` when a panel gives a
    zero-length row; it is never less, because `_row` swaps them rather than emitting a
    programme that ends before it begins.
    """
    start: int
    stop: int
    title: str
    desc: str = ""

    @property
    def seconds(self) -> int:
        return max(0, self.stop - self.start)

    def public(self) -> dict:
        return {"start": self.start, "stop": self.stop, "seconds": self.seconds,
                "title": self.title, "desc": self.desc}


# ---------------------------------------------------------------- decoding helpers

def _maybe_b64(raw: object) -> str:
    """Decode base64 text, but only when the decode is believable.

    The Xtream field is documented as base64 and usually is. Two things go wrong if that is
    trusted blindly:

    * a panel that sends plain text -- `"News"` happens to be valid base64 and decodes to three
      bytes of binary, so insisting on a decode replaces a correct title with rubbish;
    * a panel that sends base64 of something that is not UTF-8, which raises mid-render.

    So: decode with validation, require the result to be decodable UTF-8 with no control
    characters, and fall back to the original string otherwise. A title is cosmetic; getting it
    wrong quietly is not acceptable, and neither is a 500.
    """
    s = "" if raw is None else str(raw)
    if not s:
        return ""
    stripped = s.strip()
    # Base64 of anything non-trivial is a multiple of 4 characters from the base64 alphabet.
    # Anything with a space in it is prose the panel did not encode.
    if len(stripped) % 4 or " " in stripped:
        return s
    try:
        out = base64.b64decode(stripped, validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return s
    if not out.strip():
        return s
    if any(ch < " " and ch not in "\t\n\r" for ch in out):
        return s
    return out


def _epoch(raw: object) -> int | None:
    """An epoch-seconds integer, or None if this value cannot be one.

    Panels send `start_timestamp` as a string, an int, sometimes as a float, and occasionally as
    `""`. Milliseconds also appear -- a 13-digit value is not the year 402,000, it is a
    JavaScript timestamp -- and are converted rather than rejected.
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        n = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    if n > 10_000_000_000:            # milliseconds, not seconds
        n //= 1000
    return n


def _xmltv_epoch(raw: str | None) -> int | None:
    """Parse an XMLTV timestamp, offset included, into epoch seconds.

    A timestamp with no offset is refused. That is deliberate: XMLTV allows it and means "local
    time", but *whose* local time is not carried anywhere in the document -- so accepting it
    means silently assuming the server's guess is the visitor's, which is the three-hours-wrong
    failure this module exists to avoid.
    """
    m = _XMLTV_TIME.match(raw or "")
    if not m:
        return None
    stamp, offset = m.group(1), m.group(2)
    try:
        y, mo, d = int(stamp[0:4]), int(stamp[4:6]), int(stamp[6:8])
        h, mi, s = int(stamp[8:10]), int(stamp[10:12]), int(stamp[12:14])
    except ValueError:                                        # pragma: no cover - regex-guarded
        return None
    if offset is None:
        return None
    try:
        # `calendar.timegm` semantics without the import: build the UTC epoch by hand so no
        # part of this depends on the process timezone. TZ on a server is somebody else's
        # deployment detail and has been wrong here before.
        import calendar
        base = calendar.timegm((y, mo, d, h, mi, s, 0, 0, 0))
    except (ValueError, OverflowError):
        return None
    sign = 1 if offset[0] == "+" else -1
    off = sign * (int(offset[1:3]) * 3600 + int(offset[3:5]) * 60)
    return base - off


def _row(start: int | None, stop: int | None, title: str, desc: str) -> Programme | None:
    """Build one programme, or None when it cannot be placed on the clock."""
    if start is None or stop is None:
        return None
    if stop < start:
        start, stop = stop, start
    return Programme(start=start, stop=stop, title=title.strip(), desc=desc.strip())


# ---------------------------------------------------------------- the per-channel call

def short_epg(creds: XtreamCreds, stream_id: str, limit: int = DEFAULT_LIMIT,
              policy: Policy = Policy()) -> tuple[list[Programme], int]:
    """`get_short_epg` for one live stream. Returns (programmes, dropped).

    `dropped` is the number of rows the panel sent that carried no usable timestamps. It is
    returned rather than logged because a guide that is quietly half empty looks like a provider
    with no data, and the visitor is the only person who can tell those apart.

    An empty list is a legitimate answer: plenty of channels genuinely have no guide, and
    inventing a "No information" programme to fill the row would be the decorative-indicator
    rule broken in the one place a visitor is most likely to believe it.
    """
    sid = str(stream_id).strip()
    if not sid:
        raise EpgError("no stream id given")
    lim = max(1, min(MAX_LIMIT, int(limit or DEFAULT_LIMIT)))
    url = api_url(creds, "get_short_epg", stream_id=sid, limit=str(lim))
    data = _get_json(url, policy, creds)

    rows = data.get("epg_listings") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        # Some panels answer a channel with no guide as `[]`, some as `{}`, some with the key
        # missing. None of those is an error and all three mean the same thing.
        return [], 0
    out: list[Programme] = []
    dropped = 0
    for row in rows:
        if not isinstance(row, dict):
            dropped += 1
            continue
        p = _row(_epoch(row.get("start_timestamp")), _epoch(row.get("stop_timestamp")),
                 _maybe_b64(row.get("title")), _maybe_b64(row.get("description")))
        if p is None:
            dropped += 1
            continue
        out.append(p)
    out.sort(key=lambda p: p.start)
    return out, dropped


def _get_json(url: str, policy: Policy, creds: XtreamCreds):
    scrub = creds.scrubber
    try:
        body, _ctype, _target = safefetch.fetch(url, policy)
    except BlockedURL as exc:
        raise EpgError(scrub(str(exc))) from None
    except ResponseTooLarge as exc:
        raise EpgTooLarge(scrub(str(exc))) from None
    except FetchError as exc:
        raise EpgError(scrub(str(exc))) from None
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except (ValueError, UnicodeDecodeError):
        # The body may be an error page with the credentials echoed into it. Say nothing about
        # what it contained.
        raise EpgError("panel did not return guide JSON for that channel") from None


# ---------------------------------------------------------------- the whole-account document

def xmltv_epg(creds: XtreamCreds, policy: Policy = Policy(),
              wanted: set[str] | None = None,
              max_per_channel: int = 0) -> tuple[dict[str, list[Programme]], dict]:
    """`xmltv.php` for the whole account, keyed by the channel id XMLTV uses.

    That key is what a channel row calls `tvg_id` (`epg_channel_id` in the panel's JSON), which
    is why `load_channels` carries it. Matching on channel *name* instead would be wrong on
    every provider that writes "BBC One HD" in one place and "BBC ONE" in the other.

    `wanted` filters while parsing rather than after. On the measured account the document is
    31 MB and 10,124 channels; a visitor looking at 20 rows should not pay to build the other
    10,104 lists. `max_per_channel` bounds the tail per channel the same way, and when either
    bound drops something the returned meta says so -- an unreported cap is how a "full day of
    guide" quietly becomes two hours.

    Parsing is `iterparse` with `elem.clear()`, not `fromstring`: the whole document is already
    in memory as bytes, and building a full DOM on top of it would double that for no gain.
    """
    url = f"{panel_base(creds.server)}/xmltv.php?username={_q(creds.username)}&password={_q(creds.password)}"
    scrub = creds.scrubber
    try:
        body, _ctype, _target = safefetch.fetch(url, policy)
    except BlockedURL as exc:
        raise EpgError(scrub(str(exc))) from None
    except ResponseTooLarge as exc:
        raise EpgTooLarge(scrub(str(exc))) from None
    except FetchError as exc:
        raise EpgError(scrub(str(exc))) from None

    out: dict[str, list[Programme]] = {}
    dropped = 0
    skipped_by_cap = 0
    total = 0
    try:
        for _event, elem in ET.iterparse(io.BytesIO(body), events=("end",)):
            if elem.tag != "programme":
                continue
            total += 1
            chan = (elem.get("channel") or "").strip()
            if not chan or (wanted is not None and chan not in wanted):
                elem.clear()
                continue
            if max_per_channel and len(out.get(chan, ())) >= max_per_channel:
                skipped_by_cap += 1
                elem.clear()
                continue
            p = _row(_xmltv_epoch(elem.get("start")), _xmltv_epoch(elem.get("stop")),
                     _text(elem, "title"), _text(elem, "desc"))
            if p is None:
                # No bucket is created for a channel until one of its rows is usable. A
                # `{"a.tv": []}` in the result would claim "this channel has a guide and it is
                # empty", which is not what happened -- what happened is that every row it sent
                # was undateable, and `dropped_no_clock` is where that gets said.
                dropped += 1
            else:
                out.setdefault(chan, []).append(p)
            elem.clear()
    except ET.ParseError as exc:
        # A truncated document is common: a panel that times out mid-write still returns 200
        # with valid-looking XML up to the cut. Keep what parsed and say the rest is missing,
        # rather than throwing away a usable guide over its last element.
        if not out:
            raise EpgError(f"guide document is not valid XMLTV ({exc.__class__.__name__})") from None
        meta = _meta(body, total, dropped, skipped_by_cap, out, truncated=True)
        for lst in out.values():
            lst.sort(key=lambda p: p.start)
        return out, meta

    for lst in out.values():
        lst.sort(key=lambda p: p.start)
    return out, _meta(body, total, dropped, skipped_by_cap, out, truncated=False)


def _meta(body: bytes, total: int, dropped: int, capped: int,
          out: dict[str, list[Programme]], truncated: bool) -> dict:
    return {
        "source": "xmltv.php",
        "bytes": len(body),
        "programmes_seen": total,
        "programmes_kept": sum(len(v) for v in out.values()),
        "channels": len(out),
        "dropped_no_clock": dropped,
        "dropped_over_cap": capped,
        "truncated": truncated,
    }


def _text(elem: ET.Element, tag: str) -> str:
    node = elem.find(tag)
    return (node.text or "") if node is not None else ""


def _q(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(s, safe="")


# ---------------------------------------------------------------- now / next

def now_next(programmes: list[Programme], at: float | None = None) -> dict:
    """What is on and what follows, from a list this module produced.

    `now` is the programme whose window contains `at`. `next` is the earliest one starting after
    it -- **not** simply `programmes[1]`, because a list can begin in the past (a `get_short_epg`
    reply routinely starts with the programme already running) and can have a gap where the
    provider published nothing.

    Both are `None` when the list says nothing about `at`. A guide cell with no data must render
    as having no data; a "now" plucked from whatever row happened to be first is the same class
    of lie as a status LED that is always green.
    """
    t = time.time() if at is None else at
    now = None
    for p in programmes:
        if p.start <= t < p.stop or (p.stop == p.start and int(p.start) == int(t)):
            now = p
            break
    after = [p for p in programmes if p.start > (now.start if now else t)]
    nxt = min(after, key=lambda p: p.start) if after else None
    out: dict = {"now": now.public() if now else None, "next": nxt.public() if nxt else None}
    if now:
        span = max(1, now.seconds)
        out["progress"] = max(0.0, min(1.0, (t - now.start) / span))
    return out
