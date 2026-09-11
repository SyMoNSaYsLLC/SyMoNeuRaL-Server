"""The playbook slices must stay derivable from the manual.

Nineteen documents said in their own third line that they were "sliced from the consolidated
manual", and no slicer existed. 8,425 lines in two trees, derived from a third, with nothing
able to regenerate them and nothing able to notice they had drifted -- which they had, in all
nineteen, entirely in the breadcrumb path.

`tools/build_manual_slices.py` is the generator of record for the 22 playbook slices. This
asserts it stays one.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "build_manual_slices.py"


class TheSlicesAreGenerated(unittest.TestCase):

    def test_check_passes(self):
        r = subprocess.run([sys.executable, str(TOOL), "--check"],
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0,
                         f"slices are stale -- run tools/build_manual_slices.py\n{r.stdout}")

    def test_every_targeted_slice_reproduces_exactly(self):
        """22 of 22, or the tool is describing something it cannot rebuild."""
        r = subprocess.run([sys.executable, str(TOOL), "--report"],
                           capture_output=True, text=True, timeout=300)
        line = next((l for l in r.stdout.splitlines() if "reproduced exactly" in l), "")
        self.assertIn("slices covered: 22   reproduced exactly: 22", line,
                      f"the slicer no longer reproduces every slice it targets: {line!r}")

    def test_the_uncovered_curriculum_is_named_not_silent(self):
        """A gap that is written down is a finding; one that is not is a trap."""
        src = TOOL.read_text()
        self.assertIn("CURRICULUM_NOT_COVERED", src,
                      "the five 04-cuda-curriculum slices are still derived files with no "
                      "generator, and the tool must say so rather than implying coverage")

    def test_both_trees_are_generated(self):
        """The reinforce copy exists so that plugin's docs are self-contained. Generating
        only one tree is how the 32 lines of breadcrumb drift happened."""
        src = TOOL.read_text()
        self.assertIn("plugins/reinforce/docs", src)
        self.assertIn('ROOT / "docs"', src)


if __name__ == "__main__":
    unittest.main()
