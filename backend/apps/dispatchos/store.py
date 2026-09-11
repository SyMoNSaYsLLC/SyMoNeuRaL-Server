"""DispatchOS persistence: users, bookings, the lifecycle, and the record trail.

Task #106. SQLite, one file, WAL, no ORM -- the same shape `apps/accounts` and
`apps/project` already use on this box, and for the same reason: there is no wheel to
install and the whole store is one file somebody can copy.

## Why DispatchOS has its own user table

`apps/accounts` is the site's account system and it is **off** on this box --
`enabled()` wants `SYMONEURAL_ACCOUNTS_ENABLED=1` *and* a 32-character
`SYMONEURAL_SESSION_SECRET`, and `/etc/symoneural/api.env` sets neither. Switching it on
to get four logins would open public signup on `/account.html` for every visitor to
symoneural.com, days before a customer is shown the site. That is a large blast radius
for a demo login.

So the table is local, and **the crypto is not**: `hash_password` and `check_password` are
imported from `apps.accounts` rather than reimplemented. Those are scrypt with measured
parameters and a documented `maxmem` argument that OpenSSL requires above N=2^15; writing
a second password hasher next door to a good one is how the second one ends up weaker.

The roles here are `operator` and `customer`, which are not the site's `member`/`owner`
roles and do not map onto them. An operator sees every booking and can move it through the
lifecycle. A customer sees their own bookings and can request one. That is the whole model.

## What is deliberately NOT in this schema

The customer preview Donnie has read lists these as **deferred**, with the page saying in
writing that they are *"a deliberate omission with a reason, not a gap to be quietly filled
in later"*: full customer dashboard, customer database dashboard, revenue tracker,
repeat-rider memory, call/text summaries, AI dashboard metrics, full inbound AI call
workflow, and formal billing and payment terms. There is no revenue column, no rider
history join and no payment table, and adding one would contradict a document the customer
is about to be emailed.

`messages` rows are **never sent**. The preview says the record trail is "preview/demo only
-- no live email or storage is claimed from this page" and that live routing happens only
after approved email configuration. So a reminder is composed, stored and shown, and the
`sent_at` column stays NULL. There is no SMTP client in this package.
"""
from __future__ import annotations

import json
import os
import pathlib
import secrets
import sqlite3
import time
from typing import Any, Iterable

from apps.accounts import (WeakPassword, check_password_or_dummy, hash_password,
                           validate_password)

#: The lifecycle, in order, taken from the six panels of the customer preview's "booking
#: loop" section: Request, Quote, Confirm, Dispatch, Reminder, Review. `cancelled` is a
#: terminal state reachable from anywhere before `completed` -- a trip that does not happen
#: is a real outcome and pretending otherwise leaves rows stuck in `confirmed` forever.
STATES = ("requested", "quoted", "confirmed", "dispatched", "completed", "reviewed", "cancelled")

#: Which states a booking may move to from each state. Enforced in `advance()` rather than
#: trusted to the caller: the operator UI offers one button, but the API is reachable by
#: anything holding a session and an out-of-order transition corrupts the record trail
#: rather than erroring.
NEXT = {
    "requested":  ("quoted", "cancelled"),
    "quoted":     ("confirmed", "cancelled"),
    "confirmed":  ("dispatched", "cancelled"),
    "dispatched": ("completed", "cancelled"),
    "completed":  ("reviewed",),
    "reviewed":   (),
    "cancelled":  (),
}

ROLES = ("operator", "customer")

_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY,
    username   TEXT NOT NULL UNIQUE COLLATE NOCASE,
    role       TEXT NOT NULL,
    pw_hash    TEXT NOT NULL,          -- scrypt$params$salt$dk, from apps.accounts
    label      TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    -- Explicit, nullable reference to a shared-accounts identity. NULL means this user has
    -- no shared identity and is therefore NOT entitled -- the fail-closed default falls out
    -- of the nullability rather than needing a branch. Never inferred from username: a
    -- case-insensitive handle is not a normalised address, and a silent collision between
    -- the two would be an authorization bypass.
    shared_account_id TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,       -- sha256 of the cookie value; the value is not stored
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS login_attempts (
    scope        TEXT NOT NULL,          -- 'account' | 'ip'
    key          TEXT NOT NULL,
    fails        INTEGER NOT NULL DEFAULT 0,
    last_fail    REAL NOT NULL DEFAULT 0,
    locked_until REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (scope, key)
);
CREATE TABLE IF NOT EXISTS bookings (
    id          INTEGER PRIMARY KEY,
    ref         TEXT NOT NULL UNIQUE,
    state       TEXT NOT NULL,
    owner_id    INTEGER REFERENCES users(id),   -- the customer this trip belongs to
    rider       TEXT NOT NULL DEFAULT '',
    contact     TEXT NOT NULL DEFAULT '',
    pickup      TEXT NOT NULL DEFAULT '',
    dropoff     TEXT NOT NULL DEFAULT '',
    when_text   TEXT NOT NULL DEFAULT '',
    passengers  INTEGER NOT NULL DEFAULT 1,
    luggage     INTEGER NOT NULL DEFAULT 0,
    notes       TEXT NOT NULL DEFAULT '',
    quote_json  TEXT NOT NULL DEFAULT '',
    driver_id   INTEGER REFERENCES drivers(id),
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS drivers (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL,
    vehicle TEXT NOT NULL DEFAULT '',
    active  INTEGER NOT NULL DEFAULT 1
);
-- The record trail. Append-only by construction: nothing in this module updates or deletes
-- an events row, which is what makes it usable as an answer to "what happened to this job".
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY,
    booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    at         REAL NOT NULL,
    actor      TEXT NOT NULL,
    kind       TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT ''
);
-- Composed, stored, shown. NEVER sent: sent_at stays NULL and there is no sender in this
-- package. See the module docstring.
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY,
    booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    at         REAL NOT NULL,
    kind       TEXT NOT NULL,          -- reminder | review_request | confirmation
    to_whom    TEXT NOT NULL DEFAULT '',
    body       TEXT NOT NULL,
    sent_at    REAL                    -- always NULL here, on purpose
);
-- Operator configuration, keyed. Holds the rate rules, which ship EMPTY: see quotes.py for
-- why there is no default tariff anywhere in this package.
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_bookings_state ON bookings(state);
CREATE INDEX IF NOT EXISTS ix_bookings_owner ON bookings(owner_id);
CREATE INDEX IF NOT EXISTS ix_events_booking ON events(booking_id, at);
CREATE INDEX IF NOT EXISTS ix_messages_booking ON messages(booking_id, at);
"""

SESSION_TTL_S = 12 * 3600
ACCOUNT_FREE_FAILS = 3
ACCOUNT_BASE_LOCK_S = 5.0
ACCOUNT_MAX_LOCK_S = 900.0
IP_FREE_FAILS = 20
IP_BASE_LOCK_S = 5.0
IP_MAX_LOCK_S = 900.0
ATTEMPT_DECAY_S = 3600.0


class DispatchError(Exception):
    """Anything a caller did wrong. Carries a message safe to show a signed-in user."""


class DispatchThrottled(DispatchError):
    """Too many failed logins. ``retry_after`` is rounded up seconds."""

    def __init__(self, scope: str, retry_after: float):
        self.scope = scope
        self.retry_after = max(1, int(retry_after + 0.999))
        super().__init__(f"too many failed attempts ({scope}); retry in "
                         f"{self.retry_after}s")


def db_path() -> pathlib.Path:
    """Where the store lives.

    `SYMONEURAL_DISPATCHOS_DB` overrides, which is what the tests use so a run never touches
    a real store. The default is under `run/`, beside the other per-surface state on this
    box, and NOT under `site/` -- `scripts/deploy.sh` publishes `site/` at `-maxdepth 1`, so
    a database there would be one boot away from being downloadable.
    """
    env = os.environ.get("SYMONEURAL_DISPATCHOS_DB", "").strip()
    if env:
        return pathlib.Path(env)
    root = pathlib.Path(__file__).resolve().parents[3]
    return root / "run" / "dispatchos.db"


def _conn() -> sqlite3.Connection:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(p), timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def _migrate_shared_account_id(c: sqlite3.Connection) -> bool:
    """Add users.shared_account_id when an existing database predates it.

    `CREATE TABLE IF NOT EXISTS` does not add a column to a table that already exists, so a
    database created before this column would silently keep the old shape and every
    entitlement lookup would fail on a missing column rather than on a missing grant.

    There is no ALTER TABLE anywhere else in this repo's stores, so this establishes the
    pattern: probe the live columns, add only when absent, never backfill. Repeatable by
    construction -- the second run finds the column and does nothing. Returns True when it
    added the column, so a caller (and a test) can tell a migration from a no-op.
    """
    cols = {r["name"] for r in c.execute("PRAGMA table_info(users)").fetchall()}
    if not cols:
        return False                    # table not created yet; the schema will include it
    if "shared_account_id" in cols:
        return False                    # already present -- no change, no data touched
    c.execute("ALTER TABLE users ADD COLUMN shared_account_id TEXT")
    return True


def init_db() -> None:
    with _conn() as c:
        c.executescript(_SCHEMA)
        _migrate_shared_account_id(c)
    try:
        os.chmod(db_path(), 0o600)
    except OSError:
        pass          # a store on a filesystem without modes is not a reason to refuse


def enabled() -> bool:
    """Off unless switched on. One switch, and it fails closed.

    Deliberately NOT also gated on a token, unlike `apps/project` and `apps/coder`: those
    surfaces have no login of their own, so their token *is* their authentication. This one
    has real accounts with real password hashes, so a shared bearer token beside them would
    be a second, weaker credential for the same data.
    """
    return os.environ.get("SYMONEURAL_DISPATCHOS_ENABLED") == "1"


# ------------------------------------------------------------------ users and sessions

def _row_user(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "username": r["username"], "role": r["role"], "label": r["label"]}


def _validated_password(password: str, username: str) -> str:
    try:
        return validate_password(password, email=username)
    except WeakPassword as exc:
        raise DispatchError(str(exc)) from None


def create_user(username: str, password: str, role: str, label: str = "") -> dict:
    username = (username or "").strip()
    if not username:
        raise DispatchError("a username is required")
    if role not in ROLES:
        raise DispatchError(f"role must be one of {', '.join(ROLES)}")
    password = _validated_password(password, username)
    with _conn() as c:
        try:
            cur = c.execute(
                "INSERT INTO users(username, role, pw_hash, label, created_at) "
                "VALUES(?,?,?,?,?)",
                (username, role, hash_password(password), label, time.time()))
        except sqlite3.IntegrityError:
            raise DispatchError(f"the username {username!r} is already taken") from None
        return {"id": cur.lastrowid, "username": username, "role": role, "label": label}


def set_password(username: str, password: str) -> None:
    password = _validated_password(password, username)
    replacement = hash_password(password)
    with _conn() as c:
        row = c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if not row:
            raise DispatchError("no such user")
        c.execute("UPDATE users SET pw_hash=? WHERE id=?", (replacement, row["id"]))
        # A reset is also an incident-response action: every existing cookie must stop.
        c.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))


def list_users() -> list[dict]:
    with _conn() as c:
        return [_row_user(r) for r in
                c.execute("SELECT * FROM users ORDER BY role, username")]


def _attempt(c: sqlite3.Connection, scope: str, key: str) -> sqlite3.Row | None:
    return c.execute("SELECT * FROM login_attempts WHERE scope=? AND key=?",
                     (scope, key)).fetchone()


def _throttle_check(c: sqlite3.Connection, scope: str, key: str, now: float) -> None:
    row = _attempt(c, scope, key)
    if row is not None and row["locked_until"] > now:
        raise DispatchThrottled(scope, row["locked_until"] - now)


def _throttle_fail(c: sqlite3.Connection, scope: str, key: str, now: float,
                   free: int, base: float, cap: float) -> None:
    row = _attempt(c, scope, key)
    fails = int(row["fails"]) if row is not None else 0
    last = float(row["last_fail"]) if row is not None else 0.0
    locked = float(row["locked_until"]) if row is not None else 0.0
    if locked <= now and (now - last) > ATTEMPT_DECAY_S:
        fails = 0
    fails += 1
    if fails > free:
        locked = now + min(base * (2.0 ** (fails - free - 1)), cap)
    c.execute(
        "INSERT INTO login_attempts(scope,key,fails,last_fail,locked_until) VALUES(?,?,?,?,?) "
        "ON CONFLICT(scope,key) DO UPDATE SET fails=excluded.fails, "
        "last_fail=excluded.last_fail, locked_until=excluded.locked_until",
        (scope, key, fails, now, locked))


def _throttle_clear(c: sqlite3.Connection, scope: str, key: str) -> None:
    c.execute("DELETE FROM login_attempts WHERE scope=? AND key=?", (scope, key))


def login(username: str, password: str, *, ip: str = "", now: float | None = None
          ) -> str | None:
    """Verify and issue a session token, or return None.

    One answer for a wrong password and for an unknown user, and the scrypt call runs in
    both cases -- `apps/accounts` documents why at length and the reasoning is identical:
    returning early on an unknown name turns response time into a user-enumeration oracle.
    """
    username = (username or "").strip()
    account_key = username.casefold()
    ip = (ip or "").strip()
    now = time.time() if now is None else now
    with _conn() as c:
        if account_key:
            _throttle_check(c, "account", account_key, now)
        if ip:
            _throttle_check(c, "ip", ip, now)
        r = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        stored = r["pw_hash"] if r else None

    # The current precomputed dummy costs the same as a real current hash.  Never generate
    # a new one here: doing so adds a second attacker-controlled scrypt for unknown users.
    ok = check_password_or_dummy(stored, password or "")
    with _conn() as c:
        current = c.execute("SELECT id, pw_hash FROM users WHERE username=?",
                            (username,)).fetchone()
        # Re-read before issuing. If an operator changed the password while scrypt was
        # running, the old hash must not mint one final session after that reset.
        unchanged = bool(r and current and current["id"] == r["id"] and
                         current["pw_hash"] == stored)
        if not (unchanged and ok):
            if account_key:
                _throttle_fail(c, "account", account_key, now,
                               ACCOUNT_FREE_FAILS, ACCOUNT_BASE_LOCK_S, ACCOUNT_MAX_LOCK_S)
            if ip:
                _throttle_fail(c, "ip", ip, now,
                               IP_FREE_FAILS, IP_BASE_LOCK_S, IP_MAX_LOCK_S)
            return None
        _throttle_clear(c, "account", account_key)
        if ip:
            _throttle_clear(c, "ip", ip)
        token = secrets.token_urlsafe(32)
        c.execute("INSERT INTO sessions(token_hash, user_id, created_at, expires_at) "
                  "VALUES(?,?,?,?)",
                  (_token_hash(token), current["id"], now, now + SESSION_TTL_S))
        return token


def _token_hash(token: str) -> str:
    import hashlib
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def read_session(token: str) -> dict | None:
    """The signed-in user, or None. Expired rows are deleted on the way past."""
    if not token:
        return None
    with _conn() as c:
        r = c.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash=? AND s.expires_at > ?",
            (_token_hash(token), time.time())).fetchone()
        c.execute("DELETE FROM sessions WHERE expires_at <= ?", (time.time(),))
        return _row_user(r) if r else None


def logout(token: str) -> None:
    if not token:
        return
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))


# ------------------------------------------------------------------ bookings

def _ref() -> str:
    """A human-quotable reference. Not sequential: a customer-visible counter tells every
    customer how many jobs the operator has, which is the operator's business and not
    theirs."""
    return "DX-" + secrets.token_hex(3).upper()


def create_booking(*, actor: str, owner_id: int | None, rider: str, contact: str,
                   pickup: str, dropoff: str, when_text: str,
                   passengers: int = 1, luggage: int = 0, notes: str = "") -> dict:
    if not (pickup or "").strip() or not (dropoff or "").strip():
        raise DispatchError("a pickup and a drop-off are both required")
    passengers = max(1, min(int(passengers or 1), 16))
    luggage = max(0, min(int(luggage or 0), 32))
    now = time.time()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO bookings(ref, state, owner_id, rider, contact, pickup, dropoff,"
            " when_text, passengers, luggage, notes, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_ref(), "requested", owner_id, rider.strip(), contact.strip(), pickup.strip(),
             dropoff.strip(), when_text.strip(), passengers, luggage, notes.strip(), now, now))
        bid = cur.lastrowid
        c.execute("INSERT INTO events(booking_id, at, actor, kind, detail) VALUES(?,?,?,?,?)",
                  (bid, now, actor, "requested", "trip requested"))
    return get_booking(bid)


def get_booking(bid: int) -> dict:
    with _conn() as c:
        r = c.execute("SELECT * FROM bookings WHERE id=?", (bid,)).fetchone()
        if not r:
            raise DispatchError("no such booking")
        d = dict(r)
        d["quote"] = json.loads(d.pop("quote_json") or "null")
        d["events"] = [dict(e) for e in c.execute(
            "SELECT at, actor, kind, detail FROM events WHERE booking_id=? ORDER BY at, id", (bid,))]
        d["messages"] = [dict(m) for m in c.execute(
            "SELECT id, at, kind, to_whom, body, sent_at FROM messages WHERE booking_id=?"
            " ORDER BY at, id", (bid,))]
        if d["driver_id"]:
            dr = c.execute("SELECT name, vehicle FROM drivers WHERE id=?", (d["driver_id"],)).fetchone()
            d["driver"] = dict(dr) if dr else None
        else:
            d["driver"] = None
        return d


def list_bookings(*, owner_id: int | None = None, states: Iterable[str] | None = None) -> list[dict]:
    q = "SELECT * FROM bookings"
    where, args = [], []
    if owner_id is not None:
        where.append("owner_id = ?"); args.append(owner_id)
    if states:
        states = list(states)
        where.append("state IN (%s)" % ",".join("?" * len(states))); args += states
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY updated_at DESC"
    with _conn() as c:
        out = []
        for r in c.execute(q, args):
            d = dict(r)
            d["quote"] = json.loads(d.pop("quote_json") or "null")
            out.append(d)
        return out


def set_quote(bid: int, quote: dict, *, actor: str) -> dict:
    """Attach a quote and move to `quoted`.

    The quote is stored as the engine returned it, including the case where it could not
    produce a figure. That is the normal case today and is not an error: the customer
    preview says in writing that it "carries no pricing of any kind" and that rate rules are
    configured after written scope.
    """
    with _conn() as c:
        r = c.execute("SELECT state FROM bookings WHERE id=?", (bid,)).fetchone()
        if not r:
            raise DispatchError("no such booking")
        if r["state"] != "requested":
            raise DispatchError(f"a booking in state {r['state']} cannot be quoted")
        now = time.time()
        c.execute("UPDATE bookings SET quote_json=?, state='quoted', updated_at=? WHERE id=?",
                  (json.dumps(quote), now, bid))
        c.execute("INSERT INTO events(booking_id, at, actor, kind, detail) VALUES(?,?,?,?,?)",
                  (bid, now, actor, "quoted", quote.get("basis", "quoted")))
    return get_booking(bid)


def advance(bid: int, to: str, *, actor: str, driver_id: int | None = None,
            detail: str = "") -> dict:
    """Move a booking one legal step. Refuses anything `NEXT` does not allow."""
    if to not in STATES:
        raise DispatchError(f"{to!r} is not a state")
    with _conn() as c:
        r = c.execute("SELECT state FROM bookings WHERE id=?", (bid,)).fetchone()
        if not r:
            raise DispatchError("no such booking")
        cur = r["state"]
        if to not in NEXT[cur]:
            allowed = ", ".join(NEXT[cur]) or "nothing -- it is finished"
            raise DispatchError(f"a booking in state {cur} can only move to {allowed}")
        now = time.time()
        if driver_id is not None:
            c.execute("UPDATE bookings SET driver_id=? WHERE id=?", (driver_id, bid))
        c.execute("UPDATE bookings SET state=?, updated_at=? WHERE id=?", (to, now, bid))
        c.execute("INSERT INTO events(booking_id, at, actor, kind, detail) VALUES(?,?,?,?,?)",
                  (bid, now, actor, to, detail))
    return get_booking(bid)


# ------------------------------------------------------------------ drivers and messages

def add_driver(name: str, vehicle: str = "") -> dict:
    if not (name or "").strip():
        raise DispatchError("a driver needs a name")
    with _conn() as c:
        cur = c.execute("INSERT INTO drivers(name, vehicle) VALUES(?,?)",
                        (name.strip(), vehicle.strip()))
        return {"id": cur.lastrowid, "name": name.strip(), "vehicle": vehicle.strip(), "active": 1}


def list_drivers() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM drivers ORDER BY active DESC, name")]


def compose_message(bid: int, kind: str, body: str, to_whom: str = "") -> dict:
    """Store a message. It is NOT sent, and nothing in this package can send it.

    `sent_at` is left NULL and there is no code path that sets it. The customer preview
    states that live email routing requires approved configuration and written terms, so a
    surface that quietly delivered would make that page false.
    """
    if kind not in ("reminder", "review_request", "confirmation"):
        raise DispatchError(f"{kind!r} is not a message kind")
    now = time.time()
    with _conn() as c:
        if not c.execute("SELECT 1 FROM bookings WHERE id=?", (bid,)).fetchone():
            raise DispatchError("no such booking")
        cur = c.execute(
            "INSERT INTO messages(booking_id, at, kind, to_whom, body, sent_at)"
            " VALUES(?,?,?,?,?,NULL)", (bid, now, kind, to_whom, body))
        c.execute("INSERT INTO events(booking_id, at, actor, kind, detail) VALUES(?,?,?,?,?)",
                  (bid, now, "system", "message", f"{kind} composed (not sent)"))
        return {"id": cur.lastrowid, "kind": kind, "body": body, "sent_at": None}


def get_setting(key: str, default: Any = None) -> Any:
    with _conn() as c:
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def set_setting(key: str, value: Any) -> None:
    with _conn() as c:
        c.execute("INSERT INTO settings(key, value) VALUES(?,?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, json.dumps(value)))


def counts() -> dict[str, int]:
    with _conn() as c:
        rows = c.execute("SELECT state, COUNT(*) n FROM bookings GROUP BY state").fetchall()
    out = {s: 0 for s in STATES}
    for r in rows:
        out[r["state"]] = r["n"]
    return out


def seed_demo_users(passwords: dict[str, str]) -> list[dict]:
    """Create the four accounts Garrett asked to test, if they are absent.

    `garrett` and `ben` at operator level, `garrett-rider` and `ben-rider` at customer
    level -- his words were "garrett and ben logins (including test customer level garrett
    and ben logins)", which is two people at two tiers, not two accounts.

    Passwords are passed in, never generated here and never defaulted. A default password in
    a repository is a live credential the moment somebody deploys without reading this.
    """
    made = []
    have = {u["username"].lower() for u in list_users()}
    for name, role, label in (("garrett", "operator", "Garrett (operator)"),
                              ("ben", "operator", "Ben (operator)"),
                              ("garrett-rider", "customer", "Garrett (customer view)"),
                              ("ben-rider", "customer", "Ben (customer view)")):
        if name.lower() in have:
            continue
        pw = passwords.get(name)
        if not pw:
            continue
        made.append(create_user(name, pw, role, label))
    return made


# ------------------------------------------------------------------ identity correspondence
#
# One explicit nullable reference, set at provisioning. NULL means no shared identity, which
# means not entitled. Nothing here matches on username or email: D-A3-2 forbids inference,
# and the two key spaces are genuinely different (case-insensitive handle vs normalised
# address), so a "helpful" match would be a silent authorization bypass.


def shared_account_id(user_id: int) -> str | None:
    """The linked shared-accounts id, or None when this user has no shared identity."""
    with _conn() as c:
        row = c.execute("SELECT shared_account_id FROM users WHERE id=?",
                        (user_id,)).fetchone()
    if row is None:
        return None
    value = row["shared_account_id"]
    return value or None            # '' is stored by nobody, but it is not an identity


def link_shared_account(username: str, account_id: str, *, force: bool = False) -> dict:
    """Point a local user at a shared-accounts identity. Operator action only."""
    if not account_id:
        raise DispatchError("account id is required")
    with _conn() as c:
        row = c.execute("SELECT id, shared_account_id FROM users WHERE username=?",
                        (username,)).fetchone()
        if row is None:
            raise DispatchError(f"no such user: {username}")
        if row["shared_account_id"] and not force:
            raise DispatchError(
                f"{username} is already linked; pass force to repoint it")
        c.execute("UPDATE users SET shared_account_id=? WHERE id=?", (account_id, row["id"]))
    return {"username": username, "shared_account_id": account_id}


def unlink_shared_account(username: str) -> dict:
    """Clear the reference. Fails closed by construction: the user loses entitlement."""
    with _conn() as c:
        row = c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if row is None:
            raise DispatchError(f"no such user: {username}")
        c.execute("UPDATE users SET shared_account_id=NULL WHERE id=?", (row["id"],))
    return {"username": username, "shared_account_id": None}
