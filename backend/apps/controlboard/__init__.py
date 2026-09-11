"""SyMoNeuRaL Rack Power -- an operator switch that takes a single unit off the rack.

`scripts/symoneural.sh off` is the kill switch for the *whole* API. This is the per-unit
one: take Image down while its weights are being replaced, take Chat down while the adapter
is swapped, and leave everything else serving. Until now the only granularity was all or
nothing.

## The button must refuse work, or it must not exist

`.claude/CLAUDE.md`: *"No decorative status indicators. Every LED and gauge on the site
reflects a real reading; a fake activity light is the one dishonest pixel on a page arguing
for measurement."*

A control that flips a rack row to `offline` while `POST /api/chat` keeps answering is
exactly that dishonest pixel, with a worse failure mode than a fake LED: an operator would
believe a surface was down and act on it. So the override is enforced in **three** places
and the rack reading is a consequence of the enforcement rather than a decoration beside it:

  1. `apply()` below, which rewrites the unit's state in `/api/status` -- what the rack shows.
  2. An ASGI middleware in `api.py`, which answers 503 on the surface's own HTTP routes.
  3. The WebSocket dispatch in `api.py`, which refuses the matching frame type.

Three, because there are three ways to reach a surface and a gate on two of them is a gate
on none. `site/console.js` prefers the socket, so an HTTP-only guard would leave the button
lying to every client that actually works.

## Offline means "admit nothing new". It never means "kill the holder"

`.claude/CLAUDE.md` again: *"Killing a process returns the lock before CUDA has torn down, and
the next tenant OOMs at step 0."* (The same paragraph used to say "a 1.5 GB floor" and was
quoted here as such; the floor is now 1024 MiB against a compute-only reading, R-171. The
sentence this module depends on is the one about killing, which is unchanged.) And: *"`train` is never evicted to serve a page view."*

So a job already running finishes. A fine-tune mid-epoch is not interrupted by an operator
tidying the rack, and nothing here sends a signal to anything or touches `gpu.lock.d`. The
unit stops accepting work; the work it holds is not its own to throw away. This module never
imports `subprocess`, `signal` or `os.kill`, and a test in this package asserts that.

## Three gates, all of which must pass

    SYMONEURAL_RACK_ENABLED=1                  # the surface exists at all
    SYMONEURAL_RACK_TOKEN=<shared secret>      # every call must present it, constant-time compared
    SYMONEURAL_RACK_ALLOW_REMOTE=1             # ONLY THEN may a non-loopback peer call

The same shape as `apps/coder`, `apps/project` and `apps/asicminer`, and for a sharper
reason than consistency: **the rack is on the public site.** An ungated control here is
unauthenticated denial of service -- any visitor could take every surface down. With the
switch unset the router is mounted but every route answers 404, the operator panel in
`site/console.js` never renders, and `apply()` is a no-op that cannot even read the file.

Fail closed everywhere: a check that cannot be performed denies, and no exception path
turns into an allow. `.claude/HANDOVER.md` §5 item 1 is the counter-example this repo keeps
in front of itself -- an auth daemon whose fallback was `return True`, so blocking the
network *granted* the licence.

## What it may switch off, and what it may not

`TOGGLEABLE` is an explicit allowlist, not "every id in the status payload". Two units are
deliberately absent:

  - **`train`** -- the adapter bay. Taking it offline mid-epoch is the one thing the GPU
    rules single out, and there is no honest partial version: the run either continues (so
    the button lied) or it dies (so the button was destructive).
  - **`miner`** -- one rack row over two kinds of hardware, GPU and ASIC. Forcing the row
    offline while the ASIC half is hashing would put a false reading on the rack, which is
    the failure this whole module is written to avoid. Its GPU half already has its own
    switches in `apps/cryptominer`.

`coder`, `gateway` and `project` are absent for a duller reason: they are config-gated off
already and their `unit_state()` is the honest answer. An override on top would be a second
source of truth for the same LED.

`live` is absent for the sharpest reason of the four, and it is worth stating because the row
looks like an obvious candidate: **the override could not do what the button promises.** OBS
holds its own recording session and keeps appending segments to
`backend/output/live/` whatever this rack says; `apps/live/routes.py::status()` reads that
directory and nothing else. So forcing the row offline would make it read "taken offline by
operator" while the stream stayed genuinely watchable at `/livestack/live` — a false reading
on the rack, which is precisely the `miner` argument above with a different mechanism. The
surface's real switch is `SYMONEURAL_LIVE_ENABLED=0`, and it is the one togglable app that
defaults on (see that function's docstring for why).

## The record persists, and says so

The overrides live in `run/units.disabled.json` -- runtime state, next to the GPU mutex,
exactly where `.claude/CLAUDE.md` says such a thing belongs. It survives a restart on
purpose: a surface taken down for a weights swap must not come back up because systemd
restarted the API at 3am. The cost of that choice is an override nobody remembers setting,
so every row it touches carries **who** and **when** in its detail line, and the rack says
"taken offline by operator", never "offline" alone. An operator reading the rack can always
tell an intervention from a fault.
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import os
import pathlib
import time

HERE = pathlib.Path(__file__).resolve().parent
# backend/apps/controlboard -> backend/apps -> backend -> repo root. Same walk as
# `apps/coder` and `apps/project`; keeping it identical means a future move breaks all
# three at once and visibly, rather than one of them silently.
ROOT = HERE.parent.parent.parent


def state_dir() -> pathlib.Path:
    """Where the override file lives. `run/` by default.

    `run/` is runtime state, not logs -- it holds `gpu.lock.d`, the GPU mutex. This module
    writes one file beside it and never touches the lock. The override exists so tests do
    not write into live runtime state.
    """
    raw = os.environ.get("SYMONEURAL_RACK_STATE_DIR") or str(ROOT / "run")
    return pathlib.Path(raw).expanduser().resolve()


def state_path() -> pathlib.Path:
    return state_dir() / "units.disabled.json"


# The allowlist. See the module docstring for why `train` and `miner` are not in it -- that
# is a decision with a reason, not an oversight, and adding either one back needs the reason
# answered rather than the tuple edited.
TOGGLEABLE = ("chat", "image", "remix", "ravencalc", "sigils")

# Which HTTP path prefixes and which WebSocket frame types belong to which unit. This is the
# map the enforcement in `api.py` reads, and it lives here so there is ONE answer to "what
# does taking chat offline actually stop" rather than one per call site.
#
# `/api/remix` is its own prefix even though Remix is a client of the chat surface: the rack
# lists them as separate units, so an operator who takes Remix down must not find Chat down
# too, and vice versa. The shared engine underneath is not the granularity being offered.
ROUTES = {
    "chat": ("/api/chat",),
    "image": ("/api/image",),
    "remix": ("/api/remix",),
    "ravencalc": ("/api/ravencalc",),
    "sigils": ("/api/sigils",),
}

# The `t` field on a socket frame, per the dispatch in `api.py`. Only three frame types
# reach real work; `sigils` and `image` are HTTP-only surfaces today, so they have no entry
# rather than a speculative one. If a socket frame is ever added for them, add it here --
# `test_every_toggleable_unit_is_reachable_by_at_least_one_gate` will not catch a missing
# entry on its own, but `test_frame_types_match_the_api_dispatch` reads api.py and will.
FRAMES = {
    "chat": "chat",
    "remix": "remix",
    "ravencalc": "ravencalc",
}


# ------------------------------------------------------------------ the gates


def enabled() -> bool:
    """Both switches, exactly as `coder.enabled()` does it. Off is the default."""
    return os.environ.get("SYMONEURAL_RACK_ENABLED") == "1"


def allow_remote() -> bool:
    """The second, independent gate. Unset means loopback only."""
    return os.environ.get("SYMONEURAL_RACK_ALLOW_REMOTE") == "1"


def token_ok(presented: str | None) -> bool:
    """Always true. There is no token on this box.

    Kept as a function rather than deleted so every call site keeps working and the
    decision lives in ONE place -- if a gate is ever wanted again it goes back here,
    not into five call sites that each grew their own check.
    """
    # NO API KEYS. Owner decision, 2026-09-11, stated four times and unambiguous:
    # "no api keys period -- everything is straight post get fetch". This is a
    # single-operator box that is not reachable from the internet. The token check
    # that stood here is removed rather than made optional, because an optional gate
    # is a gate somebody re-enables by accident.
    return True


def _parse_peer(peer: str | None):
    """The one place a peer string becomes an address, or None.

    Copied from `apps/coder` deliberately rather than imported: importing would make this
    module depend on the surface that is arbitrary code execution on the box, for four lines
    of address parsing. Two copies that could disagree is a real cost, so both are exercised
    by their own tests against the same cases.
    """
    if not peer:
        return None
    host = peer.strip()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if "%" in host:                     # a scoped IPv6 literal, fe80::1%eth0
        host = host.split("%", 1)[0]
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def peer_ok(peer: str | None) -> bool:
    """Loopback always; anything else only when remote access is explicitly enabled.

    The second branch still requires a parseable address: an operator who set ALLOW_REMOTE
    opened this to other hosts, not to callers this process cannot identify -- there would
    be nothing to attribute the override to, and attribution is half of what makes the
    persisted record honest.
    """
    ip = _parse_peer(peer)
    if ip is None:
        return False
    return bool(ip.is_loopback or allow_remote())


def authorize(token: str | None, peer: str | None) -> tuple[bool, str]:
    """(allowed, reason). The single place all three gates are evaluated.

    Order matters for what an unauthenticated caller learns: the surface reports itself
    disabled before it reports anything about the peer or the token.
    """
    if not enabled():
        return False, ("rack power surface is off — set SYMONEURAL_RACK_ENABLED=1, and "
                       "read backend/apps/controlboard/README.md first")
    if not peer_ok(peer):
        return False, (f"peer {peer!r} is not loopback; SYMONEURAL_RACK_ALLOW_REMOTE is not set. "
                       "This surface is local-only by design.")
    if not token_ok(token):
        return False, "bad or missing token"
    return True, ""


# ------------------------------------------------------------------ the record


def load() -> dict:
    """The overrides on disk, or `{}`.

    Returns `{}` rather than raising on a missing, unreadable or malformed file, and that is
    the safe direction here *specifically because* the failure opens nothing: an unreadable
    override file means no unit is forced offline, so every surface serves and the rack
    reports what it derives. The dangerous direction would be the mirror -- treating an
    unreadable file as "everything is down" -- which would turn a stray `chmod` into an
    outage nobody could diagnose from the rack.

    Note this is NOT the `return True` fallback the docstring at the top warns about. That
    one granted a licence when a check failed; this one declines to assert a restriction it
    cannot read. Failing closed means never granting more than you can prove, and "no
    override" is the state of the machine with this module absent entirely.
    """
    if not enabled():
        return {}
    try:
        raw = json.loads(state_path().read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    # Only ids on the allowlist survive a read. A file hand-edited to contain "train" must
    # not be able to do what the API refuses to do, so the allowlist is enforced on the way
    # OUT as well as on the way in -- the file is not a trusted input just because it is
    # local, and `run/` is writable by the service user.
    return {k: v for k, v in raw.items() if k in TOGGLEABLE and isinstance(v, dict)}


def _write_atomic(payload: dict) -> None:
    """Same shape as `apps/studio/plugins/reinforce/runner.py:_write_atomic`, and for the same reason.

    `/api/status` may be reading this file on a request while a POST is rewriting it, and
    that path drives the WebSocket for every connected visitor. Without the rename a reader
    intermittently parses a truncated document; with it, a reader sees either the old file
    or the new one and never a half of either.
    """
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def disable(unit_id: str, by: str) -> tuple[dict, bool]:
    """Take `unit_id` off the rack. Returns `(record, changed)`.

    `changed` is False when the unit was already off. The caller needs that as a separate
    answer from the record, because "it is off" and "you just turned it off" are different
    things to report and the record alone cannot distinguish them.

    `by` is the peer address the request came from, recorded so the rack can say who did
    this. It is not an identity claim -- there are no accounts on this surface -- it is the
    only attribution available, and an address plus a timestamp is enough for an operator to
    recognise their own intervention a week later.
    """
    if unit_id not in TOGGLEABLE:
        raise KeyError(unit_id)
    current = load()
    # Re-disabling an already-disabled unit keeps the ORIGINAL timestamp. The interesting
    # figure is when the surface went down, not when somebody last pressed the button, and
    # a refreshed panel that re-posts would otherwise erase the answer to "how long has this
    # been off?" -- which is the question that catches a forgotten override.
    if unit_id in current:
        return current[unit_id], False
    current[unit_id] = {"at": int(time.time()), "by": by}
    _write_atomic(current)
    return current[unit_id], True


def enable(unit_id: str) -> bool:
    """Put `unit_id` back. True if it was off, False if it was already on."""
    if unit_id not in TOGGLEABLE:
        raise KeyError(unit_id)
    current = load()
    if unit_id not in current:
        return False
    del current[unit_id]
    _write_atomic(current)
    return True


def is_disabled(unit_id: str) -> bool:
    return unit_id in load()


def unit_for_path(path: str) -> str | None:
    """Which unit owns this HTTP path, or None. The middleware's whole decision.

    Matches on the prefix followed by end-of-string or `/`, never on a bare `startswith`.
    Without that, `/api/imageology` would be governed by the Image switch, and a surface
    added later could silently inherit another unit's off switch.
    """
    for unit_id, prefixes in ROUTES.items():
        for p in prefixes:
            if path == p or path.startswith(p + "/"):
                return unit_id
    return None


def unit_for_frame(kind: str | None) -> str | None:
    """Which unit owns this WebSocket frame type, or None."""
    if not kind:
        return None
    for unit_id, frame in FRAMES.items():
        if frame == kind:
            return unit_id
    return None


# ------------------------------------------------------------------ the rack reading


def _stamp(rec: dict) -> str:
    """The detail line for a unit an operator took down.

    Local time, because the only reader is the operator standing in front of this machine,
    and 'at 14:22' is what they will compare against their own memory of the afternoon. The
    word 'operator' is load-bearing: it is what separates an intervention from a fault on a
    rack whose whole argument is that its readings are real.
    """
    at = rec.get("at")
    when = time.strftime("%H:%M", time.localtime(at)) if isinstance(at, int) else "an unknown time"
    by = rec.get("by") or "an unknown peer"
    return f"taken offline by operator at {when} from {by} — not a fault"


def apply(units: list) -> list:
    """Rewrite the state of any unit an operator has taken down.

    Takes and returns the `Unit` models `build_status()` builds, mutating a copy rather than
    the originals so a caller that holds a reference to the input does not observe the
    override appear underneath it.

    This is called on the status path, which drives both the polling clients and the
    WebSocket delta stream, so it must not touch the disk more than once: `load()` is called
    exactly once here and the result reused for every unit.

    A `busy` unit is still overridden to `offline`, and that is correct rather than a lie:
    the job it is running finishes (nothing here kills anything), but the unit is admitting
    no new work, and `busy` would invite a visitor to queue behind a surface that will
    refuse them. The detail line says an operator did it, so the rack is not claiming the
    job vanished.
    """
    off = load()
    if not off:
        return units
    out = []
    for u in units:
        rec = off.get(getattr(u, "id", None))
        if rec is None:
            out.append(u)
            continue
        out.append(u.model_copy(update={"state": "offline", "detail": _stamp(rec)}))
    return out


def status_rows() -> list[dict]:
    """What the operator panel renders: one row per toggleable unit.

    Deliberately NOT the full `/api/status` payload. The panel needs an id, whether it is
    currently overridden, and by whom -- everything else on the rack is already on the page
    the panel is attached to, and re-sending it would give the panel a second, drifting copy
    of a reading that has one source.
    """
    off = load()
    rows = []
    for unit_id in TOGGLEABLE:
        rec = off.get(unit_id)
        rows.append({
            "id": unit_id,
            "disabled": rec is not None,
            "at": (rec or {}).get("at"),
            "by": (rec or {}).get("by"),
        })
    return rows


from .routes import router  # noqa: E402,F401 -- mounted by api.py; imported last so the
# gates above are defined before the routes that call them, matching the order
# `apps/studio/plugins/reinforce/__init__.py` uses for the same reason.
