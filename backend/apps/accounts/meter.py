"""The billing half of accounts: balances, holds, and a ledger.

`apps/accounts/__init__.py` knows who someone is. This knows what they have spent. The two
are one application because a charge without an identity is not a charge, and splitting them
across packages is what produced the `symoneural_accounts` / `symon_capture` / `apps.accounts`
three-way spelling in the first place.

## Reserve-then-resolve, and why it is not "charge on success"

A playlist costs SyMoN tokens. The obvious implementation charges when the job finishes, and
it is wrong: the job runs for tens of seconds against Spotify and the engine, and in that
window the same account can start twenty more. Each one checks a balance that no earlier job
has yet spent, every check passes, and the account goes negative by twenty jobs. That is a
textbook time-of-check/time-of-use hole and it costs real money.

So the balance is debited **when the hold is taken**, before the job starts, in one
transaction that both checks and deducts. Afterwards the hold is either

  * **settled** -- the work succeeded, the tokens are gone, a ledger row records it; or
  * **released** -- the work failed or was cancelled, the tokens go back.

`symoneural_dj.pipeline.run_job` calls exactly one of those in a `finally`, so a crash cannot
strand a hold silently -- and if the process dies outright, `sweep_stale()` returns anything
older than the timeout, because a reserved token that nothing will ever resolve is
indistinguishable from a stolen one from the account holder's side.

## Owners are free, and that is expressed as "no hold at all"

`hold()` returns `None` for an owner. `settle(None)` and `release(None)` are no-ops that
report zero. This is deliberate: the alternative -- a zero-amount hold row per owner action --
means the free path exercises different code from the paid path only in the *amount*, and
every future bug in hold resolution becomes a bug the owner can trigger too. A `None` hold is
the free path being visibly, structurally free. `run_job`'s docstring already documents the
contract this way ("A None hold means free (owner)"), so this matches a caller that was
written against a package that did not exist.

Integer tokens throughout. No floats anywhere near money.
"""
from __future__ import annotations

import contextlib
import os
import pathlib
import sqlite3
import time
import uuid
from typing import Any

# Holds older than this with nothing resolving them are presumed abandoned by a dead process.
# Twelve hours is far longer than any job here (a playlist is tens of seconds) -- the point is
# to be unambiguous, not prompt.
STALE_HOLD_S = 12 * 3600

OWNER_ROLES = frozenset({"owner", "admin"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS balances (
    account_id TEXT PRIMARY KEY,
    tokens     INTEGER NOT NULL DEFAULT 0 CHECK (tokens >= 0),
    updated    REAL    NOT NULL
);
CREATE TABLE IF NOT EXISTS holds (
    id         TEXT PRIMARY KEY,
    account_id TEXT    NOT NULL,
    kind       TEXT    NOT NULL,
    amount     INTEGER NOT NULL CHECK (amount >= 0),
    state      TEXT    NOT NULL CHECK (state IN ('held','settled','released')),
    created    REAL    NOT NULL,
    resolved   REAL
);
CREATE INDEX IF NOT EXISTS holds_open ON holds(state, created);
CREATE TABLE IF NOT EXISTS ledger (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT    NOT NULL,
    kind       TEXT    NOT NULL,
    amount     INTEGER NOT NULL,
    direction  TEXT    NOT NULL CHECK (direction IN ('debit','credit')),
    hold_id    TEXT,
    note       TEXT    NOT NULL DEFAULT '',
    ts         REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS ledger_account ON ledger(account_id, ts);
"""


class InsufficientFunds(Exception):
    """Not enough SyMoN tokens to take the hold.

    `symoneural_dj` turns this into a 402 Payment Required, which is the correct code and
    the reason this is its own class rather than a ValueError: the caller must be able to
    distinguish "you cannot afford this" from "you asked for something malformed", and a
    402 and a 400 are not interchangeable to a client that wants to offer a top-up.
    """

    def __init__(self, needed: int, available: int, kind: str = "") -> None:
        self.needed = int(needed)
        self.available = int(available)
        self.kind = kind
        what = f" for {kind}" if kind else ""
        super().__init__(
            f"insufficient SyMoN tokens{what}: need {self.needed}, have {self.available}")


class Meter:
    """Balances and holds in one sqlite file. One connection per operation.

    The connection policy is copied from `apps/accounts._conn` for the same reason given
    there: uvicorn runs handlers on a thread pool the moment anything touches
    `asyncio.to_thread`, and a shared sqlite3 connection across threads is either an error
    or a data race. Opening one is microseconds.
    """

    def __init__(self, db_path: str | os.PathLike) -> None:
        self.db_path = pathlib.Path(db_path)

    # -- storage ---------------------------------------------------------------------

    @contextlib.contextmanager
    def _conn(self):
        path = self.db_path
        first = not path.exists()
        if first:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        c = sqlite3.connect(str(path), timeout=10.0, isolation_level=None)
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA busy_timeout=10000")
            c.execute("PRAGMA journal_mode=WAL")
            if first:
                with contextlib.suppress(OSError):
                    os.chmod(path, 0o600)
            c.executescript(_SCHEMA)
            yield c
        finally:
            c.close()

    @contextlib.contextmanager
    def _tx(self):
        """IMMEDIATE, not DEFERRED.

        A deferred transaction takes its write lock at the first write, which is *after*
        the SELECT that read the balance -- so two concurrent holds can both read the same
        balance and both proceed. IMMEDIATE takes the lock up front and makes the
        check-and-deduct genuinely atomic. This is the line that closes the overdraft.
        """
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
            except BaseException:
                c.execute("ROLLBACK")
                raise
            c.execute("COMMIT")

    # -- balances --------------------------------------------------------------------

    def balance(self, account_id: str) -> int:
        with self._conn() as c:
            row = c.execute("SELECT tokens FROM balances WHERE account_id=?",
                            (account_id,)).fetchone()
        return int(row["tokens"]) if row else 0

    def credit(self, account_id: str, amount: int, note: str = "") -> int:
        """Add tokens. Returns the new balance."""
        amount = int(amount)
        if amount <= 0:
            raise ValueError("credit amount must be positive")
        now = time.time()
        with self._tx() as c:
            self._bump(c, account_id, amount, now)
            c.execute(
                "INSERT INTO ledger(account_id,kind,amount,direction,hold_id,note,ts)"
                " VALUES(?,?,?,'credit',NULL,?,?)",
                (account_id, "credit", amount, note, now))
            row = c.execute("SELECT tokens FROM balances WHERE account_id=?",
                            (account_id,)).fetchone()
        return int(row["tokens"])

    @staticmethod
    def _bump(c: sqlite3.Connection, account_id: str, delta: int, now: float) -> None:
        c.execute("INSERT OR IGNORE INTO balances(account_id,tokens,updated) VALUES(?,0,?)",
                  (account_id, now))
        c.execute("UPDATE balances SET tokens=tokens+?, updated=? WHERE account_id=?",
                  (delta, now, account_id))

    # -- holds -----------------------------------------------------------------------

    def hold(self, account_id: str, role: str, kind: str, amount: int) -> str | None:
        """Reserve `amount` tokens. Returns a hold id, or None when the action is free.

        Free means: an owner/admin role, or a zero cost. Raises InsufficientFunds otherwise.
        Signature matches the existing call in `symoneural_dj.app`:
        `meter.hold(ident.user_id, ident.user.role, "playlist", settings.playlist_cost)`.
        """
        amount = int(amount)
        if amount < 0:
            raise ValueError("hold amount may not be negative")
        if amount == 0 or (role or "").lower() in OWNER_ROLES:
            return None
        now = time.time()
        hold_id = uuid.uuid4().hex
        with self._tx() as c:
            row = c.execute("SELECT tokens FROM balances WHERE account_id=?",
                            (account_id,)).fetchone()
            available = int(row["tokens"]) if row else 0
            if available < amount:
                raise InsufficientFunds(amount, available, kind)
            self._bump(c, account_id, -amount, now)
            c.execute(
                "INSERT INTO holds(id,account_id,kind,amount,state,created,resolved)"
                " VALUES(?,?,?,?,'held',?,NULL)",
                (hold_id, account_id, kind, amount, now))
        return hold_id

    def settle(self, hold_id: str | None) -> dict[str, Any]:
        """Charge a hold for real. Idempotent. `None` means the action was free."""
        if hold_id is None:
            return {"charged": 0, "hold_id": None, "state": "free"}
        return self._resolve(hold_id, "settled")

    def release(self, hold_id: str | None) -> dict[str, Any]:
        """Refund a hold. Idempotent. `None` means the action was free."""
        if hold_id is None:
            return {"charged": 0, "refunded": 0, "hold_id": None, "state": "free"}
        return self._resolve(hold_id, "released")

    def _resolve(self, hold_id: str, target: str) -> dict[str, Any]:
        """The shared body of settle/release.

        Idempotency matters more than it looks: `run_job` resolves in a `finally`, and a
        retry or a double-cancel must not refund twice. An already-resolved hold reports
        what it actually did, NOT what this call asked for -- so releasing a settled hold
        answers "settled, charged N" rather than quietly inventing a refund.
        """
        now = time.time()
        with self._tx() as c:
            row = c.execute("SELECT * FROM holds WHERE id=?", (hold_id,)).fetchone()
            if row is None:
                raise KeyError(f"no such hold: {hold_id}")
            amount = int(row["amount"])
            if row["state"] != "held":
                state = row["state"]
                return {"charged": amount if state == "settled" else 0,
                        "refunded": amount if state == "released" else 0,
                        "hold_id": hold_id, "state": state, "repeated": True}
            c.execute("UPDATE holds SET state=?, resolved=? WHERE id=?",
                      (target, now, hold_id))
            if target == "released":
                self._bump(c, row["account_id"], amount, now)
                c.execute(
                    "INSERT INTO ledger(account_id,kind,amount,direction,hold_id,note,ts)"
                    " VALUES(?,?,?,'credit',?,'refund',?)",
                    (row["account_id"], row["kind"], amount, hold_id, now))
                return {"charged": 0, "refunded": amount,
                        "hold_id": hold_id, "state": "released"}
            # settled: the tokens already left the balance when the hold was taken, so
            # there is nothing to move here -- only a ledger row to write.
            c.execute(
                "INSERT INTO ledger(account_id,kind,amount,direction,hold_id,note,ts)"
                " VALUES(?,?,?,'debit',?,'settled',?)",
                (row["account_id"], row["kind"], amount, hold_id, now))
        return {"charged": amount, "refunded": 0, "hold_id": hold_id, "state": "settled"}

    # -- housekeeping ----------------------------------------------------------------

    def sweep_stale(self, older_than_s: float = STALE_HOLD_S) -> int:
        """Release holds nothing ever resolved. Returns how many were returned.

        `run_job` resolves in a `finally`, so this only fires when the process died between
        the hold and the resolve -- a SIGKILL, an OOM, a power cut. Without it those tokens
        are gone from the balance with no ledger row saying why, which from the account
        holder's side is theft with extra steps.
        """
        cutoff = time.time() - float(older_than_s)
        with self._conn() as c:
            rows = c.execute("SELECT id FROM holds WHERE state='held' AND created < ?",
                             (cutoff,)).fetchall()
        for row in rows:
            with contextlib.suppress(KeyError):
                self._resolve(row["id"], "released")
        return len(rows)

    def history(self, account_id: str, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT kind,amount,direction,note,ts FROM ledger"
                " WHERE account_id=? ORDER BY ts DESC, id DESC LIMIT ?",
                (account_id, int(limit))).fetchall()
        return [dict(r) for r in rows]
