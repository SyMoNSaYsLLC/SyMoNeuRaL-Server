"""The plugin contract in `apps/studio/plugins/__init__.py`, asserted against the disk.

Task #73 item 3. That file says what a package under `backend/studio/plugins/` must
export; this one says whether the three that exist do, and whether the row each returns is one
`api.py` can actually serialise.

Two disciplines from elsewhere in this suite, both deliberate:

* **`api.py` is read as source, never imported** -- `apps/test_status_rack.py` and
  `apps/test_studio_models.py` do the same, because importing the serving module builds every
  rate limiter, resolves the GPU governor and mounts `site/`. So the `Unit` field list and its
  two `Literal` sets come out of the AST, and this file adds no second copy of them.
* **the plugin packages ARE imported**, which is safe and is the thing being tested: all three
  are documented as importable with their surface switched off, `exp` resolves `router` lazily
  through a PEP 562 `__getattr__`, and `status()` on each is a pure read of the environment and
  the disk. If importing one of these ever costs something, this file going slow is the signal.

**Green here is not proof the rack is live.** `discovery` conforms and is deliberately not
mounted at all (no page behind the `href` yet). The live check is
`curl -s http://127.0.0.1:8800/api/status`, and nothing here substitutes for it.
"""
from __future__ import annotations

import ast
import pathlib
import sys
import unittest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from studio import plugins  # noqa: E402  -- after the sys.path insert above

API_PY = BACKEND / "api.py"
PLUGINS_DIR = pathlib.Path(plugins.__file__).parent


def _unit_model() -> tuple[set[str], set[str], dict[str, set[str]]]:
    """`(all fields, fields with no default, {field: literal values})` from `class Unit` in api.py."""
    tree = ast.parse(API_PY.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Unit":
            break
    else:
        raise AssertionError(f"{API_PY} no longer defines `class Unit`")

    fields: set[str] = set()
    required: set[str] = set()
    literals: dict[str, set[str]] = {}
    for stmt in node.body:
        if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
            continue
        name = stmt.target.id
        fields.add(name)
        if stmt.value is None:
            required.add(name)
        ann = stmt.annotation
        if isinstance(ann, ast.Subscript) and getattr(ann.value, "id", "") == "Literal":
            literals[name] = {e.value for e in ann.slice.elts}
    return fields, required, literals


UNIT_FIELDS, UNIT_REQUIRED, UNIT_LITERALS = _unit_model()


class ContractShapeTests(unittest.TestCase):
    """The contract is a reading of the disk, not a wish."""

    def test_plugins_tuple_matches_the_directories_on_disk(self):
        found = sorted(p.name for p in PLUGINS_DIR.iterdir()
                       if p.is_dir() and (p / "__init__.py").is_file())
        self.assertEqual(sorted(plugins.PLUGINS), found,
                         "a plugin package appeared or vanished; add or remove it in "
                         "`PLUGINS` and say in this commit whether it conforms")

    def test_every_plugin_resolves_the_required_exports(self):
        for name in plugins.PLUGINS:
            with self.subTest(plugin=name):
                self.assertEqual(plugins.missing(plugins.load(name)), [],
                                 f"{name} does not export all of {plugins.REQUIRED}")

    def test_the_optional_exports_are_present_exactly_where_declared(self):
        for opt, expected in plugins.OPTIONAL_PRESENT.items():
            with self.subTest(export=opt):
                actual = {n for n in plugins.PLUGINS if hasattr(plugins.load(n), opt)}
                self.assertEqual(set(expected), actual,
                                 f"`{opt}` moved. Update OPTIONAL_PRESENT, and ask whether it "
                                 "now belongs in REQUIRED")

    def test_optional_names_are_not_also_required(self):
        self.assertEqual(set(plugins.REQUIRED) & set(plugins.RECOGNISED), set())

    def test_load_returns_the_module_a_plain_import_returns(self):
        from studio.plugins import exp
        self.assertIs(plugins.load("exp"), exp)

    def test_load_refuses_a_name_not_in_the_tuple(self):
        with self.assertRaises(KeyError):
            plugins.load("nosuchplugin")


class StatusRowTests(unittest.TestCase):
    """Every plugin's `status()` must be a row `api.py`'s `Unit` model accepts.

    `state` and `bus` are `Literal`s: a fifth value is not a nicer label, it is a pydantic error
    raised inside `build_status()`, which takes the *whole* rack off the front page rather than
    one row. `exp` and `discovery` each warn about this in their own docstring; nothing asserted
    it for all three together until this file.
    """

    def test_the_unit_model_was_read_at_all(self):
        # If the AST walk silently found nothing, every assertion below would pass vacuously.
        self.assertIn("state", UNIT_LITERALS)
        self.assertIn("bus", UNIT_LITERALS)
        self.assertLessEqual({"id", "label", "slot", "state", "bus"}, UNIT_REQUIRED)

    def test_each_row_carries_every_field_unit_requires(self):
        for name in plugins.PLUGINS:
            with self.subTest(plugin=name):
                row = plugins.load(name).status()
                self.assertIsInstance(row, dict)
                self.assertEqual(UNIT_REQUIRED - set(row), set())

    def test_no_row_carries_a_field_unit_does_not_have(self):
        for name in plugins.PLUGINS:
            with self.subTest(plugin=name):
                extra = set(plugins.load(name).status()) - UNIT_FIELDS
                self.assertEqual(extra, set(), f"{name} would be rejected by Unit(**row)")

    def test_every_literal_field_holds_a_value_unit_allows(self):
        for name in plugins.PLUGINS:
            row = plugins.load(name).status()
            for field, allowed in UNIT_LITERALS.items():
                with self.subTest(plugin=name, field=field):
                    self.assertIn(row.get(field), allowed)


# At the FOOT of the file, below every class. A `__main__` block placed above a class silently
# un-collects it -- `test_streamer_migration.py` ran 9 tests instead of 11 that way. The
# sys.path insert at the top is what makes this work without the `-m` in `python3 -m pytest`.
if __name__ == "__main__":  # pragma: no cover
    unittest.main()
