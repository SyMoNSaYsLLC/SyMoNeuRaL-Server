"""The HTTP surface. Mounted at `/api/streamer` by `api.py`; nothing here assumes that prefix.

**Every credential arrives in a POST body and never in a URL.** That is not fussiness: uvicorn's
access log records the full request line, so a password in a query string or a path segment is a
password written to `run/api.log` on every request. There is consequently no `GET` route on this
router that takes a credential, and there never may be.

**Nothing is stored.** There is no server-side notion of "the visitor's playlist" -- the browser
holds the playlist and the credentials in localStorage and sends what it needs per request. The
one piece of server state is an active `Session`, which holds an upstream URL in memory for as
long as it is playing and takes it to the grave when it is reaped.
"""
from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from .lib import epg
from .lib import safefetch
from .lib import xtream
from .apps.m3u import MAX_CHANNELS, parse_m3u
from .lib.safefetch import BlockedURL, FetchError, Policy, Scrubber
from .lib.sessions import (MANAGER, MAX_SESSIONS, PLAYLIST_NAME, SEGMENT_RE, FFMPEG,
                       StreamerBusy, StreamerError)
from .lib.xtream import XtreamCreds, XtreamError

log = logging.getLogger("symoneural.streamer")

router = APIRouter(tags=["streamer"])

#: A pasted playlist. `0` means no limit, and `0` is the default at the owner's instruction
#: (2026-08-17) — provider exports genuinely are tens of megabytes and every ceiling picked here
#: has so far been someone's missing Movies section.
MAX_PASTE = 0

#: How long `POST /tune` waits for ffmpeg to write a playable playlist before handing the
#: session back for the client to poll.
#:
#: **Measured on this machine**, feeding a 1.9 Mb/s H.264/AAC transport stream into the exact
#: argv `sessions._spawn` builds, at four throttled rates, timing the appearance of
#: `live.m3u8`:
#:
#:     unthrottled   0.1 s      8 Mb/s   2.5 s      2 Mb/s   9.7 s      0.8 Mb/s   24.1 s
#:
#: The old value was 10 s, which a stream delivered at 2 Mb/s -- an entirely ordinary IPTV
#: rate, and what a provider that paces at real time gives you -- misses by a fraction of a
#: second. Every such stream returned "no playable output yet" on a request that was about to
#: succeed. 25 s covers the measured range down to 0.8 Mb/s.
#:
#: The same measurement is why `-probesize`/`-analyzeduration` were **left alone**: repeating it
#: at 2M, 5M and 10M produced times identical to within 0.1 s at every rate. Time to first
#: playlist is bounded by how much data the HLS muxer needs to close its first segment, not by
#: the probe. Raising the probe would have been a guess dressed as a fix.
TUNE_WAIT_SECONDS = 25.0


# ---------------------------------------------------------------- models
#
# Every credential-bearing field has a default. That is deliberate and it is a leak fix, not
# laziness: a *missing* required field makes pydantic raise a ValidationError whose `input` is
# the whole request body, and FastAPI serialises that into the 422 response -- so omitting
# `server` would echo the password back inside an error document. With defaults there is no
# validation path that can touch these values, and the handlers check them by hand and answer
# with a message we wrote.

class PlaylistBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    url: str = ""
    text: str = ""


class XtreamBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    server: str = ""
    username: str = ""
    password: str = ""
    kinds: list[str] = Field(default_factory=lambda: ["live"])


class EpgBody(XtreamBody):
    """One channel's guide, or a grid's worth.

    Subclasses `XtreamBody` so the credential defaults and the `extra="ignore"` contract are
    inherited rather than restated -- `kinds` comes along unused, which is harmless, and losing
    the "every credential field has a default" leak fix would not be.
    """
    #: One stream id, or many. Both are accepted on the same route because the grid and the
    #: focused row are the same question asked at different widths, and two routes that build
    #: the same URL is how they drift apart.
    stream_id: str = ""
    stream_ids: list[str] = Field(default_factory=list)
    limit: int = 0


class XmltvBody(XtreamBody):
    #: `tvg_id` values to keep. Empty means keep everything, which on a real account is 10,124
    #: channels and 31 MB -- allowed, but the caller has to ask for it explicitly by omitting
    #: this, rather than getting it because a filter was forgotten.
    ids: list[str] = Field(default_factory=list)
    max_per_channel: int = 0


class TuneBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    url: str = ""
    label: str = ""
    # Optional, and only ever used to prime the scrubber so this session's own credentials can
    # be recognised inside ffmpeg's stderr. Not stored, not echoed.
    username: str = ""
    password: str = ""
    #: The session this client is finished with, released before the new one is allocated.
    #:
    #: Changing channel is the common case and it used to leak a slot every time: the page threw
    #: its `sid` away and the old session lived on until the idle reaper noticed. On a two-slot
    #: surface that meant the third channel a visitor clicked was refused. Doing it here rather
    #: than as a separate `DELETE` is deliberate -- a client that stops and then starts can lose
    #: the slot it just freed to another visitor in between, and a channel change should not be
    #: able to fail because of that race.
    release: str = ""


def _creds(body: XtreamBody) -> XtreamCreds:
    if not body.server.strip():
        raise HTTPException(400, "no server address given")
    if not body.username or not body.password:
        raise HTTPException(400, "username and password are both required")
    if len(body.server) > 512 or len(body.username) > 256 or len(body.password) > 256:
        raise HTTPException(400, "credentials are implausibly long")
    return XtreamCreds(server=body.server.strip(), username=body.username,
                       password=body.password)


# ---------------------------------------------------------------- playlist

@router.post("/playlist", summary="Parse an M3U playlist supplied by URL or pasted text")
async def load_playlist(body: PlaylistBody) -> dict:
    """Turn a playlist into a channel list. Nothing is kept.

    The whole parsed list comes back in one response rather than being paged, because paging
    would require the server to remember the playlist between requests -- and the entire
    credential design here rests on the server remembering nothing. The browser holds it.
    `MAX_CHANNELS` bounds the parse and `truncated` says plainly when it bit.
    """
    text = body.text
    source = "pasted"
    if body.url.strip():
        source = "url"
        try:
            raw, _ctype, target = await asyncio.to_thread(
                safefetch.fetch, body.url.strip(), Policy())
        except BlockedURL as exc:
            raise HTTPException(400, f"that playlist URL was refused: {exc}") from None
        except FetchError as exc:
            raise HTTPException(502, f"could not fetch that playlist: {exc}") from None
        text = raw.decode("utf-8", "replace")
    if not text.strip():
        raise HTTPException(400, "supply either a playlist URL or the playlist text")
    if MAX_PASTE and len(text) > MAX_PASTE:
        raise HTTPException(413, "playlist is too large")

    channels, truncated = await asyncio.to_thread(parse_m3u, text)
    groups: list[str] = []
    seen = set()
    for c in channels:
        if c.group and c.group not in seen:
            seen.add(c.group)
            groups.append(c.group)
    return {
        "source": source,
        "count": len(channels),
        "truncated": truncated,
        "limit": MAX_CHANNELS,
        "groups": groups,
        "channels": [c.__dict__ for c in channels],
    }


# ---------------------------------------------------------------- xtream

@router.post("/xtream/info", summary="Check an Xtream Codes account")
async def xtream_info(body: XtreamBody) -> dict:
    creds = _creds(body)
    try:
        return await asyncio.to_thread(xtream.panel_info, creds, Policy())
    except XtreamError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/xtream/channels", summary="Fetch an Xtream Codes catalogue")
async def xtream_channels(body: XtreamBody) -> dict:
    creds = _creds(body)
    kinds = tuple(k for k in body.kinds if k in ("live", "vod", "series")) or ("live",)
    try:
        entries, notes = await asyncio.to_thread(xtream.load_channels, creds, kinds, Policy())
    except XtreamError as exc:
        raise HTTPException(400, str(exc)) from None
    groups: list[str] = []
    seen = set()
    for e in entries:
        if e["group"] and e["group"] not in seen:
            seen.add(e["group"])
            groups.append(e["group"])
    return {"count": len(entries), "groups": groups, "notes": notes, "channels": entries}


# ---------------------------------------------------------------- guide (EPG)
#
# How many of the panel's own guide requests may be in flight at once. Six, and the number is a
# politeness bound rather than a performance one: the grid asks for one channel per request, so a
# 40-row grid is 40 requests against somebody else's server, and a provider that reads that as
# abuse throttles or bans the account -- the visitor's account, not ours. Six with a 20 s read
# timeout also keeps the worst case for a whole grid inside one page load.
EPG_CONCURRENCY = 6

#: Rows per grid request. 60 is three screens of channels at a normal row height; past that the
#: honest answer is that the visitor should scroll and the page should ask again.
EPG_MAX_IDS = 60


@router.post("/epg", summary="Programme guide for one channel or a grid of them")
async def epg_route(body: EpgBody) -> dict:
    """`get_short_epg` per channel, a few at a time. Returns what the panel actually said.

    Empty is a real answer and is reported as one: `channels` carries a list for every id asked
    about, and an id whose list is empty genuinely has no guide upstream. `failed` is separate
    from that, so "the panel has no data for this channel" and "the request for this channel
    broke" never render the same way.
    """
    creds = _creds(body)
    ids = [str(s).strip() for s in (body.stream_ids or []) if str(s).strip()]
    if body.stream_id.strip():
        ids.insert(0, body.stream_id.strip())
    # dict.fromkeys, not set(): the caller's order is the order the grid draws in, and a set
    # would hand the rows back shuffled for no reason.
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise HTTPException(400, "give a stream_id, or stream_ids for a grid")
    if len(ids) > EPG_MAX_IDS:
        raise HTTPException(413, f"ask for at most {EPG_MAX_IDS} channels of guide at once")

    limit = body.limit or epg.DEFAULT_LIMIT
    gate = asyncio.Semaphore(EPG_CONCURRENCY)
    started = time.monotonic()

    async def one(sid: str) -> tuple[str, list[dict] | None, int, str]:
        async with gate:
            try:
                progs, dropped = await asyncio.to_thread(
                    epg.short_epg, creds, sid, limit, Policy())
            except epg.EpgError as exc:
                return sid, None, 0, str(exc)
            return sid, [p.public() for p in progs], dropped, ""

    results = await asyncio.gather(*(one(s) for s in ids))
    channels: dict[str, list[dict]] = {}
    failed: dict[str, str] = {}
    dropped_total = 0
    for sid, progs, dropped, err in results:
        if progs is None:
            failed[sid] = err
            continue
        channels[sid] = progs
        dropped_total += dropped
    # `now`/`next` are computed here rather than in the browser because the clock that matters
    # is the one the timestamps are on, and a visitor with a wrong system clock would otherwise
    # see a guide that is wrong in a way nothing on the page could explain.
    now = {sid: epg.now_next([epg.Programme(**{k: p[k] for k in ("start", "stop", "title", "desc")})
                              for p in progs])
           for sid, progs in channels.items()}
    return {
        "source": "get_short_epg",
        "asked": len(ids),
        "answered": len(channels),
        "limit": limit,
        "channels": channels,
        "now": now,
        "failed": failed,
        "dropped_no_clock": dropped_total,
        "server_time": int(time.time()),
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "note": "no guide, playlist or credential is stored on this box",
    }


@router.post("/epg/xmltv", summary="The whole account's guide as XMLTV")
async def epg_xmltv_route(body: XmltvBody) -> dict:
    """One request for everything, keyed by `tvg_id`.

    This is the heavy door and it is labelled: measured against one real account the document is
    31 MB for 10,124 channels, so a page that wants now-and-next for what is on screen should
    use `POST /epg` instead. Send `ids` to have the filtering happen during the parse, which is
    where it is nearly free.
    """
    creds = _creds(body)
    wanted = {str(i).strip() for i in body.ids if str(i).strip()} or None
    started = time.monotonic()
    try:
        guide, meta = await asyncio.to_thread(
            epg.xmltv_epg, creds, Policy(), wanted, max(0, int(body.max_per_channel or 0)))
    except epg.EpgError as exc:
        raise HTTPException(502, str(exc)) from None
    return {
        **meta,
        "asked": len(wanted) if wanted else 0,
        "guide": {k: [p.public() for p in v] for k, v in guide.items()},
        "now": {k: epg.now_next(v) for k, v in guide.items()},
        "server_time": int(time.time()),
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "note": "no guide, playlist or credential is stored on this box",
    }


# ---------------------------------------------------------------- tuning

@router.post("/tune", summary="Start a tuning session for one stream URL")
async def tune(body: TuneBody) -> dict:
    """Open the upstream, start ffmpeg, and wait briefly for a playable playlist.

    The wait is the honest part. `POST /tune` could return the moment the process is spawned,
    but ffmpeg on a source it cannot stream-copy exits a few seconds later -- so an immediate
    "ok" would be a status the box has not yet earned. This waits for a real `.m3u8` to appear
    on disk and reports what actually happened.
    """
    url = body.url.strip()
    if not url:
        raise HTTPException(400, "no stream URL given")
    if not FFMPEG:
        raise HTTPException(503, "ffmpeg is not installed on this machine")
    # Free the caller's previous slot first. Unconditional and unvalidated on purpose: an id
    # that is unknown, already reaped, or somebody else's simply stops nothing, and there is no
    # information to leak either way -- `stop_session` answers the same for all three.
    if body.release.strip():
        MANAGER.stop_session(body.release.strip())
    scrub = Scrubber([body.username, body.password])
    try:
        session = await asyncio.to_thread(
            MANAGER.start, url, body.label[:120], Policy(), scrub)
    except StreamerBusy as exc:
        raise HTTPException(503, str(exc)) from None
    except StreamerError as exc:
        raise HTTPException(400, str(exc)) from None

    deadline = time.monotonic() + TUNE_WAIT_SECONDS
    while time.monotonic() < deadline:
        if session.ready:
            session.state = "live" if session.state == "starting" else session.state
            break
        if session.state == "failed":
            MANAGER.stop_session(session.id)
            raise HTTPException(502, session.error or "the stream could not be opened")
        # A client waiting on this request *is* activity on the session, and the reaper measures
        # idleness from the last player request. Without this the wait spends its whole length
        # ageing towards `IDLE_TIMEOUT` without ever being seen as alive.
        MANAGER.touch(session.id)
        await asyncio.sleep(0.25)
    else:
        # Still nothing. Do not claim it is playing; hand back the session so the client can
        # keep polling, and say which state it is actually in.
        #
        # Unless it is already gone: the reaper drops a session the moment its ffmpeg exits, so
        # a long wait can outlive the thing it is waiting for. Handing back an id whose
        # `GET /session/{sid}` answers 404 makes a dead stream look like a broken streamer, which
        # is the exact confusion this whole module is trying to remove.
        if MANAGER.get(session.id) is None:
            raise HTTPException(502, session.error
                                or "the transcoder stopped before producing playable output")
        return {**session.public(), "note": "no playable output yet; poll the session"}
    session.last_seen = time.monotonic()
    return session.public()


@router.get("/session/{sid}", summary="State of one tuning session")
async def session_state(sid: str) -> dict:
    s = MANAGER.touch(sid)
    if not s:
        raise HTTPException(404, "no such session")
    return s.public()


@router.delete("/session/{sid}", summary="Stop a tuning session")
async def session_stop(sid: str) -> dict:
    if not MANAGER.stop_session(sid):
        raise HTTPException(404, "no such session")
    return {"stopped": sid}


@router.post("/session/{sid}/stop", summary="Release a session on page unload")
async def session_release(sid: str) -> dict:
    """The same stop, reachable by `navigator.sendBeacon`, which can only issue a POST.

    This exists because of what a closed tab used to cost. `DELETE` cannot be sent from an
    unload handler with any reliability -- `fetch` is cancelled as the document goes away -- so
    the only signal a leaving visitor could give was silence, and silence took `IDLE_TIMEOUT`
    plus a reaper tick to interpret. On a two-slot surface that is the whole streamer unavailable
    for the best part of a minute after everybody has already left.

    A missing session is **not** an error here. A beacon can arrive after the reaper has already
    collected the session, can be sent twice by a browser that fires both `pagehide` and
    `visibilitychange`, and cannot be retried by a page that no longer exists. Answering 404
    would turn all three into console noise on a page nobody is looking at, for an operation
    whose only purpose is that the slot ends up free -- which it is in every one of those cases.
    """
    return {"stopped": sid, "was_running": MANAGER.stop_session(sid)}


@router.get("/stream/{sid}/{name}", summary="HLS playlist and segments for a session")
async def stream_file(sid: str, name: str) -> Response:
    """Serve one file out of a session directory.

    `name` is checked against an allow-list of the exact filenames ffmpeg was told to write.
    It is never joined to a path before that check, so `..%2f..%2fetc%2fpasswd` fails on being
    an unrecognised name rather than on a traversal check that has to be got right.

    This is also the session's heartbeat: `touch` here is what keeps it alive, so a closed tab
    stops requesting and the reaper takes the slot back.
    """
    if name != PLAYLIST_NAME and not SEGMENT_RE.match(name):
        raise HTTPException(404, "no such file")
    s = MANAGER.touch(sid)
    if not s:
        raise HTTPException(404, "no such session")
    path = s.dir / name
    if not path.is_file():
        raise HTTPException(404, "not ready")
    media = ("application/vnd.apple.mpegurl" if name.endswith(".m3u8")
             else "video/mp2t" if name.endswith(".ts") else "video/iso.segment")
    return FileResponse(
        path, media_type=media,
        # A live playlist that a browser caches is a live playlist that stops updating.
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"})


# ---------------------------------------------------------------- state

@router.get("/state", summary="Streamer capacity and live sessions")
async def state() -> dict:
    """Real readings only: how many slots exist, how many are in use, what they are doing.

    There is no channel count here and no "signal" figure, because with nothing loaded this
    box genuinely holds no channels -- the playlist lives in the visitor's browser. Reporting
    a number the server does not have would be exactly the decorative indicator the house
    rules forbid.
    """
    MANAGER.reap()
    sessions = MANAGER.list()
    return {
        "ffmpeg": bool(FFMPEG),
        "max_sessions": MAX_SESSIONS,
        "active": len(sessions),
        "sessions": [s.public() for s in sessions],
        "channels_stored": 0,
        "note": "no playlist or credential is stored on this box",
    }


def status() -> dict:
    """The rack unit, as a plain dict. Called on every rack poll -- synchronous and cheap.

    Deliberately **not** built from `api.py`'s `Unit` model: importing it would put this module
    inside `api.py`'s import graph and outside the scope this module was built in. The keys
    match `Unit`'s fields so the wiring engineer can splat it into `Unit(**streamer.status())`.

    **This unit is the Streamer: the old Tuner and Guide together.** Garrett: "symon guide
    and symon tuner should be migrated together", then "you need to migrate tuner and guide to
    be 1", and then that the pair migrates to `streamer`. The rack
    carried two units whose `href` was the same page, which is a rack disagreeing with itself.
    Guide's own author had argued for exactly this fold on architecture -- it owns no weights
    and no hardware -- and was overruled only because Garrett had named it separately; he has
    now decided the other way, so the two facts finally agree.

    Nothing about the guide half is dropped in the fold, because both halves make a real and
    different claim about the hardware, and the detail line has to carry both:

      * the streaming half is I/O -- ffmpeg copying bytes, a bounded number of slots;
      * the guide half is **stdlib matching on the CPU that never takes the GPU lock**, which
        is why it answers while chat holds the card. That is the same claim RavenCalc makes and
        it is worth as much here.

    The state is a reading, not a decoration:
      * `offline` when ffmpeg is absent -- the streaming half genuinely cannot work;
      * `busy` when a session holds a slot;
      * `ready` otherwise, meaning the box can accept a source.
    It is never `ready` on the strength of the module merely being importable, and the detail
    line says outright that the box holds no channels of its own, because it does not.

    Note what `offline` now means and does not mean: without ffmpeg the guide half still works
    perfectly -- it needs nothing but the standard library -- so the offline detail names the
    part that is missing rather than implying the whole surface is dead.
    """
    active = len(MANAGER.list())
    # Said in every state, because it is the claim a visitor cannot check by looking: the
    # filtering and the guide grid do not queue behind whatever holds the card.
    guide_note = "guide filtering on the CPU, never takes the GPU lock"
    if not FFMPEG:
        state_ = "offline"
        detail = f"ffmpeg not installed — no streaming · {guide_note}"
    elif active:
        state_ = "busy"
        detail = (f"{active}/{MAX_SESSIONS} slots streaming · "
                  f"stream copy, no GPU · {guide_note} · no channels stored on this box")
    else:
        state_ = "ready"
        detail = (f"0/{MAX_SESSIONS} slots in use · {guide_note} · "
                  f"visitor supplies the playlist; none is stored here")
    return {
        "id": "streamer",
        "label": "SyMoNeuRaL Streamer",
        "slot": "1U",
        "state": state_,
        "bus": "cpu",
        "href": "/streamer.html",
        "spec": "ffmpeg stream copy → HLS · question → channel filter",
        "detail": detail,
    }
