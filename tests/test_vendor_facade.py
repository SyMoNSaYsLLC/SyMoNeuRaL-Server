"""Task #74 item 5: no shipped module names a third-party package directly.

The rule, in the task's own words: *"imports go through our own module so the vendor name
appears in exactly one file per dependency and the swap is a one-file change later."*
`backend/DEPENDENCIES.md` argues it per package and returns a verdict of **Facade** for
`sympy`, `httpx` and `fastmcp`, and **Keep** for everything else.

**Why this file exists when #74 already declares nine `ngrep` checks for the same thing.**
An `ngrep` names a path. It can only ever say "this particular file no longer imports
httpx", so it goes green the moment the seven files listed on the task are repointed and
it stays green forever afterwards -- including for the eighth file somebody adds next
week. That is the failure this repo has recorded five times on this task alone: *a check
that can pass without the work being finished is worse than no check, since it will
archive the task.* This walks the tree instead, so the rule outlives the file list.

**And the second class of test here is the one the repo is currently bleeding from.**
A facade is only a facade if every name its consumers reach for is actually on it.
`apps/ravencalc/symbolic.py` does not re-export `convert_xor`, `ravencalc.py:89` reaches
for it anyway, and `apps/ravencalc` has collected **zero tests since `49185b8`** as a
result -- `NameError` at import, which is a collection abort, which is no reading at all
rather than a smaller one. `TheFacadeSurfaceIsCompleteTests` reads every `<facade>.<name>`
the consumers actually use and asserts the attribute resolves, so an incomplete
re-export is a red line here instead of a silent zero somewhere else.
"""
from __future__ import annotations

import ast
import importlib
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
APPS = REPO / "backend" / "apps"

#: package root -> (vendor module, the one file allowed to import it)
FACADES = {
    "studio": [
        ("httpx", APPS / "studio" / "httpclient.py"),
        ("fastmcp", APPS / "studio" / "mcpframework.py"),
    ],
    "remix": [
        ("httpx", APPS / "remix" / "symoneural_dj" / "httpclient.py"),
    ],
    "ravencalc": [
        ("sympy", APPS / "ravencalc" / "symbolic.py"),
    ],
}

#: Named exemptions, each with the reason it is not simply a violation.
#:
#: `ravencalc.py`'s parser import is real outstanding work, not a decision: the file says
#: so itself ("Keep the parser direct until we wrap it"). It is listed rather than ignored
#: so that the debt is enumerated in one place a reader can count, and so that adding a
#: *new* direct import anywhere still goes red. Do not add to this dict to make a run
#: green -- that is the third state this repo rejects, wearing a test's clothing.
EXEMPT = {
    (APPS / "ravencalc" / "ravencalc.py").resolve(): {
        "sympy": "the transformation parser is not wrapped by symbolic.py yet",
    },
}

#: Test code is deliberately out of scope. DEPENDENCIES.md returns **Keep** for test-only
#: httpx in as many words, and the reason is not laziness: `apps/remix/tests/conftest.py`
#: builds an `AsyncClient(transport=MockTransport(...))` and injects it into the connector
#: under test. The facade re-exports rather than wraps, so that object is the same object
#: either way -- and a test that could not name the transport it is installing would have
#: to grow a second facade of its own to say the same thing.
def _is_test(path: pathlib.Path) -> bool:
    return path.name.startswith("test_") or "tests" in path.parts


#: `plugins/reinforce` is excluded from the pytest run itself (it imports cupy, which is
#: not on the serving interpreter), and `custom_nodes` is a plugin loaded by the render
#: engine on its own terms rather than by us.
SKIP_DIRS = {".venv", "__pycache__", "plugins", "custom_nodes", "node_modules"}


def _shipped_modules(package: str) -> list[pathlib.Path]:
    root = APPS / package
    out = []
    for path in root.rglob("*.py"):
        if SKIP_DIRS & set(path.parts) or _is_test(path):
            continue
        out.append(path)
    return sorted(out)


def _imported_vendors(source: str) -> set[str]:
    """Top-level package name of every import in `source`, by AST rather than by grep.

    Reading the syntax tree rather than the text is what makes `# httpx recomputes it`
    in a comment not a violation, and `import httpx as _h` still one -- which matters,
    because the alias form is exactly how somebody satisfies an `ngrep` without doing
    the work.
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


class OnlyTheFacadeNamesTheVendorTests(unittest.TestCase):
    """One vendor, one file, per package -- asserted over the tree, not over a file list."""

    def test_no_shipped_module_imports_the_vendor_directly(self):
        violations = []
        for package, entries in FACADES.items():
            for vendor, facade in entries:
                for path in _shipped_modules(package):
                    if path.resolve() == facade.resolve():
                        continue
                    if vendor in EXEMPT.get(path.resolve(), {}):
                        continue
                    if vendor in _imported_vendors(path.read_text()):
                        violations.append(
                            f"{path.relative_to(REPO)} imports {vendor} directly; "
                            f"import {facade.relative_to(REPO)} instead")
        self.assertEqual(violations, [], "\n" + "\n".join(violations))

    def test_every_facade_exists_and_does_import_its_vendor(self):
        """The mirror image, and not redundant.

        A facade that stopped importing its vendor would satisfy the test above
        perfectly -- there would simply be no direct import anywhere, and no working
        client either. Deleting the file is the cheapest way to make the rule pass and
        the most expensive way to be wrong.
        """
        for package, entries in FACADES.items():
            for vendor, facade in entries:
                with self.subTest(package=package, vendor=vendor):
                    self.assertTrue(facade.exists(), f"{facade} is missing")
                    self.assertIn(vendor, _imported_vendors(facade.read_text()),
                                  f"{facade.name} no longer imports {vendor}")

    def test_the_scan_would_actually_catch_the_thing_it_is_for(self):
        """Proves the AST walk, including the two forms that defeat a grep.

        `ngrep import httpx` is satisfied by `import httpx as _h` and by
        `from httpx import AsyncClient`. Both are still the vendor named in an
        application module, and both are what somebody reaches for at 2am.
        """
        for source in ("import httpx",
                       "import httpx as _h",
                       "from httpx import AsyncClient",
                       "import os, httpx",
                       "from httpx._client import AsyncClient"):
            with self.subTest(source=source):
                self.assertIn("httpx", _imported_vendors(source))
        for source in ("# httpx recomputes content-length",
                       "from . import httpclient",
                       "'httpx'",
                       "from .. import httpclient"):
            with self.subTest(source=source):
                self.assertNotIn("httpx", _imported_vendors(source))

    def test_the_exemptions_are_real_files_and_really_still_violating(self):
        """An exemption that no longer applies is a rule quietly switched off.

        When `symbolic.py` finally wraps the parser, this goes red and the entry comes
        out -- which is the only mechanism that stops `EXEMPT` growing into the place
        violations go to be forgotten.
        """
        for path, vendors in EXEMPT.items():
            with self.subTest(path=path.name):
                self.assertTrue(path.exists(), f"{path} is exempted and does not exist")
                imported = _imported_vendors(path.read_text())
                for vendor, reason in vendors.items():
                    self.assertIn(
                        vendor, imported,
                        f"{path.name} no longer imports {vendor} ({reason}) -- "
                        f"remove it from EXEMPT")


class TheFacadeSurfaceIsCompleteTests(unittest.TestCase):
    """Every `<facade>.<name>` a consumer reaches for must resolve on the facade.

    This is the `convert_xor` test, generalised. `symbolic.py` re-exports most of sympy's
    surface and not that one name; `ravencalc.py:89` uses it at module scope; the package
    therefore raises `NameError` at *import*, and `apps/ravencalc` has collected nothing
    since `49185b8`. A facade fails whole, not partially, and it fails at the point of
    import -- which is why it presents as a collection abort somewhere unrelated rather
    than as a failing test where the bug is.
    """

    #: import path -> the alias consumers bind it to
    IMPORTED = [
        ("studio.httpclient", "httpclient", "studio",
         APPS / "studio" / "httpclient.py"),
        ("symoneural_dj.httpclient", "httpclient", "remix",
         APPS / "remix" / "symoneural_dj" / "httpclient.py"),
    ]

    def _attributes_used(self, package: str, alias: str,
                         facade: pathlib.Path) -> dict[str, set[str]]:
        r"""Every `alias.<name>` in the package, read off the syntax tree.

        **This was a regex and the regex was wrong on the first run**, which is worth
        keeping in the file rather than in a commit message: `httpclient\.(\w+)` matched
        the string `httpclient.py` inside the facade's own docstring and reported that
        `studio.httpclient` fails to export `py`. A text scan cannot tell an
        attribute access from a filename, a comment or a quoted example -- and the whole
        argument for this test over an `ngrep` is that it reads structure rather than
        text, so reading text here would have conceded the point.

        The facade itself is excluded: it is the only file that legitimately talks about
        the name rather than through it.
        """
        used: dict[str, set[str]] = {}
        for path in _shipped_modules(package):
            if path.resolve() == facade.resolve():
                continue
            names = set()
            for node in ast.walk(ast.parse(path.read_text())):
                if (isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == alias):
                    names.add(node.attr)
            if names:
                used[str(path.relative_to(REPO))] = names
        return used

    def test_every_attribute_the_tree_uses_resolves_on_the_facade(self):
        for module_path, alias, package, facade in self.IMPORTED:
            used = self._attributes_used(package, alias, facade)
            self.assertTrue(used, f"nothing in {package} uses {alias} -- did a rename land?")
            module = self._import(module_path, package)
            for consumer, names in sorted(used.items()):
                for name in sorted(names):
                    with self.subTest(consumer=consumer, name=name):
                        self.assertTrue(
                            hasattr(module, name),
                            f"{consumer} uses {alias}.{name} and {module_path} does not "
                            f"export it -- this is the `convert_xor` shape: it raises at "
                            f"import and shows up as a collection abort, not as a failure "
                            f"here")

    def _import(self, module_path: str, package: str):
        """`remix` is a separate application with its own rootdir, so it is not importable
        from `backend/` without the path entry its `pyproject.toml` supplies."""
        import sys
        if package == "remix":
            root = str(APPS / "remix")
            if root not in sys.path:
                sys.path.insert(0, root)
        return importlib.import_module(module_path)

    def test_the_facades_expose_the_version_of_what_they_wrap(self):
        """Cheap, and it is the one call that proves the vendor is really behind it.

        A facade of hand-written stubs would satisfy every attribute check above.
        """
        for module_path, _alias, package, _facade in self.IMPORTED:
            with self.subTest(module=module_path):
                module = self._import(module_path, package)
                self.assertRegex(module.version(), r"^\d+\.\d+")


if __name__ == "__main__":
    unittest.main()
