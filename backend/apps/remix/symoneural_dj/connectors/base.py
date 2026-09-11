"""What a music service has to do to be exportable to, and nothing more.

SyMoNeuRaL DJ generates playlists itself. The tracklist comes out of the local model via
`symon_client`, scored and ordered by `matching` and `pipeline`, using nothing from any streaming
service -- no catalogue, no recommendations API, no audio features. A connector is an *export*:
somewhere to put a playlist that already exists.

That ordering is a product decision the owner made explicitly, and it is worth stating because the
code cannot say it on its own: *do not be solely connected to Spotify*. Two things follow, and
both are testable rather than aspirational:

  1. Generation never calls a connector. `pipeline.run_job` resolves each generated track to a
     service URI only after the list exists, so with every connector removed the DJ still produces
     a playlist -- it just has nowhere to push it.
  2. No connector is privileged. Spotify and YouTube Music implement the same protocol and are
     registered the same way; neither is imported at module scope by anything that must work
     without it.

`pipeline.run_job` already took its client as a parameter rather than importing one, which is why
this is a protocol and not a rewrite -- the recovered code was written for this shape.

SPDX-License-Identifier: GPL-2.0-or-later
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class ConnectorError(Exception):
    """The service failed. Not the user's fault and not fixable by re-authorising."""


class ConnectorAuthError(ConnectorError):
    """The service rejected the credentials, or there are none for this listener yet.

    Distinct from ConnectorError for the same reason the IPTV service splits 401 from 502: one is
    fixed by reconnecting the account and the other by waiting, and merging them sends people to
    re-link an account that was linked fine.
    """


@dataclass(frozen=True)
class Track:
    """One resolved track on one service.

    `uri` is whatever that service calls a track -- a `spotify:track:...`, a YouTube video id --
    and is only ever read out of the service's own response. Nothing here constructs one, which is
    the rule `matching.py` was already written to: a constructed URI is a guess that looks like a
    fact.
    """

    uri: str
    title: str
    artist: str
    album: str = ""
    duration_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlaylistRef:
    """Where a playlist ended up, on one service."""

    id: str
    url: str
    service: str
    name: str = ""


@runtime_checkable
class Connector(Protocol):
    """The whole surface. Deliberately small.

    Anything a connector cannot do it should decline clearly rather than emulate. YouTube Music
    has no cover-art upload in its public surface, so its `upload_cover` returns False -- the
    pipeline treats that as "no cover" and carries on, rather than the connector faking one or
    the export failing over a picture.
    """

    #: Stable lowercase identifier. Used in URLs, settings keys and the UI, so it does not change.
    name: str
    #: What a person reads.
    label: str

    def configured(self) -> bool:
        """Is there enough configuration for this to be worth offering at all?

        Checked before the UI lists it. A connector whose client id is unset should not appear as
        an option that fails when clicked.
        """
        ...

    def authorize_url(self, listener: str) -> str:
        """Where to send the browser to link an account."""
        ...

    async def handle_callback(self, code: str, listener: str = "") -> str:
        """Finish linking. Returns the service's identifier for the account."""
        ...

    async def search_track(self, listener: str, artist: str, title: str) -> list[Track]:
        """Candidates for one generated track, best first. Never raises on "not found" --
        an empty list is the answer, and the pipeline drops that track."""
        ...

    async def create_playlist(self, listener: str, name: str,
                              description: str = "") -> PlaylistRef:
        ...

    async def add_tracks(self, listener: str, playlist_id: str, uris: list[str]) -> int:
        """Returns how many were actually added."""
        ...

    async def upload_cover(self, listener: str, playlist_id: str, png: bytes) -> bool:
        """False when the service does not support it. Not an error."""
        ...

    async def taste_summary(self, listener: str) -> dict[str, Any]:
        """Optional signal for the generator: what this listener already likes.

        Returning `{}` is legitimate and must stay legitimate -- the generator has to work for a
        listener with no linked account at all, or the DJ would be a Spotify feature wearing our
        name.
        """
        ...

    async def aclose(self) -> None:
        ...
