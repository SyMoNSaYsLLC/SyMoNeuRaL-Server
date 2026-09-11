"""The NIM model table in scripts/nim-qwen36.sh.

Adding a NIM is meant to be four measured numbers in one `case` arm. Nothing enforces that
by itself: a half-filled arm is valid bash right up to the moment `preflight` reads an unset
variable, and `set -u` at the top of that script turns it into an unbound-variable abort at
the worst time -- mid-preflight, after the operator has already been told two checks passed.

So this pins the shape of the table and, more importantly, the one thing a future edit is
most likely to undo: the VRAM comparison reads the selected arm's floor. It used to be a
literal 19000 in the body of `preflight`, which was correct while there was exactly one
model and silently wrong the moment there were two.

Stdlib only, no fixtures, no subprocess: this reads the script as text. The shell behaviour
itself is covered by running `NIM_MODEL=... preflight`, which is in the commit message.
"""

import re
import unittest
from pathlib import Path

SCRIPT = next(_p for _p in Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file()) / "scripts" / "nim-qwen36.sh"

# The five variables every arm owes. IMAGE/NAME/PORT are used by `up`, `logs` and `down`;
# PULL_GB and NEED_MIB are the two figures `preflight` reports and compares against.
REQUIRED = ("IMAGE", "NAME", "PORT", "PULL_GB", "NEED_MIB")

# The model table only. Scoping matters: the command dispatcher lower down is a second
# `case` with arms at the same two-space indent (`login)`, `preflight)`, `up)`), and matching
# on indentation alone pulled those in and then failed looking for PORT= inside `login)`.
TABLE = re.compile(r'case "\$\{NIM_MODEL:-\w+\}" in\n(.*?)\nesac', re.S)

# An arm opens with `  <label>)` at two-space indent and closes with `    ;;`. The wildcard
# arm is excluded by the label pattern: it is the error path and defines nothing on purpose.
ARM = re.compile(r"^  ([a-z0-9][a-z0-9.\-]*)\)$\n(.*?)^    ;;$", re.M | re.S)


class NimModelTable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text()
        table = TABLE.search(cls.text)
        assert table, "the NIM_MODEL case block is no longer findable in nim-qwen36.sh"
        cls.arms = {label: body for label, body in ARM.findall(table.group(1))}

    def test_the_table_is_not_empty(self):
        """Vacuity guard. Every assertion below passes trivially against zero arms, so if the
        regex stops matching -- reindented arms, a rewritten case block -- this is the test
        that says so instead of the suite going quietly green."""
        self.assertGreaterEqual(len(self.arms), 2, f"parsed arms: {sorted(self.arms)}")
        self.assertIn("qwen36", self.arms)
        self.assertIn("qwen3-32b", self.arms)

    def test_every_arm_defines_every_variable(self):
        for label, body in self.arms.items():
            for var in REQUIRED:
                with self.subTest(model=label, var=var):
                    # `(?m)` is load-bearing: assertRegex compiles without re.M, so a bare
                    # `^` anchors at the start of the whole body and this passed for IMAGE --
                    # the first line -- while silently never checking any of the other four.
                    self.assertRegex(body, rf"(?m)^\s*{var}=", f"{label} never sets {var}")

    def test_the_vram_check_reads_the_selected_arm_and_not_a_literal(self):
        """The mutation this exists for. A hardcoded threshold in `preflight` compares every
        model against one model's number, which is the bug that cannot be seen by reading the
        arm you just added."""
        pre = self.text.split("preflight() {", 1)[1].split("\ncase ", 1)[0]
        self.assertIn('"$NEED_MIB"', pre, "preflight no longer compares against $NEED_MIB")
        # Any bare five-digit MiB constant left in the comparison is the old bug returning.
        self.assertNotRegex(
            pre, r'-lt\s+"?\d{4,}"?', "preflight compares VRAM against a literal, not $NEED_MIB")

    def test_the_ports_are_distinct(self):
        """One card, but both containers can be started, and two NIMs bound to one port fail
        in a way that reads like the image is broken rather than like a collision."""
        ports = {label: re.search(r"^\s*PORT=(\d+)", body, re.M).group(1)
                 for label, body in self.arms.items()}
        self.assertEqual(len(set(ports.values())), len(ports), f"port collision: {ports}")

    def test_the_unsupported_image_is_pinned_to_a_version(self):
        """`qwen3-32b` is end-of-support upstream. A floating `:latest` on an artifact NVIDIA
        has stopped refreshing can only move somewhere unexamined."""
        self.assertRegex(self.arms["qwen3-32b"], r"IMAGE=\S+/qwen3-32b:\d+\.\d+\.\d+")

    def test_each_arm_says_why_it_is_or_is_not_shippable(self):
        """The three reasons the 32B does not ship are the whole value of that arm; an arm
        carrying only an image URL invites someone to run `up` and find out slowly."""
        body = self.arms["qwen3-32b"]
        for phrase in ("END OF SUPPORT", "does not fit", "redistribute"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, body)


if __name__ == "__main__":
    unittest.main()
