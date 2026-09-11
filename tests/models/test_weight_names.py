"""Every weight on disk carries a house name, and every house name has a recorded origin.

The rule this enforces: nothing under `models/` is named after another company or
another repository. What is on disk is `symon-1.0-*` for the language tiers and
`symoneural-*` for everything else, and `models/PROVENANCE.json` is the single place
that records which upstream artefact each house name was fetched from.

A rename is cheap to do once and cheap to undo by accident: the next person to add a weight
will name it whatever the download was called, and `scripts/fetch-models.sh` will happily
place it. That is what these tests are for. They run with no GPU, no network and no weights
present -- the manifest is checked unconditionally, and the on-disk checks assert only about
files that actually exist, so a fresh clone with an empty `models/` passes for the right
reason rather than by being skipped wholesale.

Three things are deliberately exempt, and `test_the_documented_exemptions_are_still_the_only_ones`
pins the list so a fourth cannot be added silently. See the `note` block in the manifest for
why each one is a lookup key owned by someone else's code rather than a label we chose.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = next(_p for _p in Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
MODELS = ROOT / "models"
MANIFEST = MODELS / "PROVENANCE.json"
IMAGE_PATHS = {
    "image/symoneural-image-unet-q4_k.gguf",
    "image/symoneural-image-t5-q8_0.gguf",
    "image/symoneural-image-clip.safetensors",
    "image/symoneural-image-vae.safetensors",
}

#: Anchored at both ends of the basename. `symon`, `symoneural`, `symonsays` and `symon-*`
#: are the sanctioned prefixes; a bare `sym` is not one of them, which is why the character
#: after `symon` is constrained rather than left to `.*`.
HOUSE = re.compile(r"^symon(?:eural|says|)[-.][a-z0-9][a-z0-9._-]*$")

#: Directories holding weights we place by path and therefore control the name of. `hf/`,
#: `rembg/` and `licenses/` are absent on purpose -- see the exemption test below.
WEIGHT_DIRS = ("llm", "image", "whisper")

#: Suffixes that make a file a weight. `.lock`/`.metadata`/`.json` bookkeeping and
#: `CACHEDIR.TAG` are not weights and are not renamed.
WEIGHT_SUFFIXES = (".gguf", ".safetensors", ".bin", ".onnx", ".pt", ".pth")

EXEMPT = {
    "models/rembg": "rembg resolves a session by model name and expects <name>.onnx in U2NET_HOME",
    "models/hf": "the huggingface_hub cache layout -- the directory name IS the index",
    "models/licenses": "third-party licence texts; a licence that does not name its licensor is not a licence",
}


class ManifestShape(unittest.TestCase):
    """The manifest itself, checkable without any weights on disk."""

    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(MANIFEST.read_text())
        cls.weights = cls.doc["weights"]

    def test_the_manifest_is_not_empty(self):
        # Vacuity guard. Every other test in this class is a loop over `weights`, so an empty
        # list would turn the whole file green while asserting nothing at all.
        self.assertGreaterEqual(len(self.weights), 5, "manifest has suspiciously few entries")

    def test_every_entry_names_its_upstream_and_its_licence(self):
        for w in self.weights:
            with self.subTest(path=w["path"]):
                self.assertTrue(w.get("upstream_repo"), "no upstream_repo")
                self.assertTrue(w.get("upstream_file"), "no upstream_file")
                self.assertTrue(w.get("license"), "no license")
                self.assertIn("role", w, "no role -- what is this file for?")

    def test_image_entries_require_immutable_revisions_and_sha256(self):
        images = {w["path"]: w for w in self.weights if w["path"].startswith("image/")}
        self.assertEqual(set(images), IMAGE_PATHS)
        for path, w in images.items():
            with self.subTest(path=path):
                self.assertIsNotNone(re.fullmatch(r"[0-9a-f]{40}", w["upstream_revision"]))
                self.assertIsNotNone(re.fullmatch(r"[0-9a-f]{64}", w["sha256"]))

    def test_every_entry_is_named_to_the_house_rule(self):
        for w in self.weights:
            with self.subTest(path=w["path"]):
                self.assertRegex(Path(w["path"]).name, HOUSE)

    def test_no_entry_claims_we_modified_the_weights(self):
        # We rename; we do not re-quantise or merge. If that ever changes, this test is the
        # place it has to be argued -- a `true` here means the artefact is a derivative work
        # and the licence obligations shift with it.
        for w in self.weights:
            with self.subTest(path=w["path"]):
                self.assertFalse(w["modified_by_us"])

    def test_paths_are_relative_and_unique(self):
        seen = [w["path"] for w in self.weights]
        self.assertEqual(len(seen), len(set(seen)), "duplicate path in manifest")
        for p in seen:
            self.assertFalse(p.startswith("/"), f"{p} is absolute")

    def test_the_documented_exemptions_are_still_the_only_ones(self):
        # The manifest's own `note` must carry a reason for each exemption. This is what stops
        # a fourth directory being quietly added to EXEMPT above with no justification: the
        # reason has to be written down where a reader of the manifest will find it.
        note = "\n".join(self.doc["note"])
        for path in EXEMPT:
            with self.subTest(exempt=path):
                self.assertIn(path, note, f"{path} is exempt in code but unexplained in the manifest")


class OnDisk(unittest.TestCase):
    """Checks about files that are actually here. Silent when `models/` is empty."""

    def _weights(self):
        for d in WEIGHT_DIRS:
            base = MODELS / d
            if not base.is_dir():
                continue
            for f in sorted(base.iterdir()):
                if f.is_file() and f.suffix.lower() in WEIGHT_SUFFIXES:
                    yield f

    def test_no_weight_on_disk_carries_a_foreign_name(self):
        found = list(self._weights())
        if not found:
            self.skipTest("no weights on this box")
        for f in found:
            with self.subTest(name=f.name):
                self.assertRegex(f.name, HOUSE)

    def test_every_weight_on_disk_is_in_the_manifest(self):
        found = list(self._weights())
        if not found:
            self.skipTest("no weights on this box")
        known = {w["path"] for w in json.loads(MANIFEST.read_text())["weights"]}
        for f in found:
            with self.subTest(name=f.name):
                self.assertIn(f.relative_to(MODELS).as_posix(), known,
                              "on disk but not in PROVENANCE.json -- where did it come from?")

    def test_recorded_byte_counts_match_the_files(self):
        # The manifest calls these measured, so they are checked. This is also the cheapest
        # detector of a truncated or substituted download: a resumed `curl -C -` that stopped
        # early leaves a plausible-looking file with the wrong length.
        checked = 0
        for w in json.loads(MANIFEST.read_text())["weights"]:
            f = MODELS / w["path"]
            if not f.is_file():
                continue
            with self.subTest(path=w["path"]):
                self.assertEqual(f.stat().st_size, w["bytes_on_disk"])
            checked += 1
        if not checked:
            self.skipTest("no weights on this box")


    def test_recorded_image_sha256_matches_existing_payloads(self):
        checked = 0
        for w in json.loads(MANIFEST.read_text())["weights"]:
            path = MODELS / w["path"]
            if w["path"] not in IMAGE_PATHS or not path.is_file():
                continue
            with self.subTest(path=w["path"]), path.open("rb") as payload:
                digest = hashlib.sha256()
                for chunk in iter(lambda: payload.read(1024 * 1024), b""):
                    digest.update(chunk)
                self.assertEqual(digest.hexdigest(), w["sha256"])
            checked += 1
        if not checked:
            self.skipTest("no image weights on this box")


class ImageProvenanceFetch(unittest.TestCase):
    """Run the real fetch script in a tiny /tmp repository with a local curl stub.

    No network or production paths are used. Same-length wrong bytes must never
    become an accepted house payload, whether reused, renamed, or downloaded.
    """

    PAYLOAD = b"verified image fixture\n"

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="symoneural-provenance-", dir="/tmp")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.models = self.root / "models"
        self.models.mkdir(parents=True)
        (self.root / "backend").mkdir()
        (self.root / "backend/server.py").touch()
        (self.root / "scripts").mkdir()
        self.script = self.root / "scripts/fetch-models.sh"
        shutil.copyfile(ROOT / "scripts/fetch-models.sh", self.script)
        self.doc = json.loads(MANIFEST.read_text())
        self.images = [w for w in self.doc["weights"] if w["path"] in IMAGE_PATHS]
        for w in self.doc["weights"]:
            path = self.models / w["path"]
            path.parent.mkdir(exist_ok=True)
            if w["path"] in IMAGE_PATHS:
                w["sha256"] = hashlib.sha256(self.PAYLOAD).hexdigest()
                w["bytes_on_disk"] = len(self.PAYLOAD)
            else:
                path.write_bytes(b"existing unrelated model")
            if w["license_text"]:
                license_path = self.models / w["license_text"]
                license_path.parent.mkdir(exist_ok=True)
                license_path.write_text("existing license")
        self._save_manifest()
        (self.root / "bin").mkdir()
        curl = self.root / "bin/curl"
        curl.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "args = sys.argv[1:]\n"
            "with open(os.environ['CURL_CALLS'], 'a') as log:\n"
            "    log.write(json.dumps(args) + '\\n')\n"
            "Path(args[args.index('-o') + 1]).write_bytes(os.environ['CURL_PAYLOAD'].encode())\n"
        )
        curl.chmod(0o755)
        self.calls_file = self.root / "curl.calls"
        self.env = dict(os.environ, PATH=str(curl.parent) + os.pathsep + os.environ["PATH"],
                        PYTHONDONTWRITEBYTECODE="1", CURL_CALLS=str(self.calls_file),
                        CURL_PAYLOAD=self.PAYLOAD.decode(), SYMONEURAL_FETCH_27B="0",
                        SYMONEURAL_FETCH_32B="0")

    def _save_manifest(self):
        (self.models / "PROVENANCE.json").write_text(json.dumps(self.doc))

    def _run(self):
        return subprocess.run(["bash", str(self.script)], cwd=self.root, env=self.env,
                              text=True, capture_output=True, timeout=20)

    def _calls(self):
        return [json.loads(line) for line in self.calls_file.read_text().splitlines()] if self.calls_file.exists() else []

    def test_download_urls_are_pinned_and_verified_before_promotion(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertCountEqual([args[-1] for args in self._calls()], [
            f"https://huggingface.co/{w['upstream_repo']}/resolve/{w['upstream_revision']}/{w['upstream_file']}"
            for w in self.images
        ])
        for w in self.images:
            path = self.models / w["path"]
            self.assertEqual(path.read_bytes(), self.PAYLOAD)
            self.assertFalse(Path(str(path) + ".part").exists())

    def test_existing_verified_house_files_are_reused_without_fetching(self):
        for w in self.images:
            (self.models / w["path"]).write_bytes(self.PAYLOAD)
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._calls(), [])

    def test_matching_legacy_files_are_verified_before_adoption(self):
        for w in self.images:
            (self.models / "image" / w["upstream_file"]).write_bytes(self.PAYLOAD)
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._calls(), [])
        for w in self.images:
            self.assertFalse((self.models / "image" / w["upstream_file"]).exists())
            self.assertEqual((self.models / w["path"]).read_bytes(), self.PAYLOAD)

    def test_same_size_corrupt_house_file_fails_without_replacement(self):
        w = self.images[0]
        path = self.models / w["path"]
        corrupt = b"x" * len(self.PAYLOAD)
        path.write_bytes(corrupt)
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA-256 mismatch", result.stderr)
        self.assertEqual(path.read_bytes(), corrupt)
        self.assertEqual(self._calls(), [])

    def test_same_size_corrupt_legacy_file_is_not_adopted(self):
        w = self.images[0]
        legacy = self.models / "image" / w["upstream_file"]
        corrupt = b"x" * len(self.PAYLOAD)
        legacy.write_bytes(corrupt)
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA-256 mismatch", result.stderr)
        self.assertEqual(legacy.read_bytes(), corrupt)
        self.assertFalse((self.models / w["path"]).exists())
        self.assertEqual(self._calls(), [])

    def test_same_size_corrupt_download_is_not_promoted(self):
        self.env["CURL_PAYLOAD"] = "x" * len(self.PAYLOAD)
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA-256 mismatch", result.stderr)
        for w in self.images:
            self.assertFalse((self.models / w["path"]).exists())
        self.assertEqual(len(self._calls()), 1)
        part = Path(str(self.models / self.images[0]["path"]) + ".part")
        self.assertEqual(part.read_bytes(), self.env["CURL_PAYLOAD"].encode())

    def test_missing_or_invalid_pins_fail_closed(self):
        for field, value in (("upstream_revision", "main"), ("upstream_revision", None),
                             ("sha256", "0" * 63), ("sha256", None)):
            with self.subTest(field=field, value=value):
                old = self.images[0].pop(field)
                if value is not None:
                    self.images[0][field] = value
                self._save_manifest()
                result = self._run()
                self.images[0][field] = old
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("image provenance", result.stderr)
                self.assertEqual(self._calls(), [])
        self._save_manifest()

    def test_unrelated_model_adoption_and_main_fetch_are_unchanged(self):
        for w in self.images:
            (self.models / w["path"]).write_bytes(self.PAYLOAD)
        language = [w for w in self.doc["weights"] if w["path"].startswith("llm/")]
        adopted, fetched = language[:2]
        adopted_path = self.models / adopted["path"]
        old_bytes = adopted_path.read_bytes()
        legacy = adopted_path.parent / adopted["upstream_file"]
        adopted_path.rename(legacy)
        (self.models / fetched["path"]).unlink()
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(adopted_path.read_bytes(), old_bytes)
        self.assertFalse(legacy.exists())
        self.assertEqual([args[-1] for args in self._calls()], [
            f"https://huggingface.co/{fetched['upstream_repo']}/resolve/main/{fetched['upstream_file']}"
        ])
        self.assertEqual((self.models / fetched["path"]).read_bytes(), self.PAYLOAD)


class NoForeignNamesInCode(unittest.TestCase):
    """The code must not point at an upstream filename either."""

    #: Basenames the code used to carry. Kept as literals rather than a pattern: a pattern
    #: broad enough to catch "any upstream model filename" also catches the `upstream_file`
    #: fields in the manifest and the fetch URLs in fetch-models.sh, both of which must
    #: keep the upstream name to function.
    LEGACY = (
        "Qwen2.5-7B-Instruct-Q4_K_M.gguf", "Qwen2.5-14B-Instruct-Q4_K_M.gguf",
        "Qwen2.5-0.5B-Instruct-Q4_K_M.gguf", "Qwen3.6-27B-UD-Q2_K_XL.gguf",
        "flux1-schnell-q4_k.gguf", "t5xxl-Q8_0.gguf", "clip_l.safetensors",
        "ae.safetensors", "ggml-base.en.bin",
    )

    #: Files allowed to name an upstream artefact, and the reason each one must.
    ALLOWED = {
        "scripts/fetch-models.sh": "the download URL is the upstream path; it cannot be rebranded",
        "models/PROVENANCE.json": "this file exists to record the mapping",
        "backend/test_weight_names.py": "the LEGACY list above",
    }

    def test_no_source_file_resolves_a_weight_by_its_upstream_name(self):
        targets = []
        for pat in ("backend/**/*.py", "tools/*.py", "scripts/*.sh"):
            targets += [p for p in ROOT.glob(pat) if p.is_file()]
        offenders = []
        for p in targets:
            rel = p.relative_to(ROOT).as_posix()
            if rel in self.ALLOWED or "/.venv/" in rel or "/custom_nodes/" in rel:
                continue
            try:
                body = p.read_text(errors="ignore")
            except OSError:
                continue
            for legacy in self.LEGACY:
                # Boundary-matched, not substring-matched. `ae.safetensors` is a suffix of
                # the house name `symoneural-image-vae.safetensors`, so a plain `in` check
                # reports every file that was correctly renamed. This bit once.
                if re.search(r"(?<![A-Za-z0-9._-])" + re.escape(legacy), body):
                    offenders.append(f"{rel}: {legacy}")
        self.assertEqual(offenders, [], "upstream weight filenames still in source")


class NamesDocumentAgreesWithManifest(unittest.TestCase):
    """`models/NAMES.md` is the reader's copy of the manifest, and must stay one.

    Task #74 item 3 asks for a table "mapping each SyMoNeuRaL name to its upstream model and
    licence", because that table is what attribution is rendered from. Two copies of the same
    facts is exactly the arrangement this repo has been bitten by before -- three files once
    claimed to describe current state and agents acted on the stale one -- so the second copy
    only earns its place if drifting from the first is a test failure.

    Asserted in both directions on purpose. Missing a row is the obvious failure: a weight
    gets added to the manifest, nobody updates the prose, and the site renders attribution
    for ten of eleven artefacts. The reverse matters as much and is less obvious -- a row
    here for something no longer in the manifest is an attribution claim about bytes that are
    not on this box, which is the same species of untruth as a decorative status LED.

    It does not assert the prose, only the table. NAMES.md carries reasoning the JSON has no
    place for, including a section recording that three entries have no licence text on disk;
    pinning the whole document would make writing that down a test failure.
    """

    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(MANIFEST.read_text())
        cls.names = (MODELS / "NAMES.md").read_text(encoding="utf-8")

    def test_the_document_exists_and_is_not_a_stub(self):
        # The declared check on #74 is `grep upstream -- models/NAMES.md`, which a
        # one-line file satisfies -- and a task that archives on a stub is worse than one that
        # never closed. This is the floor that word-count check cannot express.
        self.assertGreater(len(self.names), 2000, "NAMES.md is too short to be the table")
        self.assertIn("upstream", self.names.lower())

    def test_every_manifest_entry_appears_with_its_upstream_and_licence(self):
        missing = []
        for w in self.doc["weights"]:
            basename = w["path"].rsplit("/", 1)[-1]
            for field in (basename, w["upstream_repo"], w["upstream_file"], w["license"]):
                if field and field not in self.names:
                    missing.append(f"{basename}: {field!r}")
        self.assertEqual(missing, [], "NAMES.md has drifted from PROVENANCE.json")

    def test_no_house_name_in_the_document_is_absent_from_the_manifest(self):
        recorded = {w["path"].rsplit("/", 1)[-1] for w in self.doc["weights"]}
        # Only names that look like a weight we placed. The document also names the three
        # documented exemptions (`u2net.onnx`, the `hf/` cache, the licence texts), and those
        # are correctly absent from the manifest -- that is what makes them exemptions.
        cited = set(re.findall(r"`(symon[a-z0-9._-]+\.(?:gguf|safetensors|bin))`", self.names))
        stale = sorted(cited - recorded)
        self.assertEqual(stale, [], "NAMES.md attributes a weight that is not in the manifest")

    def test_the_exemptions_are_explained_here_too(self):
        """A reader who only opens NAMES.md must still learn why three names are foreign."""
        for path in EXEMPT:
            self.assertIn(path.rsplit("/", 1)[-1], self.names, f"{path} unexplained in NAMES.md")


if __name__ == "__main__":
    unittest.main()
