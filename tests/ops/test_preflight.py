#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
# SyMoNeuRaL is a subdivision of SymonSays LLC. Licence: /LICENSE at the repository root.
"""`tools/lib/preflight.py` declares the serving dependency set. This proves the declaration.

A preflight check is only worth having if its list is true. The list is written by hand --
it has to be, because it carries the `apt` package name for each module and no import can
tell you that -- and a hand-written list of imports goes stale the first time somebody adds
one. That staleness is silent in the worst way: preflight keeps saying OK while the thing it
was meant to catch walks straight past it.

So the list is not trusted here, it is compared against measurement:
`tools/lib/serving_deps.py` imports `backend/server.py` the way the unit runs it and reports what
actually landed in `sys.modules`. If those two disagree, this test goes red and names the
difference in both directions.

The last test breaks the check on purpose. A preflight that cannot fail is decoration.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import unittest

def _repo_root() -> pathlib.Path:
    """Marker search, in the shape `symoneural-audit` does not flag.

    The first version terminated the walk with `if ROOT == ROOT.parent`, which the audit
    reads as the parent-counting pattern and counted against
    `test_path_fragility.py`'s baseline -- a false positive, but the baseline is a hard
    number and raising it to accommodate one is how a floor stops being a floor.
    """
    here = pathlib.Path(__file__).resolve()
    for cand in (here, *here.parents):
        if (cand / "backend" / "server.py").is_file():
            return cand
    raise RuntimeError("repo root not found: no backend/server.py marker above this file")


ROOT = _repo_root()

PREFLIGHT = ROOT / "tools" / "lib" / "preflight.py"
SERVING_DEPS = ROOT / "tools" / "lib" / "serving_deps.py"


def _load_preflight():
    spec = importlib.util.spec_from_file_location("_preflight_under_test", PREFLIGHT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class PreflightDeclarationMatchesMeasurement(unittest.TestCase):
    """The declared START set must equal what importing the app actually loads."""

    @classmethod
    def setUpClass(cls):
        if not PREFLIGHT.is_file():
            raise unittest.SkipTest(f"{PREFLIGHT} absent")
        cls.pf = _load_preflight()
        out = subprocess.run([sys.executable, str(SERVING_DEPS), "--json"],
                             capture_output=True, text=True, timeout=300)
        if out.returncode != 0 and not out.stdout.strip():
            raise unittest.SkipTest(f"serving_deps.py did not run: {out.stderr[-400:]}")
        cls.measured = json.loads(out.stdout)

    def test_the_probe_actually_imported_the_app(self):
        """Everything below is vacuous if the import failed."""
        self.assertTrue(self.measured["status"]["imported"],
                        f"api.py did not import: {self.measured['status']['error']}")
        self.assertGreater(len(self.measured["third_party"]), 10,
                           "the probe reported almost no dependencies; it proves nothing")

    def test_declared_start_set_equals_the_measured_load(self):
        declared = set(self.pf.START)
        measured = {m["module"] for m in self.measured["third_party"]}
        # uvicorn is deliberately not in START: `uvicorn.run` is inside the __main__ guard at
        # api.py:4137, so importing the module never loads it, but ExecStart runs it as a
        # script and needs it. It is declared in START_SCRIPT_ONLY for exactly that reason.
        self.assertNotIn("uvicorn", measured,
                         "uvicorn now loads on import -- move it from START_SCRIPT_ONLY "
                         "into START and delete this assertion")
        self.assertEqual(
            declared, measured,
            "tools/lib/preflight.py's START set has drifted from what api.py loads.\n"
            f"  declared but not loaded: {sorted(declared - measured)}\n"
            f"  loaded but not declared: {sorted(measured - declared)}\n"
            "Add the missing module WITH its Debian package name -- the package name is the "
            "only part of that table an operator can act on.")

    def test_every_declared_package_owns_the_module_it_claims(self):
        """`apt install <pkg>` must be the instruction that actually provides the module."""
        wrong = {}
        for mod in sorted({**self.pf.START, **self.pf.START_SCRIPT_ONLY}):
            pkg = {**self.pf.START, **self.pf.START_SCRIPT_ONLY}[mod]
            spec = importlib.util.find_spec(mod)
            if spec is None or not spec.origin:
                continue                    # absence is the other tests' business
            owner = subprocess.run(["dpkg", "-S", spec.origin],
                                   capture_output=True, text=True)
            if owner.returncode != 0:
                continue                    # not dpkg-owned; the manifest reports that
            if owner.stdout.split(":")[0] != pkg:
                wrong[mod] = (pkg, owner.stdout.split(":")[0])
        self.assertEqual({}, wrong,
                         "declared package does not own the module file "
                         f"(module: declared -> actual): {wrong}")


class PreflightActuallyChecks(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not PREFLIGHT.is_file():
            raise unittest.SkipTest(f"{PREFLIGHT} absent")
        cls.pf = _load_preflight()

    def test_it_passes_on_this_box(self):
        r = subprocess.run([sys.executable, str(PREFLIGHT), "--json"],
                           capture_output=True, text=True, timeout=120)
        payload = json.loads(r.stdout)
        self.assertEqual(0, payload["hard_failures"],
                         f"preflight reports hard failures on this box: {r.stdout[-800:]}")
        self.assertEqual(0, r.returncode)

    def test_an_absent_optional_surface_is_not_a_failure(self):
        """cupy is genuinely absent here. That must not fail the check."""
        r = subprocess.run([sys.executable, str(PREFLIGHT), "--json"],
                           capture_output=True, text=True, timeout=120)
        payload = json.loads(r.stdout)["findings"]
        absent = [f["module"] for f in payload["optional"] if not f["ok"]]
        self.assertIn("cupy", absent, "expected cupy absent on this box; if it is now "
                                      "installed, pick another absent optional module here")
        self.assertEqual(0, json.loads(r.stdout)["hard_failures"])

    def test_it_fails_and_names_the_package_when_a_hard_requirement_is_missing(self):
        """Break it on purpose: a check that cannot fail is decoration.

        Injecting a module name that cannot resolve is the honest way to test this -- it
        exercises the real resolution path rather than a mock of it.
        """
        script = (
            "import json,sys;"
            f"sys.path.insert(0, {str(ROOT / 'tools')!r});"
            "import importlib.util as u;"
            f"spec=u.spec_from_file_location('pf', {str(PREFLIGHT)!r});"
            "pf=u.module_from_spec(spec);spec.loader.exec_module(pf);"
            "pf.START['symoneural_not_a_real_module']='python3-symoneural-nonexistent';"
            "sys.exit(pf.main([]))"
        )
        r = subprocess.run([sys.executable, "-c", script],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(1, r.returncode,
                         "preflight exited 0 with a missing hard requirement")
        self.assertIn("PREFLIGHT FAILED", r.stdout)
        self.assertIn("python3-symoneural-nonexistent", r.stdout,
                      "the failure did not name the package to install, which is the only "
                      "thing that makes this better than an import traceback")

    def test_the_serve_class_explains_why_a_green_start_is_not_enough(self):
        """sympy's absence must be reported as a serve failure, not a start failure."""
        script = (
            "import sys;"
            "import importlib.util as u;"
            f"spec=u.spec_from_file_location('pf', {str(PREFLIGHT)!r});"
            "pf=u.module_from_spec(spec);spec.loader.exec_module(pf);"
            "pf.SERVE['symoneural_absent_calc']=('python3-nope','/api/fake','test injection');"
            "sys.exit(pf.main([]))"
        )
        r = subprocess.run([sys.executable, "-c", script],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(1, r.returncode)
        self.assertIn("WILL start", r.stdout,
                      "a missing serve-class dependency must say the service still starts")


if __name__ == "__main__":
    unittest.main()
