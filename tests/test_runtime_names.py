# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
"""Every `runtime=` in the registry names something real, or is a declared logical label.

Measured 2026-09-08, reading the registry against the source:

  * `voice` declared `symoneural-llm`. It executes `symoneural-listen` -- `voice/asr.py:64`
    builds that path and its own docstring describes the whisper CPU build.
  * `image` and `sigils` declared `symoneural-image-engine`. That is not a component --
    it is an ALIAS of `symoneural-diffuse`, recorded in COMPONENT-MAP.tsv's ALIASES column.
    They execute `symoneural-diffuse` (`sigils/render.py:73`), and the component ID was
    absent from the registry's own allowlist while the nickname was in it.

Neither broke anything, which is why both survived. The field is read by people and by
`/docs`, not by a loader.

The reason a plain "must be a real directory" rule will not do: thirteen of the twenty-two
surfaces name a runtime that is a LOGICAL label for in-process application modules --
`symoneural-studio`, `symoneural-live`, `symoneural-project`, `symoneural-ravencalc`,
`symoneural-platform`. Recording those is legitimate. What was not legitimate is that the
field mixed the two with nothing distinguishing them, so `voice -> symoneural-llm` read
exactly like `live -> symoneural-live` while one was wrong and the other was shorthand.

So the rule is: a runtime name is valid if it is a real runtime directory **or** it is in
`LOGICAL` below. A new typo is neither, and fails here.
"""
from __future__ import annotations

import pathlib
import sys
import unittest


def _find_root(start: pathlib.Path) -> pathlib.Path:
    """Walk up for the marker; never count parents. See symoneural-audit/README.md."""
    for cand in (start, *start.parents):
        if (cand / "backend" / "server.py").is_file():
            return cand
    raise RuntimeError(f"no repo root above {start}")


ROOT = _find_root(pathlib.Path(__file__).resolve())
sys.path.insert(0, str(ROOT / "backend"))

from registry import appdocs                                            # noqa: E402

#: Read from the registry, NOT duplicated here. A copy of this set in the test would be a
#: second source of truth, and the first thing it would do is drift -- which is the whole
#: shape of the defect being tested.
LOGICAL = set(appdocs.LOGICAL_RUNTIMES)


class EveryRuntimeNameResolves(unittest.TestCase):

    @staticmethod
    def _runtime_dirs() -> set[str]:
        """Real runtime directories: a top-level symoneural-* holding a bin/ or a build/.

        Keyed on structure rather than on the name prefix, because the repo root also holds
        `symoneural-adaptive-fabric/`, which is PLANNED and has neither -- and a surface
        claiming to run on a runtime that is not implemented should fail this.
        """
        out = set()
        for p in ROOT.iterdir():
            if p.is_dir() and p.name.startswith("symoneural-"):
                if (p / "bin").is_dir() or (p / "build").is_dir():
                    out.add(p.name)
        return out

    def test_the_runtime_directory_scan_finds_something(self):
        """An empty scan would make the assertion below vacuous."""
        found = self._runtime_dirs()
        self.assertTrue(found, "no runtime directories found; the scan is broken, so the "
                               "check below proves nothing")

    def test_every_process_runtime_has_a_real_directory(self):
        """The stronger half: a name in PROCESS_RUNTIMES must BE a process on disk.

        `symoneural-image-engine` sat in that set as an alias with no directory of its
        own, while the component ID `symoneural-diffuse` was absent
        -- so the registry's own validator would have refused the truth and did accept the
        fiction. This is the assertion that makes that impossible.
        """
        real = self._runtime_dirs()
        missing = sorted(set(appdocs.PROCESS_RUNTIMES) - real)
        self.assertEqual([], missing,
                         "these are declared as processes on disk and have no runtime "
                         f"directory (found: {sorted(real)}). Either they are logical, and "
                         "belong in LOGICAL_RUNTIMES, or the name is wrong")

    def test_the_two_runtime_kinds_do_not_overlap(self):
        overlap = set(appdocs.PROCESS_RUNTIMES) & set(appdocs.LOGICAL_RUNTIMES)
        self.assertEqual(set(), overlap,
                         "a runtime cannot be both a process and a logical grouping; the "
                         "split exists so a reader can tell which kind a name is")

    def test_every_declared_runtime_is_real_or_declared_logical(self):
        real = self._runtime_dirs()
        bad = {}
        for app in appdocs.APPLICATIONS:
            r = getattr(app, "runtime", None)
            if not r or r in real or r in LOGICAL:
                continue
            bad[app.id] = r
        self.assertEqual({}, bad,
                         "these name a runtime that is neither a real runtime directory "
                         f"nor a declared logical label (real: {sorted(real)}). Either fix "
                         "the name or add it to LOGICAL with a reason")

    def test_voice_names_the_engine_it_actually_executes(self):
        """The specific regression: ASR on the language engine.

        Asserted against the source rather than against a remembered value, so it stays
        true if the engine is renamed again.
        """
        asr = (ROOT / "backend" / "apps" / "voice" / "asr.py").read_text()
        self.assertIn("symoneural-listen", asr)
        voice = next(a for a in appdocs.APPLICATIONS if a.id == "voice")
        self.assertEqual("symoneural-listen", voice.runtime)

    def test_image_and_sigils_name_the_engine_they_actually_execute(self):
        render = (ROOT / "backend" / "apps" / "sigils" / "render.py").read_text()
        self.assertIn("symoneural-diffuse", render)
        for app_id in ("image", "sigils"):
            with self.subTest(app=app_id):
                app = next(a for a in appdocs.APPLICATIONS if a.id == app_id)
                self.assertEqual("symoneural-diffuse", app.runtime)


class TheComponentMapCoversWhatIsOnDisk(unittest.TestCase):
    """A runtime directory with no map row is a component the architecture cannot see.

    Measured 2026-09-08: the map had 14 rows and was missing `symoneural-listen` and
    `symoneural-miner` -- both BUILT and on disk, the miner answering
    `SyMoNeuRaL Miner 1.2.4` -- plus `symoneural-audit`, added the same day. Granularity was
    not the reason: the map already carried `symoneural-llm-cli` and `symoneural-buildv2`.

    Every row's SOURCE_ROOT was also stale, still reading `engines/symoneural-*` after the
    promotion to the repo root. Nothing consumes that column programmatically, which is
    exactly why it drifted.
    """

    MAP = ROOT / "docs" / "architecture" / "COMPONENT-MAP.tsv"

    @classmethod
    def setUpClass(cls):
        lines = cls.MAP.read_text().rstrip("\n").split("\n")
        cls.header = lines[0].split("\t")
        cls.rows = [dict(zip(cls.header, l.split("\t"))) for l in lines[1:] if l.strip()]

    def test_the_map_parses_and_every_row_is_the_full_width(self):
        """A short row shifts every later column silently, which is unreadable by eye."""
        self.assertTrue(self.rows, "no rows parsed; the assertions below prove nothing")
        for r in self.rows:
            with self.subTest(component=r.get("COMPONENT_ID")):
                self.assertEqual(len(self.header), len(r),
                                 "row has the wrong number of tab-separated fields")

    def test_every_runtime_directory_has_a_row(self):
        ids = {r["COMPONENT_ID"] for r in self.rows}
        on_disk = {p.name for p in ROOT.iterdir()
                   if p.is_dir() and p.name.startswith("symoneural-")}
        missing = sorted(on_disk - ids)
        self.assertEqual([], missing,
                         "these runtime directories exist on disk and the architecture map "
                         "does not record them, so nothing reading the map knows they are "
                         "here")

    def test_every_declared_source_root_exists(self):
        stale = {}
        for r in self.rows:
            root = r.get("SOURCE_ROOT", "-")
            if root in ("-", ""):
                continue                       # PLANNED components legitimately have none
            if not (ROOT / root).exists():
                stale[r["COMPONENT_ID"]] = root
        self.assertEqual({}, stale,
                         "these rows name a SOURCE_ROOT that is not on disk; the paths went "
                         "stale when the runtimes were promoted out of engines/")

    def test_a_planned_component_claims_no_implementation(self):
        """The trap the map itself warns about: a planned name pointed at working code.

        `symoneural-adaptive-fabric` is PLANNED / NOT_IMPLEMENTED with SOURCE_ROOT `-`, and
        its own ALIASES note says the Memory Governor is "distinct from
        scripts/gpu-governor.sh which IS implemented". A future row that marks it
        implemented while pointing at a neighbour's script is how planned work gets reported
        as done.
        """
        for r in self.rows:
            if r.get("IMPLEMENTATION_STATUS") == "NOT_IMPLEMENTED":
                with self.subTest(component=r["COMPONENT_ID"]):
                    self.assertEqual("-", r.get("SOURCE_ROOT"),
                                     "NOT_IMPLEMENTED with a SOURCE_ROOT points a planned "
                                     "name at code that exists")


if __name__ == "__main__":
    unittest.main()
