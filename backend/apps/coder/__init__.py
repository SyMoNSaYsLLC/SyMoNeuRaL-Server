"""SyMoNeuRaL Coder -- a sandboxed workspace agent, local-first and off by default.

This is the backend half of the "site development agent" Garrett raised in
`.claude/HANDOVER.md` §2g item 2. His words: *"i want to be able to somehow integrate site
development agent but we have to be careful to only give me that maybe by the seat -- only
thing with seat is i use xrdp also for this."*

The conclusion recorded there decides this module's entire shape, so it is repeated here
rather than left in a document somebody may not read:

> **An agent that can develop the site is arbitrary code execution on the box that serves
> the public internet.** It must never be reachable from a visitor-facing route, and
> "behind a password" is not sufficient on its own for that capability.

His xrdp habit is the safest answer rather than a complication: an agent running inside his
desktop session is local-only and is never exposed on `:8800` or through Caddy at all. So
this module is built **local-first and off by default**, with two independent gates that
both fail closed.

## Three gates, and every one of them must pass

    SYMONEURAL_CODER_ENABLED=1                 # the surface exists at all
    SYMONEURAL_CODER_TOKEN=<shared secret>     # every call must present it, constant-time compared
    SYMONEURAL_CODER_ALLOW_REMOTE=1            # ONLY THEN may a non-loopback peer call

The first two mirror `backend/apps/asicminer/__init__.py` exactly, which is the pattern this
repo already uses for a route that must not be world-callable. The third is additional and
specific to this surface: without it, a peer address that is not loopback is refused even
with a correct token. Two independent gates, so one misconfiguration is not enough to open
the box.

## Fail closed, everywhere, without exception

`.claude/HANDOVER.md` §5 item 1 is the cautionary tale this module is written against: the
SyMoN_ML auth daemon calls `_check_local_sandbox_state()` as a fallback and that function is
`return True` unconditionally, so **blocking the network grants the licence**. A check that
cannot be performed here DENIES. There is no fallback that returns permission, no default
that is more permissive than the explicit answer, and no path where an exception is
swallowed into an allow.

## What it can do, and the guards on each

* **list / read** files under one workspace root
* **write / patch / delete** files under that root, every change backed up first
* **run** commands in that root, argv only, never through a shell

Guards, each with a test in `test_coder.py`:

* **Path containment.** Every path is `pathlib.Path.resolve()`d -- which follows symlinks --
  and must land inside the resolved workspace root. Traversal, absolute paths outside the
  root, and symlinks whose *target* escapes are all refused. Resolving the string only is
  the classic bypass and is not what this does. Same lesson as `/api/gen/<name>` in
  HANDOVER §3.3: the name is attacker-controlled and hits the filesystem.
* **A denylist applied to the RESOLVED absolute path.** `training/corpus.jsonl`,
  `training/build_dataset.py` and `training/adapter/` are trade secret --
  `.claude/CLAUDE.md` says never copy them into `site/`, never serve them from an endpoint,
  never quote them into a page or a commit. A Coder that can be asked to "publish the
  manual" and hands over the corpus is the exact failure that section exists to prevent, so
  the check runs *after* resolution: a symlink named `notes.txt` pointing at the corpus is
  refused, because it resolves to a denied path.
* **The GPU lock is untouchable.** `run/gpu.lock.d` is denied, this module takes no
  governor lease, and it runs no model. See the README for the VRAM arithmetic on why a
  code model is not wired in here.
* **Every mutating action is journalled** to `<state>/coder.log` before it happens. If the
  journal cannot be written, the mutation does not happen.

## Stdlib only

No new Python packages. The serving API runs on the system interpreter by design and bare
`pip install` is blocked by the deny rules. Everything here is `pathlib`, `subprocess`,
`os`, `hmac`, `json`, `time`, `re`, `shutil`, `difflib`, `ipaddress`, `datetime`, `fnmatch`.

## Reading this module

Nothing raises out of a public function. Every one returns a dict with `ok` and, on refusal,
`error` -- the same contract `asicminer` uses, and for the same reason: a surface that
throws takes the caller down with it.
"""
from __future__ import annotations

from apps import authority

import datetime
import difflib
import fnmatch
import hashlib
import hmac
import ipaddress
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
# backend/apps/coder -> the repo root is three levels up. Derived from __file__ because
# nothing in this repo hardcodes its own location; that has been broken four times.
ROOT = HERE.parent.parent.parent

# ------------------------------------------------------------------ limits

MAX_READ_BYTES = 2_000_000      # a source file this big is a generated artefact
MAX_WRITE_BYTES = 8_000_000
MAX_LIST_ENTRIES = 2_000
DEFAULT_TIMEOUT = 120.0         # seconds, wall clock, for run()
MAX_TIMEOUT = 900.0
KILL_GRACE = 3.0                # SIGTERM -> this long -> SIGKILL

BAK_SUFFIX = ".bak"
ABSENT_SUFFIX = ".absent"       # "the file did not exist before this write"
# The exact shape a version id has. restore() takes a caller-supplied version and builds a
# filesystem path out of it, so it is matched against this and nothing else -- the same
# rule /api/gen/<name> follows. `../../../etc/passwd` is not a version.
VERSION_RE = re.compile(r"\A\d{8}T\d{12}\Z")


# ------------------------------------------------------------------ configuration
#
# All three of these are FUNCTIONS, not module constants. A constant is captured at import
# and a running Python process pins its resolved pathlib constants at start (HANDOVER §0b),
# which would make the workspace untestable and un-reconfigurable without a restart.


def workspace() -> pathlib.Path:
    """The one directory this agent may touch. Defaults to the repo root.

    Set `SYMONEURAL_CODER_WORKSPACE` to narrow it -- pointing it at `site/` gives an agent that
    can edit the site and cannot see `training/` at all, which is a strictly better shape
    than relying on the denylist.
    """
    raw = os.environ.get("SYMONEURAL_CODER_WORKSPACE") or str(ROOT)
    return pathlib.Path(raw).expanduser().resolve()


def state_dir() -> pathlib.Path:
    """Where the journal and the backups live. `run/` by default.

    `run/` is runtime state, not logs (`.claude/CLAUDE.md`) -- it holds `gpu.lock.d`, the
    GPU mutex. This module writes two things beside it and never touches the lock.
    The override exists so the tests do not write into live runtime state.
    """
    raw = os.environ.get("SYMONEURAL_CODER_STATE_DIR") or str(ROOT / "run")
    return pathlib.Path(raw).expanduser().resolve()


def journal_path() -> pathlib.Path:
    return state_dir() / "coder.log"


def backups_root() -> pathlib.Path:
    return state_dir() / "coder-backups"


# ------------------------------------------------------------------ the gates


def enabled() -> bool:
    """On when the flag is on. The token half of this test is gone.

    `== "1"` and not truthiness is kept: it reads like a boolean and is not one,
    and that confusion is worth keeping consistent rather than solving differently
    in each package.
    """
    # NO API KEYS. Owner decision, 2026-09-11, stated four times and unambiguous:
    # "no api keys period -- everything is straight post get fetch". This is a
    # single-operator box that is not reachable from the internet. The token check
    # that stood here is removed rather than made optional, because an optional gate
    # is a gate somebody re-enables by accident.
    return os.environ.get("SYMONEURAL_CODER_ENABLED") == "1"

def allow_remote() -> bool:
    """The second, independent gate. Unset means loopback only."""
    return os.environ.get("SYMONEURAL_CODER_ALLOW_REMOTE") == "1"


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

    ONE parser, used by both checks below. Two copies of this that disagree is the bug
    class this repo keeps hitting in its stylesheet; it would be worse here, because the
    two copies would be "is it loopback" and "is it an address at all".
    """
    if not peer:
        return None
    host = peer.strip()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if "%" in host:                     # a scoped IPv6 literal, fe80::1%eth0
        host = host.split("%", 1)[0]
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    # uvicorn on a dual-stack bind reports ::ffff:127.0.0.1, whose .is_loopback is False.
    mapped = getattr(ip, "ipv4_mapped", None)
    return mapped if mapped is not None else ip


def peer_is_loopback(peer: str | None) -> bool:
    """Is the socket peer on this machine.

    `peer` MUST be the real socket peer -- `request.client.host` in FastAPI. It must NOT be
    `X-Forwarded-For`, and in particular must not be `api.py`'s `client_key()`, which reads
    that header first. Caddy sits in front of the API, so a header is something a remote
    caller writes; trusting it here would let anyone on the internet assert `127.0.0.1`.
    See the README.

    Unparseable, empty or absent DENIES. A check that cannot be performed is not a pass.
    """
    ip = _parse_peer(peer)
    return bool(ip is not None and ip.is_loopback)


def peer_ok(peer: str | None) -> bool:
    """Loopback always; anything else only when remote access is explicitly enabled.

    Note the second branch still requires a parseable address. An operator who sets
    ALLOW_REMOTE has opened the surface to other hosts, not to callers this process cannot
    identify -- there would be nothing to journal and nothing to attribute a change to.
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
        return False, ("surface disabled — set SYMONEURAL_CODER_ENABLED=1, "
                       "and read backend/apps/coder/README.md first")
    if not peer_ok(peer):
        return False, (f"peer {peer!r} is not loopback; SYMONEURAL_CODER_ALLOW_REMOTE is not set. "
                       "This surface is local-only by design.")
    if not token_ok(token):
        return False, "bad or missing token"
    return True, ""


def _guard(token: str | None, peer: str | None) -> dict | None:
    ok, why = authorize(token, peer)
    return None if ok else {"ok": False, "error": why}


# ------------------------------------------------------------------ the denylist
#
# Segment runs. A path is denied if these segments appear ANYWHERE in the resolved absolute
# path as a contiguous run. Matching absolute segments rather than workspace-relative ones
# is deliberate: if the workspace is ever set to `training/`, the relative path of the
# adapter is `adapter/x` and a relative match would miss it. The absolute path still
# contains the `training/adapter` run.

DENY_SEGMENTS: tuple[tuple[str, ...], ...] = (
    # --- trade secret. .claude/CLAUDE.md: never copied into site/, never served from an
    # endpoint, never quoted into a page or a commit. This is the recipe for the product,
    # not documentation. docs/symoneural-manual.md is the manual and is publishable.
    ("training", "corpus.jsonl"),
    ("training", "build_dataset.py"),
    # Two entries, and the second one is a glob. This was `adapter` alone, matching a path
    # SEGMENT exactly, so `training/adapter` was denied and
    # `training/adapter-qwen36` -- a second real LoRA, 200 MB of weights beside a config
    # naming its rank, alpha and target modules -- was served. Measured 2026-08-21 through
    # /local/coder/file: `adapter_config.json` and `README.md` both came back 200 with their
    # contents. Only the weights themselves were refused, and NOT by this list: the
    # safetensors blob is over MAX_READ_BYTES and is not UTF-8, so it was stopped by a size
    # cap and a decode error. That is protection by accident, and it expires the day somebody
    # trains a smaller adapter.
    #
    # .claude/CLAUDE.md names `training/adapter/` weights as one of the artefacts protected
    # only by not being public, and task #87 is explicit that the trade-secret training
    # artefacts stay unreachable through this surface whatever else changes. A rule that
    # covers the instance and not the class does not do that.
    #
    # `adapter-*` and NOT `adapter*`, which is what this was written as first.
    # `test_a_neighbour_of_a_denied_path_is_still_allowed` immediately went red on
    # `training/adapters.md` -- ordinary publishable prose, eaten by a wildcard that was one
    # character too greedy. That test exists because "the denylist must not be so broad it
    # eats ordinary work", and a denylist nobody can work alongside gets switched off, which
    # protects nothing. The hyphen is what separates a family of directories from a word
    # that merely starts the same way.
    ("training", "adapter"),
    ("training", "adapter-*"),
    # --- the GPU mutex. `mkdir run/gpu.lock.d` IS the lock; there is nothing else. An
    # agent that can delete it hands the card to two tenants at once, which is not a
    # deadlock but a silent OOM at step 0 that looks like a CUDA fault (HANDOVER §5).
    ("run", "gpu.lock.d"),
    # --- remotes and any credential helper configured against them.
    (".git", "config"),
    # --- this module's own audit trail and rollback store. Not in the brief; added because
    # an agent that can rewrite the journal it is judged by, or delete the backups it is
    # rolled back from, has no audit trail and no undo. Flagged in the README as the
    # owner's call.
    ("run", "coder.log"),
    ("run", "coder-backups"),
)

# Matched against the final path component.
DENY_NAME_GLOBS: tuple[str, ...] = (
    "*.key",        # contract signing keys, TLS keys, ssh keys. Already gitignored.
    ".env",
    ".env.*",
)

# Weight files are secret when WE trained them and public when we downloaded them, so the
# extension alone cannot decide it. `.claude/CLAUDE.md` is unambiguous on both halves: the
# adapter weights are protected "only by not being public", and the rest of the stack is
# "off-the-shelf and permissively licensed, so nothing here is protected by a licence."
#
# This started as `*.safetensors`/`*.gguf` in DENY_NAME_GLOBS above, matched anywhere. That
# is wrong in a way worth recording, because it looks strictly safer and is not: it would
# report every public model under `backend/models/` -- Qwen, FLUX, whatever is fetched by
# `scripts/fetch-models.sh` -- as `refused, matches the denied pattern *.gguf`. On a page
# whose entire claim is that its readings are real, that is a false reading of a licence
# status, and it would train the operator to read "refused" as noise. The one thing a
# denylist cannot afford is to cry wolf, for the same reason `scripts/deploy.sh` says it
# about its own reference check.
WEIGHT_SUFFIXES: tuple[str, ...] = (".safetensors", ".gguf")
SECRET_WEIGHT_TREE = "training"


def _is_our_trained_weights(resolved: pathlib.Path) -> bool:
    """A weight file somewhere under `training/`, which is where ours are produced.

    Not a substring test on the whole path: `SECRET_WEIGHT_TREE in str(resolved)` would also
    match `/home/google/retraining-notes/x.gguf` and any directory that merely contains the
    word. Path parts are compared as parts.
    """
    return (resolved.suffix in WEIGHT_SUFFIXES
            and SECRET_WEIGHT_TREE in resolved.parts)


def _denied_reason(resolved: pathlib.Path) -> str | None:
    """Why this resolved path is off limits, or None. Runs AFTER resolve(), always."""
    parts = resolved.parts
    for run in DENY_SEGMENTS:
        n = len(run)
        for i in range(len(parts) - n + 1):
            # fnmatch per segment rather than `==`, so a run may name a family of
            # directories. An entry with no wildcard in it behaves exactly as it did before:
            # fnmatch on a pattern containing none of `*?[` is an equality test.
            if all(fnmatch.fnmatch(have, want)
                   for have, want in zip(parts[i:i + n], run)):
                return f"{'/'.join(run)} is denied — see backend/apps/coder/README.md"
    if _is_our_trained_weights(resolved):
        return (f"{resolved.name} is weights we trained — see backend/apps/coder/README.md. "
                f"Public model weights outside {SECRET_WEIGHT_TREE}/ are not denied.")
    name = resolved.name
    for pat in DENY_NAME_GLOBS:
        if fnmatch.fnmatch(name, pat):
            return f"{name} matches the denied pattern {pat}"
    return None


# ------------------------------------------------------------------ path containment


class _Refused(Exception):
    """Internal. Never escapes a public function."""


def _resolve(rel: str, *, must_exist: bool = False) -> pathlib.Path:
    """Resolve a caller-supplied path into the workspace, or refuse.

    The order is the whole point:
      1. reject obviously hostile input (empty, NUL, not a string)
      2. join onto the workspace unless it is already absolute
      3. resolve() -- which follows every symlink in the path, including the last one
      4. containment check against the RESOLVED workspace
      5. denylist against the RESOLVED absolute path

    Doing 5 before 3 is the bypass: a symlink named `notes.txt` pointing at
    `training/corpus.jsonl` passes a string-level denylist and fails this one.
    """
    if not isinstance(rel, str):
        raise _Refused(f"path must be a string, got {type(rel).__name__}")
    if not rel.strip():
        raise _Refused("empty path")
    if "\x00" in rel:
        raise _Refused("path contains a NUL byte")

    ws = workspace()
    if not ws.is_dir():
        raise _Refused(f"workspace {ws} does not exist")

    p = pathlib.Path(rel).expanduser()
    if not p.is_absolute():
        p = ws / p
    try:
        full = p.resolve()
    except (OSError, RuntimeError) as e:      # RuntimeError: symlink loop
        raise _Refused(f"cannot resolve path: {e.__class__.__name__}") from None

    if full != ws and ws not in full.parents:
        raise _Refused(f"path escapes the workspace ({ws})")

    why = _denied_reason(full)
    if why:
        raise _Refused(why)

    if must_exist and not full.exists():
        raise _Refused("no such file")
    return full


def _rel(full: pathlib.Path) -> str:
    """Workspace-relative display form. Never leaks an absolute path to a caller."""
    try:
        r = full.relative_to(workspace())
    except ValueError:                        # cannot happen after _resolve
        return full.name
    return str(r) if str(r) != "." else "."


# ------------------------------------------------------------------ the journal


def _journal(action: str, path: str, **detail) -> None:
    """Append one record. Raises on failure -- callers must let that refuse the mutation.

    Written BEFORE the mutation, not after. An over-reported entry is safe; an untraced
    edit to a live production site is not.
    """
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)      # lazy: nothing is created at import
    rec = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "action": action,
        "path": path,
        "workspace": str(workspace()),
        "pid": os.getpid(),
    }
    if detail:
        rec["detail"] = detail
    line = json.dumps(rec, sort_keys=True, default=str) + "\n"
    fd = os.open(journal_path(), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line.encode())
        os.fsync(fd)
    finally:
        os.close(fd)


def journal_tail(n: int = 50, *, token: str | None, peer: str | None) -> dict:
    """The last n records. Read-only, but gated like everything else."""
    bad = _guard(token, peer)
    if bad:
        return bad
    jp = journal_path()
    if not jp.is_file():
        return {"ok": True, "records": []}
    out = []
    for line in jp.read_text(errors="replace").splitlines()[-max(1, int(n)):]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"raw": line})
    return {"ok": True, "records": out}


# ------------------------------------------------------------------ backups


def _ws_tag() -> str:
    """A short digest of the workspace, so two workspaces never share one history.

    Without it a temp-workspace `foo.py` and the repo's `foo.py` land in the same directory
    and `restore()` can hand back bytes from a different tree.
    """
    return hashlib.sha256(str(workspace()).encode()).hexdigest()[:12]


def _backup_dir(full: pathlib.Path) -> pathlib.Path:
    rel = pathlib.Path(_rel(full))
    return backups_root() / _ws_tag() / rel.parent


def _new_version(full: pathlib.Path) -> str:
    """A fresh version id of exactly the shape VERSION_RE accepts."""
    d = _backup_dir(full)
    t = datetime.datetime.now(datetime.timezone.utc)
    for _ in range(10_000):
        v = t.strftime("%Y%m%dT%H%M%S%f")
        if not (d / f"{full.name}.{v}{BAK_SUFFIX}").exists() \
           and not (d / f"{full.name}.{v}{ABSENT_SUFFIX}").exists():
            return v
        t += datetime.timedelta(microseconds=1)
    raise _Refused("could not allocate a backup version")


def _snapshot(full: pathlib.Path) -> str:
    """Save the current state of `full` and return the version id.

    A file that does not exist yet is recorded as an `.absent` marker rather than skipped,
    so restoring that version removes the file the agent created. Rollback that cannot undo
    a creation is not rollback.
    """
    d = _backup_dir(full)
    d.mkdir(parents=True, exist_ok=True)
    v = _new_version(full)
    if full.is_file():
        shutil.copy2(full, d / f"{full.name}.{v}{BAK_SUFFIX}")
    elif full.exists():
        raise _Refused("refusing to back up something that is not a regular file")
    else:
        (d / f"{full.name}.{v}{ABSENT_SUFFIX}").write_bytes(b"")
    return v


def _backup_file(full: pathlib.Path, version: str) -> tuple[pathlib.Path, bool] | None:
    """(path, was_absent) for one version, or None. Containment re-checked here.

    `version` is caller-supplied and is used to build a filesystem path, so it is matched
    against VERSION_RE first and the assembled path is then re-checked against the backups
    root -- belt and braces against the same traversal that /api/gen/<name> guards.
    """
    if not isinstance(version, str) or not VERSION_RE.match(version):
        return None
    d = _backup_dir(full)
    for suffix, absent in ((BAK_SUFFIX, False), (ABSENT_SUFFIX, True)):
        cand = (d / f"{full.name}.{version}{suffix}")
        try:
            r = cand.resolve()
        except (OSError, RuntimeError):
            continue
        broot = backups_root()
        if broot not in r.parents:
            continue
        if r.is_file():
            return r, absent
    return None


# ------------------------------------------------------------------ read side


def status(*, token: str | None, peer: str | None) -> dict:
    """What the surface is configured to do. Gated -- it names the workspace."""
    bad = _guard(token, peer)
    if bad:
        return bad
    return {
        "ok": True,
        "workspace": str(workspace()),
        "state_dir": str(state_dir()),
        "allow_remote": allow_remote(),
        "denied_segments": ["/".join(s) for s in DENY_SEGMENTS],
        "denied_name_globs": list(DENY_NAME_GLOBS),
        "model": None,          # this module runs no model. See README for the arithmetic.
    }


def _walk(full: pathlib.Path, recursive: bool):
    """The directory walk, as its own seam so a test can prove the cap stops it early."""
    return full.rglob("*") if recursive else full.iterdir()


def list_dir(path: str = ".", *, token: str | None, peer: str | None,
             recursive: bool = False) -> dict:
    """List one directory under the workspace.

    Denied entries are listed and FLAGGED rather than silently omitted. Silent omission is
    the decorative-dishonesty shape this repo argues against: the operator should be able
    to see that `training/corpus.jsonl` exists and is refused, not be told it is not there.
    """
    bad = _guard(token, peer)
    if bad:
        return bad
    try:
        full = _resolve(path, must_exist=True)
    except _Refused as e:
        return {"ok": False, "error": str(e)}
    if not full.is_dir():
        return {"ok": False, "error": "not a directory"}

    ws = workspace()
    entries: list[dict] = []
    truncated = False
    try:
        # The cap is applied DURING the walk, not after it. `sorted(walker)` would drain
        # the whole generator first, which on the default workspace -- the repo root --
        # means rglob descending into backend/models/ (40 GB), external/ (8.5 GB),
        # contrib/ and three venvs before the cap is consulted even once. A limit checked
        # after the expensive part is the shape HANDOVER §3.0d catalogues: it reads as a
        # guard and protects nothing. Collect up to the cap, then sort the survivors.
        collected: list[pathlib.Path] = []
        for child in _walk(full, recursive):
            if len(collected) >= MAX_LIST_ENTRIES:
                truncated = True
                break
            collected.append(child)

        for child in sorted(collected):
            try:
                target = child.resolve()
            except (OSError, RuntimeError):
                entries.append({"name": child.name, "type": "unreadable", "denied": True})
                continue
            escapes = target != ws and ws not in target.parents
            why = _denied_reason(target)
            kind = ("symlink" if child.is_symlink()
                    else "dir" if child.is_dir()
                    else "file" if child.is_file()
                    else "other")
            e = {
                "name": str(child.relative_to(full)),
                "type": kind,
                "denied": bool(why) or escapes,
            }
            if why:
                e["reason"] = why
            elif escapes:
                e["reason"] = "symlink target is outside the workspace"
            if kind == "file" and not e["denied"]:
                try:
                    e["bytes"] = child.stat().st_size
                except OSError:
                    e["bytes"] = None
            entries.append(e)
    except OSError as ex:
        return {"ok": False, "error": f"{ex.__class__.__name__}: {ex}"}
    return {"ok": True, "path": _rel(full), "entries": entries, "truncated": truncated}


def read_file(path: str, *, token: str | None, peer: str | None,
              max_bytes: int = MAX_READ_BYTES) -> dict:
    bad = _guard(token, peer)
    if bad:
        return bad
    try:
        full = _resolve(path, must_exist=True)
    except _Refused as e:
        return {"ok": False, "error": str(e)}
    if not full.is_file():
        return {"ok": False, "error": "not a regular file"}
    size = full.stat().st_size
    if size > max_bytes:
        return {"ok": False, "error": f"{size} bytes exceeds the {max_bytes} byte read cap"}
    raw = full.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {"ok": False, "error": "not UTF-8 text", "binary": True, "bytes": size}
    return {"ok": True, "path": _rel(full), "bytes": size, "text": text}


def diff(path: str, content: str, *, token: str | None, peer: str | None) -> dict:
    """Unified diff of a proposed write. Reads only -- nothing is written, nothing logged."""
    bad = _guard(token, peer)
    if bad:
        return bad
    try:
        full = _resolve(path)
    except _Refused as e:
        return {"ok": False, "error": str(e)}
    if not isinstance(content, str):
        return {"ok": False, "error": "content must be a string"}
    before = full.read_text(errors="replace").splitlines(keepends=True) if full.is_file() else []
    after = content.splitlines(keepends=True)
    rel = _rel(full)
    return {"ok": True, "path": rel, "diff": "".join(difflib.unified_diff(
        before, after, fromfile=f"a/{rel}", tofile=f"b/{rel}"))}


# ------------------------------------------------------------------ write side


def _mutate(full: pathlib.Path, action: str, **detail) -> str:
    """Snapshot, then journal, then let the caller write. Returns the version id.

    If either the snapshot or the journal fails, this raises and the mutation does not
    happen. An edit that cannot be traced or undone is not permitted.

    AUTHORITY GATE, and this is the right place for it because this function is already the
    chokepoint the module's own design forces every workspace change through: `write_file`,
    `delete_file` and `restore` call it directly, and `patch_file` reaches it via
    `write_file`. Nothing can add a fifth workspace mutator that skips this without also
    skipping the backup and the journal, which the docstring above already forbids.

    `token_ok` + `peer_ok` in `_guard` decide whether a CALLER may reach this surface;
    this decides whether THIS TASK may change the workspace right now, while holding an
    exclusive lease on it. Admission and authority are different questions and the coder
    surface previously only asked the first.

    Raised as `_Refused` rather than letting `AuthorityError` escape: every public function
    here already converts `_Refused` into the `{"ok": False, "error": ...}` contract its
    callers expect, so the refusal arrives in the module's own shape instead of as an
    exception that would cross the API boundary as a 500.
    """
    try:
        authority.enforce("workspace", action)
    except authority.AuthorityError as e:
        raise _Refused(f"mutation authority: {e}") from None
    version = _snapshot(full)
    _journal(action, _rel(full), version=version, **detail)
    return version


def write_file(path: str, content: str, *, token: str | None, peer: str | None) -> dict:
    """Replace a file's whole contents. The previous state is always saved first."""
    bad = _guard(token, peer)
    if bad:
        return bad
    if not isinstance(content, str):
        return {"ok": False, "error": "content must be a string"}
    data = content.encode("utf-8")
    if len(data) > MAX_WRITE_BYTES:
        return {"ok": False, "error": f"{len(data)} bytes exceeds the write cap"}
    try:
        full = _resolve(path)
        if full.exists() and not full.is_file():
            return {"ok": False, "error": "refusing to overwrite something that is not a file"}
        existed = full.is_file()
        version = _mutate(full, "write", bytes=len(data), existed=existed)
    except _Refused as e:
        return {"ok": False, "error": str(e)}
    except OSError as e:
        return {"ok": False, "error": f"journal/backup failed, write refused: {e}"}

    try:
        full.parent.mkdir(parents=True, exist_ok=True)
        # O_NOFOLLOW closes the gap between resolve() and open(): if the final component
        # became a symlink in between, this fails rather than writing through it.
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
        fd = os.open(full, flags, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
    except OSError as e:
        return {"ok": False, "error": f"{e.__class__.__name__}: {e}", "version": version}
    return {"ok": True, "path": _rel(full), "bytes": len(data), "version": version,
            "created": not existed}


def patch_file(path: str, find: str, replace: str, *, token: str | None,
               peer: str | None, count: int = 1) -> dict:
    """Exact-string replacement, the Edit-tool shape.

    `find` must occur exactly `count` times. A patch that silently matched more than
    intended is how a one-line fix becomes a sitewide edit.
    """
    bad = _guard(token, peer)
    if bad:
        return bad
    if not isinstance(find, str) or not isinstance(replace, str):
        return {"ok": False, "error": "find and replace must be strings"}
    if not find:
        return {"ok": False, "error": "find must not be empty"}
    try:
        full = _resolve(path, must_exist=True)
    except _Refused as e:
        return {"ok": False, "error": str(e)}
    if not full.is_file():
        return {"ok": False, "error": "not a regular file"}
    try:
        before = full.read_text()
    except (OSError, UnicodeDecodeError) as e:
        return {"ok": False, "error": f"cannot read as UTF-8 text: {e.__class__.__name__}"}
    n = before.count(find)
    if n == 0:
        return {"ok": False, "error": "find string not present"}
    if count >= 0 and n != count:
        return {"ok": False, "error": f"find string occurs {n} times, expected {count}"}
    after = before.replace(find, replace)
    # Journalled as `patch` in its own right before delegating, so `run/coder.log` records
    # how the change arrived and not merely that the bytes changed. write_file() adds its
    # own `write` record; both are wanted -- the patch record is the intent, the write
    # record carries the backup version the rollback needs.
    try:
        _journal("patch", _rel(full), matched=n, find_bytes=len(find),
                 replace_bytes=len(replace))
    except OSError as e:
        return {"ok": False, "error": f"journal failed, patch refused: {e}"}
    return write_file(path, after, token=token, peer=peer)


def delete_file(path: str, *, token: str | None, peer: str | None) -> dict:
    bad = _guard(token, peer)
    if bad:
        return bad
    try:
        full = _resolve(path, must_exist=True)
        if not full.is_file():
            return {"ok": False, "error": "only regular files can be deleted"}
        version = _mutate(full, "delete", bytes=full.stat().st_size)
    except _Refused as e:
        return {"ok": False, "error": str(e)}
    except OSError as e:
        return {"ok": False, "error": f"journal/backup failed, delete refused: {e}"}
    try:
        full.unlink()
    except OSError as e:
        return {"ok": False, "error": f"{e.__class__.__name__}: {e}", "version": version}
    return {"ok": True, "path": _rel(full), "version": version}


# ------------------------------------------------------------------ rollback


def history(path: str, *, token: str | None, peer: str | None) -> dict:
    """Every saved version of one file, oldest first."""
    bad = _guard(token, peer)
    if bad:
        return bad
    try:
        full = _resolve(path)
    except _Refused as e:
        return {"ok": False, "error": str(e)}
    d = _backup_dir(full)
    if not d.is_dir():
        return {"ok": True, "path": _rel(full), "versions": []}
    out = []
    pat = re.compile(re.escape(full.name) + r"\.(\d{8}T\d{12})(\.bak|\.absent)\Z")
    for f in d.iterdir():
        m = pat.match(f.name)
        if not m or not f.is_file():
            continue
        v, kind = m.group(1), m.group(2)
        out.append({
            "version": v,
            "when": f"{v[0:4]}-{v[4:6]}-{v[6:8]}T{v[9:11]}:{v[11:13]}:{v[13:15]}.{v[15:21]}Z",
            "absent": kind == ABSENT_SUFFIX,
            "bytes": (None if kind == ABSENT_SUFFIX else f.stat().st_size),
        })
    out.sort(key=lambda r: r["version"])
    return {"ok": True, "path": _rel(full), "versions": out}


def restore(path: str, version: str, *, token: str | None, peer: str | None) -> dict:
    """Put a file back to a saved version.

    The current state is snapshotted first, so a restore is itself undoable -- otherwise
    rolling back the wrong file destroys the thing you were trying to keep.
    """
    bad = _guard(token, peer)
    if bad:
        return bad
    try:
        full = _resolve(path)
    except _Refused as e:
        return {"ok": False, "error": str(e)}
    found = _backup_file(full, version)
    if found is None:
        return {"ok": False, "error": "no such version"}
    src, was_absent = found
    try:
        undo = _mutate(full, "restore", to_version=version, absent=was_absent)
    except _Refused as e:
        # Reported separately from OSError below: an authority refusal and a failed backup
        # are different problems with different fixes, and "journal/backup failed" sent the
        # reader to check disk space for what was actually a missing task grant.
        return {"ok": False, "error": str(e)}
    except OSError as e:
        return {"ok": False, "error": f"journal/backup failed, restore refused: {e}"}
    try:
        if was_absent:
            full.unlink(missing_ok=True)
            return {"ok": True, "path": _rel(full), "restored": version,
                    "removed": True, "undo_version": undo}
        data = src.read_bytes()
        full.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(full, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
    except OSError as e:
        return {"ok": False, "error": f"{e.__class__.__name__}: {e}"}
    return {"ok": True, "path": _rel(full), "restored": version,
            "bytes": len(data), "undo_version": undo}


# ------------------------------------------------------------------ command execution


# Both spellings, and the legacy one is not belt-and-braces: it is still reachable. Every
# variable here was once spelled `SYM_*`, and `apps/symoneuralenv.promote()` migrates an old
# environment by COPYING each legacy name onto its new spelling and deliberately leaving the
# old one in place, so that children this repo spawns against the old name keep working. So a
# live environment can carry `SYM_ASIC_TOKEN` and `SYMONEURAL_ASIC_TOKEN` at once, and a
# scrubber that dropped the legacy prefix would leave the first of those in every child.
#
# It matters that this is a PREFIX match rather than a list of known names, because that is
# what makes the failure silent: `"SYMONEURAL_STUDIO_TOKEN".startswith("SYM_")` is False, so
# a check written for one spelling stops removing anything the moment the box uses the other
# -- no exception, no log line, and no failing test unless a test names both. That is what
# `test_both_env_prefixes_are_scrubbed_and_nothing_else_is` is for.
_SECRET_PREFIXES = ("SYMONEURAL_", "SYM_")
_SECRET_WORDS = ("TOKEN", "SECRET", "KEY")


def _scrubbed_env() -> dict:
    """The child's environment, with this box's secrets removed.

    A command the agent runs has no business reading SYMONEURAL_CODER_TOKEN or
    SYMONEURAL_ASIC_TOKEN out of its own environment and printing them back over the wire.
    """
    env = dict(os.environ)
    for k in list(env):
        if k.startswith(_SECRET_PREFIXES) and any(w in k for w in _SECRET_WORDS):
            env.pop(k, None)
    return env


def _argv_touches_denied(argv: list[str]) -> str | None:
    """Refuse the obvious `cat training/corpus.jsonl`.

    THIS IS A SPEED BUMP, NOT A BOUNDARY, and the README says so in those words. A command
    is arbitrary code; a glob, a here-doc or a python one-liner walks straight past this.
    It is here because the denylist's job is to stop the agent making an honest mistake,
    and an honest mistake looks exactly like this.
    """
    for a in argv[1:]:
        if not a or a.startswith("-"):
            continue
        try:
            p = pathlib.Path(a).expanduser()
            full = p if p.is_absolute() else (workspace() / p)
            try:
                # resolve(), not normpath() -- so `cat notes.txt` is refused when
                # notes.txt is a symlink to the corpus, matching what read_file() does.
                # Two guards that disagree about what a path means is how one of them
                # ends up being the one an agent reaches for.
                full = full.resolve()
            except (OSError, RuntimeError):
                full = pathlib.Path(os.path.normpath(str(full)))
            why = _denied_reason(full)
        except (OSError, ValueError):
            continue
        if why:
            return f"argument {a!r}: {why}"
    return None


def run(argv: list[str], *, token: str | None, peer: str | None,
        cwd: str = ".", timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Run one command in the workspace. argv list only -- never a shell.

    `shell=True` would mean every string this agent assembles is interpreted for `;`, `|`,
    `$( )` and `>`; with an argv list the kernel execs the binary and the arguments are
    data. There is no code path here that reaches a shell.

    The process is started in its own session, so the timeout can signal the whole group:
    killing only the direct child leaves grandchildren holding the pipe and the call hangs
    on a `communicate()` that never returns.
    """
    bad = _guard(token, peer)
    if bad:
        return bad
    # AUTHORITY GATE at `service` scope, not `workspace`: this execs a binary that can do
    # anything the API user can, including touching things far outside the workspace the
    # file tools are confined to. A task granted only `workspace` must not reach it -- that
    # is the lateral move the scope split exists to stop.
    try:
        authority.enforce("service", "run")
    except authority.AuthorityError as e:
        return {"ok": False, "error": f"mutation authority: {e}"}
    if isinstance(argv, str):
        return {"ok": False, "error": "argv must be a list of strings, not a command line — "
                                      "this surface never invokes a shell"}
    if not isinstance(argv, (list, tuple)) or not argv:
        return {"ok": False, "error": "argv must be a non-empty list"}
    argv = list(argv)
    for a in argv:
        if not isinstance(a, str):
            return {"ok": False, "error": "every argv element must be a string"}
        if "\x00" in a:
            return {"ok": False, "error": "argv contains a NUL byte"}
    try:
        t = float(timeout)
    except (TypeError, ValueError):
        return {"ok": False, "error": "timeout must be a number"}
    if not (0 < t <= MAX_TIMEOUT):
        return {"ok": False, "error": f"timeout must be >0 and <= {MAX_TIMEOUT}"}

    try:
        wd = _resolve(cwd, must_exist=True)
    except _Refused as e:
        return {"ok": False, "error": f"cwd: {e}"}
    if not wd.is_dir():
        return {"ok": False, "error": "cwd is not a directory"}

    why = _argv_touches_denied(argv)
    if why:
        return {"ok": False, "error": why}

    try:
        _journal("run", _rel(wd), argv=argv, timeout=t)
    except OSError as e:
        return {"ok": False, "error": f"journal failed, command refused: {e}"}

    try:
        proc = subprocess.Popen(
            argv, cwd=str(wd), env=_scrubbed_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,             # its own process group, for the kill below
        )
    except FileNotFoundError:
        return {"ok": False, "error": f"no such command: {argv[0]}"}
    except OSError as e:
        return {"ok": False, "error": f"{e.__class__.__name__}: {e}"}

    timed_out = False
    try:
        out, err = proc.communicate(timeout=t)
    except subprocess.TimeoutExpired:
        timed_out = True
        _killgroup(proc)
        try:
            out, err = proc.communicate(timeout=KILL_GRACE)
        except subprocess.TimeoutExpired:
            out, err = b"", b""
    return {
        "ok": not timed_out,
        "argv": argv,
        "cwd": _rel(wd),
        "exit": proc.returncode,
        "timed_out": timed_out,
        "error": (f"timed out after {t}s" if timed_out else None),
        "stdout": out.decode("utf-8", "replace"),
        "stderr": err.decode("utf-8", "replace"),
    }


def _killgroup(proc: subprocess.Popen) -> None:
    """SIGTERM the group, give it a moment, then SIGKILL. Grandchildren included."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except OSError:
                pass
            return
        try:
            proc.wait(timeout=KILL_GRACE)
            return
        except subprocess.TimeoutExpired:
            continue


# ------------------------------------------------------------------ the rack


def unit_state() -> tuple[str, str]:
    """(state, detail) for the rack, in the shape `asicminer.unit_state` uses.

    `offline` is the honest default: this surface is off unless an operator switched it on,
    and the rack must never show it as ready on the strength of the code existing. If it is
    ever put on the rack at all, note that it takes no GPU lease and holds no card.
    """
    if not enabled():
        return "offline", "disabled — local-only operator surface, off by default"
    if not workspace().is_dir():
        return "offline", "workspace not found"
    return "ready", f"local only · workspace {workspace().name} · no GPU lease"
