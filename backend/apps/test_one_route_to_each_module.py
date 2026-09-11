"""One module, one name. Two routes to the same file is the SymonClient ambiguity.

Three `SymonClient` classes once resolved ambiguously because both `backend/` and
`backend/apps/` were on `sys.path`. That was diagnosed as a naming problem. It was not: it was
the general case of a second import route, and the next one will not be called `SymonClient`.

## What is actually wrong

`backend/api.py` inserts `backend/apps` into `sys.path`, so the same file is reachable twice:

    import apps.gateway   ->  via backend/        ->  sys.modules["apps.gateway"]
    import gateway        ->  via backend/apps/   ->  sys.modules["gateway"]

Python caches by NAME, so those are two module objects built from one file. Every class in
them is a distinct type: `isinstance` fails across the pair, module-level state is duplicated,
and a registry populated through one spelling is empty when read through the other.

Measured 2026-09-10, on the tree this file arrives in:

    apps.gateway  -> <module 'apps.gateway' from '.../backend/apps/gateway/__init__.py'>
    gateway       -> <module 'gateway'      from '.../backend/apps/gateway/__init__.py'>
    SAME OBJECT?  -> False

## What is NOT wrong, and why this test is shaped the way it is

**Nothing currently imports a module both ways.** Importing `api` the way production does
loads 674 modules and produces **zero** dual-identity pairs. The defect is *latent*: the second
route is open, and nothing walks through it today.

So the obvious assertion -- "no module is loaded under two names" -- **passes right now** and
would be vacuous. It would go green on a tree that still has the hazard, and stay green until
the day someone adds the import that trips it.

This asserts the property that is actually false today instead: **importing `api` must not
leave `backend/apps` on `sys.path`.** That is red on the tree this file arrives in, and green
once `backend/api.py` stops inserting it.

Note which assertion does the work. "Bare `import gateway` fails" is TRUE in a clean
interpreter before the fix as well as after -- nothing has opened the route yet -- so it is a
baseline, not a guard. The discriminating one runs `import api` first and then looks at
`sys.path`.

`backend/` itself is on `sys.path` without anyone inserting it -- Python puts a script's own
directory at `sys.path[0]`, and systemd runs `python3 /home/google/Symoneural/backend/api.py`.
So `apps.<x>` is the spelling that works under production's real invocation, and
`backend.apps.<x>` is NOT: `import backend` raises `ModuleNotFoundError` there, because
`sys.path[0]` is `backend/`, not the repository root. That spelling needs either
`python3 -m backend.api` or an installed package, and both are separate decisions.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parent
ROOT = BACKEND.parent

#: Modules under `backend/apps/` that are importable as a bare name today, and must not be.
#: `gateway` carries 30 of the 54 bare imports measured in the tree and is the one the
#: original ambiguity was found in, so it is named explicitly rather than discovered.
SECOND_ROUTE_CANARIES = ("gateway", "asicminer", "cryptominer", "project", "voice")


def _probe(code: str) -> subprocess.CompletedProcess:
    """Run `code` in a fresh interpreter with production's own sys.path[0].

    A subprocess, not an import here: pytest has already put several directories on this
    process's path, so an in-process check would be measuring the test runner rather than
    the server.
    """
    return subprocess.run([sys.executable, "-c", code], cwd=str(BACKEND),
                          capture_output=True, text=True, timeout=300)


class OneRouteToEachModule(unittest.TestCase):

    def test_the_apps_directory_is_a_package(self):
        """`apps.<x>` only works if `apps` is a real package."""
        self.assertTrue((HERE / "__init__.py").is_file(),
                        "backend/apps/__init__.py is missing, so `import apps.gateway` "
                        "depends on namespace-package behaviour rather than on a declared "
                        "package")

    def test_every_app_directory_declares_itself_a_package(self):
        missing = sorted(d.name for d in HERE.iterdir()
                         if d.is_dir() and not d.name.startswith((".", "__"))
                         and any(d.glob("*.py")) and not (d / "__init__.py").is_file())
        self.assertEqual(missing, [],
                         f"app directories with .py files but no __init__.py: {missing}. "
                         "Each is reachable only by putting its parent on sys.path, which is "
                         "the second route this file exists to close")

    def test_a_bare_app_name_does_not_resolve(self):
        """The baseline, and it is GREEN today -- stated so nobody reads it as the guard.

        A clean interpreter started in `backend/` cannot import `gateway` bare, because
        nothing has put `backend/apps` on the path yet. So this passes before the fix and
        after it, and on its own it proves nothing about the defect.

        It is kept because it pins the *other* direction: if someone ever makes
        `backend/apps` importable by default -- a `.pth` file, an install, a namespace
        package -- this goes red and says so. The discriminating assertion is
        `test_importing_api_does_not_open_a_second_route` below, which is red on the tree
        this file arrives in.
        """
        for name in SECOND_ROUTE_CANARIES:
            with self.subTest(module=name):
                r = _probe(f"import {name}")
                self.assertNotEqual(
                    r.returncode, 0,
                    f"bare `import {name}` resolved. That is the second route to "
                    f"backend/apps/{name}, and a module imported both ways becomes two "
                    "objects with two sets of class identities")
                self.assertIn("ModuleNotFoundError", r.stderr,
                              f"`import {name}` failed for some reason other than being "
                              f"absent: {r.stderr.strip()[:200]}")

    def test_the_package_spelling_does_resolve(self):
        """The other half. Closing the second route must not close the first."""
        for name in SECOND_ROUTE_CANARIES:
            with self.subTest(module=name):
                r = _probe(f"import apps.{name}")
                self.assertEqual(r.returncode, 0,
                                 f"`import apps.{name}` failed, so closing the bare route "
                                 f"would leave no route at all: {r.stderr.strip()[:300]}")

    def test_importing_api_does_not_open_a_second_route(self):
        """Regression shape: `api` must not re-open what this file closes.

        Distinct from the test above -- that one asks whether the route exists in a clean
        interpreter, this one asks whether importing the server creates it. A future
        `sys.path.insert` anywhere in the import graph fails here.
        """
        r = _probe(
            "import sys; import api;"
            "import json;"
            "bad=[p for p in sys.path if p.rstrip('/').endswith('backend/apps')];"
            "print(json.dumps(bad))")
        self.assertEqual(r.returncode, 0, f"importing api failed: {r.stderr.strip()[-400:]}")
        listed = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "[]"
        self.assertEqual(
            listed, "[]",
            "after importing api, backend/apps is on sys.path. Every module under it is then "
            "reachable by a bare name as well as by apps.<x>, which is the two-objects defect")


class TheEnvPromotionOrderingSurvives(unittest.TestCase):
    """`api.py` promotes legacy env names BEFORE any app import, and must keep doing so.

    Some modules read environment at MODULE scope, so a promotion that runs after they are
    imported is too late for them -- and the failure is a silently wrong configuration, not an
    error. Changing how modules are imported is exactly the kind of edit that can reorder this
    without anyone noticing, which is why it is pinned here rather than trusted to a comment.
    """

    def test_promote_runs_before_the_first_app_import(self):
        src = (BACKEND / "api.py").read_text()
        promote = src.index("symoneuralenv.promote()")
        # Both spellings, so this keeps working across the package conversion rather than
        # going red on a tree that is correct. `from apps import x` is the converted form;
        # the bare `import x` is what it replaced.
        candidates = []
        for m in ("asicminer", "cryptominer", "coder", "gateway", "licensing"):
            for form in (f"\nfrom apps import {m}", f"\nimport {m}"):
                if form in src:
                    candidates.append(src.index(form))
        first_app = min(candidates, default=-1)
        self.assertNotEqual(first_app, -1, "no app import found -- this guard needs rewriting")
        self.assertLess(promote, first_app,
                        "symoneuralenv.promote() now runs after the first app import. A "
                        "module that reads a legacy SYM_* name at module scope gets the "
                        "unpromoted value, and nothing raises")

    def test_runtimeconfig_loads_before_promote(self):
        src = (BACKEND / "api.py").read_text()
        self.assertLess(src.index("runtimeconfig.load()"), src.index("symoneuralenv.promote()"),
                        "config is loaded after promotion, so a legacy name arriving from "
                        "run/config/api.env is not promoted like one from the environment")


if __name__ == "__main__":
    unittest.main()
