"""Routes and the auth middleware, through fastapi's in-process TestClient
(no sockets). Fakes stand in for both outbound clients."""
import dataclasses
import time

import pytest
from fastapi.testclient import TestClient

from symoneural_dj.app import create_app
from symoneural_dj.spotify import TokenStore

from conftest import DJ_TOKEN, FakeSpotify, FakeSymon, fresh_entry

AUTH = {"Authorization": f"Bearer {DJ_TOKEN}"}


@pytest.fixture
def client(settings):
    # `put_user`, not `set_user`: the store has never had a `set_user`. Both spellings entered
    # the tree in the same commit (9b5da84) and neither has changed since, so this line has been
    # calling a method that does not exist since the day it was written -- invisible because
    # `apps/remix/tests` sat behind a pytest `--ignore` and never ran. `put_user(listener, record)`
    # is the real API and is what both connectors call (connectors/spotify.py:159, ytmusic.py:105).
    TokenStore(settings.token_path).put_user("alice", fresh_entry(display_name="Alice"))
    app = create_app(settings, spotify=FakeSpotify(), symon=FakeSymon())
    with TestClient(app) as c:
        yield c


def _body(**over):
    body = {"prompt": "rainy day indie", "user": "alice"}
    body.update(over)
    return body


def test_index_is_open_html(client):
    """GET / serves the UI shell without auth — it holds no data; the page
    itself asks for the DJ token and sends it on every API call."""
    resp = client.get("/")  # no Authorization header
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "SyMoNeuRaL" in resp.text  # house wordmark, not the old "symon dj"
    assert "d97757" not in resp.text  # Studio's Crail orange stays out — green accent
    assert "localStorage" not in resp.text.replace("never localStorage", "")


def test_health_is_open(client):
    resp = client.get("/health")  # no Authorization header at all
    assert resp.status_code == 200
    # Was `== {}` until 2026-08-10. The body now names the service, because an
    # empty 200 cannot distinguish "DJ answered" from "something else is on
    # this port". Still open and still cheap — that part is the point of the test.
    assert resp.json() == {"ok": True, "app": "symoneural_dj", "port": 8090}


def test_missing_or_wrong_bearer_is_401(client):
    assert client.post("/playlist", json=_body()).status_code == 401
    assert client.get("/users").status_code == 401
    wrong = {"Authorization": "Bearer nope"}
    assert client.post("/playlist", json=_body(), headers=wrong).status_code == 401


def test_unset_dj_token_serves_loopback_only(settings):
    """TestClient's peer is 'testclient' (not loopback), so with DJ_TOKEN
    unset every guarded route must refuse — fail closed, like the engine."""
    bare = dataclasses.replace(settings, dj_token="")
    app = create_app(bare, spotify=FakeSpotify(), symon=FakeSymon())
    with TestClient(app) as c:
        assert c.get("/users").status_code == 401
        assert c.get("/health").status_code == 200


def test_users_lists_authed_accounts_without_tokens(client):
    resp = client.get("/users", headers=AUTH)
    assert resp.status_code == 200
    users = resp.json()["users"]
    assert [u["user"] for u in users] == ["alice"]
    assert "access_token" not in resp.text
    assert "refresh_token" not in resp.text


def test_unknown_user_is_404_with_known_list(client):
    resp = client.post("/playlist", json=_body(user="nobody"), headers=AUTH)
    assert resp.status_code == 404
    assert resp.json()["known_users"] == ["alice"]


def test_unknown_blend_user_is_404(client):
    resp = client.post("/playlist", json=_body(blend_with=["ghost"]), headers=AUTH)
    assert resp.status_code == 404
    body = resp.json()
    assert "ghost" in body["error"]
    assert body["known_users"] == ["alice"]


def test_track_count_bounds_enforced(client):
    assert client.post("/playlist", json=_body(track_count=4), headers=AUTH).status_code == 422
    assert client.post("/playlist", json=_body(track_count=101), headers=AUTH).status_code == 422
    assert client.post("/playlist", json=_body(prompt=""), headers=AUTH).status_code == 422


def test_unknown_job_id_is_404(client):
    assert client.get("/playlist/doesnotexist", headers=AUTH).status_code == 404


def test_full_job_flow_to_done(client):
    resp = client.post("/playlist", json=_body(), headers=AUTH)
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    deadline = time.time() + 5
    body = {}
    while time.time() < deadline:
        body = client.get(f"/playlist/{job_id}", headers=AUTH).json()
        if body["state"] in {"done", "failed"}:
            break
        time.sleep(0.01)

    assert body["state"] == "done", body
    assert body["playlist_id"] == "pl1"
    assert body["playlist_url"].startswith("https://open.spotify.com/")
    assert body["tracks_added"] == 3
    assert body["tracks_dropped"] == []
