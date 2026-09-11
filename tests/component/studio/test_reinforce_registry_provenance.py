"""The Reinforce catalogue must connect a house name to its upstream, and must not be silent
about an offloaded cache entry.

Both properties exist because of one incident. On 2026-09-09 the catalogue printed, adjacently:

    symon-1.0-14b-q4_k_m           present=True   trainable=False
    Qwen/Qwen2.5-14B-Instruct      present=False  trainable=False

Two rows about **one model** -- the same weights house-named and upstream -- with nothing
connecting them. At the same time `scan_hf_cache()` returned an empty list for two cache
entries whose blobs had been offloaded to Drive by policy, because every file in the snapshot
is a symlink and `config.json.is_file()` is False once the blobs are gone.

A commissioning pass read that combination as "this box has no trainable weights at all",
published it as a finding against the project's standing objective, and had to be corrected
by the owner. Every individual field was true. The catalogue could not say that two rows were
one model, and said nothing whatsoever about the offloaded ones.

These tests pin the two fixes. This module lives at `backend/` rather than in the
plugin's own suite deliberately: `plugins/reinforce/tests/` is `importorskip`-ed on cupy,
which is absent here, so a test placed there would silently not run. `registry.py` needs no
cupy, so it can be tested where the suite actually executes.
"""

from __future__ import annotations

import json
import pathlib
import sys
import unittest


def _repo_root() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for cand in (here, *here.parents):
        if (cand / "backend" / "server.py").is_file():
            return cand
    raise AssertionError(f"repo root not found above {here}: no backend/server.py marker")


ROOT = _repo_root()
sys.path.insert(0, str(ROOT / "backend"))

from studio.plugins.reinforce import registry  # noqa: E402


class BaseModelName(unittest.TestCase):
    """The normalisation that lets a repackager's GGUF repo match an upstream cache key."""

    def test_strips_org_and_gguf_suffix(self):
        self.assertEqual("Qwen2.5-14B-Instruct",
                         registry._base_model_name("bartowski/Qwen2.5-14B-Instruct-GGUF"))
        self.assertEqual("Qwen3.6-27B",
                         registry._base_model_name("unsloth/Qwen3.6-27B-GGUF"))

    def test_suffix_match_is_case_insensitive(self):
        """`leejet/FLUX.1-schnell-gguf` is a real row in PROVENANCE.json, lowercased."""
        self.assertEqual("FLUX.1-schnell",
                         registry._base_model_name("leejet/FLUX.1-schnell-gguf"))

    def test_leaves_a_bare_name_alone(self):
        self.assertEqual("whisper.cpp", registry._base_model_name("ggerganov/whisper.cpp"))
        self.assertEqual("something", registry._base_model_name("something"))

    def test_does_not_strip_gguf_from_the_middle(self):
        """Only a TRAILING container marker is a container marker.

        The first version of this test used `org/GGUF-tools-x`, which contains no `-GGUF`
        substring at all -- it starts with GGUF -- so it passed against a deliberately
        broken regex with the `$` anchor removed. It tested nothing. The fixture now has
        `-GGUF` genuinely mid-string, where an unanchored pattern would eat it.
        """
        self.assertEqual("x-GGUF-tools",
                         registry._base_model_name("org/x-GGUF-tools"))


class ProvenanceIndex(unittest.TestCase):
    def test_this_box_maps_house_names_to_upstreams(self):
        by_stem, by_base = registry._provenance_index()
        self.assertIn("symon-1.0-14b-q4_k_m", by_stem,
                      "PROVENANCE.json should carry the 14b row; if the manifest changed "
                      "shape this index is silently empty and the catalogue stops linking")
        self.assertIn("Qwen2.5-14B-Instruct", by_base)
        self.assertIn("symon-1.0-14b-q4_k_m", by_base["Qwen2.5-14B-Instruct"])

    def test_a_missing_manifest_degrades_and_does_not_raise(self):
        """Labelling is a nicety; the picker must still work without the manifest."""
        real = registry.PROVENANCE
        try:
            registry.PROVENANCE = ROOT / "does-not-exist-provenance.json"
            by_stem, by_base = registry._provenance_index()
            self.assertEqual({}, by_stem)
            self.assertEqual({}, by_base)
        finally:
            registry.PROVENANCE = real


class CacheStateDistinguishesOffloadFromAbsence(unittest.TestCase):
    """"Offloaded to Drive by policy" and "never fetched" must not share a message.

    Reading the first as the second is what produced a false finding. `cache_state()` is the
    predicate; `fetchable()` is where an operator reads the consequence.
    """

    @staticmethod
    def _snapshot(hub: pathlib.Path, repo: str, files: list[str], dangling: bool) -> pathlib.Path:
        snap = hub / f"models--{repo.replace('/', '--')}" / "snapshots" / "deadbeef"
        snap.mkdir(parents=True)
        for name in files:
            target = snap / name
            if dangling:
                target.symlink_to(snap / ".." / ".." / "blobs" / f"blob-{name}")
            else:
                target.write_text("{}")
        return snap

    def test_dangling_symlinks_are_offloaded_not_absent(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            hub = pathlib.Path(td)
            self._snapshot(hub, "Qwen/Qwen2.5-7B-Instruct",
                           ["config.json", "model-00001-of-00004.safetensors"], dangling=True)
            self.assertEqual("offloaded",
                             registry.cache_state("Qwen/Qwen2.5-7B-Instruct", hub))

    def test_no_cache_directory_is_absent(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual("absent",
                             registry.cache_state("Qwen/Nothing-Here", pathlib.Path(td)))

    def test_real_files_without_a_usable_config_are_partial(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            hub = pathlib.Path(td)
            self._snapshot(hub, "Org/Damaged", ["notes.txt"], dangling=False)
            self.assertEqual("partial", registry.cache_state("Org/Damaged", hub))

    def test_an_empty_snapshot_is_absent_not_partial(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            hub = pathlib.Path(td)
            (hub / "models--Org--Empty" / "snapshots" / "deadbeef").mkdir(parents=True)
            self.assertEqual("absent", registry.cache_state("Org/Empty", hub))

    def test_this_box_reports_the_two_offloaded_models_as_offloaded(self):
        """The live check. These two are the models whose blobs went to Drive."""
        for repo in ("Qwen/Qwen2.5-7B-Instruct", "Qwen/Qwen3.6-27B"):
            self.assertEqual("offloaded", registry.cache_state(repo),
                             f"{repo} should read as offloaded on this box; if the blobs were "
                             "fetched back this becomes 'partial' or a trainable row instead")


class FetchableRowsSayWhichKindOfAbsent(unittest.TestCase):
    def test_offloaded_rows_say_offloaded_and_name_drive(self):
        rows = {e.id: e for e in registry.fetchable()}
        seven = rows.get("Qwen/Qwen2.5-7B-Instruct")
        self.assertIsNotNone(seven, "the 7B should be offered as fetchable; if this is None "
                                    "the provenance-driven pair list stopped working")
        self.assertIn("OFFLOADED", seven.reason)
        self.assertIn("Drive", seven.reason)
        self.assertIn("offloaded", seven.path)

    def test_never_fetched_rows_do_not_claim_an_offload(self):
        rows = {e.id: e for e in registry.fetchable()}
        fourteen = rows.get("Qwen/Qwen2.5-14B-Instruct")
        self.assertIsNotNone(fourteen)
        self.assertNotIn("OFFLOADED", fourteen.reason)
        self.assertIn("never fetched", fourteen.reason)

    def test_every_fetchable_row_names_its_house_model(self):
        """The two-rows-one-model problem, from the upstream side."""
        for e in registry.fetchable():
            self.assertTrue(e.same_model_as,
                            f"{e.id} does not name the house-named GGUF it became")
            self.assertIn("same model", e.reason)

    def test_the_pair_list_comes_from_provenance_not_a_hardcoded_tuple(self):
        """The hardcoded pair excluded the 7B and 27B -- the only two that are offloaded."""
        pairs = dict((r, g) for g, r in registry._fetchable_pairs())
        for repo in ("Qwen/Qwen2.5-0.5B-Instruct", "Qwen/Qwen2.5-7B-Instruct",
                     "Qwen/Qwen2.5-14B-Instruct", "Qwen/Qwen3.6-27B"):
            self.assertIn(repo, pairs)

    def test_only_llm_rows_are_offered(self):
        """PROVENANCE also lists image and whisper artefacts; they are not LM targets."""
        ids = {r for _, r in registry._fetchable_pairs()}
        for not_an_lm in ("FLUX.1-schnell", "whisper.cpp"):
            self.assertFalse([i for i in ids if not_an_lm.lower() in i.lower()],
                             f"{not_an_lm} is not a causal-LM training target")

    def test_the_llm_prefix_guard_is_load_bearing_on_its_own(self):
        """Isolates the `llm/` check from the `startswith("qwen")` check.

        The version above passes even with the `llm/` guard removed, because the real
        manifest's non-LLM rows are FLUX and whisper and the Qwen filter already excludes
        them. Two guards, one observable outcome, so breaking either looked harmless. This
        feeds a synthetic row that a Qwen-named IMAGE artefact would produce -- which only
        the path guard rejects.
        """
        real = registry._provenance_rows
        try:
            registry._provenance_rows = lambda: [
                {"path": "image/symoneural-image-qwen-vl.gguf",
                 "upstream_repo": "Qwen/Qwen2-VL-7B-Instruct",
                 "upstream_file": "x.gguf"},
            ]
            self.assertEqual([], registry._fetchable_pairs(),
                             "a Qwen-named artefact under image/ must not be offered as a "
                             "causal-LM training target")
        finally:
            registry._provenance_rows = real


class GgufRowsNameTheirUpstream(unittest.TestCase):
    def test_every_gguf_with_provenance_links_back(self):
        rows = [e for e in registry.scan_gguf() if e.kind == "gguf"]
        self.assertTrue(rows, "no GGUF weights found; this box should have six")
        linked = [e for e in rows if e.same_model_as]
        self.assertTrue(linked, "no GGUF row names its upstream -- the provenance index is "
                                "not being read, which is the whole point of the change")
        for e in linked:
            self.assertTrue(e.upstream, f"{e.id} has same_model_as but no upstream string")
            self.assertIn("training target", e.reason,
                          "a GGUF row should point the operator at the trainable form")


if __name__ == "__main__":
    unittest.main()
