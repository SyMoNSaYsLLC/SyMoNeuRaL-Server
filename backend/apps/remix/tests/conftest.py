"""Shared fixtures. House convention (from symon_llm): CPU-only, no network,
no sockets — both outbound clients ride httpx.MockTransport, the app is
exercised through fastapi's in-process TestClient, and nothing writes outside
tmp_path."""
from __future__ import annotations

import time

import httpx
import pytest

from symoneural_dj.config import Settings
from symoneural_dj.jobs import Job
from symoneural_dj.spotify import SpotifyClient, TokenStore

DJ_TOKEN = "test-dj-token"
AUTH_HEADER = {"Authorization": f"Bearer {DJ_TOKEN}"}


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        spotify_client_id="cid",
        spotify_client_secret="csecret",
        spotify_redirect_uri="http://127.0.0.1:8090/auth/callback",
        symon_url="http://engine.test",
        vllm_api_key="engine-key",
        dj_token=DJ_TOKEN,
        token_path=tmp_path / "tokens.json",
        host="127.0.0.1",
        port=8090,
        accounts_db=tmp_path / "accounts.db",
        secure_cookies=False,
        playlist_cost=1,
        capture_dir=tmp_path / "distill",
    )


def fresh_entry(**over) -> dict:
    entry = {
        "access_token": "fresh-access",
        "refresh_token": "fresh-refresh",
        "expires_at": time.time() + 3600,
        "display_name": "Someone",
    }
    entry.update(over)
    return entry


def make_spotify(settings: Settings, handler) -> tuple[SpotifyClient, list[httpx.Request]]:
    """A SpotifyClient whose transport is `handler`; returns (client, requests
    seen). handler(request) -> httpx.Response."""
    seen: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(recording_handler))
    client = SpotifyClient(
        settings.spotify_client_id,
        settings.spotify_client_secret,
        settings.spotify_redirect_uri,
        TokenStore(settings.token_path),
        http=http,
    )
    return client, seen


def track_item(uri: str, artist: str, name: str = "Song") -> dict:
    return {"uri": uri, "name": name, "artists": [{"name": artist}]}


def search_body(items: list[dict]) -> dict:
    return {"tracks": {"items": items}}


def make_job(**over) -> Job:
    fields = dict(
        id="job1",
        user="alice",
        prompt="rainy day indie",
        track_count=5,
        name=None,
        public=False,
        use_taste_profile=False,
    )
    fields.update(over)
    return Job(**fields)


class FakeSymon:
    """Instant stand-in for SymonClient.generate_playlist."""

    def __init__(self, name="Test Mix", tracks=None, on_call=None):
        self.name = name
        self.tracks = tracks or [
            {"artist": "Artist A", "track": "Song One"},
            {"artist": "Artist B", "track": "Song Two"},
            {"artist": "Artist C", "track": "Song Three"},
        ]
        self.on_call = on_call

    async def generate_playlist(self, prompt, count, taste_summary=None):
        if self.on_call:
            self.on_call()
        return self.name, list(self.tracks)

    async def aclose(self):
        pass


class _FakeStore:
    def __init__(self, entries=None):
        self.entries = entries or {}

    def get_user(self, user):
        return self.entries.get(user)


class FakeSpotify:
    """Instant stand-in for the SpotifyClient methods the pipeline uses.
    Every suggested track resolves, credited to the artist that was asked for."""

    def __init__(self, on_call=None, store_entries=None):
        self.added: list[list[str]] = []
        self.created: list[dict] = []
        self.on_call = on_call
        self.store = _FakeStore(store_entries)

    def _note(self, method):
        if self.on_call:
            self.on_call(method)

    async def taste_summary(self, user):
        self._note("taste_summary")
        return None

    async def search_track(self, user, artist, track):
        self._note("search_track")
        return [track_item(f"spotify:track:{artist}-{track}".replace(" ", "_"), artist, track)]

    async def create_playlist(self, user, name, public, description):
        self._note("create_playlist")
        self.created.append({"name": name, "public": public, "description": description})
        return {"id": "pl1", "external_urls": {"spotify": "https://open.spotify.com/playlist/pl1"}}

    async def add_tracks(self, user, playlist_id, uris):
        self._note("add_tracks")
        self.added.append(list(uris))

    async def upload_cover(self, user, playlist_id, jpeg):
        self._note("upload_cover")
        self.covers = getattr(self, "covers", [])
        self.covers.append(jpeg)

    async def aclose(self):
        pass
