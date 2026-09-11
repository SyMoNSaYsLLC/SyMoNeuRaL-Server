"""Where SyMoNeuRaL Studio thinks it is.

Every tool in this package that touches the disk resolves paths through here, so there is
exactly one answer to "what is the project" and it is derived rather than typed. The brief
asked for the agent to "pick a project folder that makes most sense as default on startup";
this is that decision, made once, at import, and published on `/api/studio/state` so the UI
shows the operator the real path instead of a guess.

## How the root is found

Three strategies, in order, first hit wins:

1. `SYMONEURAL_STUDIO_ROOT` if it is set and passes the signature test. An explicit override always
   beats a search.
2. Walk up from this file. The package lives at `<root>/backend/studio/`, so
   the root is three parents up -- but the walk is written as a loop rather than
   `parents[2]` so that moving the package one level does not silently resolve to `/home`.
3. Scan `~` one level deep for a directory that passes the signature test, preferring the
   names the operator actually uses (`Symoneural`, `SyMoNeuRaLAIServer`).

## The signature

    scripts/gpu-governor.sh   AND   backend/server.py

Both, not either. This is deliberately the *same* pair that `backend/server.py` asserts on its
own third line and that `scripts/gpu-governor.sh` checks before it will take a lock -- if
those two files are present this is the live stack, and if the assertion in `api.py` ever
changes shape this will fail in the same direction rather than quietly disagreeing about
which directory is the project.

A `Path.home()` fallback is *not* provided. A tool server that silently decides the project
is `/home/google` would let `write_file("README.md", ...)` land somewhere nobody looks. When
the signature is not found anywhere, `ROOT` is None and every disk tool says so.
"""
from __future__ import annotations

import functools
import os
import pathlib

__all__ = ["ROOT", "root", "found_by", "describe", "resolve", "COMFYUI", "RUN", "SITE",
           "APPS", "MODELS"]

SIGNATURE = ("scripts/gpu-governor.sh", "backend/server.py")

# Names worth preferring during the home-directory scan. Not a filter -- any directory
# carrying the signature is accepted -- just an ordering, so a checkout and a backup copy
# resolve deterministically instead of by readdir order.
PREFERRED = ("Symoneural", "SyMoNeuRaLAIServer", "symoneural")


def _is_stack(p: pathlib.Path) -> bool:
    """Both signature files present and readable. Symlinks are resolved by the caller."""
    try:
        return all((p / rel).is_file() for rel in SIGNATURE)
    except OSError:
        # An unreadable directory is not the stack for our purposes; a permission error
        # here should not take down import of the whole package.
        return False


def _from_env() -> pathlib.Path | None:
    raw = os.environ.get("SYMONEURAL_STUDIO_ROOT")
    if not raw:
        return None
    p = pathlib.Path(raw).expanduser()
    try:
        p = p.resolve()
    except OSError:
        return None
    return p if _is_stack(p) else None


def _from_walk() -> pathlib.Path | None:
    """Up from this file until the signature appears. Bounded by the filesystem root."""
    here = pathlib.Path(__file__).resolve()
    for candidate in here.parents:
        if _is_stack(candidate):
            return candidate
    return None


def _from_home() -> pathlib.Path | None:
    home = pathlib.Path.home()
    try:
        entries = [d for d in home.iterdir() if d.is_dir()]
    except OSError:
        return None

    def rank(d: pathlib.Path) -> tuple[int, str]:
        try:
            return (PREFERRED.index(d.name), d.name)
        except ValueError:
            return (len(PREFERRED), d.name)

    for d in sorted(entries, key=rank):
        if _is_stack(d):
            return d.resolve()
    return None


@functools.lru_cache(maxsize=1)
def _discover() -> tuple[pathlib.Path | None, str]:
    for label, fn in (("env", _from_env), ("walk", _from_walk), ("home-scan", _from_home)):
        hit = fn()
        if hit is not None:
            return hit, label
    return None, "not-found"


ROOT, FOUND_BY = _discover()


def root() -> pathlib.Path:
    """The project root, or a RuntimeError naming the override. Callers that can degrade
    should read `ROOT` and check for None instead of calling this."""
    if ROOT is None:
        raise RuntimeError(
            "no SyMoNeuRaL stack found: looked for "
            f"{' + '.join(SIGNATURE)} via $SYMONEURAL_STUDIO_ROOT, the parents of {__file__}, and "
            f"one level under {pathlib.Path.home()}. Set SYMONEURAL_STUDIO_ROOT to the checkout.")
    return ROOT


def found_by() -> str:
    return FOUND_BY


# Derived locations. Computed once so a tool never re-runs the search, and left as plain
# Paths (not asserted to exist) because several of them are generated artefacts -- `site/`
# does not exist in a fresh checkout and `run/` is created by the governor on first use.
def _sub(*parts: str) -> pathlib.Path | None:
    return ROOT.joinpath(*parts) if ROOT is not None else None


COMFYUI = _sub("ComfyUI")
RUN = _sub("run")
SITE = _sub("site")
APPS = _sub("backend", "apps")
MODELS = _sub("backend", "models")


def resolve(path: str) -> pathlib.Path:
    """Interpret a tool argument as a filesystem path.

    Relative paths are taken against the project root, which is what makes `read_file("backend/server.py")`
    mean the same thing from any working directory. Absolute paths are honoured as given --
    the operator asked for host-wide access and `/etc/systemd/system/symoneural-api.service`
    is a legitimate target for a tool whose job is configuring services. `~` expands.

    No containment check is implemented here as of 2026-08-20 -- a deliberate pre-launch state,
    not a cleared posture (request ledger R-98, held). The guard on this surface today is the
    two-switch token gate in `__init__.py`, not a path allow-list here.
    """
    p = pathlib.Path(path).expanduser()
    if not p.is_absolute():
        if ROOT is None:
            raise RuntimeError(f"cannot resolve relative path {path!r}: no project root found")
        p = ROOT / p
    return p


def describe() -> dict:
    """What `/api/studio/state` publishes about the workspace."""
    return {
        "root": str(ROOT) if ROOT else None,
        "found_by": FOUND_BY,
        "signature": list(SIGNATURE),
        "comfyui": str(COMFYUI) if COMFYUI and COMFYUI.is_dir() else None,
        "override_env": "SYMONEURAL_STUDIO_ROOT",
    }
