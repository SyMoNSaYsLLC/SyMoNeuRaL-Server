"""Legacy env-var promotion: `SYM_FOO` becomes `SYMONEURAL_FOO` at startup.

Every environment variable this repo reads was once spelled `SYM_*`. The house naming rule
is that nothing carries a bare `sym` -- only `symon`, `symonsays` or `symoneural` with an
extension -- so they are all `SYMONEURAL_*` now. That rename would break every box already
running: `/etc/symoneural/api.env` is written once by `scripts/enable-surfaces.sh` and then
edited by hand, so an upgrade cannot assume the file has been rewritten. A surface whose
`_ENABLED` variable stopped being read does not error, it silently vanishes from the rack,
and a token that stopped being read turns every request into a 401.

## Why promotion rather than a reader

The obvious alternative is a `get()` helper that tries both spellings, called at each site.
There are 771 of those sites. This module instead runs once, before anything reads the
environment, and copies each legacy name onto its new spelling inside `os.environ` -- so all
771 plain `os.environ.get("SYMONEURAL_...")` calls keep working against an old env file with
no per-site knowledge of the rename at all. The fallback becomes a property of process
startup, which is one place to reason about and one place to delete when the legacy spelling
is finally dropped.

`scripts/fetch-models.sh:90` already does this in shell for a single variable --
`"${SYMONEURAL_FETCH_27B:-${SYM_FETCH_27B:-${SYM_FETCH_QWEN36:-0}}}"`, the new name first and
two legacy spellings behind it -- and that is the same idea at one call site. This is that
idiom for the whole environment.

## What it deliberately does not do

  * **It never overwrites.** If both spellings are set, the new one wins and the legacy one
    is left alone rather than deleted, because something else in the process tree may still
    be reading it -- `subprocess` children inherit this environment.
  * **It does not touch a name that is already `SYMONEURAL_*`.** `SYM_` is a strict prefix of
    nothing else here; `SYMONEURAL_STUDIO_TOKEN` does not start with `SYM_` followed by an
    uppercase word boundary this cares about, and the explicit skip below says so rather than
    relying on that.
  * **It logs once per promoted name, at WARNING.** An operator running on legacy names has a
    working box and a deprecation notice, which is the only combination that is honest. A
    silent promotion would mean nobody ever fixes the env file.

Stdlib only, and it must stay that way: `backend/server.py` calls this above its own app
imports, which is the whole point -- `apps/studio/inference.py` reads two variables
at module scope, so a promotion that ran after the app packages were imported would be too
late for them.
"""
from __future__ import annotations

import logging
import os

__all__ = ["LEGACY_PREFIX", "PREFIX", "legacy_name", "new_name", "promote", "promoted"]

log = logging.getLogger("symoneural.env")

LEGACY_PREFIX = "SYM_"
PREFIX = "SYMONEURAL_"

# Names promoted by the last `promote()` call, newest last. Exposed so a test can assert the
# promotion happened rather than inferring it from `os.environ`, and so `GET /api/status`
# could report it later if that turns out to be worth showing.
_promoted: list[tuple[str, str]] = []


def new_name(legacy: str) -> str:
    """`SYM_STUDIO_TOKEN` -> `SYMONEURAL_STUDIO_TOKEN`."""
    return PREFIX + legacy[len(LEGACY_PREFIX):]


def legacy_name(name: str) -> str:
    """`SYMONEURAL_STUDIO_TOKEN` -> `SYM_STUDIO_TOKEN`. The inverse, for error messages."""
    return LEGACY_PREFIX + name[len(PREFIX):]


def promoted() -> list[tuple[str, str]]:
    return list(_promoted)


def promote(env: dict | None = None, warn: bool = True) -> list[tuple[str, str]]:
    """Copy every `SYM_*` name in `env` onto its `SYMONEURAL_*` spelling. Idempotent.

    `env` defaults to `os.environ` and is mutated in place; passing a dict is how the test
    exercises this without editing the interpreter's environment. Returns the (legacy, new)
    pairs it promoted, which is empty on a box whose env file has already been rewritten --
    the state this exists to make reachable.
    """
    target = os.environ if env is None else env
    pairs = []
    for key in sorted(target):
        if not key.startswith(LEGACY_PREFIX) or key.startswith(PREFIX):
            continue
        want = new_name(key)
        if want in target:
            # Both spellings set. The new one is authoritative; say so, because an operator
            # mid-migration with two different values is otherwise debugging in the dark.
            if warn and target[want] != target[key]:
                log.warning("%s and %s are both set with different values; using %s",
                            key, want, want)
            continue
        target[want] = target[key]
        pairs.append((key, want))
    if pairs:
        if warn:
            log.warning("promoted %d legacy env var(s) to the SYMONEURAL_ prefix: %s. "
                        "Rewrite them in /etc/symoneural/api.env; the SYM_ spelling is "
                        "deprecated and will stop being read.",
                        len(pairs), ", ".join(old for old, _ in pairs))
        if env is None:
            _promoted.clear()
            _promoted.extend(pairs)
    return pairs
