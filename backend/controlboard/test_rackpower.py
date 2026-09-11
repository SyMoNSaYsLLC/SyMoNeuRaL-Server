"""Tests for the per-unit power switch.

The two that matter most are the ones that would let this feature become dishonest:
`test_the_module_refuses_everything_when_the_switch_is_unset`, because the rack is public
and an ungated control here is unauthenticated denial of service; and
`test_every_toggleable_unit_is_gated_somewhere`, because a unit that can be switched off on
the rack but not in the request path is the fake activity light `.claude/CLAUDE.md` forbids.

`api.py` is read as source and never imported -- importing it starts a lifespan, touches the
GPU governor and binds nothing useful. The two tests that check the wiring parse it instead.
"""
from __future__ import annotations

import ast
import json
import os
import pathlib

import pytest
import unittest

import controlboard as rp

API = pathlib.Path(__file__).resolve().parent.parent.parent / "api.py"
ENV_KEYS = ("SYMONEURAL_RACK_ENABLED", "SYMONEURAL_RACK_TOKEN", "SYMONEURAL_RACK_ALLOW_REMOTE",
            "SYMONEURAL_RACK_STATE_DIR")


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    """Every key cleared, and the state file pointed at a tmpdir.

    Without the SYMONEURAL_RACK_STATE_DIR override these tests would write into `run/`, which holds
    the live GPU mutex -- and a test that disables `chat` in the real override file would
    take the running site's chat surface down.
    """
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SYMONEURAL_RACK_STATE_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def switched_on(clean_env, monkeypatch):
    monkeypatch.setenv("SYMONEURAL_RACK_ENABLED", "1")
    monkeypatch.setenv("SYMONEURAL_RACK_TOKEN", "correct-horse-battery-staple")
    return clean_env


# ------------------------------------------------------------------ the gates


def test_the_module_refuses_everything_when_the_switch_is_unset(clean_env):
    """Off is the default and it is total. This is the load-bearing test."""
    assert rp.enabled() is False
    assert rp.load() == {}
    assert rp.is_disabled("chat") is False
    for token in (None, "", "anything", "correct-horse-battery-staple"):
        ok, why = rp.authorize(token, "127.0.0.1")
        assert ok is False
        assert "SYMONEURAL_RACK_ENABLED" in why




def test_the_token_alone_is_not_enough_without_the_switch(clean_env, monkeypatch):
    monkeypatch.setenv("SYMONEURAL_RACK_TOKEN", "t")            # but no SYMONEURAL_RACK_ENABLED
    assert rp.enabled() is False




@pytest.mark.parametrize("peer", ["8.8.8.8", "2001:db8::1", "not-an-address", "", None])
def test_a_non_loopback_peer_is_refused_by_default(switched_on, peer):
    assert rp.authorize("correct-horse-battery-staple", peer)[0] is False


@pytest.mark.parametrize("peer", ["127.0.0.1", "::1", "[::1]", "127.5.5.5"])
def test_loopback_is_allowed(switched_on, peer):
    assert rp.authorize("correct-horse-battery-staple", peer)[0] is True


def test_allow_remote_opens_it_but_still_needs_a_parseable_address(switched_on, monkeypatch):
    monkeypatch.setenv("SYMONEURAL_RACK_ALLOW_REMOTE", "1")
    assert rp.authorize("correct-horse-battery-staple", "8.8.8.8")[0] is True
    # An operator who set ALLOW_REMOTE opened this to other hosts, not to callers this
    # process cannot identify -- there would be nothing to attribute the override to.
    assert rp.authorize("correct-horse-battery-staple", "gibberish")[0] is False


# ------------------------------------------------------------------ the allowlist


@pytest.mark.parametrize("unit_id", ["train", "miner"])
def test_the_two_units_with_reasons_to_be_excluded_cannot_be_switched(switched_on, unit_id):
    """`train` mid-epoch and `miner`'s ASIC half are the two documented exclusions.

    If someone adds either back, this test fails and they have to answer the reason in the
    module docstring rather than discover the consequence on a running fine-tune.
    """
    assert unit_id not in rp.TOGGLEABLE
    with pytest.raises(KeyError):
        rp.disable(unit_id, "127.0.0.1")
    with pytest.raises(KeyError):
        rp.enable(unit_id)


def test_a_hand_edited_file_cannot_disable_something_off_the_allowlist(switched_on):
    """`run/` is writable by the service user, so the file is not a trusted input."""
    rp.state_path().write_text(json.dumps({"train": {"at": 1, "by": "x"},
                                           "chat": {"at": 2, "by": "y"}}))
    loaded = rp.load()
    assert "train" not in loaded
    assert "chat" in loaded


@pytest.mark.parametrize("junk", ["", "{", "[]", '{"chat": "not-a-dict"}', "null"])
def test_an_unreadable_override_file_leaves_every_surface_serving(switched_on, junk):
    """The safe direction: a broken file restricts nothing rather than downing everything."""
    rp.state_path().write_text(junk)
    assert rp.load() == {}
    assert rp.is_disabled("chat") is False


# ------------------------------------------------------------------ the record


def test_disable_then_enable_round_trips(switched_on):
    rec, changed = rp.disable("chat", "127.0.0.1")
    assert changed is True
    assert rp.is_disabled("chat") is True
    assert rec["by"] == "127.0.0.1" and isinstance(rec["at"], int)
    assert rp.enable("chat") is True
    assert rp.is_disabled("chat") is False
    assert rp.enable("chat") is False          # already on


def test_re_disabling_keeps_the_original_timestamp(switched_on):
    """How long has this been off is the question that catches a forgotten override.

    A panel that refreshes and re-posts must not be able to erase the answer.
    """
    first, _ = rp.disable("image", "127.0.0.1")
    second, changed = rp.disable("image", "10.0.0.9")
    assert changed is False
    assert second["at"] == first["at"]
    assert second["by"] == first["by"]


def test_the_write_is_atomic_and_leaves_no_temp_file(switched_on):
    rp.disable("chat", "127.0.0.1")
    names = sorted(p.name for p in rp.state_dir().iterdir())
    assert names == ["units.disabled.json"]


def test_disabling_one_unit_does_not_touch_another(switched_on):
    rp.disable("chat", "127.0.0.1")
    rp.disable("image", "127.0.0.1")
    rp.enable("chat")
    assert rp.is_disabled("chat") is False
    assert rp.is_disabled("image") is True


# ------------------------------------------------------------------ the mapping


@pytest.mark.parametrize("path,expected", [
    ("/api/chat", "chat"),
    ("/api/chat/stream", "chat"),
    ("/api/image", "image"),
    ("/api/remix", "remix"),
    ("/api/ravencalc", "ravencalc"),
    ("/api/sigils/packs", "sigils"),
    # The over-match this deliberately avoids: a bare startswith would hand these to the
    # Image and Chat switches, and a surface added later would silently inherit an off
    # switch belonging to a different unit.
    ("/api/imageology", None),
    ("/api/chatter", None),
    ("/api/status", None),
    ("/api/ws", None),
    ("/", None),
])
def test_path_mapping_matches_on_a_boundary_not_a_prefix(path, expected):
    assert rp.unit_for_path(path) == expected


def test_remix_and_chat_are_separate_switches():
    """Remix is a client of the chat engine, but the rack lists them as two units."""
    assert rp.unit_for_path("/api/remix") == "remix"
    assert rp.unit_for_path("/api/chat") == "chat"
    assert rp.FRAMES["remix"] != rp.FRAMES["chat"]


def test_every_toggleable_unit_is_gated_somewhere(switched_on):
    """A unit switchable on the rack but reachable in the request path is a fake LED.

    Every id on the allowlist must appear in ROUTES or FRAMES -- otherwise the button would
    change the rack reading and stop nothing, which is precisely the dishonest indicator
    `.claude/CLAUDE.md` singles out.
    """
    for unit_id in rp.TOGGLEABLE:
        assert unit_id in rp.ROUTES or unit_id in rp.FRAMES, unit_id


def test_frame_types_match_the_api_dispatch():
    """Every frame in FRAMES is one api.py actually dispatches on.

    Read as source, never imported. A frame type that api.py does not handle would be a
    switch guarding nothing; one it handles but we do not list would be a hole.
    """
    src = API.read_text()
    dispatched = {c for c in ("chat", "ravencalc", "remix")
                  if f'kind == "{c}"' in src}
    assert set(rp.FRAMES.values()) == dispatched


def test_api_applies_the_override_to_the_status_payload():
    """The rack reading and the request gate ship together or not at all."""
    src = API.read_text()
    assert "rackpower.apply(" in src
    assert "rackpower.unit_for_path(" in src      # the HTTP gate
    assert "rackpower.unit_for_frame(" in src     # the WebSocket gate


# ------------------------------------------------------------------ never destructive


def test_the_module_cannot_kill_anything(switched_on):
    """No signals, no subprocesses, no lock.

    `.claude/CLAUDE.md`: killing a GPU process returns the lock before CUDA has torn down
    and the next tenant OOMs at step 0, and `train` is never evicted to serve a page view.
    Taking a unit off the rack means admitting no NEW work; a job already running finishes.
    Enforced by parsing this package's own source, so a future edit that imports subprocess
    fails here rather than on a live fine-tune.

    Parsed rather than grepped, deliberately: the first version of this test searched the
    raw text and failed on its own module docstring, which says "never sends a signal to
    anything". A prose ban catches the documentation that promises the property as readily
    as the code that would break it, so it has to read imports and calls.
    """
    here = pathlib.Path(__file__).resolve().parent
    banned_modules = {"subprocess", "signal", "multiprocessing", "psutil"}
    banned_calls = {"kill", "killpg", "system", "popen", "spawnl", "terminate"}
    for src_file in sorted(here.glob("*.py")):
        if src_file.name.startswith("test_"):
            continue
        tree = ast.parse(src_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert a.name.split(".")[0] not in banned_modules, \
                        f"{src_file.name} imports {a.name}"
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in banned_modules, \
                    f"{src_file.name} imports from {node.module}"
            elif isinstance(node, ast.Attribute):
                assert node.attr not in banned_calls, \
                    f"{src_file.name} references .{node.attr}"


def test_the_override_file_lives_in_run_not_logs(clean_env, monkeypatch):
    """`run/` is runtime state and the name is load-bearing -- see `.claude/CLAUDE.md`."""
    monkeypatch.delenv("SYMONEURAL_RACK_STATE_DIR")
    assert rp.state_dir().name == "run"
    assert rp.state_path().name == "units.disabled.json"


# ------------------------------------------------------------------ the rack reading


class _FakeUnit:
    """Stands in for the pydantic `Unit` without importing api.py."""

    def __init__(self, uid, state, detail):
        self.id, self.state, self.detail = uid, state, detail

    def model_copy(self, update):
        clone = _FakeUnit(self.id, self.state, self.detail)
        for k, v in update.items():
            setattr(clone, k, v)
        return clone


def test_apply_is_the_identity_function_when_nothing_is_switched_off(clean_env):
    units = [_FakeUnit("chat", "ready", "fine")]
    assert rp.apply(units) is units


def test_apply_rewrites_only_the_disabled_unit(switched_on):
    rp.disable("chat", "127.0.0.1")
    units = [_FakeUnit("chat", "ready", "fine"), _FakeUnit("image", "busy", "rendering")]
    out = rp.apply(units)
    assert out[0].state == "offline"
    assert "operator" in out[0].detail and "not a fault" in out[0].detail
    assert out[1].state == "busy" and out[1].detail == "rendering"
    # The input is not mutated: a caller holding a reference must not see the override
    # appear underneath it.
    assert units[0].state == "ready"


def test_a_busy_unit_is_still_taken_offline_and_says_who_did_it(switched_on):
    """`busy` would invite a visitor to queue behind a surface that will refuse them."""
    rp.disable("image", "127.0.0.1")
    out = rp.apply([_FakeUnit("image", "busy", "rendering")])
    assert out[0].state == "offline"
    assert "127.0.0.1" in out[0].detail


def test_status_rows_covers_every_toggleable_unit_and_nothing_else(switched_on):
    rows = rp.status_rows()
    assert [r["id"] for r in rows] == list(rp.TOGGLEABLE)
    assert all(r["disabled"] is False for r in rows)
    rp.disable("sigils", "127.0.0.1")
    rows = {r["id"]: r for r in rp.status_rows()}
    assert rows["sigils"]["disabled"] is True
    assert rows["sigils"]["by"] == "127.0.0.1"


# ------------------------------------------------------------------ the HTTP surface


def test_routes_are_404_when_the_surface_is_off(clean_env):
    """Absent, not forbidden. The rack is public; a 403 advertises a control to attack."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(rp.router, prefix="/api/rack")
    client = TestClient(app)
    assert client.get("/api/rack/power").status_code == 404
    assert client.post("/api/rack/power/chat", json={"offline": True}).status_code == 404


def test_routes_work_end_to_end_when_the_surface_is_on(switched_on):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(rp.router, prefix="/api/rack")
    client = TestClient(app)
    # The forwarded header is how a peer is identified here, and TestClient's socket peer is
    # the literal string "testclient" rather than an address -- which `_parse_peer` denies,
    # correctly. Supplying the chain is not test scaffolding around the gate; it is the same
    # thing Caddy does in front of the real API.
    # NO API KEYS, 2026-09-11. The two 403-without-a-token assertions that stood here are
    # gone: `token_ok` is unconditionally true, so no token can be missing or wrong. What
    # still gates this surface is the SWITCH and the PEER, and the peer half is asserted by
    # its own tests above -- so the header below carries only the forwarded address.
    head = {"X-Forwarded-For": "127.0.0.1"}

    # The plain-fetch case the owner asked for: no credential header at all, 200.
    assert client.get("/api/rack/power", headers=head).status_code == 200

    doc = client.get("/api/rack/power", headers=head).json()
    assert [u["id"] for u in doc["units"]] == list(rp.TOGGLEABLE)

    r = client.post("/api/rack/power/chat", json={"offline": True}, headers=head)
    assert r.status_code == 200 and r.json()["disabled"] is True and r.json()["changed"] is True
    assert rp.is_disabled("chat") is True

    r = client.post("/api/rack/power/chat", json={"offline": False}, headers=head)
    assert r.json()["disabled"] is False and r.json()["changed"] is True
    assert rp.is_disabled("chat") is False

    # Off the allowlist -> 404, and the answer names what IS switchable.
    r = client.post("/api/rack/power/train", json={"offline": True}, headers=head)
    assert r.status_code == 404 and "chat" in r.json()["detail"]


def test_a_forwarded_header_decides_the_peer_not_the_socket(switched_on):
    """THE gate that would silently vanish if `request.client.host` were used.

    Caddy and the gateway both sit in front, so the socket peer is 127.0.0.1 for every
    request that ever arrived from the internet. Reading the forwarded chain is what keeps
    the loopback gate meaning anything at all.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(rp.router, prefix="/api/rack")
    client = TestClient(app)
    tok = {"X-Symoneural-Token": "correct-horse-battery-staple"}

    # A request that reached Caddy from the box itself: the chain's first entry is loopback.
    local = dict(tok, **{"X-Forwarded-For": "127.0.0.1"})
    assert client.get("/api/rack/power", headers=local).status_code == 200

    # The same socket, the same token, a real visitor at the far end of the chain. The
    # socket peer is identical in both cases -- ONLY the forwarded chain distinguishes them,
    # which is exactly why `request.client.host` cannot be what this gate reads.
    remote = dict(tok, **{"X-Forwarded-For": "203.0.113.7, 127.0.0.1"})
    assert client.get("/api/rack/power", headers=remote).status_code == 403






def test_the_attribution_records_the_forwarded_client(switched_on, monkeypatch):
    monkeypatch.setenv("SYMONEURAL_RACK_ALLOW_REMOTE", "1")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(rp.router, prefix="/api/rack")
    client = TestClient(app)
    head = {"X-Symoneural-Token": "correct-horse-battery-staple",
            "X-Forwarded-For": "203.0.113.7, 127.0.0.1"}
    r = client.post("/api/rack/power/image", json={"offline": True}, headers=head)
    assert r.json()["by"] == "203.0.113.7"


class TheDisabledSurfaceRevealsNothing(unittest.TestCase):
    """404 on every route when the switch is off, including the one with a body.

    The module docstring's argument is that a public rack served to anyone must not tell a
    visitor this installation has an operator control worth attacking. Measured 2026-09-08,
    the GET honoured that and the POST did not: a declared `body: PowerRequest` parameter
    makes FastAPI validate before the handler runs, so `_guard` was never reached and the
    reply was **422 naming the required field**. The token gate held; the concealment was
    bypassed by the framework, one layer above the code implementing it.
    """

    def setUp(self):
        for var in ("SYMONEURAL_RACK_ENABLED", "SYMONEURAL_RACK_TOKEN"):
            os.environ.pop(var, None)

    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from . import router
        app = FastAPI()
        app.include_router(routes.router, prefix="/api/rack")
        return TestClient(app)

    def test_the_post_answers_404_and_not_422_when_the_switch_is_off(self):
        r = self._client().post("/api/rack/power/chat", json={"offline": True})
        self.assertEqual(404, r.status_code,
                         f"expected the same answer an absent feature gives; got "
                         f"{r.status_code} {r.text[:120]}")
        self.assertNotIn("offline", r.text,
                         "the reply names the payload field, which tells a visitor the "
                         "shape of a control they were not supposed to learn exists")

    def test_an_empty_body_also_answers_404_when_the_switch_is_off(self):
        """The 422 path specifically: no body at all used to be the loudest disclosure."""
        r = self._client().post("/api/rack/power/chat")
        self.assertEqual(404, r.status_code, r.text[:120])

    def test_the_get_still_answers_404_too(self):
        self.assertEqual(404, self._client().get("/api/rack/power").status_code)
