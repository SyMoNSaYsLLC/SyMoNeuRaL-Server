"""The playlist directory: what OBS wrote, and which of it is live.

    from live.lib import hls
    hls.scan()            # -> [Session, ...], newest first
    hls.live_session()    # -> the one being written right now, or None

This module is the whole of the video path and it deliberately holds no network code, no
credentials and no obs-websocket. It reads a directory. That separation is the point: the
bridge in `obs.py` needs a password and can be down, and if watching a stream depended on it
then a mistyped secret would take the video off the site. It does not. A visitor can watch
before the password has ever been configured.

## Live and VOD are the same files

OBS writes HLS: one `.m3u8` playlist and a run of `.ts` segments beside it. While it is
recording, the playlist grows a line per segment. When it stops, the muxer appends
`#EXT-X-ENDLIST` and the same playlist becomes a complete VOD. There is no second recording
and nothing is re-encoded, which is what makes "live on the site AND watchable after" one
output rather than two.

## Why there are three states and not two

The obvious reading is `#EXT-X-ENDLIST` present = finished, absent = live. That is wrong in
exactly the case that matters. If OBS is killed, crashes, or the box loses power mid-stream,
the muxer never gets to write its trailer, so the playlist sits there with no `ENDLIST`
forever -- and a two-state rule would light the LIVE lamp on the site permanently, on a page
whose whole argument is that its indicators reflect real readings. Every LED here is a real
one (`.claude/CLAUDE.md`: "no decorative status indicators"), so:

    finished    trailer present. A VOD. Never changes again.
    live        no trailer, and the playlist was written to within LIVE_WINDOW_S.
    abandoned   no trailer, and it has not been touched since. OBS died. Watchable as a VOD,
                honestly labelled as incomplete, and NOT reported as live.

`abandoned` is a reading, not a repair. Nothing here rewrites a playlist to add the trailer a
crash lost: a file OBS is about to append to is not ours to edit, and the difference between
"finished cleanly" and "we decided it had finished" is precisely the kind of thing this repo
does not paper over.

## Why nothing is ever deleted

An earlier draft pruned to the newest N sessions. That deletes his recordings -- the ones he
asked to be "available to watch after im done streaming" -- on a timer, to solve a problem
that does not exist yet: `/home` has ~1 TB free, measured 2026-08-21. So retention is manual
and `usage()` exists to make the number visible on the page instead. Renders are pruned to 60
because a render is a byproduct of a request; a recording is the thing the user made.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

# `backend/output/live`, beside the renders, and NOT in `site/`.
#
# `site/` is the staging directory this repo builds into; the web server serves
# `/var/www/symoneural`. A file written to `site/` therefore 404s for every visitor until
# somebody runs a deploy, and `scripts/deploy.sh` then copies it into the public webroot --
# which is how nineteen unreferenced renders ended up published. That was fixed by moving
# renders to `backend/output/` and serving them from `/api/gen/<name>`; this is the same fix
# applied on arrival rather than after the bug. A stream is a much worse thing to get wrong:
# segments arrive every few seconds, so the deploy race is permanent rather than occasional.
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output" / "live"

# How recently the playlist must have been written for "no trailer" to mean "live".
#
# The floor is the segment length: with `hls_time=2` the playlist is rewritten roughly every
# two seconds, so anything above that is slack rather than a race. Twenty is generous enough
# to survive a stalled encoder or a slow disk without flickering the lamp, and short enough
# that a killed OBS stops claiming to be live within one screen refresh.
LIVE_WINDOW_S = 20.0

# What may appear in a URL and reach the filesystem.
#
# The name comes off the wire and lands in a path, so this matches the exact shape rather than
# trying to strip traversal out of arbitrary input -- the same reasoning `/api/gen/{name}`
# gives for its `re.fullmatch`. No slashes, no dots outside the extension, no spaces.
#
# The space matters more than it looks. OBS's default FilenameFormatting is
# `%CCYY-%MM-%DD %hh-%mm-%ss`, which produces `2026-08-21 10-30-00.m3u8` and is NOT servable
# by this pattern. `README.md` therefore has him set a formatting string with an underscore,
# and `scan()` reports such a file as unservable instead of skipping it -- see below.
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
PLAYLIST_RE = re.compile(SAFE_NAME.pattern + r"\.m3u8")
SEGMENT_RE = re.compile(SAFE_NAME.pattern + r"\.(?:ts|m4s|mp4)")

ENDLIST = "#EXT-X-ENDLIST"
_EXTINF = re.compile(r"^#EXTINF:\s*([0-9.]+)", re.M)


@dataclass
class Session:
    """One recording: its playlist, its state, and what it costs on disk."""

    name: str                    # the playlist filename, e.g. `2026-08-21_10-30-00.m3u8`
    stem: str                    # the same without `.m3u8`; the human label
    state: str                   # live | finished | abandoned
    started: float               # epoch seconds, from the playlist's ctime
    modified: float              # epoch seconds, last append
    seconds: float               # summed #EXTINF durations -- what a player will show
    segments: int
    bytes: int
    servable: bool = True
    detail: str = ""             # why it is not servable, when it is not

    def as_dict(self) -> dict:
        d = {"name": self.name, "stem": self.stem, "state": self.state,
             "started": round(self.started, 3), "modified": round(self.modified, 3),
             "seconds": round(self.seconds, 3), "segments": self.segments,
             "bytes": self.bytes, "servable": self.servable}
        if self.servable:
            d["playlist_url"] = f"/api/live/hls/{self.name}"
        if self.detail:
            d["detail"] = self.detail
        return d


def _duration(text: str) -> float:
    """Summed `#EXTINF` values.

    Read out of the playlist rather than taken from segment count x target duration, because
    the last segment of a stopped recording is almost always short and the difference is
    visible to anyone with a stopwatch.
    """
    total = 0.0
    for hit in _EXTINF.finditer(text):
        try:
            total += float(hit.group(1))
        except ValueError:      # a half-written line; the next scan will see it whole
            continue
    return total


def _segment_bytes(directory: Path, stem: str) -> tuple[int, int]:
    """(count, bytes) for the segments belonging to one playlist.

    ffmpeg's hls muxer names segments after the playlist by default -- `<stem>0.ts`,
    `<stem>1.ts` -- so the prefix is the ownership relation. Counted from disk rather than
    from the playlist's own lines because a rolling window playlist (`hls_list_size` > 0)
    lists fewer segments than exist, and the disk figure is the one an operator wants.
    """
    count = 0
    size = 0
    for f in directory.glob(f"{stem}*"):
        if f.suffix in (".ts", ".m4s", ".mp4") and f.is_file():
            count += 1
            try:
                size += f.stat().st_size
            except OSError:     # deleted between glob and stat
                continue
    return count, size


def scan(directory: Path | None = None, now: float | None = None) -> list[Session]:
    """Every recording in the directory, newest first.

    Never raises. This is read on a request path and by a status endpoint that must answer
    even when the directory does not exist -- which is the normal state of a fresh checkout,
    and is not an error.
    """
    directory = OUTPUT_DIR if directory is None else directory
    now = time.time() if now is None else now
    out: list[Session] = []
    if not directory.is_dir():
        return out

    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix != ".m3u8":
            continue
        try:
            st = path.stat()
            text = path.read_text(errors="replace")
        except OSError:
            continue

        # An unservable playlist is REPORTED, not skipped. A stream that is recording
        # perfectly well in OBS and is invisible on the site with nothing in any log to read
        # is this repo's most expensive failure shape -- see #94 -- and the one cause here is
        # a filename OBS was configured to write and the URL pattern refuses. Saying so on
        # `/api/live/state` turns twenty minutes of hunting into one line.
        servable = PLAYLIST_RE.fullmatch(path.name) is not None
        detail = "" if servable else (
            f"{path.name!r} cannot appear in a URL. Set OBS's Filename Formatting to "
            f"%CCYY-%MM-%DD_%hh-%mm-%ss -- the default contains a space.")

        finished = ENDLIST in text
        if finished:
            state = "finished"
        elif now - st.st_mtime <= LIVE_WINDOW_S:
            state = "live"
        else:
            state = "abandoned"
            if not detail:
                detail = (f"no {ENDLIST} and nothing written for "
                          f"{int(now - st.st_mtime)}s — OBS stopped without closing the "
                          f"playlist. Playable, but the tail may be short.")

        count, size = _segment_bytes(directory, path.stem)
        out.append(Session(name=path.name, stem=path.stem, state=state,
                           started=st.st_ctime, modified=st.st_mtime,
                           seconds=_duration(text), segments=count,
                           bytes=size + st.st_size, servable=servable, detail=detail))

    out.sort(key=lambda s: s.modified, reverse=True)
    return out


def live_session(directory: Path | None = None,
                 now: float | None = None) -> Session | None:
    """The one being written right now, or None.

    Newest wins if two are somehow live at once. That should not happen -- OBS has one
    recording output -- but "should not happen" is not a reason to return an arbitrary one.
    """
    for s in scan(directory, now):
        if s.state == "live" and s.servable:
            return s
    return None


def vods(directory: Path | None = None, now: float | None = None) -> list[Session]:
    """Everything watchable that is not the live stream, newest first.

    `abandoned` is included on purpose. It is a real recording with a real duration and he
    asked to be able to watch what he streamed; hiding it because the trailer is missing
    would be silently discarding his work. It carries its own `detail` saying what happened,
    which is the honest version of the same information.
    """
    return [s for s in scan(directory, now)
            if s.state in ("finished", "abandoned") and s.servable]


def usage(directory: Path | None = None) -> dict:
    """Total bytes and session count.

    Exists because nothing here deletes anything (see the module docstring), so the number
    has to be visible somewhere or unbounded growth is invisible until the disk fills.
    """
    sessions = scan(directory)
    return {"sessions": len(sessions),
            "bytes": sum(s.bytes for s in sessions),
            "directory": str(directory or OUTPUT_DIR)}


def resolve(name: str, directory: Path | None = None) -> Path | None:
    """A URL path component to a file on disk, or None.

    The only place a caller-supplied string becomes a path. Both patterns are anchored
    `fullmatch`, so `..`, `/`, a leading dot and a trailing space are all rejected before any
    filesystem call -- and the `is_file()` at the end is checked against the resolved path
    being inside the directory, because a symlink planted in the output directory would
    otherwise satisfy a perfectly well-formed name.
    """
    directory = OUTPUT_DIR if directory is None else directory
    if not (PLAYLIST_RE.fullmatch(name) or SEGMENT_RE.fullmatch(name)):
        return None
    candidate = directory / name
    try:
        real = candidate.resolve(strict=True)
        root = directory.resolve(strict=True)
    except OSError:
        return None
    if root not in real.parents or not real.is_file():
        return None
    return real
