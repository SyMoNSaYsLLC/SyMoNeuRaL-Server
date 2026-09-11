"""Extended M3U parsing. Two dialects, deliberately kept apart.

`parse_m3u` reads the **channel-list** dialect: `#EXTINF:-1 tvg-id="..." group-title="...",Name`
followed by a stream URL, repeated a few thousand times. That is what a visitor pastes in.

`parse_hls` reads the **HLS** dialect: `#EXT-X-STREAM-INF`, `#EXT-X-MEDIA-SEQUENCE`, segment
URIs. That is what the upstream pump needs when the source it was given turns out to be an
`.m3u8` rather than a continuous transport stream.

They share a file extension and almost nothing else, and one parser trying to serve both is how
you end up presenting a video segment to a visitor as a TV channel. Kept separate on purpose.

No sample playlist from `external/` is used, quoted, or shipped anywhere in this module or its
tests -- those files embed real provider credentials in their URLs. The test fixtures are
synthetic and were written here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = ["Channel", "parse_m3u", "HlsVariant", "HlsSegment", "HlsPlaylist", "HlsKey",
           "NO_KEY", "parse_hls", "MAX_CHANNELS"]

#: **No channel cap. `0` means parse the whole file**, and `0` is the default at the owner's
#: instruction (2026-08-17). A provider list of 60k channels is real, so a 20,000 cap silently
#: deleted the tail of a real playlist -- and the tail of a provider file is where Movies
#: usually is. `truncated` still exists and is still reported; with no cap it is simply always
#: `False`. A caller that wants a bound sets this to a positive number.
MAX_CHANNELS = 0


@dataclass
class Channel:
    """One entry. `name` is what the visitor sees; `url` is never shown or logged."""
    name: str
    url: str
    tvg_id: str = ""
    tvg_name: str = ""
    logo: str = ""
    group: str = ""
    duration: float = -1.0
    kind: str = "live"          # live | vod | series -- guessed from the URL shape, see below


# `#EXTINF:<duration> <k="v" ...>,<display name>`. The duration may be negative (live) or a
# float, the attributes are optional, and the comma before the name is the only reliable
# separator -- names routinely contain colons, quotes and further commas.
_EXTINF = re.compile(r"^#EXTINF\s*:\s*(-?\d+(?:\.\d+)?)\s*(.*)$", re.IGNORECASE)
_ATTR = re.compile(r'([A-Za-z0-9_-]+)\s*=\s*"([^"]*)"')


def _split_extinf(rest: str) -> tuple[dict[str, str], str]:
    """Separate the attribute block from the display name.

    The naive `rest.split(",", 1)` is wrong: `tvg-name="Sky Sports, Main Event"` contains a
    comma inside a quoted value, and splitting on the first one truncates the attributes and
    turns the rest of them into the channel's name. So: find the first comma that is not inside
    double quotes.
    """
    depth = 0
    for i, ch in enumerate(rest):
        if ch == '"':
            depth ^= 1
        elif ch == "," and not depth:
            return dict(_ATTR.findall(rest[:i])), rest[i + 1:].strip()
    # No comma at all: the whole remainder is attributes, and there is no display name.
    return dict(_ATTR.findall(rest)), ""


# Group-title vocabulary, consulted **only** when the URL says nothing. Matched on word
# boundaries against the lowercased group so that "Movies" hits and "Moviestar TV" does not.
# English plus the four languages that turn up most often in provider exports.
_GROUP_VOD = re.compile(
    r"(?i)\b(vod|movie|movies|film|films|filme|filmes|cine|cinema|peliculas|"
    r"pel[ií]culas|kino|videoteca)\b")
_GROUP_SERIES = re.compile(
    r"(?i)\b(series|serie|s[ée]ries|serien|s[ée]rie|tv ?shows?|boxsets?|box ?sets?|"
    r"seasons?|staffel)\b")


def _classify(url: str, group: str = "") -> str:
    """Guess live / vod / series from the URL shape, falling back to the group title.

    Xtream builds `/live/<u>/<p>/<id>.ts`, `/movie/<u>/<p>/<id>.mp4` and `/series/...`, and when
    one of those segments is present it is **authoritative** -- the provider is telling us what
    the item is, and a group title never overrides it.

    The fallback is the fix for a real and quiet failure. A plain M3U export -- not one built
    from the Xtream API -- routinely lists a film as `http://host/12345.mp4` under
    `group-title="VOD | Movies"`. There is no `/movie/` segment anywhere in that URL, so the old
    unconditional `return "live"` marked every such film as a live channel, and a UI that
    filters `kind == "vod"` to fill a Movies section showed an empty section however the
    frontend spelled the category name. The group title is the only signal those playlists carry
    and it was being ignored.

    **The cost, stated plainly:** a genuinely linear channel whose group is named for films --
    "24/7 Movies", "Cinema Live" -- now classifies as `vod`. That is a real misclassification
    and it is the better trade: it moves one always-on channel into the Movies list, where it
    at least belongs thematically, instead of hiding every actual film from it. The default when
    neither signal says anything is still `live`, which is what the great majority of a channel
    list is.
    """
    low = url.lower()
    if "/movie/" in low or "/vod/" in low:
        return "vod"
    if "/series/" in low:
        return "series"
    if "/live/" in low:
        # `live` as an *explicit* answer, not as the default. Without this line the group title
        # would outrank the provider on `/live/<u>/<p>/1.ts` under `group-title="VOD | Movies"`,
        # which is a real playlist shape -- a genuinely linear channel filed in a film category
        # -- and the whole rule above is that the URL wins when the URL says anything.
        return "live"
    g = group or ""
    if g:
        # Series first: "TV Series | Movies & Boxsets" is a series group, and a group naming
        # both is far more often a series shelf than a film shelf.
        if _GROUP_SERIES.search(g):
            return "series"
        if _GROUP_VOD.search(g):
            return "vod"
    return "live"


def parse_m3u(text: str) -> tuple[list[Channel], bool]:
    """Parse a channel playlist. Returns (channels, truncated).

    Tolerant by design -- these files are generated by hundreds of different panels and half of
    them are slightly malformed. Specifically:

    - a UTF-8 BOM, CRLF line endings and trailing whitespace are all absorbed;
    - `#EXTM3U` is not required (plenty of exports omit it) and its attributes are ignored;
    - `#EXTGRP:` sets the group for the following entry, which is the older way of doing what
      `group-title` does now;
    - `#EXTVLCOPT:`, `#KODIPROP:`, `#EXT-X-*` and any other directive are skipped rather than
      treated as a URL;
    - a bare URL with no preceding `#EXTINF` is kept, named from its filename, because dropping
      it would be discarding a channel the visitor can see in their own file;
    - an `#EXTINF` with no following URL is dropped, because there is nothing to play.

    What it will not do is invent anything. An entry with no name is named from its URL's last
    path segment, and if that is empty it is named "(unnamed)" -- not "Channel 1", which reads
    like real metadata and is not.
    """
    channels: list[Channel] = []
    truncated = False
    pending: Channel | None = None
    pending_group = ""

    for raw in text.lstrip("﻿").splitlines():
        line = raw.strip()
        if not line:
            continue

        if line.startswith("#"):
            m = _EXTINF.match(line)
            if m:
                attrs, name = _split_extinf(m.group(2))
                lower = {k.lower(): v for k, v in attrs.items()}
                pending = Channel(
                    name=name or lower.get("tvg-name", "") or "(unnamed)",
                    url="",
                    tvg_id=lower.get("tvg-id", ""),
                    tvg_name=lower.get("tvg-name", ""),
                    logo=lower.get("tvg-logo", "") or lower.get("logo", ""),
                    group=lower.get("group-title", "") or pending_group,
                    duration=float(m.group(1)),
                )
                continue
            if line.upper().startswith("#EXTGRP:"):
                pending_group = line.split(":", 1)[1].strip()
                if pending is not None and not pending.group:
                    pending.group = pending_group
                continue
            # Every other directive, including HLS tags that have no business here.
            continue

        # A non-comment line is a URL.
        if pending is None:
            tail = line.rsplit("/", 1)[-1].split("?", 1)[0]
            pending = Channel(name=tail or "(unnamed)", url="", group=pending_group)
        pending.url = line
        pending.kind = _classify(line, pending.group)
        channels.append(pending)
        pending = None
        if MAX_CHANNELS and len(channels) >= MAX_CHANNELS:
            truncated = True
            break

    return channels, truncated


# ---------------------------------------------------------------- HLS

@dataclass
class HlsVariant:
    uri: str
    bandwidth: int = 0
    resolution: str = ""


@dataclass(frozen=True)
class HlsKey:
    """One `#EXT-X-KEY`. Attached to every segment it governs, not to the playlist.

    Per-segment rather than per-playlist because HLS rotates keys mid-playlist -- a new
    `#EXT-X-KEY` applies from the segment after it to the next one, and `METHOD=NONE` in the
    middle of a playlist genuinely means "the rest of this is in the clear". A single
    playlist-level flag cannot express either, and a pump that assumed one key for the whole
    list would decrypt cleartext segments into noise the moment a provider rotated.
    """
    method: str = "NONE"          # NONE | AES-128 | SAMPLE-AES | SAMPLE-AES-CTR | anything
    uri: str = ""                 # where to fetch the key. Relative URIs are common.
    iv: str = ""                  # `0x...` hex, or empty -- then the sequence number is the IV
    #: `identity` means "the URI is the key". Anything else -- `urn:uuid:edef8ba9-...` is
    #: Widevine, `com.apple.streamingkeydelivery` is FairPlay -- is DRM wearing an AES-128
    #: METHOD, and there is no key at the other end of that URI that we could use.
    keyformat: str = "identity"

    @property
    def encrypted(self) -> bool:
        return self.method.upper() not in ("", "NONE")


NO_KEY = HlsKey()


@dataclass
class HlsSegment:
    uri: str
    duration: float = 0.0
    sequence: int = 0
    key: HlsKey = NO_KEY


@dataclass
class HlsPlaylist:
    """Either a master playlist (`variants` non-empty) or a media playlist (`segments`)."""
    variants: list[HlsVariant] = field(default_factory=list)
    segments: list[HlsSegment] = field(default_factory=list)
    target_duration: float = 6.0
    media_sequence: int = 0
    ended: bool = False           # #EXT-X-ENDLIST -- a VOD-shaped playlist, not a live one

    @property
    def is_master(self) -> bool:
        return bool(self.variants) and not self.segments

    @property
    def keys(self) -> list[HlsKey]:
        """Every distinct encryption key in effect over this playlist's segments."""
        out: list[HlsKey] = []
        for seg in self.segments:
            if seg.key.encrypted and seg.key not in out:
                out.append(seg.key)
        return out

    @property
    def encrypted(self) -> bool:
        """True if any segment is encrypted at all -- by any method, supported or not.

        Kept as a property with the name it had as a field, because it is the honest one-line
        answer to "does this need a key?" and callers still ask it. What changed is that
        answering `True` no longer means "refuse": see `sessions.py`, which branches on METHOD.
        """
        return any(seg.key.encrypted for seg in self.segments)


_ATTR_LIST = re.compile(r'([A-Za-z0-9-]+)=("[^"]*"|[^,]*)')


def _attrs(s: str) -> dict[str, str]:
    return {k.upper(): v.strip('"') for k, v in _ATTR_LIST.findall(s)}


def parse_hls(text: str) -> HlsPlaylist:
    """Parse an HLS master or media playlist.

    Only the tags the pump acts on are interpreted. `EXT-X-KEY` is parsed in full -- METHOD,
    URI, IV and KEYFORMAT -- and attached to each segment it governs, because the pump can now
    decrypt `AES-128` and must be able to tell that apart from `SAMPLE-AES` (which it refuses)
    and from DRM (which wears an AES-128 METHOD and has no usable key). Reporting a single
    playlist-level boolean was what forced the old blanket refusal.
    """
    pl = HlsPlaylist()
    seq = None
    pending_duration = 0.0
    pending_variant: HlsVariant | None = None
    current_key = NO_KEY

    for raw in text.lstrip("﻿").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            upper = line.upper()
            if upper.startswith("#EXT-X-STREAM-INF"):
                a = _attrs(line.split(":", 1)[1] if ":" in line else "")
                try:
                    bw = int(a.get("BANDWIDTH") or a.get("AVERAGE-BANDWIDTH") or 0)
                except ValueError:
                    bw = 0
                pending_variant = HlsVariant(uri="", bandwidth=bw,
                                             resolution=a.get("RESOLUTION", ""))
            elif upper.startswith("#EXT-X-TARGETDURATION"):
                try:
                    pl.target_duration = float(line.split(":", 1)[1])
                except (ValueError, IndexError):
                    pass
            elif upper.startswith("#EXT-X-MEDIA-SEQUENCE"):
                try:
                    pl.media_sequence = int(line.split(":", 1)[1])
                except (ValueError, IndexError):
                    pass
            elif upper.startswith("#EXT-X-ENDLIST"):
                pl.ended = True
            elif upper.startswith("#EXT-X-KEY"):
                # Applies from here to the next #EXT-X-KEY. `#EXT-X-SESSION-KEY` is deliberately
                # not matched (it does not start with `#EXT-X-KEY`): it only announces a key so
                # a player can pre-fetch it, and encrypts nothing by itself.
                a = _attrs(line.split(":", 1)[1] if ":" in line else "")
                current_key = HlsKey(
                    method=(a.get("METHOD") or "NONE").strip().upper(),
                    uri=(a.get("URI") or "").strip(),
                    iv=(a.get("IV") or "").strip(),
                    keyformat=(a.get("KEYFORMAT") or "identity").strip())
            elif upper.startswith("#EXTINF"):
                try:
                    pending_duration = float(line.split(":", 1)[1].split(",")[0])
                except (ValueError, IndexError):
                    pending_duration = 0.0
            continue

        if pending_variant is not None:
            pending_variant.uri = line
            pl.variants.append(pending_variant)
            pending_variant = None
            continue

        if seq is None:
            seq = pl.media_sequence
        pl.segments.append(HlsSegment(uri=line, duration=pending_duration, sequence=seq,
                                      key=current_key))
        seq += 1
        pending_duration = 0.0

    return pl
