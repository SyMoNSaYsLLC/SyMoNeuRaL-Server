"""Make a repository-wide `pytest` collect this tree the way production imports it.

TWO problems, one file, and both were path problems rather than product defects.

1. `from apps.X import ...` -- what production actually does
------------------------------------------------------------
`backend/**` imports its siblings as `apps.something`. That works when pytest's
rootdir is `backend/`, which is what the documented invocation gives you, and it is also
exactly what the running service gets: `symoneural-api.service` is

    WorkingDirectory=/home/google/Symoneural
    ExecStart=/usr/bin/python3 /home/google/Symoneural/backend/server.py

and Python puts the *script's own directory* -- `backend/` -- at `sys.path[0]`. So `apps`
is a top-level package at runtime, by construction.

A run rooted at the repository root does not reproduce that, so `pytest` from the repo root
reported `ModuleNotFoundError: No module named 'apps'` as a collection ERROR for
`apps/controlboard`, `apps/dispatchos`, `apps/live` and `apps/streamer/guide` -- 169 tests
that pass perfectly, presented as if four modules were broken. A collection error and a
real failure look identical at a glance, which is the part that costs time.

Inserting `backend/` here fixes both invocations at once, because pytest imports the
conftest of every collected directory before the tests beneath it. It is the same fix, at
the same level, as `apps/remix/conftest.py` -- and it mirrors production rather than
inventing a test-only layout, which is the reason to prefer it over a `pythonpath` setting
in a new config file: if this line were ever wrong, the service would be wrong too.

Prepending is deliberate. `apps` is a first-party name and must not be shadowed by an
installed distribution that happens to share it.

2. `vendor/` is not ours to run
-------------------------------
`archive/vendor-sdks/` holds the vendored Anthropic and OpenAI SDKs -- 15,297 tracked files
carrying their own suites, including `e2e-tests/` that expect network access and provider
credentials. Collecting them aborted the entire first-party run at 48 errors before a
single first-party test executed, so the suite could not report on itself.

`collect_ignore_glob` makes the exclusion self-enforcing rather than an `--ignore` flag
every operator has to remember -- the same reasoning `apps/studio/plugins/reinforce/tests`
applies to cupy, where the documented exclusion had silently gone stale. Their tests are
still runnable deliberately, by pointing pytest straight at `archive/vendor-sdks/...`; what is
excluded is their appearance in *our* result.

3. The suite must not read this box's real configuration
--------------------------------------------------------
`apps/runtimeconfig.py` loads `run/config/*.env` into `os.environ` at import of `api.py`, so
that the service can be configured without a root-owned file in `/etc`. Correct in
production, and wrong in a test process for two separate reasons.

**It made the suite order-dependent.** `apps/test_symoneural_cli.py::SplashTests` asserts on
what the CLI prints when no Studio token is set. Those eleven tests pass alone and five of
them failed in a full run, because something earlier had already imported the loader and put
this box's real Studio token into the shared environment -- carried in the file under the
legacy spelling `SYM_STUDIO_TOKEN`, which `apps/symoneuralenv.py` then promotes to
`SYMONEURAL_STUDIO_TOKEN`, so both names were live by the time the splash read one. A test
that passes alone and fails in company is the worst kind: the failure names the innocent test.

**And it put real secrets in the test process.** The names loaded include
`SYMONEURAL_SESSION_SECRET` and three surface tokens. `test_symoneural_cli.py` spawns the
real CLI through a pty, and a subprocess inherits its parent's environment -- so the session
signing secret was reaching processes launched by the suite. That is a secret-hygiene defect
independent of any test outcome, and it is why the fix belongs here rather than in the one
test file that happened to notice.

Pointing `SYMONEURAL_CONFIG_DIR` at an empty directory is the whole fix: `runtimeconfig`
honours it above every other location, finds no `.env` files, and loads nothing. A test that
wants to exercise the loader sets the variable itself -- `apps/test_runtimeconfig.py` does
exactly that -- so this closes the leak without closing the door.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_BACKEND = str(Path(__file__).resolve().parent)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

# Set at import of this conftest, which pytest reads before collecting anything beneath it --
# so it is in place before any test module imports `api.py` or `runtimeconfig`. Kept alive for
# the life of the process on purpose: a TemporaryDirectory that is garbage collected would take
# the directory with it, and `runtimeconfig.config_dir()` would fall through to the real one.
_HERMETIC_CONFIG = tempfile.mkdtemp(prefix="symoneural-test-config-")
os.environ["SYMONEURAL_CONFIG_DIR"] = _HERMETIC_CONFIG

# Relative to this directory, which is what pytest resolves these against.
# vendor/ left this tree entirely on 2026-09-11 -- 15,298 third-party SDK files
# that nothing imported. There is no longer anything here to exclude.
collect_ignore_glob: list[str] = []
