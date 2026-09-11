"""`tools/sabotage_matrix.py` held to its own claims -- without running it.

The harness proves the matrix suite bites, by mutating documents and checking the right test goes
red. That is exactly the kind of thing that rots silently: an anchor string drifts, the harness
prints STALE ANCHOR, and a green summary line still says "all caught" to anyone skimming.

So this file checks the harness is *runnable and honest* while mutating nothing:

  * every anchor it searches for is present in the file it names;
  * every replacement actually differs from what it replaces;
  * every test id it points at exists in the matrix suite;
  * it still covers at least the nine mutations the branch claimed, plus the two added after the
    review that found four hand-typed Safety cells.

Deliberately does NOT invoke the tool. A test that mutates tracked documents mid-suite would be a
side effect in `pytest apps/`, and `test_modelops.py` already demonstrates how surprising that is:
it rewrites a staging ROLLBACK.md by design. Run the harness by hand:

    python3 tools/sabotage_matrix.py
"""

import ast
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "sabotage_matrix.py"
SUITE = ROOT / "backend" / "apps" / "test_control_plane_matrix.py"

#: The nine the branch originally claimed, plus two the pre-merge review made necessary, plus one
#: added after the post-merge count failure. Raise this when cases are added -- a stale floor here
#: would let the harness quietly shrink while every document still claimed the old number.
EXPECTED_CASES = 12


def cases():
    """The CASES table, read with `ast` rather than imported -- no execution, no side effects."""
    tree = ast.parse(TOOL.read_text(encoding="utf-8"))
    consts = {}
    out = []
    for node in ast.walk(tree):
        # `CASES: list[...] = [...]` is an AnnAssign, not an Assign. The first version of this
        # parser only handled Assign, so it found ZERO cases -- and every other test in this file
        # then passed vacuously over an empty list. Third time that trap has appeared in this
        # batch, hence the hard guard at the end of this function.
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if len(targets) != 1 or node.value is None:
                continue
            name = getattr(targets[0], "id", None)
            if name and isinstance(node.value, ast.Constant):
                consts[name] = node.value.value
            elif name == "CASES":
                for elt in node.value.elts:
                    label, path, find, repl, test_id = elt.elts
                    def val(n):
                        if isinstance(n, ast.Constant):
                            return n.value
                        if isinstance(n, ast.Name):
                            return consts[n.id]
                        if isinstance(n, ast.BinOp):          # implicit string concat via +
                            return val(n.left) + val(n.right)
                        if isinstance(n, ast.JoinedStr):
                            raise AssertionError("f-string in CASES; keep it literal")
                        raise AssertionError(f"unexpected node {type(n).__name__}")
                    # Adjacent string literals parse as one Constant, so this covers wrapped ids.
                    out.append((val(label), val(path), val(find), val(repl), val(test_id)))
    # Never hand back an empty list. Every test below iterates it, so an empty parse would make
    # all of them pass while checking nothing -- which is exactly what happened on the first run.
    assert out, ("parsed no CASES out of tools/sabotage_matrix.py -- the parser is broken, not "
                 "the harness, and every assertion in this file would be vacuous")
    return out


class TheHarnessIsPresentAndParseable(unittest.TestCase):
    def test_the_tool_is_tracked_and_executable_as_a_script(self):
        self.assertTrue(TOOL.is_file(), f"{TOOL} is missing -- the sabotage proof is unreproducible")
        text = TOOL.read_text(encoding="utf-8")
        self.assertIn("__main__", text, "not runnable as a script")
        self.assertIn("--list", text, "no --list mode, so the cases cannot be inspected safely")

    def test_it_declares_at_least_the_claimed_number_of_mutations(self):
        got = cases()
        self.assertGreaterEqual(len(got), EXPECTED_CASES,
                                f"harness declares {len(got)} cases; the docs and commit message "
                                f"claim at least {EXPECTED_CASES}")


class EveryCaseIsStillValid(unittest.TestCase):
    """A stale anchor is the failure mode: the harness would skip the case and still look fine."""

    def test_every_anchor_is_present_in_the_file_it_names(self):
        for label, rel, find, _repl, _tid in cases():
            with self.subTest(case=label):
                path = ROOT / rel
                self.assertTrue(path.is_file(), f"{rel} does not exist")
                self.assertIn(find, path.read_text(encoding="utf-8"),
                              f"anchor for {label!r} is stale in {rel}")

    def test_every_mutation_actually_changes_something(self):
        for label, _rel, find, repl, _tid in cases():
            with self.subTest(case=label):
                self.assertNotEqual(find, repl, f"{label!r} is a no-op mutation")

    def test_every_case_points_at_a_test_that_exists(self):
        src = SUITE.read_text(encoding="utf-8")
        classes = set(re.findall(r"^class (\w+)\(", src, flags=re.M))
        methods = set(re.findall(r"^\s+def (test_\w+)", src, flags=re.M))
        for label, _rel, _f, _r, test_id in cases():
            with self.subTest(case=label):
                cls, _, meth = test_id.partition("::")
                self.assertIn(cls, classes, f"{label!r} names class {cls}, which is gone")
                if meth:
                    self.assertIn(meth, methods, f"{label!r} names {meth}, which is gone")

    def test_the_harness_only_ever_mutates_documentation(self):
        """It must never be able to edit app code, a weight or a service file."""
        for label, rel, _f, _r, _t in cases():
            with self.subTest(case=label):
                self.assertTrue(rel.startswith("docs/"),
                                f"{label!r} targets {rel}, which is outside docs/")
                self.assertTrue(rel.endswith(".md"), f"{label!r} targets a non-markdown file")


class TheHarnessRefusesToRunOnADirtyTree(unittest.TestCase):
    def test_it_checks_git_status_before_mutating(self):
        """Without this guard a crash mid-run loses whatever was uncommitted."""
        text = TOOL.read_text(encoding="utf-8")
        self.assertIn("--porcelain", text, "no dirty-tree guard")
        self.assertIn("REFUSING", text, "the guard does not refuse")

    def test_it_restores_in_a_finally_block(self):
        text = TOOL.read_text(encoding="utf-8")
        self.assertIn("finally:", text, "no guaranteed restore")
        self.assertIn("failed to restore", text, "the restore is not asserted byte-exact")


if __name__ == "__main__":
    unittest.main()
