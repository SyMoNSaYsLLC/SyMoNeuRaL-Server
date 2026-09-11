"""One mutation-authority plane for every host effect this server can perform.

## What this is for

Three surfaces can change this machine -- `apps/coder`, `apps/coders` and `apps/studio` --
and until now each decided for itself whether a caller was allowed to. Studio in particular
admits a caller once, at the surface, with `enabled() + token_ok()`; after that a request
holds 28 tools including a shell and an environment mutator. Admission is not authority. A
token that says "you may talk to Studio" is not the same claim as "you may delete this file
now, on behalf of this task, while nobody else is writing it".

This module is that second claim, made once, in one place.

## The rule that shapes everything here

**Provider identity does not grant mutation authority.** The provider is *who is speaking* --
Claude, Codex, Symon, a browser session. The authority is *what this task was authorised to
change*. They are separate fields and one is never derived from the other. A compromised or
confused provider can therefore ask for anything and still be refused, because the grant it
would need lives on the task record rather than in its own identity.

## Why a mkdir lock

Taken verbatim from `scripts/gpu-governor.sh`, which has held the GPU on this box for weeks:
the lock has to outlive the shell that took it, because the API acquires in one request
handler and releases in another. `flock` on a file descriptor dies with the process that
opened it; `mkdir` is atomic on every filesystem here and leaves a directory that survives.

The governor also supplies the staleness rule, and it is the one that matters most: a holder
that dies without releasing must not wedge the resource forever, so a lease whose pid is gone
is broken **explicitly and loudly**, never silently inherited.

## What is deliberately NOT here

No distributed consensus, no cross-host coordination, no lease renewal protocol. This is one
Debian host with one API process. A design that solved for a cluster would be more code, more
failure modes, and no more correct for the machine it actually runs on.
"""
from __future__ import annotations

import contextlib
import datetime
import errno
import json
import os
import pathlib
import secrets
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Iterator

ROOT = pathlib.Path(__file__).resolve().parents[3]

#: All authority state. Sibling of `run/gpu.lock.d`, deliberately: an operator looking for
#: "what currently owns something on this box" finds both in one place.
def state_dir() -> pathlib.Path:
    raw = os.environ.get("SYMONEURAL_AUTHORITY_DIR") or str(ROOT / "run" / "authority")
    return pathlib.Path(raw).expanduser().resolve()


def leases_dir() -> pathlib.Path:
    return state_dir() / "leases"


def journal_path() -> pathlib.Path:
    return state_dir() / "journal.log"


def tasks_path() -> pathlib.Path:
    return state_dir() / "tasks.log"


class AuthorityError(Exception):
    """Base. Every refusal below is one of these -- a caller can catch this and know the
    mutation did not happen, without matching on message text."""


class NoTask(AuthorityError):
    """A host effect was attempted with no task record at all."""


class NotAuthorised(AuthorityError):
    """A task exists but does not carry authority for this scope."""


class LeaseConflict(AuthorityError):
    """Another live owner holds this scope. Never resolved by taking it."""


class LeaseExpired(AuthorityError):
    """The lease existed and is no longer valid for this operation."""


#: Scopes are coarse on purpose. A scope per file would be unenforceable bookkeeping; these
#: are the resources whose concurrent mutation actually corrupts something.
SCOPES = ("workspace", "repository", "service", "environment", "deployment", "model-state",
          "provider")
#: `provider` is separate from `service` on purpose. `service` is this box -- systemd units,
#: a shell, anything with root's blast radius. `provider` is the operator's own logged-in
#: third-party account: spawning `claude` or `codex` spends HIS quota under HIS credentials,
#: which is a different resource, a different cost and a different thing to be accountable
#: for. Folding it into `service` would mean a task granted a shell also silently got the
#: right to spend money.


def _utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


@dataclass
class Task:
    """The authorisation record. Created once, referenced by every effect it permits.

    `provider` and `operator` are recorded for the journal and are NEVER consulted when
    deciding whether a mutation is allowed -- `mutation_authority` is. That separation is the
    module's central claim and `test_provider_identity_does_not_grant_authority` pins it.
    """
    task_id: str
    owner: str                      # the principal accountable for this task
    operator: str = ""              # the human who asked, if any
    provider: str = ""              # claude | codex | symon | browser -- informational ONLY
    role: str = ""                  # specialist role, informational
    mutation_authority: tuple[str, ...] = ()   # THE grant. Scopes this task may change.
    resource_scope: str = ""        # the scope this task is primarily about
    stop_condition: str = ""
    created: str = field(default_factory=_utc)

    def may_mutate(self, scope: str) -> bool:
        return scope in self.mutation_authority


@dataclass
class Lease:
    lease_id: str
    task_id: str
    owner: str
    scope: str
    pid: int
    acquired: str
    start_state_identity: str = ""


def _append(path: pathlib.Path, rec: dict) -> str:
    """Append one record, 0600, fsynced. Returns the record id.

    fsync matters here in a way it does not for an ordinary log: the pre-mutation journal is
    only worth writing if it survives the crash that the mutation might cause. A buffered
    write that is lost with the process defeats the entire point of writing it first.
    """
    d = path.parent
    d.mkdir(parents=True, exist_ok=True)
    line = json.dumps(rec, sort_keys=True, default=str) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line.encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    return rec["id"]


def record_task(task: Task) -> str:
    """Persist a task. Durable because an authority decision nobody can retrace later is not
    an authority decision, it is a shrug."""
    rec = {"id": task.task_id, "ts": _utc(), "kind": "task", **asdict(task)}
    return _append(tasks_path(), rec)


def journal(event: str, **detail: Any) -> str:
    jid = "j-" + secrets.token_hex(8)
    _append(journal_path(), {"id": jid, "ts": _utc(), "event": event,
                             "pid": os.getpid(), **detail})
    return jid


# ---------------------------------------------------------------- the lease

def _lock_dir(scope: str) -> pathlib.Path:
    return leases_dir() / f"{scope}.lease.d"


def _holder_file(scope: str) -> pathlib.Path:
    return _lock_dir(scope) / "holder"


def current_holder(scope: str) -> dict | None:
    """The live holder of a scope, or None. Reconciles a stale holder as a side effect.

    Reading is where staleness is noticed, because that is where somebody is about to be told
    'you cannot have this'. Telling them that on behalf of a process that died an hour ago is
    the failure this function exists to prevent.
    """
    hf = _holder_file(scope)
    try:
        rec = json.loads(hf.read_text())
    except (OSError, ValueError):
        return None
    pid = int(rec.get("pid", 0) or 0)
    if pid and not _alive(pid):
        # EXPLICIT, never silent. The governor logs this and so does this: an inherited lock
        # is indistinguishable from a lock that was never taken, and that ambiguity is how a
        # second writer gets in.
        journal("lease.stale-reconciled", scope=scope, dead_pid=pid,
                lease_id=rec.get("lease_id"), task_id=rec.get("task_id"))
        _force_release(scope)
        return None
    return rec


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True          # exists, owned by someone else
    return True


def _force_release(scope: str) -> None:
    hf = _holder_file(scope)
    with contextlib.suppress(OSError):
        hf.unlink()
    with contextlib.suppress(OSError):
        _lock_dir(scope).rmdir()


def acquire(task: Task, scope: str, *, start_state_identity: str = "") -> Lease:
    """Take exclusive authority over `scope` for `task`, or refuse. Never steals.

    Order matters and is asserted by tests: the AUTHORITY check comes before the lock. A task
    with no grant must be refused whether or not the resource happens to be free, otherwise
    the answer to 'may I?' depends on who else is busy.
    """
    if scope not in SCOPES:
        raise NotAuthorised(f"unknown scope {scope!r}")
    if not task.task_id:
        raise NoTask("no task record")
    if not task.may_mutate(scope):
        journal("lease.refused", reason="not-authorised", scope=scope,
                task_id=task.task_id, owner=task.owner, provider=task.provider)
        raise NotAuthorised(
            f"task {task.task_id} carries no mutation authority for {scope!r} "
            f"(granted: {list(task.mutation_authority)})")

    held = current_holder(scope)
    if held is not None:
        if held.get("task_id") == task.task_id and held.get("owner") == task.owner:
            # Re-entrant for the SAME task and owner. Not a steal: the same authority already
            # holds it, and refusing here would make nested controlled operations impossible.
            return Lease(**{k: held[k] for k in
                            ("lease_id", "task_id", "owner", "scope", "pid", "acquired")},
                         start_state_identity=held.get("start_state_identity", ""))
        journal("lease.refused", reason="conflict", scope=scope, task_id=task.task_id,
                owner=task.owner, held_by_task=held.get("task_id"),
                held_by_owner=held.get("owner"), held_by_pid=held.get("pid"))
        raise LeaseConflict(
            f"{scope!r} is held by task {held.get('task_id')} (owner {held.get('owner')}, "
            f"pid {held.get('pid')}); refusing to steal it")

    d = _lock_dir(scope)
    d.parent.mkdir(parents=True, exist_ok=True)
    try:
        d.mkdir()                       # atomic; the whole mutex
    except OSError as e:
        if e.errno == errno.EEXIST:
            raise LeaseConflict(f"{scope!r} became held while acquiring") from None
        raise
    lease = Lease(lease_id="l-" + secrets.token_hex(8), task_id=task.task_id,
                  owner=task.owner, scope=scope, pid=os.getpid(), acquired=_utc(),
                  start_state_identity=start_state_identity)
    _holder_file(scope).write_text(json.dumps(asdict(lease), sort_keys=True))
    os.chmod(_holder_file(scope), 0o600)
    journal("lease.acquired", **asdict(lease))
    return lease


def release(lease: Lease) -> bool:
    """Give a scope back. Only the holding lease may release it."""
    held = current_holder(lease.scope)
    if held is None:
        return False
    if held.get("lease_id") != lease.lease_id:
        # Releasing by scope alone would let any caller free somebody else's lock, which is
        # lease stealing with extra steps.
        journal("lease.release-refused", scope=lease.scope, presented=lease.lease_id,
                held=held.get("lease_id"))
        raise LeaseConflict("that lease does not hold this scope")
    _force_release(lease.scope)
    journal("lease.released", lease_id=lease.lease_id, scope=lease.scope,
            task_id=lease.task_id)
    return True


@contextlib.contextmanager
def guard(task: Task, scope: str, operation: str, *,
          start_state_identity: str = "", **detail: Any) -> Iterator[Lease]:
    """The controlled executor. Everything mutating goes through here.

        with authority.guard(task, "workspace", "delete", path=p):
            p.unlink()

    The pre-mutation journal is written BEFORE the body runs and is fsynced, so a crash
    mid-effect still leaves a record of what was about to happen and what the state was
    before it. An after-the-fact log describes only the mutations that succeeded, which is
    the opposite of what a recovery needs.
    """
    lease = acquire(task, scope, start_state_identity=start_state_identity)
    jid = journal("effect.intent", lease_id=lease.lease_id, task_id=task.task_id,
                  owner=task.owner, provider=task.provider, scope=scope,
                  operation=operation, start_state_identity=start_state_identity, **detail)
    started = time.time()
    try:
        yield lease
    except BaseException as exc:
        journal("effect.failed", journal_id=jid, lease_id=lease.lease_id,
                operation=operation, error=f"{type(exc).__name__}: {exc}"[:400],
                elapsed_s=round(time.time() - started, 3))
        raise
    else:
        journal("effect.result", journal_id=jid, lease_id=lease.lease_id,
                operation=operation, ok=True,
                elapsed_s=round(time.time() - started, 3))
    finally:
        with contextlib.suppress(AuthorityError):
            release(lease)


def require(task: Task | None, scope: str, operation: str) -> None:
    """Assert authority without taking a lease -- for call sites that check early and mutate
    later. Raises the same exceptions, so a caller cannot accidentally treat 'no task' as a
    soft warning."""
    if task is None:
        journal("effect.refused", reason="no-task", scope=scope, operation=operation)
        raise NoTask(f"{operation} on {scope!r} requires a task record")
    if not task.may_mutate(scope):
        journal("effect.refused", reason="not-authorised", scope=scope,
                operation=operation, task_id=task.task_id, provider=task.provider)
        raise NotAuthorised(f"task {task.task_id} may not mutate {scope!r}")


# ---------------------------------------------------------------- call-site binding
#
# Tool functions are called deep inside an agent loop that has no way to pass a task down
# through every frame. A ContextVar carries it instead, set once when a request is admitted
# and authorised, read by whichever effect eventually runs.
#
# IT DEFAULTS TO None, AND THAT IS THE ENFORCEMENT. A surface that has not been converted to
# establish a task gets no task, so `enforce()` refuses -- the unconverted mutating feature is
# disabled by construction rather than by somebody remembering to disable it. Converting a
# surface is what turns it back on, which is the right direction for that work to flow.
import contextvars

_CURRENT_TASK: contextvars.ContextVar[Task | None] = contextvars.ContextVar(
    "symoneural_authority_task", default=None)


def current_task() -> Task | None:
    return _CURRENT_TASK.get()


@contextlib.contextmanager
def acting_as(task: Task) -> Iterator[Task]:
    """Bind a task for the duration of a request. Restores the previous binding on exit so a
    nested call cannot leak its authority outward to the caller that admitted it."""
    token = _CURRENT_TASK.set(task)
    try:
        yield task
    finally:
        _CURRENT_TASK.reset(token)


def enforce(scope: str, operation: str) -> Task:
    """Gate one host effect. Returns the task, or raises.

    `NoTask` and `NotAuthorised` are distinct on purpose: "this surface never established a
    task" and "this task was not granted that" are different defects with different fixes,
    and collapsing them into one message sends the next person to the wrong file.
    """
    task = current_task()
    require(task, scope, operation)
    return task            # type: ignore[return-value]
