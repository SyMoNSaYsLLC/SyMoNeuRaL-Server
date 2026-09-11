"""The playlist generator. Ours, and the reason the DJ is not a streaming-service client.

`pipeline.run_job` imports `_SYSTEM_PROMPT`, `PlaylistGenerationError` and `SymonClient` from here
and calls the model BEFORE it touches any connector. That ordering is the product: a tracklist
comes out of the local model, and a connector is somewhere to put the result. With every connector
removed this file still produces a playlist -- it just has nowhere to push it.

It talks to the SyMoNeuRaL server's `/ask/remix`, so the DJ inherits the platform's rules for free:
one model on the card under the turnstile, and nothing leaving the box.

The model returns JSON and is not trusted to. `parse_tracklist` accepts a fenced block, a bare
object or a bare array, drops rows that are not `{artist, track}`, and de-duplicates -- because a
14B model asked for twenty tracks will occasionally return nineteen and a sentence, or the same
song twice with different capitalisation. Refusing the whole reply over that would make the DJ
fail at a rate the user experiences as "it does not work".

SPDX-License-Identifier: GPL-2.0-or-later
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from . import httpclient

_SYSTEM_PROMPT = """You are the playlist generator for SyMoNeuRaL DJ, a product of Symon Says LLC.

You are given a description of a set and you return the tracklist for it. Reply with JSON and
nothing else: an array of objects, each with exactly "artist" and "track".

  [{"artist": "Nina Simone", "track": "Sinnerman"}, ...]

Rules that come from what a set IS, not from formatting:
  - An ordered set, not a pile of songs. Consecutive tracks should have somewhere to go —
    key, tempo, energy or mood — and the order you return is the order they play.
  - Range over safety. One obvious anchor is fine; twelve is a radio station.
  - Respect the constraints you are given. If one makes the request impossible, return the
    closest honest set rather than quietly dropping it.
  - Real recordings by the artists you name. A track that does not exist resolves to nothing
    and is worse than one fewer track.
"""

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


class PlaylistGenerationError(Exception):
    """The model did not produce a usable tracklist. Terminal for the job."""


@dataclass(frozen=True)
class GeneratedTrack:
    artist: str
    track: str


def parse_tracklist(reply: str) -> list[GeneratedTrack]:
    """Whatever the model said, turned into rows. Raises only when there is nothing usable."""
    text = (reply or "").strip()
    if not text:
        raise PlaylistGenerationError("the model returned nothing")

    if (fenced := _FENCE.search(text)):
        text = fenced.group(1).strip()
    else:
        # No fence: take from the first bracket to the last matching one. A model that prefaces
        # its JSON with "Here is your playlist:" is otherwise a hard failure over a greeting.
        start = min((i for i in (text.find("["), text.find("{")) if i >= 0), default=-1)
        end = max(text.rfind("]"), text.rfind("}"))
        if start >= 0 and end > start:
            text = text[start:end + 1]

    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlaylistGenerationError(f"the model's reply was not JSON: {exc.msg}") from exc

    if isinstance(payload, dict):
        # Accepts {"tracks": [...]} and {"playlist": [...]}, which is what it produces about a
        # third of the time however the prompt is worded.
        for key in ("tracks", "playlist", "items", "songs"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        raise PlaylistGenerationError("the model's reply was not a list of tracks")

    seen: set[tuple[str, str]] = set()
    tracks: list[GeneratedTrack] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        artist = str(row.get("artist") or row.get("Artist") or "").strip()
        title = str(row.get("track") or row.get("title") or row.get("Track") or "").strip()
        if not artist or not title:
            continue
        key = (artist.casefold(), title.casefold())
        if key in seen:
            continue                       # the same song twice, differently capitalised
        seen.add(key)
        tracks.append(GeneratedTrack(artist=artist, track=title))

    if not tracks:
        raise PlaylistGenerationError("the model returned no usable tracks")
    return tracks


class SymonClient:
    """Asks the local model for a tracklist. No streaming service anywhere in this path."""

    def __init__(self, base_url: str = "", api_key: str = "", timeout: float = 300.0):
        self.base_url = (base_url or os.environ.get("SYMON_SERVER")
                         or "http://127.0.0.1:9100").rstrip("/")
        # NO API KEYS, owner decision 2026-09-11. This client talks to OUR OWN model
        # server on loopback; the bearer token it used to send was a key this box presented
        # to this box. The parameter is kept so the signature is unchanged for callers, and
        # it is simply never populated from the environment any more.
        self.api_key = api_key
        # Long: a 14B model writing twenty tracks with reasoning takes real time, and a timeout
        # tuned for a JSON API turns "still thinking" into "failed".
        self._http = httpclient.AsyncClient(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        return headers

    async def generate(self, prompt: str, count: int = 20,
                       taste: dict[str, Any] | None = None) -> list[GeneratedTrack]:
        """The tracklist. `taste` is optional and `{}` is a supported value -- a listener with no
        linked account gets a playlist, or the DJ would be a connector feature wearing our name."""
        wanted = f"{prompt.strip()}\n\nReturn exactly {int(count)} tracks."
        if taste and taste.get("artists"):
            wanted += ("\n\nThis listener already likes: "
                       + ", ".join(taste["artists"][:15])
                       + ". Use that as a hint about range, not a list to draw from.")

        try:
            reply = await self._http.post(
                f"{self.base_url}/ask/remix", headers=self._headers(),
                json={"question": wanted, "context": _SYSTEM_PROMPT,
                      # Above the measured floor: this model spends small budgets reasoning and
                      # returns empty content. Twenty tracks of JSON also needs the room.
                      "max_tokens": 4096, "temperature": 0.8})
        except httpclient.HTTPError as exc:
            raise PlaylistGenerationError(f"could not reach the SyMoNeuRaL server: {exc}") from exc

        if reply.status_code == 503:
            raise PlaylistGenerationError("no model is loaded on the server")
        if reply.status_code != 200:
            raise PlaylistGenerationError(
                f"the server refused the request ({reply.status_code})")
        return parse_tracklist(reply.json().get("answer", ""))

    async def aclose(self) -> None:
        await self._http.aclose()
