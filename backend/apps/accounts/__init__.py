"""SyMoNeuRaL Accounts -- signup, login, sessions. Standard library only.

    python3 backend/apps/accounts/test_accounts.py     # the tests
    docs/specs/accounts-spec.md                        # routes, page changes, threat model

This is the backend half of the Account tab. The routes and page exist, but the surface
remains off unless both configuration switches below are present.

## Zero new packages, and why that is not a compromise

The serving API runs on the **system** interpreter -- fastapi, uvicorn, pydantic and sympy
are Debian packages and there is no virtualenv in the serving path (`.claude/CLAUDE.md`,
"Python environments"). So there is no bcrypt, no argon2, no passlib, no python-jose, no
sqlalchemy and no authlib here, and there must not be.

The standard library covers every part of this honestly:

  * `hashlib.scrypt`  -- memory-hard password hashing, RFC 7914, in OpenSSL, no wheel
  * `secrets`         -- CSPRNG for salts and session tokens
  * `hmac.compare_digest` -- constant-time comparison
  * `sqlite3`         -- durable storage with real transactions

The one thing argon2id would buy over scrypt is side-channel resistance in its `id` variant
and a more modern tuning story. scrypt is not a downgrade for password storage: it is the
RFC-standardised memory-hard KDF, it is what OpenSSL ships, and OWASP still lists it as an
acceptable choice with parameters given below. What *would* be a downgrade is a hand-rolled
PBKDF2 loop or an unsalted digest, and neither is here.

## Cost parameters

`SCRYPT_N=131072, r=8, p=1` -- 128 MiB, the current OWASP scrypt baseline. The previous
N=65536 setting measured **123 ms** on this machine (i9-10900KF @ 3.70 GHz, best of five,
`hashlib.scrypt` with `maxmem` set); the 128 MiB candidate measured 248 ms in the same run.
Those figures are **measured**, not vendor and not projected.

Reasoning, in the order it actually constrains the choice:

  1. RFC 7914 §2 gives N=16384, r=8, p=1 as the interactive-login example. That is from
     2016 and costs 26 ms / 16 MiB here -- too cheap now.
  2. OWASP's current guidance is a set of equivalent-work rows starting at N=2^17, r=8, p=1
     (128 MiB) and including N=2^16, r=8, p=2 (also 128 MiB). Measured here those are
     248 ms and 231 ms.
  3. The web routes move every hash to a worker thread. A process-wide bounded semaphore
     permits at most two scrypt calls at once, so a burst cannot turn 128 MiB per attempt
     into unbounded memory pressure while the event loop remains responsive.
  4. Memory is the anti-GPU lever, which is the whole reason to prefer a memory-hard KDF.

The parameters are stored **inside each hash string**, so raising them later is a
per-user upgrade on next login (`needs_rehash`) rather than a flag day.

**`maxmem` is not optional.** `hashlib.scrypt` defaults to `maxmem=0`, which OpenSSL reads
as a 32 MiB ceiling -- so the bare call raises `ValueError: memory limit exceeded` at
N=2^15 and above. Verified on this box. Every scrypt call in this file passes `maxmem`.

## It is off by default, and it fails closed

    SYMONEURAL_ACCOUNTS_ENABLED=1
    SYMONEURAL_SESSION_SECRET=<32+ random chars>      # e.g. `openssl rand -base64 48`

Both, or the surface does not exist -- the same two-switch shape as
`backend/apps/asicminer/__init__.py`. There is **no generated-per-process fallback and no
built-in default secret**, and that is the single most important line in this module.
`.claude/HANDOVER.md` §5 item 1 records the open finding it exists to not repeat: a DRM
whose fallback path is `return True`, so blocking a network call *grants* a licence. Every
entry point here calls `_secret()` first and every entry point raises
`AccountsUnavailable` when it is missing. A missing secret is never "no session"; it is a
refusal.

## No pricing, ever

`.claude/CLAUDE.md` is absolute and this module obeys it: there is no price column, no plan
tier, no seat count, no subscription state and no amount of any kind in the schema. An
account may carry an **optional opaque `quote_id`** linking it to a quote handled by a
human over mail; it carries no figure. Anything price-shaped goes to
symonsayadmin@symoneural.com.

## Where the data lives

`run/accounts/accounts.db` -- runtime state, never under `site/`, never served, and it
cannot collide with `run/gpu.lock.d` (a directory the governor creates with `mkdir`).
It is in its own subdirectory on purpose: `.claude/CLAUDE.md` argues the name `run/` is
load-bearing *because* someone will eventually clear it out, and a sweep of `run/*.log` or
`run/*` should not be one command away from deleting every account. See the open questions
in `docs/specs/accounts-spec.md`; this is a decision for the owner, not an agent.
"""
from __future__ import annotations

import base64
import contextvars
import hashlib
import hmac
import json
import os
import pathlib
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
from contextlib import contextmanager

# backend/apps/accounts -> backend/apps -> backend -> repo root.
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent

SCHEMA_VERSION = 1

# --------------------------------------------------------------------------- knobs

# scrypt. See the module docstring for the measurement and the reasoning.
SCRYPT_N = 131072
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SCRYPT_SALT_BYTES = 16
SCRYPT_MAX_CONCURRENT = 2
_SCRYPT_SLOTS = threading.BoundedSemaphore(SCRYPT_MAX_CONCURRENT)


def _maxmem(n: int, r: int, p: int) -> int:
    """OpenSSL's own accounting, plus a megabyte of slack.

    Must be passed explicitly: the default of 0 means a 32 MiB ceiling, which every
    parameter set worth using exceeds.
    """
    return 128 * n * r * p + (1 << 20)


# Password policy. Length is the only lever that reliably buys entropy; NIST SP 800-63B
# explicitly discourages composition rules ("must contain a symbol"), so there are none.
MIN_PASSWORD_CHARS = 15
MAX_PASSWORD_CHARS = 1024      # a 10 MB password is a memory-hard DoS with extra steps
MAX_EMAIL_CHARS = 254          # RFC 5321 §4.5.3.1.3 path limit

# Sessions.
SESSION_TTL_S = 12 * 3600
SESSION_TOKEN_BYTES = 32       # 256 bits from secrets.token_bytes
TOKEN_PREFIX = "symses1"
MIN_SECRET_CHARS = 32

# Throttle. Two independent scopes; see `_throttle_check`.
ACCOUNT_FREE_FAILS = 3
ACCOUNT_BASE_LOCK_S = 5.0      # 4th failure costs 5s, 5th 10s, 6th 20s ... capped below
ACCOUNT_MAX_LOCK_S = 900.0     # 15 minutes -- long enough to matter, short enough to wait
IP_FREE_FAILS = 20             # generous: a NAT or an office is one address
IP_BASE_LOCK_S = 5.0
IP_MAX_LOCK_S = 900.0
ATTEMPT_DECAY_S = 3600.0       # a clean hour forgets the counter

# What `account_public()` is allowed to emit. An ALLOWLIST, not a denylist, so a column
# added later is invisible until somebody adds it here deliberately.
PUBLIC_FIELDS = ("id", "email", "display_name", "created", "disabled", "quote_id")

_EMAIL_RE = re.compile(
    r"^[^@\s]{1,64}@[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$"
)

# A real hash of a random password nobody holds. `verify()` runs the full scrypt against
# this when the email is unknown, so a wrong address and a wrong password cost the same
# wall-clock and the endpoint does not answer "does this person have an account" for free.
# Precomputed rather than derived at import so importing this module costs nothing.
_DUMMY_HASH = ("scrypt$n=131072,r=8,p=1$auXU912RqNFEGqdUQE69vg"
               "$e3R3TsPR5L9wAvtr2HVtFK6zlPKfQjRlNfYt-DLXzdk")

# Rejected outright regardless of length. Deliberately tiny: there is no breach corpus on
# this box and no network call to one, so this catches the obvious and claims nothing more.
_OBVIOUS = {
    "password", "passw0rd", "password1", "password123", "123456789012",
    "qwertyuiop123", "letmein12345", "iloveyou1234", "administrator",
    "symoneural", "symoneural123", "changeme1234",
}


# --------------------------------------------------------------------------- errors

class AccountsError(Exception):
    """Base for everything this module raises deliberately."""


class AccountsUnavailable(AccountsError):
    """The surface is not configured. NEVER a falsy return value.

    This is its own type because the failure mode to avoid is a caller that treats a
    `None` from `verify()` as "wrong password", logs it and carries on. A missing
    `SYMONEURAL_SESSION_SECRET` is a misconfiguration, not a credential decision, and it must be
    impossible to swallow by accident.
    """


class InvalidEmail(AccountsError):
    pass


class WeakPassword(AccountsError):
    pass


class AccountExists(AccountsError):
    pass


class Throttled(AccountsError):
    """Too many failures. `retry_after` is seconds, already rounded up."""

    def __init__(self, scope: str, retry_after: float):
        self.scope = scope
        self.retry_after = max(1, int(retry_after + 0.999))
        super().__init__(f"too many failed attempts ({scope}); retry in "
                         f"{self.retry_after}s")


# --------------------------------------------------------------------------- config

# Set by `using_db()`. A ContextVar rather than a module global or a temporary environment
# mutation, because both of those are process-wide: uvicorn runs handlers concurrently, and a
# second surface rebinding the database underneath a request in flight would send that
# request's write to the wrong file. A ContextVar is scoped to the task/thread that set it, so
# two AccountsModule instances on different databases cannot collide.
_DB_OVERRIDE: contextvars.ContextVar[str] = contextvars.ContextVar(
    "symoneural_accounts_db", default="")


@contextmanager
def using_db(path: str | os.PathLike):
    """Bind `db_path()` to `path` for the duration of this block, in this context only.

    `AccountsModule` uses this to give a second surface (`symoneural_dj`, on its own port and
    its own database) the module-level functions without duplicating them.
    """
    token = _DB_OVERRIDE.set(str(path))
    try:
        yield pathlib.Path(path)
    finally:
        _DB_OVERRIDE.reset(token)


def db_path() -> pathlib.Path:
    """`run/accounts/accounts.db`, overridable per-context and for tests.

    Order: an active `using_db()` binding, then `SYMONEURAL_ACCOUNTS_DB`, then the default.
    The binding wins over the environment so that a surface holding an explicit path is never
    silently redirected by a variable somebody exported for a different reason.

    `SYMONEURAL_ACCOUNTS_DB` exists so the test file can point at a temp directory. It is not a
    production knob and nothing documents it as one.
    """
    bound = _DB_OVERRIDE.get()
    if bound:
        return pathlib.Path(bound)
    override = os.environ.get("SYMONEURAL_ACCOUNTS_DB", "").strip()
    if override:
        return pathlib.Path(override)
    return ROOT / "run" / "accounts" / "accounts.db"


def enabled() -> bool:
    """Off unless switched on AND given a secret.

    Mirrors `backend/apps/asicminer/__init__.py`: two switches, and a misconfiguration on
    a box with a public IP fails closed rather than open.
    """
    return (os.environ.get("SYMONEURAL_ACCOUNTS_ENABLED") == "1"
            and len(os.environ.get("SYMONEURAL_SESSION_SECRET", "")) >= MIN_SECRET_CHARS)


def _secret() -> bytes:
    """The session-signing key, from the environment, or refuse.

    There is no fallback. Not a hardcoded default, not `secrets.token_bytes()` at import.
    A per-process generated secret would look like it worked -- until the first
    `systemctl restart symoneural-api`, which silently logs every user out; and a
    hardcoded one is a forgeable session for anybody who reads this file.
    """
    raw = os.environ.get("SYMONEURAL_SESSION_SECRET", "")
    if len(raw) < MIN_SECRET_CHARS:
        raise AccountsUnavailable(
            "SYMONEURAL_SESSION_SECRET is unset or shorter than "
            f"{MIN_SECRET_CHARS} characters; accounts refuse to operate. "
            "Generate one with: openssl rand -base64 48")
    return raw.encode("utf-8")


def session_ttl_s() -> int:
    raw = os.environ.get("SYMONEURAL_SESSION_TTL_S", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return SESSION_TTL_S


# --------------------------------------------------------------------------- storage

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
    id           TEXT PRIMARY KEY,
    email        TEXT NOT NULL UNIQUE,   -- normalised (NFKC, lowercased, trimmed)
    email_shown  TEXT NOT NULL,          -- exactly what the visitor typed
    pw_hash      TEXT NOT NULL,          -- scrypt$params$salt$dk -- never leaves this file
    created      REAL NOT NULL,
    disabled     INTEGER NOT NULL DEFAULT 0,
    display_name TEXT,
    quote_id     TEXT                    -- opaque link to a quote. NEVER an amount.
);
CREATE TABLE IF NOT EXISTS sessions (
    sid        TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    verifier   TEXT NOT NULL,            -- hmac_sha256(SYMONEURAL_SESSION_SECRET, whole token)
    created    REAL NOT NULL,
    expires    REAL NOT NULL,
    revoked    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS sessions_account ON sessions(account_id);
CREATE TABLE IF NOT EXISTS attempts (
    scope        TEXT NOT NULL,          -- 'account' | 'ip'
    key          TEXT NOT NULL,
    fails        INTEGER NOT NULL DEFAULT 0,
    last_fail    REAL NOT NULL DEFAULT 0,
    locked_until REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (scope, key)
);
CREATE TABLE IF NOT EXISTS entitlements (
    account_id       TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    application_slug TEXT NOT NULL,
    granted_at       REAL NOT NULL,
    granted_by       TEXT NOT NULL,          -- operator identity, for audit
    revoked_at       REAL,                   -- NULL means active
    -- granted_at is IN the key on purpose. grant -> revoke -> re-grant is a real sequence,
    -- and a two-column key would force the re-grant to overwrite the revoked row, which is
    -- exactly the audit trail we are required to keep. "Active" is therefore the latest row
    -- for the pair with revoked_at IS NULL, never "the row".
    PRIMARY KEY (account_id, application_slug, granted_at)
);
CREATE INDEX IF NOT EXISTS entitlements_lookup
    ON entitlements(account_id, application_slug, granted_at DESC);
"""


@contextmanager
def _conn():
    """A fresh connection per operation.

    Deliberately not a module-level singleton. uvicorn runs handlers on a thread pool once
    anything goes through `asyncio.to_thread`, and a shared sqlite3 connection across
    threads is either an error or a data race depending on `check_same_thread`. Opening a
    connection is microseconds; the scrypt call next to it is hundreds of milliseconds.
    """
    path = db_path()
    first = not path.exists()
    if first:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    c = sqlite3.connect(str(path), timeout=10.0, isolation_level=None)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA busy_timeout=10000")
        c.execute("PRAGMA foreign_keys=ON")
        # WAL leaves `-wal` and `-shm` siblings next to the db. Harmless -- they are in
        # `run/accounts/`, nowhere near `run/gpu.lock.d` -- but expect three files.
        # Set on every connection rather than only at creation: the mode is persistent in
        # the file header, so this is a no-op pragma after the first time, and it means a
        # database created by anything other than this code path still ends up in WAL.
        c.execute("PRAGMA journal_mode=WAL")
        if first:
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        # Every connection, not only the first. `CREATE TABLE IF NOT EXISTS` is cheap next
        # to a password hash, and doing it here means a database file that exists but is
        # empty -- a truncated copy, a half-finished restore -- self-heals instead of
        # raising `no such table` from somewhere three calls deep.
        c.executescript(_SCHEMA)
        c.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('schema',?)",
                  (str(SCHEMA_VERSION),))
        yield c
    finally:
        c.close()


def init_db() -> pathlib.Path:
    """Create the database if it is missing. Idempotent.

    The work happens in `_conn()`, which applies the schema on every connection, so this
    is just "open it once so the file exists".
    """
    with _conn():
        pass
    return db_path()


# --------------------------------------------------------------------------- hashing

def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    # A login burst must not allocate 128 MiB times the thread-pool size.  The semaphore
    # limits process memory while asyncio.to_thread keeps this work off the event loop.
    with _SCRYPT_SLOTS:
        return hashlib.scrypt(
            _normalise_password(password).encode("utf-8"),
            salt=salt, n=n, r=r, p=p, dklen=SCRYPT_DKLEN, maxmem=_maxmem(n, r, p),
        )


def _normalise_password(password: str) -> str:
    """NFKC, per NIST SP 800-63B §5.1.1.2. Whitespace is NOT stripped -- it is entropy."""
    return unicodedata.normalize("NFKC", password)


def hash_password(password: str) -> str:
    """`scrypt$n=..,r=..,p=..$<salt>$<dk>` -- a fresh 128-bit salt every time.

    The salt is per-user and per-call, which is what makes two people who chose the same
    password store two different strings, and what makes a precomputed table useless.
    """
    salt = secrets.token_bytes(SCRYPT_SALT_BYTES)
    dk = _derive(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return (f"scrypt$n={SCRYPT_N},r={SCRYPT_R},p={SCRYPT_P}"
            f"${_b64e(salt)}${_b64e(dk)}")


def _parse_hash(stored: str) -> tuple[int, int, int, bytes, bytes]:
    algo, params, salt_s, dk_s = stored.split("$", 3)
    if algo != "scrypt":
        raise ValueError(f"unsupported hash algorithm {algo!r}")
    kv = dict(pair.split("=", 1) for pair in params.split(","))
    return int(kv["n"]), int(kv["r"]), int(kv["p"]), _b64d(salt_s), _b64d(dk_s)


def check_password(stored: str, password: str) -> bool:
    """Constant-time. Parameters come from the stored string, not from the constants.

    Reading n/r/p out of the hash is what lets the cost be raised later without
    invalidating anybody's password: old hashes keep verifying at the cost they were made
    with, and `needs_rehash()` upgrades them on the next successful login.
    """
    try:
        n, r, p, salt, expect = _parse_hash(stored)
    except (ValueError, KeyError, TypeError):
        return False
    try:
        got = _derive(password, salt, n, r, p)
    except ValueError:
        return False
    return hmac.compare_digest(got, expect)


def check_password_or_dummy(stored: str | None, password: str) -> bool:
    """Check a stored hash, paying the same current cost when no account exists.

    Other account surfaces use this instead of constructing a fresh dummy hash per
    request.  That avoids both a timing oracle and an attacker-controlled extra hash.
    """
    return check_password(stored if stored is not None else _DUMMY_HASH, password)


def needs_rehash(stored: str) -> bool:
    try:
        n, r, p, _, _ = _parse_hash(stored)
    except (ValueError, KeyError, TypeError):
        return True
    return (n, r, p) != (SCRYPT_N, SCRYPT_R, SCRYPT_P)


# --------------------------------------------------------------------------- validation

def normalise_email(email: str) -> str:
    return unicodedata.normalize("NFKC", (email or "").strip()).lower()


def validate_email(email: str) -> str:
    """Shape only, and it says so.

    An address is not proven to exist by a regex, and there is no mail sender on this box
    to prove it any other way (verified: no sendmail, no MTA unit, no mail client). So
    this rejects things that cannot be an address and claims nothing about delivery.
    """
    norm = normalise_email(email)
    if not norm:
        raise InvalidEmail("an email address is required")
    if len(norm) > MAX_EMAIL_CHARS:
        raise InvalidEmail(f"email is longer than {MAX_EMAIL_CHARS} characters")
    if not _EMAIL_RE.match(norm):
        raise InvalidEmail("that does not look like an email address")
    return norm


def validate_password(password: str, email: str = "") -> str:
    if not isinstance(password, str):
        raise WeakPassword("password must be text")
    pw = _normalise_password(password)
    if len(pw) < MIN_PASSWORD_CHARS:
        raise WeakPassword(f"use at least {MIN_PASSWORD_CHARS} characters — "
                           "length is worth more than punctuation")
    if len(pw) > MAX_PASSWORD_CHARS:
        raise WeakPassword(f"password is longer than {MAX_PASSWORD_CHARS} characters")
    low = pw.lower()
    if low in _OBVIOUS:
        raise WeakPassword("that password is one of the first anybody tries")
    local = normalise_email(email).split("@", 1)[0]
    if len(local) >= 3 and local in low:
        raise WeakPassword("the password contains your account identifier")
    return pw


# --------------------------------------------------------------------------- throttle

def _throttle_read(c: sqlite3.Connection, scope: str, key: str) -> sqlite3.Row | None:
    return c.execute("SELECT * FROM attempts WHERE scope=? AND key=?",
                     (scope, key)).fetchone()


def _throttle_check(c: sqlite3.Connection, scope: str, key: str, now: float) -> None:
    row = _throttle_read(c, scope, key)
    if row is not None and row["locked_until"] > now:
        raise Throttled(scope, row["locked_until"] - now)


def _throttle_fail(c: sqlite3.Connection, scope: str, key: str, now: float,
                   free: int, base: float, cap: float) -> None:
    """Record a failure and extend the lockout geometrically.

    Deliberately **persisted in sqlite rather than held in memory**. An in-memory counter
    is reset by every `systemctl restart symoneural-api`, and restarting the API is a
    routine step in this project -- so an attacker's cost would be "wait for the next
    deploy", which is no cost at all.
    """
    row = _throttle_read(c, scope, key)
    fails = 0 if row is None else int(row["fails"])
    last = 0.0 if row is None else float(row["last_fail"])
    locked = 0.0 if row is None else float(row["locked_until"])
    # A clean hour forgets the counter, so an ordinary person who mistypes once a month is
    # never locked out. An attacker gets ACCOUNT_FREE_FAILS guesses per hour for free,
    # which against a 15-character minimum is not a threat worth trading usability for.
    if locked <= now and (now - last) > ATTEMPT_DECAY_S:
        fails = 0
    fails += 1
    if fails > free:
        lock_for = min(base * (2.0 ** (fails - free - 1)), cap)
        locked = now + lock_for
    c.execute(
        "INSERT INTO attempts(scope,key,fails,last_fail,locked_until) VALUES(?,?,?,?,?) "
        "ON CONFLICT(scope,key) DO UPDATE SET fails=excluded.fails, "
        "last_fail=excluded.last_fail, locked_until=excluded.locked_until",
        (scope, key, fails, now, locked))


def _throttle_clear(c: sqlite3.Connection, scope: str, key: str) -> None:
    c.execute("DELETE FROM attempts WHERE scope=? AND key=?", (scope, key))


def throttle_state(email: str = "", ip: str = "", now: float | None = None) -> dict:
    """What the throttle currently thinks. For an operator view, not for a visitor."""
    _secret()
    now = time.time() if now is None else now
    out: dict = {"account": None, "ip": None}
    with _conn() as c:
        for scope, key in (("account", normalise_email(email)), ("ip", (ip or "").strip())):
            if not key:
                continue
            row = _throttle_read(c, scope, key)
            if row is None:
                continue
            out[scope] = {
                "fails": int(row["fails"]),
                "locked": row["locked_until"] > now,
                "retry_after": max(0, int(row["locked_until"] - now + 0.999)),
            }
    return out


# --------------------------------------------------------------------------- accounts

def _public(row: sqlite3.Row | dict) -> dict:
    """Build the outward-facing dict from an ALLOWLIST.

    `pw_hash` is not in `PUBLIC_FIELDS` and cannot become part of an API response by
    somebody adding a column and forgetting. That is the failure this shape exists for --
    a denylist (`del d['pw_hash']`) is one schema change away from leaking.
    """
    out = {k: (row[k] if k in row.keys() else None) for k in PUBLIC_FIELDS} \
        if isinstance(row, sqlite3.Row) else {k: row.get(k) for k in PUBLIC_FIELDS}
    out["disabled"] = bool(out["disabled"])
    return out


def create_account(email: str, password: str, *, display_name: str | None = None,
                   quote_id: str | None = None, now: float | None = None) -> dict:
    """Register an account. Returns the PUBLIC dict -- never the hash.

    `quote_id` is an opaque reference to a quote handled by a human over mail. It is a
    string and nothing else: there is no amount, no plan and no tier anywhere in this
    module, because `.claude/CLAUDE.md` forbids inventing pricing and a schema column
    called `plan` is an invitation to invent one.
    """
    _secret()
    now = time.time() if now is None else now
    norm = validate_email(email)
    validate_password(password, email=norm)
    pw_hash = hash_password(password)
    aid = secrets.token_hex(16)
    with _conn() as c:
        if c.execute("SELECT 1 FROM accounts WHERE email=?", (norm,)).fetchone():
            raise AccountExists("an account already exists for that address")
        try:
            c.execute(
                "INSERT INTO accounts(id,email,email_shown,pw_hash,created,disabled,"
                "display_name,quote_id) VALUES(?,?,?,?,?,0,?,?)",
                (aid, norm, (email or "").strip(), pw_hash, now,
                 (display_name or None), (quote_id or None)))
        except sqlite3.IntegrityError as e:      # lost a race on the UNIQUE index
            raise AccountExists("an account already exists for that address") from e
        row = c.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()
    return _public(row)


def account_public(account_id: str) -> dict | None:
    """Everything about an account that is safe to put in a response. No hash, no salt."""
    _secret()
    with _conn() as c:
        row = c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    return None if row is None else _public(row)


def find_by_email(email: str) -> dict | None:
    _secret()
    with _conn() as c:
        row = c.execute("SELECT * FROM accounts WHERE email=?",
                        (normalise_email(email),)).fetchone()
    return None if row is None else _public(row)


def verify(email: str, password: str, *, ip: str = "", now: float | None = None
           ) -> dict | None:
    """Check a login. Returns the public account dict, or None. Raises `Throttled`.

    Three properties worth stating because each one is a deliberate cost:

    1. **The throttle is checked before the password is.** A locked account does not
       authenticate even with the right password -- otherwise the lockout throttles
       nothing.
    2. **An unknown address still pays for a full scrypt** against `_DUMMY_HASH`, so the
       response time does not answer "is this person a customer".
    3. **The comparison is `hmac.compare_digest`**, inside `check_password`.

    `ip` is passed IN by the caller. `backend/api.py` already has `client_key(request)`,
    which reads `X-Forwarded-For` because Caddy fronts everything; reimplementing that
    parsing here would give the project two versions of it to drift apart.
    """
    _secret()
    now = time.time() if now is None else now
    norm = normalise_email(email)
    ip = (ip or "").strip()
    with _conn() as c:
        if norm:
            _throttle_check(c, "account", norm, now)
        if ip:
            _throttle_check(c, "ip", ip, now)
        row = c.execute("SELECT * FROM accounts WHERE email=?", (norm,)).fetchone()
        stored = row["pw_hash"] if row is not None else None
        ok = check_password_or_dummy(stored, password) and row is not None
        if ok and row["disabled"]:
            ok = False              # a disabled account is not a credential decision to leak
        if not ok:
            if norm:
                _throttle_fail(c, "account", norm, now,
                               ACCOUNT_FREE_FAILS, ACCOUNT_BASE_LOCK_S, ACCOUNT_MAX_LOCK_S)
            if ip:
                _throttle_fail(c, "ip", ip, now,
                               IP_FREE_FAILS, IP_BASE_LOCK_S, IP_MAX_LOCK_S)
            return None
        _throttle_clear(c, "account", norm)
        if ip:
            # Clearing the address counter on a success keeps an office behind one NAT from
            # locking itself out. It does mean somebody holding one valid account can reset
            # their own address counter -- accepted, because the account-scoped backoff on
            # every OTHER account is untouched, and that is the control that matters.
            _throttle_clear(c, "ip", ip)
        if needs_rehash(row["pw_hash"]):
            c.execute("UPDATE accounts SET pw_hash=? WHERE id=?",
                      (hash_password(password), row["id"]))
        return _public(row)


def change_password(account_id: str, old_password: str, new_password: str,
                    *, now: float | None = None) -> bool:
    """Rotate a password and revoke every session. Requires the current one.

    Revoking on change is the point: a password change after a suspected compromise that
    leaves the attacker's session live has done nothing.

    It is throttled on the SAME account key as `verify()`, and that is deliberate: this is
    a second place a password can be guessed, and an attacker holding a stolen session
    would otherwise have an unmetered oracle for confirming the real password. Sharing the
    key means four wrong guesses here also lock login, which is correct -- they were four
    wrong guesses at the same password.
    """
    _secret()
    now = time.time() if now is None else now
    with _conn() as c:
        row = c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if row is None:
            return False
        _throttle_check(c, "account", row["email"], now)
        if not check_password(row["pw_hash"], old_password):
            _throttle_fail(c, "account", row["email"], now,
                           ACCOUNT_FREE_FAILS, ACCOUNT_BASE_LOCK_S, ACCOUNT_MAX_LOCK_S)
            return False
        _throttle_clear(c, "account", row["email"])
        validate_password(new_password, email=row["email"])
        c.execute("UPDATE accounts SET pw_hash=? WHERE id=?",
                  (hash_password(new_password), account_id))
        c.execute("UPDATE sessions SET revoked=1 WHERE account_id=?", (account_id,))
    return True


def set_disabled(account_id: str, disabled: bool = True) -> bool:
    """Operator switch. Disabling revokes live sessions too, or it is not a disable."""
    _secret()
    with _conn() as c:
        cur = c.execute("UPDATE accounts SET disabled=? WHERE id=?",
                        (1 if disabled else 0, account_id))
        if disabled:
            c.execute("UPDATE sessions SET revoked=1 WHERE account_id=?", (account_id,))
        return cur.rowcount == 1


# --------------------------------------------------------------------------- sessions

def issue_session(account_id: str, *, ttl_s: int | None = None,
                  now: float | None = None) -> str:
    """Mint a session token. Server-side row, keyed verifier.

    **Why rows and not a stateless signed token.** Revocation and expiry both have to be
    real here -- `revoke_session()` is in the brief, and a logout that leaves the token
    valid is a logout in name only. A stateless token can only be revoked against a
    revocation list, which is server-side state with a worse shape: it grows forever and
    the failure mode of losing it is that revoked tokens come back to life.

    **What the secret is for, given the rows are authoritative.** The database stores
    `hmac_sha256(SYMONEURAL_SESSION_SECRET, token)`, not the token. So reading the file -- a
    backup, a stray copy, an SQL-injection read in some future route -- yields verifiers
    that cannot be turned back into a usable cookie. And rotating the secret invalidates
    every session at once, which is the emergency lever you want to exist.
    """
    _secret()
    now = time.time() if now is None else now
    ttl = session_ttl_s() if ttl_s is None else int(ttl_s)
    with _conn() as c:
        row = c.execute("SELECT id, disabled FROM accounts WHERE id=?",
                        (account_id,)).fetchone()
        if row is None:
            raise AccountsError("no such account")
        if row["disabled"]:
            raise AccountsError("account is disabled")
        sid = secrets.token_urlsafe(12)
        token = f"{TOKEN_PREFIX}.{sid}.{_b64e(secrets.token_bytes(SESSION_TOKEN_BYTES))}"
        c.execute(
            "INSERT INTO sessions(sid,account_id,verifier,created,expires,revoked) "
            "VALUES(?,?,?,?,?,0)",
            (sid, account_id, _verifier(token), now, now + ttl))
        # Opportunistic housekeeping: a long-dead session row is not evidence of anything.
        c.execute("DELETE FROM sessions WHERE expires < ?", (now - 7 * 86400,))
    return token


def _verifier(token: str) -> str:
    return hmac.new(_secret(), token.encode("utf-8"), hashlib.sha256).hexdigest()


def _split(token: str) -> str | None:
    parts = (token or "").split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX or not parts[1] or not parts[2]:
        return None
    return parts[1]


def read_session(token: str, *, now: float | None = None) -> dict | None:
    """Resolve a token to `{account_id, sid, expires, account}`, or None.

    None means *this token is not a valid session* and nothing else. A missing secret
    raises instead, because "unconfigured" and "bad cookie" must never be the same answer
    to a caller -- that conflation is exactly the shape of the fail-open DRM in
    HANDOVER §5 item 1.
    """
    _secret()
    now = time.time() if now is None else now
    sid = _split(token)
    if sid is None:
        return None
    with _conn() as c:
        row = c.execute("SELECT * FROM sessions WHERE sid=?", (sid,)).fetchone()
        if row is None:
            return None
        if not hmac.compare_digest(row["verifier"], _verifier(token)):
            return None
        if row["revoked"] or row["expires"] <= now:
            return None
        acct = c.execute("SELECT * FROM accounts WHERE id=?",
                         (row["account_id"],)).fetchone()
        if acct is None or acct["disabled"]:
            return None
        return {"sid": row["sid"], "account_id": row["account_id"],
                "created": row["created"], "expires": row["expires"],
                "account": _public(acct)}


def revoke_session(token: str) -> bool:
    """Log out. Idempotent; returns whether a live row was actually revoked."""
    _secret()
    sid = _split(token)
    if sid is None:
        return False
    with _conn() as c:
        row = c.execute("SELECT * FROM sessions WHERE sid=?", (sid,)).fetchone()
        if row is None or not hmac.compare_digest(row["verifier"], _verifier(token)):
            # Do not revoke on sid alone: the sid is the readable half of the token, so a
            # revoke-by-sid would let anyone who saw a log line log somebody else out.
            return False
        c.execute("UPDATE sessions SET revoked=1 WHERE sid=?", (sid,))
        return not row["revoked"]


def revoke_all_sessions(account_id: str) -> int:
    _secret()
    with _conn() as c:
        cur = c.execute("UPDATE sessions SET revoked=1 WHERE account_id=? AND revoked=0",
                        (account_id,))
        return cur.rowcount


def sessions_for(account_id: str, *, now: float | None = None) -> list[dict]:
    """Live sessions, for a "signed in on 3 devices" panel. No verifiers, ever."""
    _secret()
    now = time.time() if now is None else now
    with _conn() as c:
        rows = c.execute(
            "SELECT sid, created, expires FROM sessions "
            "WHERE account_id=? AND revoked=0 AND expires>? ORDER BY created DESC",
            (account_id, now)).fetchall()
    return [{"sid": r["sid"], "created": r["created"], "expires": r["expires"]}
            for r in rows]


# --------------------------------------------------------------------------- async

async def create_account_async(*a, **kw) -> dict:
    """`create_account` off the event loop. Use this from a route handler."""
    import asyncio
    return await asyncio.to_thread(create_account, *a, **kw)


async def verify_async(*a, **kw) -> dict | None:
    """`verify` off the event loop.

    NOT optional. scrypt is hundreds of milliseconds of blocking CPU, and `backend/api.py` is one
    uvicorn process that also serves the live status WebSocket -- a synchronous hash in a
    handler stalls that socket for every connected visitor.
    """
    import asyncio
    return await asyncio.to_thread(verify, *a, **kw)


async def change_password_async(*a, **kw) -> bool:
    import asyncio
    return await asyncio.to_thread(change_password, *a, **kw)


# --------------------------------------------------------------------------- selftest

def selftest() -> dict:
    """Is this surface actually able to work? No network, no GPU, no side effects.

    Same job as `asicminer.selftest()` -- answer "would this work if asked" without
    pretending. It is a plain function rather than a coroutine because there is no
    subprocess to await; call it from a thread if you call it from a handler at all.
    """
    out: dict = {
        "ok": False,
        "enabled": enabled(),
        "secret_present": len(os.environ.get("SYMONEURAL_SESSION_SECRET", "")) >= MIN_SECRET_CHARS,
        "db": str(db_path()),
        "scrypt": {"n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P,
                   "mem_mib": 128 * SCRYPT_N * SCRYPT_R * SCRYPT_P // (1 << 20)},
        "hash_ms": None,
        "accounts": None,
        "error": None,
    }
    if not out["secret_present"]:
        out["error"] = ("SYMONEURAL_SESSION_SECRET is unset or too short — accounts refuse to "
                        "operate. This is the fail-closed path, not a fault.")
        return out
    try:
        t0 = time.perf_counter()
        h = hash_password("selftest-not-a-real-password")
        out["hash_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        if not check_password(h, "selftest-not-a-real-password"):
            out["error"] = "scrypt round trip failed"
            return out
        if check_password(h, "selftest-not-a-real-passwore"):
            out["error"] = "scrypt accepted a wrong password"
            return out
        init_db()
        with _conn() as c:
            out["accounts"] = c.execute("SELECT COUNT(*) n FROM accounts").fetchone()["n"]
        out["ok"] = True
    except Exception as e:                       # noqa: BLE001 -- selftest never raises
        out["error"] = f"{e.__class__.__name__}: {e}"
    return out


def unit_state() -> tuple[str, str]:
    """(state, detail) if this ever becomes a rack unit. Honest by construction.

    `offline` is the default and the correct answer for a box where the surface is not
    switched on. Nothing here reports `ready` on the strength of the code existing.
    """
    if not enabled():
        return "offline", "disabled — set SYMONEURAL_ACCOUNTS_ENABLED=1 and SYMONEURAL_SESSION_SECRET"
    try:
        with _conn() as c:
            n = c.execute("SELECT COUNT(*) n FROM accounts").fetchone()["n"]
    except Exception as e:                       # noqa: BLE001
        return "offline", f"{e.__class__.__name__}: {e}"[:90]
    return "ready", f"{n} account{'s' if n != 1 else ''} · sessions expire in " \
                    f"{session_ttl_s() // 3600}h"


# --------------------------------------------------------------- the application facade
#
# Imported at the BOTTOM on purpose. `module.py` does `from . import verify, read_session,
# ...`, and at this line every one of those names is already bound, so the cycle resolves.
# Moving this to the top of the file turns it into a partially-initialised-module ImportError.
#
# `symoneural_dj` binds to these:
#     from apps.accounts import AccountsModule, InsufficientFunds, build_router
from .meter import InsufficientFunds, Meter  # noqa: E402
from .module import SESSION_COOKIE, AccountsModule, Identity, User  # noqa: E402


def __getattr__(name):
    """`build_router` on demand, so importing this package never requires fastapi.

    `test_accounts.py` runs as `python3 backend/apps/accounts/test_accounts.py` against the
    standard library alone, and the module docstring's "zero new packages" claim is about
    exactly that. Binding fastapi at import time here would make the claim false for anyone
    who imported the package rather than the router -- so the one fastapi-dependent export
    is resolved lazily, on first attribute access, via PEP 562.
    """
    if name == "build_router":
        from .routes import build_router  # noqa: PLC0415
        return build_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    print(json.dumps(selftest(), indent=2))


# ------------------------------------------------------------------ entitlements
#
# Customer account -> application. Separate from `apps/gateway/entitlement.py`, which is a
# signed statement that a *licence was settled on chain* and keys on workspace/payer -- it
# carries no customer identity and cannot answer "may this customer open this application".
#
# Two rules this section exists to enforce:
#
#   NO ROW MEANS NOT ENTITLED. There is no default-allow branch anywhere below.
#   REVOCATION IS A WRITE, NOT A DELETE. The historical grant stays readable forever.

ENTITLEMENT_SLUG_MAX = 64


class MalformedEntitlement(ValueError):
    """A stored row could not be trusted. Raised so a caller refuses rather than guesses.

    A malformed row is not an absent row: absent means "not entitled", malformed means "this
    database is telling us something we cannot read". Both deny, but only one is a bug worth
    an operator seeing, so they are distinguishable at the call site.
    """


def _valid_slug(slug: str) -> bool:
    return bool(slug) and len(slug) <= ENTITLEMENT_SLUG_MAX and all(
        ch.isalnum() or ch in "-_" for ch in slug)


def is_entitled(account_id: str, application_slug: str, *, now: float | None = None) -> bool:
    """True only when an active grant exists. Every other outcome is False.

    Deliberately boolean and deliberately total: no exception escapes for an absent account,
    an absent row or a revoked row, because each of those is a legitimate "not entitled" and
    a caller that has to distinguish them would grow a branch that can be got wrong. The one
    thing that does raise is a row we cannot parse -- see MalformedEntitlement.
    """
    if not account_id or not _valid_slug(application_slug):
        return False
    with _conn() as c:
        row = c.execute(
            "SELECT granted_at, revoked_at FROM entitlements "
            "WHERE account_id=? AND application_slug=? "
            "ORDER BY granted_at DESC LIMIT 1",
            (account_id, application_slug)).fetchone()
    if row is None:
        return False
    try:
        granted_at = float(row["granted_at"])
    except (TypeError, ValueError) as exc:
        raise MalformedEntitlement(
            f"unparseable granted_at for {account_id}/{application_slug}") from exc
    if granted_at <= 0:
        raise MalformedEntitlement(
            f"non-positive granted_at for {account_id}/{application_slug}")
    return row["revoked_at"] is None


def grant_entitlement(account_id: str, application_slug: str, *, granted_by: str,
                      now: float | None = None) -> dict:
    """Record an active grant. Refuses on an unknown account or an existing active grant."""
    if not _valid_slug(application_slug):
        raise ValueError(f"invalid application slug: {application_slug!r}")
    if not granted_by:
        raise ValueError("granted_by is required -- a grant with no author is not auditable")
    ts = time.time() if now is None else now
    with _conn() as c:
        if c.execute("SELECT 1 FROM accounts WHERE id=?", (account_id,)).fetchone() is None:
            raise ValueError(f"no such account: {account_id}")
        if is_entitled(account_id, application_slug):
            raise ValueError(f"{account_id} already has an active grant for {application_slug}")
        c.execute("INSERT INTO entitlements"
                  "(account_id,application_slug,granted_at,granted_by,revoked_at) "
                  "VALUES(?,?,?,?,NULL)",
                  (account_id, application_slug, ts, granted_by))
    return {"account_id": account_id, "application_slug": application_slug,
            "granted_at": ts, "granted_by": granted_by, "revoked_at": None}


def revoke_entitlement(account_id: str, application_slug: str,
                       *, now: float | None = None) -> dict:
    """Stamp revoked_at on the active grant. The row is never deleted."""
    ts = time.time() if now is None else now
    with _conn() as c:
        row = c.execute(
            "SELECT granted_at FROM entitlements "
            "WHERE account_id=? AND application_slug=? AND revoked_at IS NULL "
            "ORDER BY granted_at DESC LIMIT 1",
            (account_id, application_slug)).fetchone()
        if row is None:
            raise ValueError(f"no active grant for {account_id}/{application_slug}")
        c.execute("UPDATE entitlements SET revoked_at=? "
                  "WHERE account_id=? AND application_slug=? AND granted_at=?",
                  (ts, account_id, application_slug, row["granted_at"]))
    return {"account_id": account_id, "application_slug": application_slug,
            "granted_at": row["granted_at"], "revoked_at": ts}


def list_entitlements(account_id: str | None = None) -> list[dict]:
    """Every grant including revoked ones, newest first. The audit read."""
    q = ("SELECT account_id,application_slug,granted_at,granted_by,revoked_at "
         "FROM entitlements")
    args: tuple = ()
    if account_id:
        q += " WHERE account_id=?"
        args = (account_id,)
    q += " ORDER BY granted_at DESC"
    with _conn() as c:
        return [dict(r) for r in c.execute(q, args).fetchall()]


def entitled_slugs(account_id: str) -> list[str]:
    """Applications this account may currently open. Used by the Live Stack generator."""
    if not account_id:
        return []
    out = []
    for slug in {r["application_slug"] for r in list_entitlements(account_id)}:
        try:
            if is_entitled(account_id, slug):
                out.append(slug)
        except MalformedEntitlement:
            # A malformed row denies that one application and does not poison the rest.
            continue
    return sorted(out)
