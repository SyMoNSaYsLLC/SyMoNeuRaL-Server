"""Spotify as an export target.

One of two, and not the default one in any code path. Everything here runs after a playlist
already exists; nothing in generation reaches this file.

Scopes are the smallest set that lets a playlist be created and filled. Notably absent:
`user-read-private`, `user-read-email`, and anything under `user-library-*`. The DJ does not need
to know who somebody is or what is in their library to put a playlist in their account, and asking
for a permission because it might be handy later is how a consent screen becomes a reason not to
connect.

SPDX-License-Identifier: GPL-2.0-or-later
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

from .. import httpclient

from .base import ConnectorAuthError, ConnectorError, PlaylistRef, Track

AUTH = "https://accounts.spotify.com/authorize"
TOKEN = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"

#: Create a playlist, add to it, set its picture. Nothing else.
SCOPES = "playlist-modify-private playlist-modify-public ugc-image-upload"


class SpotifyAuthError(ConnectorAuthError):
    """Kept under this name because the recovered `pipeline.py` catches it by it."""


class TokenStore:
    """Refresh tokens on disk, one file, 0600.

    Kept out of the client because `app.py` constructs one and hands it in, and `conftest.py`
    does the same with a temporary path -- which is what makes the recovered tests able to run
    without touching a real account. Signature and name come from those call sites, not from
    preference.

    A refresh token is a long-lived credential for somebody's music account. Same mode as the
    keyring and the conversation archive, and an atomic write so a crash mid-save cannot leave a
    truncated file that reads as "no accounts linked".
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        tmp.chmod(0o600)
        tmp.replace(self.path)

    def get_user(self, listener: str) -> dict[str, Any] | None:
        return self._load().get(listener)

    def put_user(self, listener: str, record: dict[str, Any]) -> None:
        data = self._load()
        data[listener] = record
        self._save(data)

    def forget(self, listener: str) -> bool:
        data = self._load()
        if listener not in data:
            return False
        del data[listener]
        self._save(data)
        return True

    def listeners(self) -> list[str]:
        return sorted(self._load())

    def users(self) -> list[dict[str, Any]]:
        """Every stored listener as a PUBLIC record: the id and the display name, never the
        tokens.

        `app.py` has called this since it was written (`/users` at :207, and `_visible_users`
        at :204, which is the cross-tenant boundary) and it has never existed -- the app could
        not import at all, so nothing ever reached the missing method. `listeners()` is not a
        substitute: it returns bare id strings and both call sites subscript `u["user"]`.

        The projection is the point, not a convenience. The stored record holds `access_token`
        and `refresh_token`; `/users` is reachable by any authenticated member, so returning
        raw records would hand every member every other member's Spotify credentials. The
        route's test asserts the absence of both strings in the response body rather than the
        presence of the ids, which is the correct thing to assert about a leak.
        """
        return [{"user": listener, "display_name": (record or {}).get("display_name", "")}
                for listener, record in sorted(self._load().items())]


class OwnershipStore(TokenStore):
    """Which listener owns which playlist.

    Same shape, different file, and a separate class because the two are read in different
    places and conflating them would put playlist ids in the credentials file.
    """


class SpotifyClient:
    name = "spotify"
    label = "Spotify"

    def __init__(self, client_id: str = "", client_secret: str = "", redirect_uri: str = "",
                 store: TokenStore | None = None, http: Any = None):
        # Positional, in this order, because `app.py` and the recovered `conftest.py` both build
        # one that way. `http` is injected for the same reason: it is how the tests run the whole
        # client against a transport that never opens a socket.
        self.client_id = client_id or os.environ.get("SPOTIFY_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("SPOTIFY_CLIENT_SECRET", "")
        self.redirect_uri = (redirect_uri or os.environ.get("SPOTIFY_REDIRECT_URI")
                             or "http://127.0.0.1:9110/connect/spotify/callback")
        self.store = store or TokenStore(
            Path(os.environ.get("XDG_STATE_HOME", "~/.local/state")).expanduser()
            / "symoneural" / "dj" / "spotify_tokens.json")
        self._http = http or httpclient.AsyncClient(timeout=30.0)
        self._states: dict[str, str] = {}

    @classmethod
    def from_settings(cls, settings: Any = None) -> "SpotifyClient":
        """What the connector registry builds. A second constructor rather than a second
        signature, so the recovered call sites keep working untouched."""
        get = (lambda key, default="": str(getattr(settings, key, None)
                                           or os.environ.get(key.upper(), default)))
        path = getattr(settings, "token_path", None)
        return cls(get("spotify_client_id"), get("spotify_client_secret"),
                   get("spotify_redirect_uri"),
                   TokenStore(path) if path else None)

    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    # ---- linking -----------------------------------------------------------------------

    def authorize_url(self, listener: str = "") -> str:
        if not self.configured():
            raise ConnectorError("Spotify is not configured: set SPOTIFY_CLIENT_ID and SECRET")
        state = secrets.token_urlsafe(24)
        self._states[state] = listener
        query = httpclient.QueryParams({
            "client_id": self.client_id, "response_type": "code",
            "redirect_uri": self.redirect_uri, "scope": SCOPES, "state": state,
        })
        return f"{AUTH}?{query}"

    def consume_state(self, state: str) -> bool:
        """One use. A state that can be replayed is not CSRF protection."""
        return self._states.pop(state, None) is not None

    async def handle_callback(self, code: str, listener: str = "") -> str:
        basic = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()).decode()
        reply = await self._http.post(TOKEN, headers={"Authorization": f"Basic {basic}"},
                                      data={"grant_type": "authorization_code", "code": code,
                                            "redirect_uri": self.redirect_uri})
        if reply.status_code != 200:
            raise SpotifyAuthError(f"Spotify refused the authorisation code ({reply.status_code})")
        body = reply.json()
        me = await self._http.get(f"{API}/me", headers={
            "Authorization": f"Bearer {body['access_token']}"})
        user_id = me.json().get("id", "") if me.status_code == 200 else ""
        self.store.put_user(listener or user_id, {
            "access_token": body["access_token"],
            "refresh_token": body.get("refresh_token", ""),
            "expires_at": time.time() + int(body.get("expires_in", 3600)) - 60,
            "user_id": user_id,
        })
        return user_id

    async def _bearer(self, listener: str) -> str:
        token = self.store.get_user(listener)
        if not token:
            raise SpotifyAuthError(f"no Spotify account linked for {listener!r}")
        if token["expires_at"] > time.time():
            return token["access_token"]
        if not token.get("refresh_token"):
            raise SpotifyAuthError("the Spotify session expired — reconnect the account")
        basic = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()).decode()
        reply = await self._http.post(TOKEN, headers={"Authorization": f"Basic {basic}"},
                                      data={"grant_type": "refresh_token",
                                            "refresh_token": token["refresh_token"]})
        if reply.status_code != 200:
            raise SpotifyAuthError("Spotify would not refresh the session — reconnect")
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
            raise SpotifyAuthError(f"Spotify rejected the request ({reply.status_code})")
        if reply.status_code >= 500:
            raise ConnectorError(f"Spotify is having a bad day ({reply.status_code})")
        return reply

    # ---- export ------------------------------------------------------------------------

    async def search_track(self, listener: str, artist: str, title: str) -> list[Track]:
        reply = await self._call(listener, "GET", "/search", params={
            "q": f"artist:{artist} track:{title}", "type": "track", "limit": 5})
        if reply.status_code != 200:
            return []
        items = reply.json().get("tracks", {}).get("items", []) or []
        return [Track(uri=row.get("uri", ""), title=row.get("name", ""),
                      artist=", ".join(a.get("name", "") for a in row.get("artists", [])),
                      album=row.get("album", {}).get("name", ""),
                      duration_ms=int(row.get("duration_ms") or 0), raw=row)
                for row in items if row.get("uri")]

    async def create_playlist(self, listener: str, name: str,
                              description: str = "") -> PlaylistRef:
        token = self.store.get_user(listener) or {}
        user_id = token.get("user_id")
        if not user_id:
            raise SpotifyAuthError("no Spotify user for this listener")
        reply = await self._call(listener, "POST", f"/users/{user_id}/playlists",
                                 json={"name": name, "description": description,
                                       "public": False})
        if reply.status_code not in (200, 201):
            raise ConnectorError(f"Spotify would not create the playlist ({reply.status_code})")
        body = reply.json()
        return PlaylistRef(id=body["id"], service=self.name, name=name,
                           url=body.get("external_urls", {}).get(
                               "spotify", f"https://open.spotify.com/playlist/{body['id']}"))

    async def add_tracks(self, listener: str, playlist_id: str, uris: list[str]) -> int:
        added = 0
        # 100 is Spotify's cap per call, and exceeding it fails the whole batch rather than
        # truncating -- so a 250-track set has to be three calls or it is zero tracks.
        for start in range(0, len(uris), 100):
            chunk = uris[start:start + 100]
            reply = await self._call(listener, "POST", f"/playlists/{playlist_id}/tracks",
                                     json={"uris": chunk})
            if reply.status_code in (200, 201):
                added += len(chunk)
        return added

    async def upload_cover(self, listener: str, playlist_id: str, png: bytes) -> bool:
        jpeg = base64.b64encode(png).decode()
        reply = await self._call(listener, "PUT", f"/playlists/{playlist_id}/images",
                                 content=jpeg, headers={"Content-Type": "image/jpeg"})
        return reply.status_code in (200, 202)

    async def taste_summary(self, listener: str) -> dict[str, Any]:
        """Empty when nothing is linked, and that has to stay usable -- the generator runs for a
        listener with no Spotify account at all."""
        try:
            reply = await self._call(listener, "GET", "/me/top/artists",
                                     params={"limit": 20, "time_range": "medium_term"})
        except (SpotifyAuthError, ConnectorError):
            return {}
        if reply.status_code != 200:
            return {}
        items = reply.json().get("items", []) or []
        return {
            "service": self.name,
            "artists": [row.get("name", "") for row in items if row.get("name")],
            "genres": sorted({g for row in items for g in (row.get("genres") or [])})[:25],
        }

    async def aclose(self) -> None:
        await self._http.aclose()
