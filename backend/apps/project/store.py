"""The store. SQLite via the stdlib, CPU only, and it never asks for the card.

Everything in this file is a read or a write to a small structured database. There is no
model here, no `subprocess`, no socket and no import of `scripts/gpu-governor.sh`. That is
the surface's defining property rather than an implementation detail -- see the README and
`docs/specs/project-spec.md` §2.2.

Nothing raises out of a public function. Every one returns a dict carrying `ok`, and on
refusal a machine-readable `code` alongside the human `error`. That is the contract
`backend/apps/coder/__init__.py` uses, extended with `code` because an iPhone app cannot
read a sentence and branch on it (`docs/specs/project-spec.md` §3.3).
"""
from __future__ import annotations

import datetime
import fnmatch
import hashlib
import hmac
import logging
import os
import pathlib
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from typing import Callable

log = logging.getLogger("symoneural.project")

HERE = pathlib.Path(__file__).resolve().parent
# backend/apps/project -> backend/apps -> backend -> the repo root. Derived from __file__
# because nothing in this repo hardcodes its own location.
ROOT = HERE.parent.parent.parent

#: Bumped when a response shape changes in a way a shipped client could misparse. It rides
#: on every response so a binary that cannot be updated on demand can detect the change
#: rather than silently misread it (`docs/specs/project-spec.md` §3.3).
API_VERSION = 1

#: The database schema's own version, in `meta`. Separate from API_VERSION: the wire shape
#: and the on-disk shape do not have to move together.
SCHEMA_VERSION = 1


# ------------------------------------------------------------------ structural caps
#
# These stop the box falling over. They are NOT content policy: as of 2026-08-20 nothing here
# inspects what a note says and no keyword list is implemented anywhere in this package, so the
# only limits are the ones that keep a request from exhausting memory or a response from being
# unbounded. That absence is a deliberate pre-launch state and not a cleared posture -- request
# ledger R-98, held, being re-scoped per surface.

MAX_NAME = 400                  # a project name / item title
MAX_TEXT = 200_000              # an item body, a note, an event record
MAX_PATH = 1_024
MAX_PROJECTS = 2_000
MAX_ITEMS_PER_PROJECT = 20_000
MAX_FILES_PER_PROJECT = 5_000
MAX_ROWS = 500                  # rows in one list response
MAX_SEARCH_ROWS = 200
BUSY_TIMEOUT_MS = 10_000

#: The states a work item may be in. A closed vocabulary because the *client* branches on
#: it -- a free-text state means a phone app with a switch statement that silently falls
#: through. This is a data-shape constraint, not a policy about content.
ITEM_STATES = ("open", "doing", "blocked", "done")

#: Event kinds. Same reasoning. `note` is the catch-all, so nothing a caller wants to
#: record is refused for want of a category.
EVENT_KINDS = ("note", "session", "change", "decision", "draft")

_ID_RE = re.compile(r"\A[0-9a-f]{16}\Z")


def new_id() -> str:
    """An opaque server-generated key. Never a name, never a path.

    `docs/specs/project-spec.md` §3.2: ids must never reach a path join, which removes the
    traversal class of bug rather than guarding it. `_ID_RE` is still enforced on the way
    in, because the id arrives in a URL and lands in a SQL parameter -- and because a
    validator that exists is what stops the next person deciding an id may be a filename.
    """
    return secrets.token_hex(8)


def valid_id(s: object) -> bool:
    return isinstance(s, str) and bool(_ID_RE.match(s))


# ------------------------------------------------------------------ configuration
#
# Functions, not module constants. A constant is captured at import, and a long-running
# uvicorn process would pin it -- which makes the surface untestable and unreconfigurable
# without a restart. Same reasoning as `backend/apps/coder`.


def db_path() -> pathlib.Path:
    """`run/project/store.db`, overridable with `SYMONEURAL_PROJECT_DB`.

    `docs/specs/project-spec.md` §2.5 proposes `backend/project/store.db` and argues `run/`
    is wrong because `.claude/CLAUDE.md` describes it as runtime state somebody will
    eventually clear out. That argument is sound and the default here still points at
    `run/`, for one reason that is not a disagreement: `run/` is already in `.gitignore`
    and `backend/project/` is not. A store that defaults to an untracked path is a store
    that cannot be committed by accident on its first write, which is the failure §7.2
    calls out as unrecoverable ("a workspace committed by accident is in the history
    permanently"). `backend/apps/accounts/` made the same call for the same reason and
    keeps its database at `run/accounts/accounts.db`.

    To take the spec's placement instead, add `backend/project/` to `.gitignore` and set
    `SYMONEURAL_PROJECT_DB=backend/project/store.db`. Both are one line and neither is this
    package's to write.
    """
    override = os.environ.get("SYMONEURAL_PROJECT_DB", "").strip()
    if override:
        return pathlib.Path(override).expanduser()
    return ROOT / "run" / "project" / "store.db"


def backup_dir() -> pathlib.Path:
    override = os.environ.get("SYMONEURAL_PROJECT_BACKUP_DIR", "").strip()
    if override:
        return pathlib.Path(override).expanduser()
    return db_path().parent / "backups"


# ------------------------------------------------------------------ the gate


def enabled() -> bool:
    """On when the flag is on. The token half is gone.

    # NO API KEYS. Owner decision, 2026-09-11: "no api keys period". Single-operator box.
    """
    return os.environ.get("SYMONEURAL_PROJECT_ENABLED") == "1"


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


def authorize(token: str | None) -> tuple[bool, str, str]:
    """(allowed, code, reason). The one place the gate is evaluated.

    Order matters for what an unauthenticated caller learns: the surface reports itself
    disabled before it reports anything about the token.
    """
    if not enabled():
        return False, "disabled", ("surface disabled — set SYMONEURAL_PROJECT_ENABLED=1, and read "
                                   "backend/apps/project/README.md first")
    if not token_ok(token):
        return False, "unauthorized", "bad or missing X-Symoneural-Token"
    return True, "", ""


# ------------------------------------------------------------------ the file denylist
#
# Project references files by path and never holds a copy (`docs/specs/project-spec.md`
# §1.2). A reference is still a path this process resolves, so the same guard Coder applies
# to reads applies here to links -- and for the sharper reason: an item body quoting the
# corpus would be the trade secret in a second, less-guarded location (§7.2).
#
# Segment runs, matched against the RESOLVED ABSOLUTE path. Absolute rather than
# repo-relative so that narrowing the root later cannot make `training/adapter` stop
# matching, and resolved rather than textual so a symlink named `notes.txt` pointing at the
# corpus is refused -- doing the denylist before resolution is the classic bypass.

DENY_SEGMENTS: tuple[tuple[str, ...], ...] = (
    # Trade secret. `.claude/CLAUDE.md`: never copied into site/, never served from an
    # endpoint, never quoted into a page or a commit. This is the recipe for the product.
    ("training", "corpus.jsonl"),
    ("training", "build_dataset.py"),
    ("training", "adapter"),
    # The GPU mutex. `mkdir run/gpu.lock.d` IS the lock; there is nothing else. Project has
    # no business naming it, and a workspace that lists it invites somebody to go and look.
    ("run", "gpu.lock.d"),
    # This store, and its backups. A workspace item pointing at its own database is a loop
    # with an exfiltration path on the end of it.
    ("run", "project"),
    (".git", "config"),
)

DENY_NAME_GLOBS: tuple[str, ...] = ("*.key", ".env", ".env.*")


class Refused(Exception):
    """Internal. Carries a machine code; never escapes a public function."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _denied_reason(resolved: pathlib.Path) -> str | None:
    parts = resolved.parts
    for run in DENY_SEGMENTS:
        n = len(run)
        for i in range(len(parts) - n + 1):
            if parts[i:i + n] == run:
                return f"{'/'.join(run)} is denied — see backend/apps/project/README.md"
    for pat in DENY_NAME_GLOBS:
        if fnmatch.fnmatch(resolved.name, pat):
            return f"{resolved.name} matches the denied pattern {pat}"
    return None


def repo_root() -> pathlib.Path:
    """The tree a file reference may name. `SYMONEURAL_PROJECT_ROOT` narrows it for tests."""
    raw = os.environ.get("SYMONEURAL_PROJECT_ROOT", "").strip() or str(ROOT)
    return pathlib.Path(raw).expanduser().resolve()


def normalise_path(raw: object) -> str:
    """A caller-supplied file reference -> a root-relative string, or Refused.

    The order is the whole point, and it is Coder's:
      1. reject obviously hostile input
      2. join onto the root unless already absolute
      3. resolve() -- which follows every symlink, including the last component
      4. containment against the RESOLVED root
      5. denylist against the RESOLVED absolute path

    Nothing is opened and no bytes are read. This validates a *name*; the store keeps the
    relative string and never the contents.
    """
    if not isinstance(raw, str):
        raise Refused("bad_path", f"path must be a string, got {type(raw).__name__}")
    s = raw.strip()
    if not s:
        raise Refused("bad_path", "empty path")
    if "\x00" in s:
        raise Refused("bad_path", "path contains a NUL byte")
    if len(s) > MAX_PATH:
        raise Refused("too_large", f"path exceeds {MAX_PATH} characters")

    root = repo_root()
    p = pathlib.Path(s).expanduser()
    if not p.is_absolute():
        p = root / p
    try:
        full = p.resolve()
    except (OSError, RuntimeError) as e:            # RuntimeError: symlink loop
        raise Refused("bad_path", f"cannot resolve path: {e.__class__.__name__}") from None

    if full != root and root not in full.parents:
        raise Refused("outside_root", f"path escapes the repository root ({root})")

    why = _denied_reason(full)
    if why:
        raise Refused("denied", why)

    rel = full.relative_to(root)
    return str(rel) if str(rel) != "." else "."


def path_reading(rel: str) -> dict:
    """What is true about a referenced path right now. A reading, never a copy.

    `exists`, `bytes` and `modified` come from `stat`. The file's *contents* are never read
    here and there is no endpoint in this package that returns them: reading and writing
    files is `backend/apps/coder/`'s job and it has the journal and the rollback store that
    make that safe. Project stores the reference.
    """
    out: dict = {"path": rel, "exists": False, "kind": None,
                 "bytes": None, "modified": None}
    try:
        full = (repo_root() / rel).resolve()
    except (OSError, RuntimeError):
        return out
    # Re-checked on the way out as well as on the way in: a path that was legal when it was
    # linked can become a symlink into `training/` afterwards.
    root = repo_root()
    if (full != root and root not in full.parents) or _denied_reason(full):
        out["kind"] = "denied"
        return out
    try:
        st = full.stat()
    except OSError:
        return out
    out["exists"] = True
    out["kind"] = ("dir" if full.is_dir() else "file" if full.is_file() else "other")
    out["bytes"] = st.st_size if full.is_file() else None
    out["modified"] = st.st_mtime
    return out


# ------------------------------------------------------------------ the database

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS projects (
    id       TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    summary  TEXT NOT NULL DEFAULT '',
    archived INTEGER NOT NULL DEFAULT 0,
    version  INTEGER NOT NULL DEFAULT 1,
    created  REAL NOT NULL,
    updated  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    body       TEXT NOT NULL DEFAULT '',
    state      TEXT NOT NULL DEFAULT 'open',
    ordinal    REAL NOT NULL,
    version    INTEGER NOT NULL DEFAULT 1,
    created    REAL NOT NULL,
    updated    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS items_project ON items(project_id, state);
CREATE INDEX IF NOT EXISTS items_order   ON items(project_id, ordinal);

CREATE TABLE IF NOT EXISTS files (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    path       TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    created    REAL NOT NULL,
    UNIQUE (project_id, path)
);

-- Append-only. There is no UPDATE and no DELETE route onto this table, which is what makes
-- the history worth reading and what keeps it free of the concurrency argument in §3.4.
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    text       TEXT NOT NULL DEFAULT '',
    actor      TEXT NOT NULL DEFAULT '',
    at         REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS events_project ON events(project_id, id DESC);

-- FTS5, which is CPU, exact and built in. `docs/specs/project-spec.md` §2.3: substring and
-- full-text search over a personal workspace of a few hundred items is not a problem that
-- needs a neural network, and an embedding model here would make this surface evictable.
CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(
    title, body, kind UNINDEXED, ref UNINDEXED, project_id UNINDEXED,
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS projects_ai AFTER INSERT ON projects BEGIN
    INSERT INTO search(title, body, kind, ref, project_id)
    VALUES (new.name, new.summary, 'project', new.id, new.id);
END;
CREATE TRIGGER IF NOT EXISTS projects_au AFTER UPDATE ON projects BEGIN
    UPDATE search SET title = new.name, body = new.summary
    WHERE kind = 'project' AND ref = new.id;
END;
CREATE TRIGGER IF NOT EXISTS projects_ad AFTER DELETE ON projects BEGIN
    DELETE FROM search WHERE project_id = old.id;
END;

CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN
    INSERT INTO search(title, body, kind, ref, project_id)
    VALUES (new.title, new.body, 'item', new.id, new.project_id);
END;
CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE ON items BEGIN
    UPDATE search SET title = new.title, body = new.body
    WHERE kind = 'item' AND ref = new.id;
END;
CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN
    DELETE FROM search WHERE kind = 'item' AND ref = old.id;
END;

CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
    INSERT INTO search(title, body, kind, ref, project_id)
    VALUES (new.kind, new.text, 'event', CAST(new.id AS TEXT), new.project_id);
END;
"""


@contextmanager
def connect():
    """A fresh connection per operation, and it CREATES the store if it is missing.

    Deliberately not a module-level singleton: uvicorn runs handlers on a thread pool the
    moment anything goes through `asyncio.to_thread`, and a shared `sqlite3` connection
    across threads is either an error or a data race depending on `check_same_thread`.
    Opening one is microseconds.

    **Nothing on the rack-poll path may call this.** `unit_state()` uses `probe()` instead,
    which opens read-only and therefore cannot create the file -- otherwise the honest
    "no project store initialised" state would create the thing whose absence it reports.
    """
    path = db_path()
    first = not path.exists()
    if first:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    c = sqlite3.connect(str(path), timeout=BUSY_TIMEOUT_MS / 1000.0, isolation_level=None)
    c.row_factory = sqlite3.Row
    try:
        c.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        c.execute("PRAGMA foreign_keys=ON")
        # Foreign-key cascade actions fire triggers only with recursive triggers enabled.
        # Deleting a project must clear its items out of the FTS index, so this is
        # load-bearing rather than tidiness -- and `delete_project` also deletes by
        # project_id directly, because a search index that outlives its rows hands back
        # results pointing at nothing.
        c.execute("PRAGMA recursive_triggers=ON")
        # WAL so a reader never blocks a writer. §3.4 calls this the single most important
        # line in the storage layer, and it is: a phone and a laptop polling the same store
        # is exactly the pattern the default journal turns into `database is locked`.
        # Read the mode first and only set it when it is wrong: the mode lives in the file
        # header, so an unconditional set is a no-op that still asks for a lock.
        if c.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
            c.execute("PRAGMA journal_mode=WAL")
        if first:
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        # The schema is applied only when `user_version` says it is not there yet.
        #
        # Running `executescript(_SCHEMA)` on every connection is what the neighbouring
        # `apps/accounts` does, and it is wrong for this surface: `CREATE TABLE IF NOT
        # EXISTS` still opens a WRITE transaction even when every table already exists, so
        # every read would queue behind every write and WAL's whole benefit -- the one
        # thing §3.4 calls the most important line in the storage layer -- would be handed
        # back. `PRAGMA user_version` is a read of four bytes in the file header.
        #
        # The self-healing property survives: a truncated copy or a half-finished restore
        # reports version 0 and gets the schema reapplied, rather than raising `no such
        # table` from three calls deep.
        if c.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            c.executescript(_SCHEMA)
            c.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema', ?)",
                      (str(SCHEMA_VERSION),))
            c.execute(f"PRAGMA user_version={int(SCHEMA_VERSION)}")
        yield c
    finally:
        c.close()


def init_db() -> pathlib.Path:
    """Create the store if it is missing. Idempotent. Never called from a rack poll."""
    with connect():
        pass
    return db_path()


def bootstrap() -> pathlib.Path | None:
    """Create the store at process start if the surface is switched on. Path, or None.

    Why this exists as a function rather than as two lines in `api.py`'s lifespan: the
    pairing of the switch with the create *is* the behaviour, and it has two failure modes
    that point opposite ways. Calling `init_db()` unconditionally would put a database on
    disk for a surface the operator never enabled, which is the one thing a disabled surface
    must not do. Calling nothing -- the state this repo was in -- leaves a fresh install
    reporting `offline / no project store initialised` forever, because the only code that
    creates the file is `connect()`, the rack poll deliberately uses `probe()` instead
    (see `probe`'s docstring), and nothing else runs until a write request arrives. Both
    halves need a test, and a test of two lines inside a lifespan would have to import a
    125 KB module and start an event loop to reach them.

    This is not a rack poll, so it does not violate the rule `connect()` sets.

    Failures are swallowed on purpose, and this is the only place in the module that does
    that. The call site is `api.py`'s lifespan, inline and before `yield` -- every other
    startup line there is either a pure env read or an `asyncio.create_task`, where an
    exception dies inside the task. An `OSError` out of `mkdir` or an
    `sqlite3.OperationalError` out of `executescript` would propagate out of the lifespan,
    uvicorn would fail to start, and `Restart=always` would make that a crashloop taking
    down all thirteen units -- for a function whose entire purpose is making one rack row
    honest. Returning `None` instead costs nothing, because the true reading for "no store"
    already exists and the rack already prints it: `probe()` answers
    `offline / no project store initialised`. A degraded start lands on a state that is
    true rather than on one that was manufactured, and no new state string is invented.
    """
    if not enabled():
        return None
    try:
        return init_db()
    except (OSError, sqlite3.Error):
        # The path is logged, not the exception's own text, which can carry the full
        # filesystem path of a store an operator chose to put somewhere private.
        log.exception("project store could not be created at %s; surface stays offline",
                      db_path())
        return None


def probe() -> tuple[bool, str]:
    """(answers, why). Read-only, cheap, and it CANNOT create the file.

    This is the only database call on `/api/status`'s path. `mode=ro` is what makes the
    "no project store initialised" reading honest -- `sqlite3.connect` on a plain path
    creates an empty database, so probing with a normal connection would mean the rack
    reported the store missing exactly once and then manufactured it.
    """
    path = db_path()
    if not path.is_file():
        return False, "no project store initialised"
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=0.5)
    except sqlite3.Error as e:
        return False, f"project store unreadable ({e.__class__.__name__})"
    try:
        c.execute("PRAGMA busy_timeout=250")
        c.execute("SELECT 1 FROM projects LIMIT 1").fetchall()
        return True, ""
    except sqlite3.Error as e:
        return False, f"project store unreadable ({e.__class__.__name__})"
    finally:
        c.close()


# ------------------------------------------------------------------ helpers


def _now() -> float:
    return time.time()


def _text(value: object, field: str, *, limit: int, required: bool = False) -> str:
    """Length-check and nothing else.

    No content inspection is implemented here as of 2026-08-20: no keyword list, no profanity
    check, no "does this look like a prompt injection" heuristic. The cap exists so a single
    POST cannot pin memory. That absence is a deliberate pre-launch state and not a cleared
    posture -- request ledger R-98, held, being re-scoped per surface. (This docstring used to
    read "and there never may be", which overstated a "not yet" into a permanent bar.)
    """
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise Refused("bad_field", f"{field} must be a string")
    if required and not value.strip():
        raise Refused("bad_field", f"{field} is required")
    if len(value) > limit:
        raise Refused("too_large", f"{field} exceeds {limit} characters")
    return value


def _row(r: sqlite3.Row) -> dict:
    return {k: r[k] for k in r.keys()}


def _ok(**kw) -> dict:
    return {"ok": True, "api_version": API_VERSION, **kw}


def _err(code: str, message: str, **kw) -> dict:
    return {"ok": False, "api_version": API_VERSION, "code": code, "error": message, **kw}


def _refusal(e: Refused) -> dict:
    return _err(e.code, str(e))


def etag_of(rows: list[dict], *keys: str) -> str:
    """A weak-ish validator over the fields a client can actually observe.

    Hashing the whole payload is what `backend/api.py::semantic_etag` had to stop doing:
    a tag that changes on every request costs a hash and saves nothing. Here the semantic
    state of a list is which rows exist and what version each is at.
    """
    h = hashlib.sha256()
    h.update(f"v{API_VERSION}\n".encode())
    for r in rows:
        h.update(("\x1f".join(str(r.get(k)) for k in keys) + "\x1e").encode())
    return '"' + h.hexdigest()[:32] + '"'


def last_modified_of(rows: list[dict], *keys: str) -> float | None:
    best = None
    for r in rows:
        for k in keys:
            v = r.get(k)
            if isinstance(v, (int, float)) and (best is None or v > best):
                best = float(v)
    return best


# ------------------------------------------------------------------ projects


def list_projects(*, include_archived: bool = False, limit: int = MAX_ROWS,
                  offset: int = 0) -> dict:
    lim = max(1, min(int(limit or MAX_ROWS), MAX_ROWS))
    off = max(0, int(offset or 0))
    try:
        with connect() as c:
            sql = ("SELECT p.*, "
                   "(SELECT COUNT(*) FROM items i WHERE i.project_id = p.id) AS items, "
                   "(SELECT COUNT(*) FROM items i WHERE i.project_id = p.id "
                   " AND i.state = 'open') AS items_open, "
                   "(SELECT COUNT(*) FROM events e WHERE e.project_id = p.id) AS events "
                   "FROM projects p ")
            if not include_archived:
                sql += "WHERE p.archived = 0 "
            sql += "ORDER BY p.updated DESC LIMIT ? OFFSET ?"
            rows = [_row(r) for r in c.execute(sql, (lim, off)).fetchall()]
            total = c.execute(
                "SELECT COUNT(*) FROM projects" if include_archived
                else "SELECT COUNT(*) FROM projects WHERE archived = 0").fetchone()[0]
    except sqlite3.Error as e:
        return _err("store_error", f"{e.__class__.__name__}: {e}")
    return _ok(projects=rows, total=total, limit=lim, offset=off)


def create_project(name: str, summary: str = "") -> dict:
    try:
        name = _text(name, "name", limit=MAX_NAME, required=True)
        summary = _text(summary, "summary", limit=MAX_TEXT)
    except Refused as e:
        return _refusal(e)
    pid, now = new_id(), _now()
    try:
        with connect() as c:
            n = c.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
            if n >= MAX_PROJECTS:
                return _err("cap", f"this store already holds {n} projects "
                                   f"(cap {MAX_PROJECTS})")
            c.execute("INSERT INTO projects(id, name, summary, archived, version, "
                      "created, updated) VALUES (?,?,?,0,1,?,?)",
                      (pid, name, summary, now, now))
            row = _row(c.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone())
    except sqlite3.Error as e:
        return _err("store_error", f"{e.__class__.__name__}: {e}")
    return _ok(project=row)


def get_project(pid: str, *, with_items: bool = True) -> dict:
    if not valid_id(pid):
        return _err("not_found", "no such project")
    try:
        with connect() as c:
            r = c.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
            if r is None:
                return _err("not_found", "no such project")
            out = _row(r)
            items = [_row(x) for x in c.execute(
                "SELECT * FROM items WHERE project_id = ? ORDER BY ordinal, created "
                "LIMIT ?", (pid, MAX_ROWS)).fetchall()] if with_items else []
            files = [_row(x) for x in c.execute(
                "SELECT * FROM files WHERE project_id = ? ORDER BY path LIMIT ?",
                (pid, MAX_ROWS)).fetchall()]
            events = c.execute("SELECT COUNT(*) FROM events WHERE project_id = ?",
                               (pid,)).fetchone()[0]
    except sqlite3.Error as e:
        return _err("store_error", f"{e.__class__.__name__}: {e}")
    for f in files:
        f["reading"] = path_reading(f["path"])
    return _ok(project=out, items=items, files=files, events=events)


def update_project(pid: str, *, if_version: int | None = None, name: object = None,
                   summary: object = None, archived: object = None) -> dict:
    """Rename, re-summarise or archive. Optimistic concurrency, and it is not optional.

    `if_version` is the version the client read. A mismatch is a 409, not a silent
    last-write-wins: two devices open on the same note is exactly the situation a workspace
    invites, and losing a note without an error is the failure that stops people trusting
    one (`docs/specs/project-spec.md` §3.4, §7.7). Omitting `if_version` is allowed and
    means "I did not read a version" -- it is the escape hatch for a script, and the README
    says so rather than pretending the check is unconditional.
    """
    if not valid_id(pid):
        return _err("not_found", "no such project")
    sets, args = [], []
    try:
        if name is not None:
            sets.append("name = ?")
            args.append(_text(name, "name", limit=MAX_NAME, required=True))
        if summary is not None:
            sets.append("summary = ?")
            args.append(_text(summary, "summary", limit=MAX_TEXT))
        if archived is not None:
            if not isinstance(archived, bool):
                return _err("bad_field", "archived must be true or false")
            sets.append("archived = ?")
            args.append(1 if archived else 0)
    except Refused as e:
        return _refusal(e)
    if not sets:
        return _err("bad_field", "nothing to change")
    sets += ["version = version + 1", "updated = ?"]
    args.append(_now())
    return _versioned_update("projects", "project", pid, sets, args, if_version)


def delete_project(pid: str, *, if_version: int | None = None) -> dict:
    """Archive first, then delete. Never a silent drop.

    A project that is not archived is refused: `docs/specs/project-spec.md` §3.2 asks for
    archive-then-delete, and the reason is that DELETE on a workspace is the one action
    with no undo in this package. Two deliberate steps means the destructive one cannot be
    reached by a mis-aimed request.
    """
    if not valid_id(pid):
        return _err("not_found", "no such project")
    try:
        with connect() as c:
            r = c.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
            if r is None:
                return _err("not_found", "no such project")
            if if_version is not None and int(if_version) != int(r["version"]):
                return _err("stale", f"this project is at version {r['version']}",
                            version=r["version"])
            if not r["archived"]:
                return _err("not_archived",
                            "archive this project before deleting it — "
                            "PATCH with {\"archived\": true} first")
            c.execute("DELETE FROM projects WHERE id = ?", (pid,))
            # Belt and braces beside the cascade trigger: a stale FTS row returns a search
            # hit pointing at a project that no longer exists.
            c.execute("DELETE FROM search WHERE project_id = ?", (pid,))
    except sqlite3.Error as e:
        return _err("store_error", f"{e.__class__.__name__}: {e}")
    return _ok(deleted=pid)


def _versioned_update(table: str, label: str, rid: str, sets: list[str], args: list,
                      if_version: int | None) -> dict:
    """The one place a conditional UPDATE happens, so 404 and 409 cannot be confused.

    `UPDATE ... WHERE id = ? AND version = ?` returning zero rows means either "gone" or
    "stale", and answering the wrong one sends a client into a retry loop against a row
    that will never exist. So the row is re-read before deciding.
    """
    sql = f"UPDATE {table} SET {', '.join(sets)} WHERE id = ?"
    params = list(args) + [rid]
    if if_version is not None:
        try:
            want = int(if_version)
        except (TypeError, ValueError):
            return _err("bad_field", "if_version must be an integer")
        sql += " AND version = ?"
        params.append(want)
    try:
        with connect() as c:
            cur = c.execute(sql, params)
            if cur.rowcount == 0:
                cur2 = c.execute(f"SELECT * FROM {table} WHERE id = ?", (rid,)).fetchone()
                if cur2 is None:
                    return _err("not_found", f"no such {label}")
                return _err("stale",
                            f"this {label} is at version {cur2['version']}, "
                            f"you wrote against {if_version} — re-read and retry",
                            **{label: _row(cur2)})
            row = _row(c.execute(f"SELECT * FROM {table} WHERE id = ?", (rid,)).fetchone())
    except sqlite3.Error as e:
        return _err("store_error", f"{e.__class__.__name__}: {e}")
    return _ok(**{label: row})


# ------------------------------------------------------------------ items


def list_items(pid: str, *, state: str | None = None, limit: int = MAX_ROWS,
               offset: int = 0) -> dict:
    if not valid_id(pid):
        return _err("not_found", "no such project")
    if state is not None and state not in ITEM_STATES:
        return _err("bad_field", f"state must be one of {', '.join(ITEM_STATES)}")
    lim = max(1, min(int(limit or MAX_ROWS), MAX_ROWS))
    off = max(0, int(offset or 0))
    try:
        with connect() as c:
            if c.execute("SELECT 1 FROM projects WHERE id = ?", (pid,)).fetchone() is None:
                return _err("not_found", "no such project")
            sql = "SELECT * FROM items WHERE project_id = ?"
            args: list = [pid]
            if state:
                sql += " AND state = ?"
                args.append(state)
            sql += " ORDER BY ordinal, created LIMIT ? OFFSET ?"
            rows = [_row(r) for r in c.execute(sql, args + [lim, off]).fetchall()]
            counts = {s: 0 for s in ITEM_STATES}
            for s, n in c.execute("SELECT state, COUNT(*) FROM items WHERE project_id = ? "
                                  "GROUP BY state", (pid,)).fetchall():
                counts[s] = n
    except sqlite3.Error as e:
        return _err("store_error", f"{e.__class__.__name__}: {e}")
    return _ok(project_id=pid, items=rows, counts=counts, limit=lim, offset=off)


def create_item(pid: str, title: str, body: str = "", state: str = "open",
                ordinal: float | None = None) -> dict:
    if not valid_id(pid):
        return _err("not_found", "no such project")
    if state not in ITEM_STATES:
        return _err("bad_field", f"state must be one of {', '.join(ITEM_STATES)}")
    try:
        title = _text(title, "title", limit=MAX_NAME, required=True)
        body = _text(body, "body", limit=MAX_TEXT)
    except Refused as e:
        return _refusal(e)
    iid, now = new_id(), _now()
    try:
        with connect() as c:
            if c.execute("SELECT 1 FROM projects WHERE id = ?", (pid,)).fetchone() is None:
                return _err("not_found", "no such project")
            n = c.execute("SELECT COUNT(*) FROM items WHERE project_id = ?",
                          (pid,)).fetchone()[0]
            if n >= MAX_ITEMS_PER_PROJECT:
                return _err("cap", f"this project already holds {n} items "
                                   f"(cap {MAX_ITEMS_PER_PROJECT})")
            if ordinal is None:
                top = c.execute("SELECT MAX(ordinal) FROM items WHERE project_id = ?",
                                (pid,)).fetchone()[0]
                ordv = (float(top) + 1.0) if top is not None else 1.0
            else:
                ordv = float(ordinal)
            c.execute("INSERT INTO items(id, project_id, title, body, state, ordinal, "
                      "version, created, updated) VALUES (?,?,?,?,?,?,1,?,?)",
                      (iid, pid, title, body, state, ordv, now, now))
            c.execute("UPDATE projects SET updated = ? WHERE id = ?", (now, pid))
            row = _row(c.execute("SELECT * FROM items WHERE id = ?", (iid,)).fetchone())
    except (sqlite3.Error, ValueError, TypeError) as e:
        return _err("store_error", f"{e.__class__.__name__}: {e}")
    return _ok(item=row)


def update_item(iid: str, *, if_version: int | None = None, title: object = None,
                body: object = None, state: object = None,
                ordinal: object = None) -> dict:
    if not valid_id(iid):
        return _err("not_found", "no such item")
    sets, args = [], []
    try:
        if title is not None:
            sets.append("title = ?")
            args.append(_text(title, "title", limit=MAX_NAME, required=True))
        if body is not None:
            sets.append("body = ?")
            args.append(_text(body, "body", limit=MAX_TEXT))
        if state is not None:
            if state not in ITEM_STATES:
                return _err("bad_field", f"state must be one of {', '.join(ITEM_STATES)}")
            sets.append("state = ?")
            args.append(state)
        if ordinal is not None:
            try:
                args.append(float(ordinal))
            except (TypeError, ValueError):
                return _err("bad_field", "ordinal must be a number")
            sets.append("ordinal = ?")
    except Refused as e:
        return _refusal(e)
    if not sets:
        return _err("bad_field", "nothing to change")
    sets += ["version = version + 1", "updated = ?"]
    args.append(_now())
    return _versioned_update("items", "item", iid, sets, args, if_version)


def delete_item(iid: str, *, if_version: int | None = None) -> dict:
    if not valid_id(iid):
        return _err("not_found", "no such item")
    try:
        with connect() as c:
            r = c.execute("SELECT * FROM items WHERE id = ?", (iid,)).fetchone()
            if r is None:
                return _err("not_found", "no such item")
            if if_version is not None and int(if_version) != int(r["version"]):
                return _err("stale", f"this item is at version {r['version']}",
                            item=_row(r))
            # The item goes; the record that it existed does not. An events log that only
            # shows what survived is not history.
            c.execute("INSERT INTO events(project_id, kind, text, actor, at) "
                      "VALUES (?,?,?,?,?)",
                      (r["project_id"], "change", f"deleted item: {r['title']}",
                       "store", _now()))
            c.execute("DELETE FROM items WHERE id = ?", (iid,))
    except sqlite3.Error as e:
        return _err("store_error", f"{e.__class__.__name__}: {e}")
    return _ok(deleted=iid, project_id=r["project_id"])


# ------------------------------------------------------------------ file references


def list_files(pid: str) -> dict:
    if not valid_id(pid):
        return _err("not_found", "no such project")
    try:
        with connect() as c:
            if c.execute("SELECT 1 FROM projects WHERE id = ?", (pid,)).fetchone() is None:
                return _err("not_found", "no such project")
            rows = [_row(r) for r in c.execute(
                "SELECT * FROM files WHERE project_id = ? ORDER BY path LIMIT ?",
                (pid, MAX_ROWS)).fetchall()]
    except sqlite3.Error as e:
        return _err("store_error", f"{e.__class__.__name__}: {e}")
    for r in rows:
        r["reading"] = path_reading(r["path"])
    return _ok(project_id=pid, files=rows, root=str(repo_root()))


def link_file(pid: str, path: str, note: str = "") -> dict:
    """Attach a repository path to a project. The path is validated; nothing is copied."""
    if not valid_id(pid):
        return _err("not_found", "no such project")
    try:
        rel = normalise_path(path)
        note = _text(note, "note", limit=MAX_TEXT)
    except Refused as e:
        return _refusal(e)
    fid, now = new_id(), _now()
    try:
        with connect() as c:
            if c.execute("SELECT 1 FROM projects WHERE id = ?", (pid,)).fetchone() is None:
                return _err("not_found", "no such project")
            n = c.execute("SELECT COUNT(*) FROM files WHERE project_id = ?",
                          (pid,)).fetchone()[0]
            if n >= MAX_FILES_PER_PROJECT:
                return _err("cap", f"this project already references {n} files "
                                   f"(cap {MAX_FILES_PER_PROJECT})")
            try:
                c.execute("INSERT INTO files(id, project_id, path, note, created) "
                          "VALUES (?,?,?,?,?)", (fid, pid, rel, note, now))
            except sqlite3.IntegrityError:
                return _err("duplicate", f"{rel} is already linked to this project")
            row = _row(c.execute("SELECT * FROM files WHERE id = ?", (fid,)).fetchone())
    except sqlite3.Error as e:
        return _err("store_error", f"{e.__class__.__name__}: {e}")
    row["reading"] = path_reading(rel)
    return _ok(file=row)


def unlink_file(fid: str) -> dict:
    if not valid_id(fid):
        return _err("not_found", "no such file reference")
    try:
        with connect() as c:
            cur = c.execute("DELETE FROM files WHERE id = ?", (fid,))
            if cur.rowcount == 0:
                return _err("not_found", "no such file reference")
    except sqlite3.Error as e:
        return _err("store_error", f"{e.__class__.__name__}: {e}")
    return _ok(deleted=fid)


# ------------------------------------------------------------------ events


def list_events(pid: str, *, limit: int = MAX_ROWS, before: int | None = None) -> dict:
    """Newest first. Append-only, so this is the one list with no version to check."""
    if not valid_id(pid):
        return _err("not_found", "no such project")
    lim = max(1, min(int(limit or MAX_ROWS), MAX_ROWS))
    try:
        with connect() as c:
            if c.execute("SELECT 1 FROM projects WHERE id = ?", (pid,)).fetchone() is None:
                return _err("not_found", "no such project")
            sql = "SELECT * FROM events WHERE project_id = ?"
            args: list = [pid]
            if before is not None:
                sql += " AND id < ?"
                args.append(int(before))
            sql += " ORDER BY id DESC LIMIT ?"
            rows = [_row(r) for r in c.execute(sql, args + [lim]).fetchall()]
            total = c.execute("SELECT COUNT(*) FROM events WHERE project_id = ?",
                              (pid,)).fetchone()[0]
    except (sqlite3.Error, ValueError, TypeError) as e:
        return _err("store_error", f"{e.__class__.__name__}: {e}")
    return _ok(project_id=pid, events=rows, total=total, limit=lim)


def add_event(pid: str, kind: str, text: str, actor: str = "") -> dict:
    if not valid_id(pid):
        return _err("not_found", "no such project")
    if kind not in EVENT_KINDS:
        return _err("bad_field", f"kind must be one of {', '.join(EVENT_KINDS)}")
    try:
        text = _text(text, "text", limit=MAX_TEXT, required=True)
        actor = _text(actor, "actor", limit=MAX_NAME)
    except Refused as e:
        return _refusal(e)
    now = _now()
    try:
        with connect() as c:
            if c.execute("SELECT 1 FROM projects WHERE id = ?", (pid,)).fetchone() is None:
                return _err("not_found", "no such project")
            cur = c.execute("INSERT INTO events(project_id, kind, text, actor, at) "
                            "VALUES (?,?,?,?,?)", (pid, kind, text, actor, now))
            c.execute("UPDATE projects SET updated = ? WHERE id = ?", (now, pid))
            row = _row(c.execute("SELECT * FROM events WHERE id = ?",
                                 (cur.lastrowid,)).fetchone())
    except sqlite3.Error as e:
        return _err("store_error", f"{e.__class__.__name__}: {e}")
    return _ok(event=row)


# ------------------------------------------------------------------ search


def search(q: str, *, project_id: str | None = None, limit: int = 50) -> dict:
    """FTS5 over projects, items and events. CPU, exact, no model involved.

    A malformed MATCH expression -- `foo"`, a bare `AND`, an unbalanced paren -- raises
    `sqlite3.OperationalError`, which without this handler is a 500 on the one endpoint
    reachable with a single unauthenticated-shaped request. That is caught and reported as
    a bad query. It is a robustness guard, not a filter: the query is not inspected for
    *what it asks about*, only for whether SQLite can parse it.
    """
    if not isinstance(q, str) or not q.strip():
        return _err("bad_field", "q is required")
    if len(q) > MAX_NAME:
        return _err("too_large", f"q exceeds {MAX_NAME} characters")
    if project_id is not None and not valid_id(project_id):
        return _err("not_found", "no such project")
    lim = max(1, min(int(limit or 50), MAX_SEARCH_ROWS))
    sql = ("SELECT kind, ref, project_id, title, "
           "snippet(search, 1, '', '', '…', 16) AS excerpt, rank "
           "FROM search WHERE search MATCH ?")
    args: list = [q]
    if project_id:
        sql += " AND project_id = ?"
        args.append(project_id)
    sql += " ORDER BY rank LIMIT ?"
    args.append(lim)
    try:
        with connect() as c:
            rows = [_row(r) for r in c.execute(sql, args).fetchall()]
    except sqlite3.OperationalError as e:
        return _err("bad_query", f"that search expression is not valid FTS5 syntax: {e}")
    except sqlite3.Error as e:
        return _err("store_error", f"{e.__class__.__name__}: {e}")
    return _ok(q=q, results=rows, count=len(rows), limit=lim)


# ------------------------------------------------------------------ readings


def readings() -> dict:
    """What this surface is actually holding. Every number read from the store.

    If there are no workspaces open, this says zero. It does not invent activity, and there
    is deliberately no uptime figure, no availability percentage and no synthesised
    "recent activity" number -- `.claude/CLAUDE.md`: every gauge reflects a real reading.
    """
    path = db_path()
    if not path.is_file():
        return _ok(initialised=False, projects=0, projects_archived=0, items=0,
                   items_open=0, files=0, events=0, bytes_on_disk=0,
                   store=str(path), root=str(repo_root()),
                   note="no project store initialised — nothing has been created yet")
    try:
        with connect() as c:
            g = lambda sql: c.execute(sql).fetchone()[0]  # noqa: E731
            out = {
                "initialised": True,
                "projects": g("SELECT COUNT(*) FROM projects WHERE archived = 0"),
                "projects_archived": g("SELECT COUNT(*) FROM projects WHERE archived = 1"),
                "items": g("SELECT COUNT(*) FROM items"),
                "items_open": g("SELECT COUNT(*) FROM items WHERE state = 'open'"),
                "files": g("SELECT COUNT(*) FROM files"),
                "events": g("SELECT COUNT(*) FROM events"),
            }
    except sqlite3.Error as e:
        return _err("store_error", f"{e.__class__.__name__}: {e}")
    total = 0
    for suffix in ("", "-wal", "-shm"):
        try:
            total += (path.parent / (path.name + suffix)).stat().st_size
        except OSError:
            pass
    out["bytes_on_disk"] = total
    out["store"] = str(path)
    out["root"] = str(repo_root())
    out["gpu"] = {
        "holds_lock": False,
        "vram_mib": 0,
        "note": "this surface loads no weights and never takes the GPU lock",
    }
    if out["projects"] == 0 and out["projects_archived"] == 0:
        out["note"] = "no workspaces open"
    return _ok(**out)


def backup(dest: str | None = None) -> dict:
    """A dated copy, via `sqlite3`'s online backup API. Consistent under WAL.

    `docs/specs/project-spec.md` §7.4: the store is gitignored, there is no git remote, and
    this project has already lost a private key that lived somewhere nobody backed up.
    **Nothing schedules this.** It is a function and a route; a cron entry or a systemd
    timer is the operator's to add, and until one exists the backup is only as good as
    somebody remembering. The README says so in those words rather than implying cover
    that does not exist.
    """
    src = db_path()
    if not src.is_file():
        return _err("not_found", "no project store to back up")
    d = pathlib.Path(dest).expanduser() if dest else backup_dir()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = d / f"store-{stamp}.db"
    try:
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        with connect() as c:
            tgt = sqlite3.connect(str(out))
            try:
                c.backup(tgt)
            finally:
                tgt.close()
        os.chmod(out, 0o600)
    except (sqlite3.Error, OSError) as e:
        return _err("store_error", f"{e.__class__.__name__}: {e}")
    return _ok(backup=str(out), bytes=out.stat().st_size)


# ------------------------------------------------------------------ the model, borrowed
#
# Project owns no weights. When it needs a model it asks the chat surface through an
# injected callable, exactly as `apps/streamer/guide` does and as `remix()` in `backend/api.py`
# does. This module never imports the API, never touches `scripts/gpu-governor.sh` and
# never opens a socket -- whatever the caller does about the GPU lock is the caller's
# business, and that is what keeps this package importable and fully testable with no card,
# no network and no service running.

#: Set by the wiring in `backend/api.py`, or left `None`. Unset is not an error state and
#: is not hidden: the draft routes answer `ok: false, code: "no_model"` and say so.
_ASK_MODEL: Callable[[str], str] | None = None


def set_ask_model(fn: Callable[[str], str] | None) -> None:
    """Register the route to the chat surface. `str -> str`, synchronous.

    The pure functions below take `ask_model` as an argument; this hook exists only so the
    HTTP layer has something to read. Keeping the functions parameterised is what makes
    them testable without a global, and what stops a second copy of the chat path growing
    inside this package.
    """
    global _ASK_MODEL
    _ASK_MODEL = fn


def ask_model_available() -> bool:
    return _ASK_MODEL is not None


DRAFT_PROMPT = (
    "Below is the state of a work project. Write a short plain-text summary of where it "
    "stands: what is done, what is in progress, and what is next.\n"
    "Plain sentences only. Do not use JSON, bullet characters, or Markdown headings.\n\n"
    "PROJECT: {name}\n{summary}\n\nITEMS:\n{items}\n\nRECENT:\n{events}\n"
)

BREAKDOWN_PROMPT = (
    "Turn the note below into a list of work items.\n"
    "One item per line. No numbering, no bullet characters, no JSON. "
    "A line is a short title, nothing else. At most {n} lines.\n\nNOTE:\n{note}\n"
)

#: The model's answer is a plain list; anything with JSON punctuation in it means the model
#: started emitting an object. `.claude/HANDOVER.md` §2c-bis, measured: asking this 7B for a
#: JSON object made it loop until the token cap, so nothing ever parsed and the fallback
#: fired on every request while the feature looked fine. `apps/streamer/guide` rejects the same
#: shape for the same reason.
_JSON_ISH = re.compile(r'[{}\[\]"]|^\s*\w+\s*:', re.M)

MAX_DRAFT_ITEMS = 20


class ModelUnusable(Exception):
    """The model answered, and the answer cannot be used. Never silently swallowed."""


def build_draft_prompt(project: dict, items: list[dict], events: list[dict]) -> str:
    lines = [f"- [{i.get('state', '?')}] {i.get('title', '')}" for i in items[:60]]
    ev = [f"- {e.get('kind', '')}: {str(e.get('text', ''))[:300]}" for e in events[:20]]
    return DRAFT_PROMPT.format(
        name=project.get("name", ""), summary=project.get("summary", ""),
        items="\n".join(lines) or "(none)", events="\n".join(ev) or "(none)")


def parse_item_lines(raw: str) -> list[str]:
    """One title per line. Refuses the JSON-loop shape outright."""
    if not isinstance(raw, str) or not raw.strip():
        raise ModelUnusable("the model returned nothing")
    if _JSON_ISH.search(raw):
        raise ModelUnusable("the model started emitting structured output, not a list")
    out, seen = [], set()
    for line in raw.splitlines():
        t = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
        if not t or len(t) > MAX_NAME:
            continue
        k = t.lower()
        if k in seen:                 # a repeated line is the loop, in its other spelling
            continue
        seen.add(k)
        out.append(t)
        if len(out) >= MAX_DRAFT_ITEMS:
            break
    if not out:
        raise ModelUnusable("no usable lines in the model's answer")
    return out


def draft_summary(pid: str, *, ask_model: Callable[[str], str] | None = None) -> dict:
    """Ask the chat surface to summarise a project. Nothing is written.

    The draft comes back for a person to read. It is not stored, it does not become the
    project summary, and it never becomes a work item on its own -- recording it is a
    separate, deliberate `POST .../events`. That is the §7.3 seam held open on purpose:
    a surface that turned model output into stored instructions would be a step on the
    two-hop path this spec exists to close.
    """
    fn = ask_model if ask_model is not None else _ASK_MODEL
    if fn is None:
        return _err("no_model", "no model is wired into this surface — "
                                "apps.project.set_ask_model() has not been called")
    got = get_project(pid)
    if not got.get("ok"):
        return got
    ev = list_events(pid, limit=20)
    prompt = build_draft_prompt(got["project"], got.get("items", []),
                               ev.get("events", []) if ev.get("ok") else [])
    try:
        text = fn(prompt)
    except Exception as e:                      # the chat surface is somebody else's code
        return _err("model_error", f"the chat surface did not answer: "
                                   f"{e.__class__.__name__}")
    if not isinstance(text, str) or not text.strip():
        return _err("model_error", "the chat surface returned nothing")
    return _ok(project_id=pid, draft=text.strip(), stored=False,
               note="this is a draft for a person to read; nothing was written")


def draft_items(pid: str, note: str, *, ask_model: Callable[[str], str] | None = None,
                n: int = MAX_DRAFT_ITEMS) -> dict:
    """Turn a rambling note into candidate item titles. Nothing is written."""
    fn = ask_model if ask_model is not None else _ASK_MODEL
    if fn is None:
        return _err("no_model", "no model is wired into this surface — "
                                "apps.project.set_ask_model() has not been called")
    if not valid_id(pid):
        return _err("not_found", "no such project")
    try:
        note = _text(note, "note", limit=MAX_TEXT, required=True)
    except Refused as e:
        return _refusal(e)
    try:
        raw = fn(BREAKDOWN_PROMPT.format(n=max(1, min(int(n), MAX_DRAFT_ITEMS)), note=note))
    except Exception as e:
        return _err("model_error", f"the chat surface did not answer: "
                                   f"{e.__class__.__name__}")
    try:
        titles = parse_item_lines(raw)
    except ModelUnusable as e:
        return _err("model_unusable", str(e))
    return _ok(project_id=pid, titles=titles, stored=False,
               note="candidates only; POST them as items if you want them")


# ------------------------------------------------------------------ the rack


def unit_state() -> tuple[str, str]:
    """(state, detail) for the rack, in the shape `asicminer.unit_state` uses.

    Read-only and cheap: `/api/status` is polled AND drives the websocket, so nothing here
    may block, take a lock or create a file. It calls `probe()`, never `connect()`.

    There is no `busy` state and that is correct rather than an omission. `busy` on this
    rack means *holding the card*; this surface never holds it, and a workspace that
    flashed `busy` while a SQL query ran would be exactly the decorative indicator
    `.claude/CLAUDE.md` forbids. There is no `queued` state either — there is nothing to
    queue behind.
    """
    if not enabled():
        return "offline", "surface disabled on this installation"
    ok, why = probe()
    if not ok:
        return "offline", why
    return "ready", "cpu only, never queues"
