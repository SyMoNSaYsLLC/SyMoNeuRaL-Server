"""SyMoNeuRaL Live's HTTP surface: the video, the catalogue, and the bridge's readings.

    import live
    app.include_router(live.router, prefix="/api/live")   # before the static mount

Five routes, and the split between them is the design:

    GET /api/live/state        readings. Needs the bridge. Degrades to words, never to 503.
    GET /api/live/now          the live playlist, or 404. Needs only the disk.
    GET /api/live/vods         everything watchable afterwards. Needs only the disk.
    GET /api/live/hls/{name}   playlist and segment bytes. Needs only the disk.
    GET /api/live/usage        what the recordings cost, because nothing here deletes them.

**Four of the five never touch obs-websocket.** That is deliberate and it is the whole
robustness argument: a wrong password, a stopped OBS or a changed handshake takes the
telemetry line off the page and leaves the video playing. `hls.py` does not import `obs.py`,
so this cannot be undone by accident later -- the import graph is the guarantee, not a comment.

## Tokenless, and why that is defensible here

The same reasoning `apps/news/routes.py` gives, applied to a bigger surface. Everything served
is either a reading of whether a recording is running, or a video file that OBS was
deliberately configured to write into a directory whose entire purpose is to be served. The
directory is empty until he points OBS at it, so switching this on publishes nothing by
itself.

The one thing withheld by default is the **scene name**, because it is the one field that
describes his setup rather than his stream -- "Desktop", "Webcam + PW dialog", whatever he
happens to have named things. `SYMONEURAL_LIVE_PUBLIC_SCENE=1` publishes it. The default is
the quiet one because a scene name is not something a visitor needs and is exactly the kind of
detail that reads as harmless right up until it is not.

## No range requests, and why that is fine

HLS is already chunked -- that is what the segments are for -- so a player fetches whole
`.ts` files and never asks for a byte range. `FileResponse` handles `Range` itself in any case.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()


def enabled() -> bool:
    """The surface switch, defaulting ON.

    Every other togglable app here defaults off, and this one deliberately does not. Those
    surfaces cost something when switched on -- the GPU, an outbound fetcher, a miner. This
    one serves files out of a directory that is empty unless he has configured OBS to write
    into it, so the default-off version has no safety to offer: it can only produce a tab that
    is broken on arrival for a request marked ASAP. `SYMONEURAL_LIVE_ENABLED=0` turns it off.
    """
    return os.environ.get("SYMONEURAL_LIVE_ENABLED", "1").strip() not in ("0", "false", "no")


def _public_scene() -> bool:
    return os.environ.get("SYMONEURAL_LIVE_PUBLIC_SCENE", "").strip() in ("1", "true", "yes")


LABEL = "SyMoNeuRaL Live"


#: What the row advertises. No bitrate and no latency figure: `README.md`'s own rule is that
#: neither is published until one has been read off a real stream, and a rack row is exactly
#: the place a projected number would get mistaken for a measurement.
SPEC = "OBS Recording · HLS on disk · no media server"


def status() -> dict:
    """The rack unit, keys matching `api.py`'s `Unit` model.

    Read at call time from the disk, every field of it. `state` is decided by what is
    watchable, never by what OBS believes: `state()` above explains why the two are reported
    side by side rather than reconciled, and the same argument applies harder to a rack row --
    a row reading `busy` off a websocket frame while no playlist is growing would be a green
    LED for a stream nobody can watch, which is the decorative-indicator failure this rack
    does not have. So this function does not touch the bridge at all.

    `busy` while a playlist is being appended to. That is this row's own work -- segments
    leaving this box to whoever is watching -- and not somebody else's, which is the line
    `apps/studio.status()` draws when it refuses to go `busy` for a render it merely ordered.

    **`bus` is `net`, not `gpu`, and that is a claim about the governor rather than about
    hardware.** OBS encodes with NVENC and does hold a slice of the card, but it holds it
    outside `scripts/gpu-governor.sh` entirely: the governor cannot see that session, cannot
    evict it, and does not count it against its 1500 MiB drain floor. Publishing `gpu` here
    would put this row in the rack's "who holds the card" readout and imply the governor is
    managing something it has never been told about. What this surface actually spends is
    upstream bandwidth -- `README.md` sizes it at ~0.77 MB/s per visitor -- so `net` is the
    honest bus, and `README.md`'s NVENC section is where the unmeasured GPU cost is recorded
    as unmeasured.
    """
    from . import hls

    if not enabled():
        return {"id": "live", "label": LABEL, "slot": "1U", "state": "offline", "bus": "net",
                "href": "/livestack/live", "spec": SPEC,
                "detail": "switched off by SYMONEURAL_LIVE_ENABLED — unset it to switch back on"}

    sessions = hls.scan()
    current = next((s for s in sessions if s.state == "live" and s.servable), None)
    watchable = sum(1 for s in sessions if s.state in ("finished", "abandoned") and s.servable)
    unservable = sum(1 for s in sessions if not s.servable)

    if current is not None:
        state_ = "busy"
        detail = (f"live now · {current.seconds:.0f} s in {current.segments} segments "
                  f"· {watchable} recorded")
    elif sessions:
        state_ = "ready"
        gb = sum(s.bytes for s in sessions) / 1_000_000_000
        detail = f"{watchable} recording{'' if watchable == 1 else 's'} · {gb:.2f} GB on disk"
    else:
        # `ready`, not `queued`. Nothing is pending: the page works, the routes answer, and
        # the directory is simply empty because OBS has not been pointed at it yet. `queued`
        # would describe an intention, and `Unit.state` has no word for "correct and idle".
        state_ = "ready"
        detail = ("nothing recorded yet — point OBS's Recording output at "
                  f"{hls.OUTPUT_DIR} (apps/live/README.md has the settings)")

    if unservable:
        # Front of the line, the way `exp` counts failed plugins: a name OBS cannot have
        # served is the one thing here that needs a human, and burying it after the totals
        # is how it stays unnoticed.
        detail = f"{unservable} unservable name · " + detail

    return {"id": "live", "label": LABEL, "slot": "1U", "state": state_, "bus": "net",
            "href": "/livestack/live", "spec": SPEC, "detail": detail}


@router.get("/state", summary="Is he live, what is on disk, and what OBS last reported")
def state() -> dict:
    """One read of the directory plus the bridge's last reading.

    Answers 200 in every case, including switched off and bridge down, for the reason
    `apps/news/routes.py` gives: the caller is a page, and a 503 for a normal expected state
    puts a red line in a visitor's console and makes a real outage indistinguishable from
    "nothing is streaming right now".

    `live` comes from the DISK, not from the bridge. OBS reporting `recording: true` while no
    playlist is being written means it is recording somewhere else -- a real and likely
    misconfiguration -- and the page should say what is actually watchable, not what OBS
    believes. The two are reported side by side precisely so that disagreement is visible.
    """
    from . import bridge
    from . import hls

    if not enabled():
        return {"enabled": False, "live": None, "vods": 0, "obs": None,
                "detail": "the live surface is off — unset SYMONEURAL_LIVE_ENABLED "
                          "(or set it to 1) and restart"}

    sessions = hls.scan()
    current = next((s for s in sessions if s.state == "live" and s.servable), None)
    obs_state = bridge.state()
    if not _public_scene():
        obs_state["scene"] = None
        obs_state["scene_withheld"] = True

    # Reported rather than dropped: a playlist OBS is writing perfectly well and this cannot
    # put in a URL is invisible on the site with nothing in any log, which is #94's shape.
    unservable = [{"name": s.name, "detail": s.detail} for s in sessions if not s.servable]

    return {
        "enabled": True,
        "live": current.as_dict() if current else None,
        "vods": sum(1 for s in sessions if s.state in ("finished", "abandoned") and s.servable),
        "sessions": len(sessions),
        "unservable": unservable,
        "obs": obs_state,
        "usage": hls.usage(),
    }


@router.get("/now", summary="The playlist being written right now")
def now() -> dict:
    """404 when nothing is live, which is the normal state and not an error.

    A distinct route from `/state` because a player polling for "has he gone live" wants one
    small answer, and because 404-or-200 is a cheaper thing for `site/live.js` to branch on
    than a null field inside a larger document.
    """
    from . import hls

    if not enabled():
        raise HTTPException(503, "the live surface is off")
    current = hls.live_session()
    if current is None:
        raise HTTPException(404, "nothing is being recorded right now")
    return current.as_dict()


@router.get("/vods", summary="Everything watchable after the fact, newest first")
def vod_list() -> dict:
    from . import hls

    if not enabled():
        return {"enabled": False, "items": [], "count": 0}
    items = [s.as_dict() for s in hls.vods()]
    return {"enabled": True, "items": items, "count": len(items)}


@router.get("/usage", summary="What the recordings cost on disk")
def usage() -> dict:
    """Exists because nothing in this package deletes anything.

    `hls.py` states the reason: a render is a byproduct of a request and is pruned to sixty; a
    recording is the thing the user made and is not ours to delete on a timer. The cost of
    that choice is unbounded growth, so the number is put where somebody will see it.
    """
    from . import hls

    return hls.usage()


@router.get("/hls/{name}", summary="A playlist or one of its segments",
            responses={200: {"content": {"application/vnd.apple.mpegurl": {}, "video/mp2t": {}}},
                       404: {"description": "No such playlist or segment"}})
def hls_file(name: str) -> FileResponse:
    """The bytes. The only route here that takes a caller-supplied string.

    `hls.resolve()` owns the whole of the path handling -- anchored `fullmatch` against the
    exact shape OBS emits, then a resolved-path containment check so a symlink planted in the
    output directory cannot escape it. Nothing is sanitised or stripped here, for the reason
    `/api/gen/{name}` gives: matching the shape the generator emits is a decision that can be
    read, and stripping traversal out of arbitrary input is a decision that has to be trusted.

    ## The cache headers are load-bearing

    A `.m3u8` being appended to must never be cached: a player that re-fetches a stale
    playlist sees the same last segment forever and the stream appears to freeze on a
    perfectly healthy encoder. Segments are the opposite -- content-addressed by name, written
    once, never changed -- so they are `immutable`, which is what lets a viewer scrub a VOD
    without re-downloading. Getting this backwards produces a stream that looks broken in
    exactly the way a network fault does.
    """
    from . import hls

    if not enabled():
        raise HTTPException(503, "the live surface is off")
    path = hls.resolve(name)
    if path is None:
        raise HTTPException(404, "No such playlist or segment.")

    if path.suffix == ".m3u8":
        return FileResponse(path, media_type="application/vnd.apple.mpegurl",
                            headers={"Cache-Control": "no-store"})
    media = {".ts": "video/mp2t", ".m4s": "video/iso.segment",
             ".mp4": "video/mp4"}.get(path.suffix, "application/octet-stream")
    return FileResponse(path, media_type=media,
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})
