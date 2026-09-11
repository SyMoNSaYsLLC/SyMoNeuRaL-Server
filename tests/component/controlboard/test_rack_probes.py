"""The rack's readiness probes, held to the disk they claim to describe.

On 2026-08-20 the chat, image and sigils rows read offline on the live rack while every
weight and both engine binaries sat on disk under their correct names, and 1267 tests were
green. The mechanism: commit 34c5009 renamed the weights on disk (~04:23-04:38) and the
constants in api.py together -- a coherent commit -- but symoneural-api.service had started
at 03:21 and was never restarted, so the running process kept probing the OLD names from
memory. The rename outran the process, and three live surfaces went down silently.

Why nothing caught it, test by test:
  * `test_weight_names.py` checks the files on disk against the provenance manifest --
    it never reads what the CODE probes for, so code and disk can disagree freely;
  * `test_status_rack.py` reads api.py as source and compares its count, names and comment
    with each other -- its own docstring concedes "Green here is not proof the rack is
    live" and names `curl -s http://127.0.0.1:8800/api/status` as the check nothing in the
    file substitutes for. Nobody had automated that curl.

This file closes both gaps and adds the linkage between them:
  * every path the rack probes read (api.py's CHAT_MODEL, DRAFT_MODEL, FLUX, CHAT_ADAPTER,
    LLM_ENGINE, DIFFUSE_ENGINE; sigils' DIFFUSE_ENGINE and WEIGHTS) must exist on disk. Rename either
    side without the other and this goes red AT COMMIT TIME. The paths are extracted from
    api.py's SOURCE -- the house discipline from `test_status_rack.py`: importing the
    serving module builds rate limiters, resolves the governor and mounts site/;
  * the probe must actually drive the state: sigils' weights_present() flips false when a
    probe path is pointed at a name that is not there (the in-suite mutation), and the
    `offline` arms in api.py and routes.py are pinned to those very probes by source;
  * the live rack must agree with the disk: if :8800 answers and the disk is servable,
    chat, image and sigils may not read offline. This is the automated form of the curl,
    and it is the only test here that would have caught the stale-process case -- red from
    ~04:38 on 2026-08-20 until the service restart. It skips, loudly and honestly, on a
    box where the service is not running; it does not skip on a box where it is.

No GPU is taken, nothing is spawned, and the live check is one read-only GET.
"""
from __future__ import annotations

import json
import re
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = next(_p for _p in Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
API_PY = ROOT / "backend" / "server.py"
API_SOURCE = API_PY.read_text()
MODELS = ROOT / "models"
STATUS_URL = "http://127.0.0.1:8800/api/status"


def api_probe_paths() -> dict:
    """Every model/engine path api.py's rack probes read, extracted from source.

    Two shapes cover all of them: `NAME = ROOT / "seg" / ... ` for the binaries and the
    adapter, and `MODELS / "seg" / "file"` chains for the weights (both the named
    constants and the FLUX dict values). Extraction from source keeps this file out of
    api.py's import graph, and the count guards below make silent extraction rot loud.
    """
    paths = {}
    # TWO spellings of the same thing, and the second one is why this pattern is not a single
    # anchored line any more:
    #
    #   CHAT_ADAPTER  = ROOT / "training" / ...                    -- the original shape
    #   LLM_ENGINE    = _engine_path("SYMONEURAL_LLM_ENGINE",
    #                                ROOT / "engines" / ...)       -- env override, ROOT default
    #
    # The engines grew an environment override and moved onto a continuation line. `^NAME = ROOT`
    # then matched neither, so this extractor silently found ONE of the three binaries and the
    # count guard below went red saying so -- which is exactly what that guard is for, and it is
    # kept rather than relaxed.
    #
    # The ROOT default is the right thing to resolve even though `_engine_path` may return an
    # override instead: the override is read from the environment at import, cannot be known from
    # source, and `_engine_path` already refuses a non-existent one loudly and falls back to this
    # default. So the default is the path the rack reads unless someone has deliberately pointed
    # it elsewhere, and it is the only one a source-only extractor can honestly assert about.
    for m in re.finditer(
            r'^(LLM_ENGINE|DIFFUSE_ENGINE|CHAT_ADAPTER) = (?:_engine_path\(\s*"[^"]+",\s*)?'
            r'ROOT((?:\s*/\s*"[^"]+")+)',
            API_SOURCE, re.M):
        paths[m.group(1)] = ROOT.joinpath(*re.findall(r'"([^"]+)"', m.group(2)))
    for m in re.finditer(r'MODELS((?: / "[^"]+")+)', API_SOURCE):
        segs = re.findall(r'"([^"]+)"', m.group(1))
        paths["/".join(segs)] = MODELS.joinpath(*segs)
    return paths


def disk_is_servable() -> bool:
    """True when this box holds weights at all -- the agreement tests are about a box
    that claims to serve, and a fresh clone with an empty models/ is not claiming to."""
    llm = MODELS / "llm"
    return llm.is_dir() and any(llm.glob("*.gguf"))


class ProbePathsAgreeWithDisk(unittest.TestCase):

    def setUp(self):
        if not disk_is_servable():
            self.skipTest("no weights on this box -- nothing claims to serve")

    def test_every_probe_path_the_rack_reads_exists_on_disk(self):
        """The commit-time tripwire: rename disk or constant alone and this is red.

        Mutation-checked by construction: point any constant at a wrong name and the
        joined path stops existing. (Verified once by hand on 2026-08-20: CHAT_MODEL
        edited to a wrong basename turned exactly this test red.)
        """
        paths = api_probe_paths()
        binaries = {k for k in paths if k in ("LLM_ENGINE", "DIFFUSE_ENGINE", "CHAT_ADAPTER")}
        self.assertEqual(len(binaries), 3,
                         "extraction lost a ROOT-anchored probe constant in api.py")
        weights = [k for k in paths if k not in binaries]
        self.assertGreaterEqual(len(weights), 6,
                                "extraction found fewer MODELS chains than CHAT_MODEL, "
                                "DRAFT_MODEL and the four FLUX entries")
        for name, p in paths.items():
            self.assertTrue(p.exists(),
                            f"api.py probes {name} at {p}, which is not on disk -- "
                            f"a rename has outrun its probes (the 34c5009 incident class)")

    def test_sigils_probe_agrees_with_disk_and_drives_its_state(self):
        """The sigils half of the same agreement, plus the in-suite mutation.

        weights_present() must be True against the real disk, and pointing its DIFFUSE_ENGINE at
        a name that is not there must flip it -- proving the reading derives from these
        paths and not from anything softer.
        """
        from sigils.lib import render
        self.assertTrue(render.DIFFUSE_ENGINE.is_file(),
                        f"sigils probes {render.DIFFUSE_ENGINE}, which is not on disk")
        for k, p in render.WEIGHTS.items():
            self.assertTrue(p.is_file(), f"sigils probes {k} at {p}, not on disk")
        self.assertTrue(render.weights_present())
        real = render.DIFFUSE_ENGINE
        try:
            render.DIFFUSE_ENGINE = real.with_name("symoneural-diffuse-renamed-out-from-under-the-probe")
            self.assertFalse(render.weights_present(),
                             "weights_present() ignored DIFFUSE_ENGINE -- the state no longer "
                             "derives from the probe this file pins")
        finally:
            render.DIFFUSE_ENGINE = real


class ProbesDriveTheStates(unittest.TestCase):
    """The linkage pins, by source: the offline arms must read from these exact probes.

    Without these, the agreement tests above could hold while a refactor quietly rewired
    `state=` to something that never looks at the probes -- agreeing paths proving nothing.
    """

    def test_api_status_derives_chat_and_image_from_the_probes(self):
        for needle in (
                "chat_ok = CHAT_MODEL.exists() and LLM_ENGINE.exists()",
                'image_ok = all(p.exists() for p in FLUX.values()) and DIFFUSE_ENGINE.exists()',
                'state=gpu_unit("chat", chat_ok)',
                'state=gpu_unit("image", image_ok)'):
            self.assertIn(needle, API_SOURCE,
                          f"api.py no longer contains {needle!r} -- re-point this test "
                          "at how the rack states are derived now")

    def test_sigils_status_derives_offline_from_weights_present(self):
        source = (ROOT / "backend" / "sigils" / "routes.py").read_text()
        self.assertIn("if not render.weights_present():", source)
        self.assertIn('"image engine not installed on this box"', source)


class LiveRackAgreesWithDisk(unittest.TestCase):
    """The automated curl -- the check `test_status_rack.py` says nothing substitutes for.

    The one test in the suite that catches the stale-process case: code and disk renamed
    together, service never restarted. Red from ~04:38 to the restart on 2026-08-20.
    """

    def test_live_chat_image_sigils_are_not_offline_when_disk_is_servable(self):
        if not disk_is_servable():
            self.skipTest("no weights on this box -- nothing claims to serve")
        try:
            with urllib.request.urlopen(STATUS_URL, timeout=3) as r:
                doc = json.load(r)
        except (urllib.error.URLError, OSError) as e:
            self.skipTest(f"live service not answering on :8800 ({e}) -- "
                          "nothing live to hold to the disk")
        states = {u["id"]: u["state"] for u in doc["units"]}
        for unit in ("chat", "image", "sigils"):
            self.assertNotEqual(
                states.get(unit), "offline",
                f"the live rack reports {unit}=offline while every probe target for it "
                "exists on disk. The running process is probing paths that were renamed "
                "out from under it -- restart symoneural-api so the service runs the "
                "code that matches the disk (the 2026-08-20 outage).")


if __name__ == "__main__":
    unittest.main()


class NoUnitClaimsResidencyItDoesNotMeasure(unittest.TestCase):
    """A rack row may say what a model WOULD cost. It may not say what is loaded now.

    `/api/status` reported chat and image as `ready` with details reading "~5 GB resident"
    and "~7 GB resident". `ready` is honest -- `chat_ok`/`image_ok` are existence checks and
    this box loads nothing until a request arrives, so it means "loadable on demand". The
    detail lines were not: measured 2026-09-03 while both said resident, the card held
    1,429 MiB in total INCLUDING the desktop, and the governor's holder was None. Twelve
    gigabytes claimed, none of it there.

    That is the failure this repo's own rules name -- a decorative status that reports a
    number nothing measured. Footprint-when-loaded is a true statement at any load state;
    "resident" is a measurement, and nothing in `build_status()` measures it per unit.
    """

    SRC = (ROOT / "backend" / "server.py").read_text()

    def test_no_detail_string_asserts_present_tense_residency(self):
        """Scoped to `detail=` so prose, docstrings and comments explaining the history --
        including the one directly above `gpu_unit` -- are not what this matches."""
        offenders = [d for d in re.findall(r'detail="([^"]*)"', self.SRC)
                     if re.search(r"\bresident\b", d)]
        self.assertEqual(offenders, [], (
            "a unit detail claims residency. Nothing in build_status() measures per-unit VRAM, "
            "so this is a number with no reading behind it. Say '~N GB when loaded'."))

    def test_the_footprint_figures_survive_as_a_conditional_claim(self):
        """The other direction: deleting the sizes would pass the test above and lose real
        information an operator uses to reason about a 16 GiB card three surfaces share."""
        self.assertIn("when loaded", self.SRC,
                      "the footprint figures were removed rather than reworded")

    def test_ready_is_documented_where_it_is_computed(self):
        """The misreading that started this was reasonable, and the fix for a reasonable
        misreading is to write the meaning down beside the code, not to remember it."""
        m = re.search(r"def gpu_unit\(.*?\n(.*?)\n\s*if not ok:", self.SRC, re.S)
        self.assertIsNotNone(m, "gpu_unit changed shape; re-derive this test")
        self.assertIn("LOADABLE ON DEMAND", m.group(1),
                      "gpu_unit no longer states what `ready` means")
