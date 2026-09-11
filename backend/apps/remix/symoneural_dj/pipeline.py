"""The job pipeline: taste profile -> generate -> resolve -> create.

run_job is the coroutine POST /playlist backgrounds. Its contract: the job
ALWAYS lands in a terminal state — cancellation, engine faults and Spotify
faults included — so no poller ever watches a job that silently stopped.
"""
from __future__ import annotations

import asyncio
import json
import logging

from . import httpclient

from . import cover
from .jobs import TERMINAL_STATES, Job, JobJournal
from .matching import pick_track
from .spotify import SpotifyAuthError, SpotifyClient
from .symon_client import _SYSTEM_PROMPT, PlaylistGenerationError, SymonClient


async def run_job(
    job: Job,
    spotify: SpotifyClient,
    symon: SymonClient,
    journal: JobJournal | None = None,
    meter=None,
    hold_id=None,
    capture=None,
) -> None:
    """`meter`+`hold_id` carry the SyMoN-token charge: the tokens are held
    before the job starts; here they are SETTLED on success and RELEASED
    (refunded) on any failure or cancellation. A None hold means free (owner).
    """
    try:
        await _run(job, spotify, symon, capture)
    except asyncio.CancelledError:
        job.fail("cancelled")
        raise
    except PlaylistGenerationError as exc:
        job.raw_llm_output = exc.raw
        job.fail(f"symon produced unusable output after one retry: {exc}")
    except SpotifyAuthError as exc:
        job.fail(str(exc))
    except httpclient.HTTPError as exc:
        job.fail(f"upstream call failed: {exc}")
    except Exception as exc:  # a bug — but the job must still land terminal
        job.fail(f"internal error: {exc!r}")
    finally:
        if job.state not in TERMINAL_STATES:
            job.fail("job ended without reaching a terminal state")
        # Money: a paying member's playlist only charges when it actually
        # succeeds; any failure refunds the hold. Never lets billing raise
        # into the job result.
        if meter is not None:
            try:
                if job.state == "done":
                    job.charged = meter.settle(hold_id).get("charged", 0)
                else:
                    meter.release(hold_id)
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "job %s: charge settle/release failed: %s", job.id, exc)
        if journal is not None:
            try:
                journal.append(job)
            except Exception as exc:  # journaling must never mask the job result
                logging.getLogger(__name__).warning(
                    "job %s: journal append failed: %s", job.id, exc
                )


async def _fetch_taste(spotify: SpotifyClient, user: str) -> tuple[str | None, str | None]:
    """(summary, error). Taste is an enhancement, never a blocker."""
    try:
        return await spotify.taste_summary(user), None
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return None, str(exc) or exc.__class__.__name__


def _compose_blend(sections: list[tuple[str, str]]) -> str:
    """Clearly separated per-person sections + the balancing instruction."""
    parts = [
        "This playlist is a BLEND for multiple listeners. Balance the "
        "selections fairly across ALL of their tastes while honoring the "
        "request — every listener should hear themselves in it."
    ]
    for label, summary in sections:
        parts.append(f"--- {label} ---\n{summary}")
    return "\n".join(parts)


async def _run(job: Job, spotify: SpotifyClient, symon: SymonClient, capture=None) -> None:
    job.state = "generating"
    taste = None
    if job.blend_with:
        # Blend implies profiles: fetch the primary's and every blend user's.
        listeners = [job.user, *job.blend_with]
        job.progress = f"fetching taste profiles ({len(listeners)} listeners)"
        sections: list[tuple[str, str]] = []
        for i, listener in enumerate(listeners):
            entry = spotify.store.get_user(listener) or {}
            label = entry.get("display_name") or listener
            if i == 0:
                label += " (primary)"
            summary, err = await _fetch_taste(spotify, listener)
            if summary:
                sections.append((label, summary))
            else:
                job.blend_skipped.append(
                    {"user": listener, "reason": err or "no taste data"}
                )
        if sections:
            taste = _compose_blend(sections)
    elif job.use_taste_profile:
        job.progress = "fetching taste profile"
        taste, _ = await _fetch_taste(spotify, job.user)
    job.progress = "asking symon (40-90s)"
    suggested_name, wanted = await symon.generate_playlist(
        job.prompt, job.track_count, taste
    )

    job.state = "resolving"
    # symon over-delivers candidates (2x the target); walk the list until the
    # target lands, so a dud suggestion costs a search, not a playlist slot.
    target = job.track_count
    uris: list[str] = []
    seen: set[str] = set()
    dropped: list[dict] = []
    for item in wanted:
        if len(uris) >= target:
            break
        results = await spotify.search_track(job.user, item["artist"], item["track"])
        match = pick_track(item["artist"], results)
        uri = match.get("uri") if match else None
        if not uri:
            dropped.append(
                {
                    "artist": item["artist"],
                    "track": item["track"],
                    "reason": "no search results" if not results else "artist mismatch",
                }
            )
        elif uri not in seen:  # de-dupe, keeping first-seen order
            seen.add(uri)
            uris.append(uri)
        job.progress = f"resolved {len(uris)}/{target}"
    job.tracks_dropped = dropped
    if not uris:
        job.fail("none of the suggested tracks could be resolved on Spotify")
        return

    job.state = "creating"
    playlist_name = job.name or suggested_name or f"symon dj: {job.prompt[:50]}"
    playlist = await spotify.create_playlist(
        job.user, playlist_name, job.public, job.prompt
    )
    await spotify.add_tracks(job.user, playlist["id"], uris)

    # Cover art is a bonus, never a blocker: any failure is logged onto the
    # job as "skipped: <why>" and the job still finishes.
    job.progress = "uploading cover art"
    try:
        art = cover.render_cover(playlist_name, job.prompt)
        await spotify.upload_cover(job.user, playlist["id"], art)
        job.cover = "ok"
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "job %s: cover upload skipped: %s", job.id, exc
        )
        job.cover = f"skipped: {exc}"
    job.playlist_id = playlist["id"]
    job.playlist_url = (playlist.get("external_urls") or {}).get(
        "spotify"
    ) or f"https://open.spotify.com/playlist/{playlist['id']}"
    job.tracks_added = len(uris)
    job.progress = f"added {len(uris)} tracks"
    job.state = "done"

    # Data pump: bank symon's own tracklist as a commercial-clean training
    # pair, graded by how many tracks actually resolved on Spotify. Never let
    # capture raise into the job result.
    if capture is not None:
        try:
            messages = [
                {"role": "system", "content": _SYSTEM_PROMPT.replace("{count}", str(job.track_count))},
                {"role": "user", "content": job.prompt},
                {"role": "assistant",
                 "content": json.dumps({"name": suggested_name, "tracks": wanted},
                                       ensure_ascii=False)},
            ]
            capture(messages,
                    {"added": job.tracks_added, "dropped": len(job.tracks_dropped)},
                    {"job_id": job.id, "user": job.user})
        except Exception as exc:
            logging.getLogger(__name__).warning("job %s: capture failed: %s", job.id, exc)
