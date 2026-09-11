"""YouTube Music as an export target.

The second connector, and the reason there is a connector layer at all. With only Spotify, "our
own playlist generator" would be a claim contradicted by the import list.

Built on the YouTube Data API v3 rather than an unofficial YouTube Music client, deliberately.
The unofficial libraries are better at YouTube *Music* specifically -- they see the music
catalogue rather than videos -- and they work by replaying browser internals, which breaks without
warning and puts us outside the terms we are asking the user to rely on. A playlist of official
music videos created through the documented API is a worse match and a thing that keeps working.

What this cannot do is stated rather than emulated:

  * `upload_cover` returns False. Playlist thumbnails are derived from contents; there is no
    supported upload. The pipeline treats False as "no cover" and carries on.
  * `taste_summary` returns `{}`. Reading someone's watch history to profile their taste is a
    much larger consent than "put this playlist in my account", and the generator does not need
    it -- it works with no signal at all.

SPDX-License-Identifier: GPL-2.0-or-later
"""
from __future__ import annotations

import os
import secrets
import time
from pathlib import Path
from typing import Any

from .. import httpclient

from .base import ConnectorAuthError, ConnectorError, PlaylistRef, Track

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"

#: Create and modify the user's own playlists. Not `youtube.readonly`, not `youtube.force-ssl`.
SCOPES = "https://www.googleapis.com/auth/youtube"


class YouTubeMusicAuthError(ConnectorAuthError):
    pass


class YouTubeMusicClient:
    name = "ytmusic"
    label = "YouTube Music"

    def __init__(self, client_id: str = "", client_secret: str = "", redirect_uri: str = "",
                 store: Any = None, http: Any = None):
        # Same shape as SpotifyClient, deliberately: two connectors that are constructed
        # differently are two connectors one of which is the special case.
        from .spotify import TokenStore

        self.client_id = client_id or os.environ.get("GOOGLE_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("GOOGLE_CLIENT_SECRET", "")
        self.redirect_uri = (redirect_uri or os.environ.get("GOOGLE_REDIRECT_URI")
                             or "http://127.0.0.1:9110/connect/ytmusic/callback")
        self.store = store or TokenStore(
            Path(os.environ.get("XDG_STATE_HOME", "~/.local/state")).expanduser()
            / "symoneural" / "dj" / "ytmusic_tokens.json")
        self._http = http or httpclient.AsyncClient(timeout=30.0)
        self._states: dict[str, str] = {}

    @classmethod
    def from_settings(cls, settings: Any = None) -> "YouTubeMusicClient":
        get = (lambda key, default="": str(getattr(settings, key, None)
                                           or os.environ.get(key.upper(), default)))
        return cls(get("google_client_id"), get("google_client_secret"),
                   get("google_redirect_uri"))

    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    # ---- linking -----------------------------------------------------------------------

    def authorize_url(self, listener: str = "") -> str:
        if not self.configured():
            raise ConnectorError(
                "YouTube Music is not configured: set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET")
        state = secrets.token_urlsafe(24)
        self._states[state] = listener
        query = httpclient.QueryParams({
            "client_id": self.client_id, "response_type": "code",
            "redirect_uri": self.redirect_uri, "scope": SCOPES, "state": state,
            # Without these two Google issues no refresh token on re-consent, and the link
            # silently stops working an hour later.
            "access_type": "offline", "prompt": "consent",
        })
        return f"{AUTH}?{query}"

    def consume_state(self, state: str) -> bool:
        return self._states.pop(state, None) is not None

    async def handle_callback(self, code: str, listener: str = "") -> str:
        reply = await self._http.post(TOKEN, data={
            "code": code, "client_id": self.client_id, "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri, "grant_type": "authorization_code"})
        if reply.status_code != 200:
            raise YouTubeMusicAuthError(
                f"Google refused the authorisation code ({reply.status_code})")
        body = reply.json()
        who = listener or "default"
        self.store.put_user(who, {
            "access_token": body["access_token"],
            "refresh_token": body.get("refresh_token", ""),
            "expires_at": time.time() + int(body.get("expires_in", 3600)) - 60,
        })
        return who

    async def _bearer(self, listener: str) -> str:
        token = self.store.get_user(listener)
        if not token:
            raise YouTubeMusicAuthError(f"no YouTube account linked for {listener!r}")
        if token["expires_at"] > time.time():
            return token["access_token"]
        if not token.get("refresh_token"):
            raise YouTubeMusicAuthError("the YouTube session expired — reconnect the account")
        reply = await self._http.post(TOKEN, data={
            "client_id": self.client_id, "client_secret": self.client_secret,
            "refresh_token": token["refresh_token"], "grant_type": "refresh_token"})
        if reply.status_code != 200:
            raise YouTubeMusicAuthError("Google would not refresh the session — reconnect")
        body = reply.json()
        token["access_token"] = body["access_token"]
        token["expires_at"] = time.time() + int(body.get("expires_in", 3600)) - 60
        self.store.put_user(listener, token)
        return token["access_token"]

    async def _call(self, listener: str, method: str, path: str, **kw) -> httpclient.Response:
        headers = kw.pop("headers", {})
        headers["Authorization"] = f"Bearer {await self._bearer(listener)}"
        reply = await self._http.request(method, f"{API}{path}", headers=headers, **kw)
        if reply.status_code in (401, 403):
            raise YouTubeMusicAuthError(f"YouTube rejected the request ({reply.status_code})")
        if reply.status_code >= 500:
            raise ConnectorError(f"YouTube is having a bad day ({reply.status_code})")
        return reply

    # ---- export ------------------------------------------------------------------------

    async def search_track(self, listener: str, artist: str, title: str) -> list[Track]:
        reply = await self._call(listener, "GET", "/search", params={
            "part": "snippet", "q": f"{artist} {title}", "type": "video",
            # 10 is YouTube's music category. Without it the top hit for a song is as likely to
            # be a lyric compilation or a reaction video as the track.
            "videoCategoryId": "10", "maxResults": 5})
        if reply.status_code != 200:
            return []
        out = []
        for row in reply.json().get("items", []) or []:
            video = (row.get("id") or {}).get("videoId")
            snippet = row.get("snippet") or {}
            if video:
                out.append(Track(uri=video, title=snippet.get("title", ""),
                                 artist=snippet.get("channelTitle", ""), raw=row))
        return out

    async def create_playlist(self, listener: str, name: str,
                              description: str = "") -> PlaylistRef:
        reply = await self._call(listener, "POST", "/playlists",
                                 params={"part": "snippet,status"},
                                 json={"snippet": {"title": name, "description": description},
                                       "status": {"privacyStatus": "private"}})
        if reply.status_code not in (200, 201):
            raise ConnectorError(f"YouTube would not create the playlist ({reply.status_code})")
        body = reply.json()
        return PlaylistRef(id=body["id"], service=self.name, name=name,
                           url=f"https://music.youtube.com/playlist?list={body['id']}")

    async def add_tracks(self, listener: str, playlist_id: str, uris: list[str]) -> int:
        # One request per item: the API has no batch insert. Slower than Spotify's 100-at-a-time
        # and there is no way around it, so a failure part-way leaves a partial playlist rather
        # than none -- which is the better half of a bad choice.
        added = 0
        for video in uris:
            reply = await self._call(listener, "POST", "/playlistItems",
                                     params={"part": "snippet"},
                                     json={"snippet": {
                                         "playlistId": playlist_id,
                                         "resourceId": {"kind": "youtube#video",
                                                        "videoId": video}}})
            if reply.status_code in (200, 201):
                added += 1
        return added

    async def upload_cover(self, listener: str, playlist_id: str, png: bytes) -> bool:
        return False        # no supported upload; stated rather than emulated

    async def taste_summary(self, listener: str) -> dict[str, Any]:
        return {}           # deliberately: see the module docstring

    async def aclose(self) -> None:
        await self._http.aclose()
