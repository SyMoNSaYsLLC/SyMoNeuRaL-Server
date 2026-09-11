"""`AccountsModule` -- the per-instance facade the application surfaces bind to.

`apps/accounts/__init__.py` is a module of functions against one process-wide database,
which is right for the API's own account routes: there is one accounts database and
`api.py` mounts one router. It is wrong for a *second* surface -- `symoneural_dj` runs its
own process, on its own port, against its own db path, and needs an object it can hold.

This is that object. It does not reimplement anything: identity, hashing, throttling and
sessions all delegate to the module-level functions, with the database bound per instance by
`using_db()`. The only genuinely new behaviour is money, and that lives in `meter.py`.

    accounts = AccountsModule(settings.accounts_db, owner_env_token=settings.dj_token)
    ident = accounts.identify(cookie=..., bearer=...)
    hold  = accounts.meter.hold(ident.user_id, ident.user.role, "playlist", 1)

## The owner token is break-glass, and is compared in constant time

`owner_env_token` is `DJ_TOKEN` -- a single high-privilege bearer from the environment, the
same fail-safe shape as the engine's `VLLM_API_KEY`. With it unset the app serves loopback
peers only. It is compared with `hmac.compare_digest`, never `==`: an early-exit comparison
on a secret is a timing oracle, and this one grants owner.

The token's VALUE is never logged, never included in an error, and never returned by any
method here. Only whether it matched.

## Sessions degrade rather than fail the process

`_secret()` raises `AccountsUnavailable` when `SYMONEURAL_SESSION_SECRET` is unset, by
design -- there is no generated fallback, because a per-process secret logs every user out on
restart and a hardcoded one is forgeable. `identify()` therefore treats an unavailable
session subsystem as "no cookie identity", not as a crash: a box configured with only
`DJ_TOKEN` gets a working owner path and no member logins, which is exactly what it asked
for. What it must never do is treat an unverifiable cookie as valid.
"""
from __future__ import annotations

import dataclasses
import hmac
import os
import pathlib

from . import (
    AccountsUnavailable,
    PUBLIC_FIELDS,
    _conn,
    account_public,
    read_session,
    using_db,
)
from .meter import OWNER_ROLES, InsufficientFunds, Meter

__all__ = ["AccountsModule", "Identity", "User", "InsufficientFunds", "SESSION_COOKIE"]

# One spelling of the cookie name. `routes.py` imports it from here rather than keeping a
# second copy -- two constants that must agree is one constant that eventually will not.
SESSION_COOKIE = "sym_session"

# The synthetic account id the break-glass owner acts as. It is not a row in `accounts`:
# the owner token is an environment credential, not a signup, and minting a real account
# for it would put a password hash column on something that has no password.
OWNER_ACCOUNT_ID = "owner"


@dataclasses.dataclass(frozen=True)
class User:
    """Who someone is. `role` is what the meter charges against."""

    id: str
    email: str = ""
    display_name: str = ""
    role: str = "member"
    disabled: bool = False

    @classmethod
    def from_public(cls, row: dict, role: str = "member") -> "User":
        return cls(
            id=str(row.get("id", "")),
            email=str(row.get("email", "")),
            display_name=str(row.get("display_name") or ""),
            role=role,
            disabled=bool(row.get("disabled")),
        )


@dataclasses.dataclass(frozen=True)
class Identity:
    """A resolved caller: the user, and how they proved it.

    `via` is kept because "owner by environment token" and "owner by session cookie" are
    the same authority arrived at very differently, and an audit line that cannot tell them
    apart cannot answer the only question worth asking after an incident.
    """

    user: User
    via: str = "session"

    @property
    def user_id(self) -> str:
        return self.user.id

    @property
    def is_owner(self) -> bool:
        return (self.user.role or "").lower() in OWNER_ROLES


class _AccountsFacade:
    """The identity half, bound to one database. `module.accounts.listing()`."""

    def __init__(self, owner: "AccountsModule") -> None:
        self._owner = owner

    def listing(self, limit: int = 500) -> list[dict]:
        """Every account, public fields only -- no hash, no salt, no session token.

        `symoneural_dj` calls this to answer "is anybody signed up at all?", which is what
        gates its loopback-only development path. Returning full rows for that question
        would put password material in the hands of a caller that wanted a count.
        """
        cols = ",".join(PUBLIC_FIELDS)
        with self._owner.bind(), _conn() as c:
            rows = c.execute(
                f"SELECT {cols} FROM accounts ORDER BY created ASC LIMIT ?",
                (int(limit),)).fetchall()
        return [dict(r) for r in rows]

    def count(self) -> int:
        with self._owner.bind(), _conn() as c:
            return int(c.execute("SELECT COUNT(*) AS n FROM accounts").fetchone()["n"])

    def public(self, account_id: str) -> dict | None:
        with self._owner.bind():
            return account_public(account_id)


class AccountsModule:
    """Accounts + billing for one surface, against one database file."""

    def __init__(
        self,
        db_path: str | os.PathLike,
        owner_env_token: str = "",
        *,
        owner_account_id: str = OWNER_ACCOUNT_ID,
        app_name: str = "",
    ) -> None:
        self.db_path = pathlib.Path(db_path)
        self.app_name = app_name
        self._owner_token = str(owner_env_token or "")
        self._owner_account_id = owner_account_id
        self.meter = Meter(self.db_path)
        self.accounts = _AccountsFacade(self)

    # -- database binding --------------------------------------------------------------

    def bind(self):
        """Point the module-level functions at THIS instance's database.

        Public because `routes.build_router` needs it: the router delegates signup and
        login to the module-level functions, and those read `db_path()`.
        """
        return using_db(self.db_path)

    # -- identity ----------------------------------------------------------------------

    def cookie_name(self) -> str:
        return SESSION_COOKIE

    def owner_identity(self) -> Identity:
        return Identity(
            user=User(id=self._owner_account_id, display_name="owner", role="owner"),
            via="owner-token")

    def has_owner_token(self) -> bool:
        """Whether a break-glass token is configured. Never reveals the token."""
        return bool(self._owner_token)

    def _is_owner_token(self, presented: str) -> bool:
        if not self._owner_token or not presented:
            return False
        return hmac.compare_digest(self._owner_token, presented)

    def identify(self, cookie: str = "", bearer: str = "") -> Identity | None:
        """Resolve a caller, or None.

        Order is deliberate. The owner environment token is checked first and costs one
        constant-time compare with no database work at all, so the break-glass path keeps
        working when the accounts database is missing, unreadable or empty -- which is
        precisely the situation break-glass exists for.
        """
        if self._is_owner_token(bearer):
            return self.owner_identity()
        for token, via in ((bearer, "bearer"), (cookie, "cookie")):
            if not token:
                continue
            ident = self._from_session(token, via)
            if ident is not None:
                return ident
        return None

    def _from_session(self, token: str, via: str) -> Identity | None:
        try:
            with self.bind():
                session = read_session(token)
        except AccountsUnavailable:
            # No session secret configured. An unverifiable cookie is not an identity.
            return None
        if not session:
            return None
        account = session.get("account") or {}
        if not account or account.get("disabled"):
            return None
        return Identity(user=User.from_public(account, role=self._role_for(account)),
                        via=via)

    def _role_for(self, account: dict) -> str:
        """Roles are not a column in the accounts schema, so they are derived.

        Today that means: the account id designated as owner is the owner, everyone else is
        a member. This is written as one method rather than inline in three places because
        it is the obvious next thing to grow a real column, and when it does there is one
        line to change.
        """
        if str(account.get("id", "")) == self._owner_account_id:
            return "owner"
        return "member"

    # -- convenience -------------------------------------------------------------------

    def balance(self, identity: Identity) -> int | None:
        """An owner has no balance -- not a zero balance. None says so."""
        if identity.is_owner:
            return None
        return self.meter.balance(identity.user_id)
