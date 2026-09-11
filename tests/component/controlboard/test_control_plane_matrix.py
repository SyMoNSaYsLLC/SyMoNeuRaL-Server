"""The Control Plane Matrix, held to its own claims.

A matrix of ratings and reachability cells is prose, and prose drifts. These tests exist so the
four documents cannot quietly stop being true:

  * `backend/controlboard/docs/symoneural-control-plane-matrix.md`
  * `ops/docs/APPLICATION-MODEL-CAPABILITY-MATRIX.md`
  * `ops/docs/MODEL-BENCHMARKS.md`
  * `ops/docs/VLLM-BENCH-PARITY.md`

**Everything here is pure parse plus `stat`.** Nothing is imported from the app, no subprocess is
launched, and in particular nothing under `scripts/model-staging/` is invoked -- that script rewrites
`ROLLBACK.md` on its refusal path, so a test that shelled out to it would have a filesystem side
effect. Measured 2026-08-23: running `test_model_staging.py` does exactly that, by design.

The four assertions worth having are the ones a document cannot satisfy by being well written:

  1. every app module a capability cell names actually exists;
  2. the instance count in prose equals the number of table rows (the "19 vs 20" class of drift);
  3. every benchmark figure appears in BOTH the ledger and its narrative source, so duplication is
     enforced rather than trusted;
  4. a claim contradicted by the disk fails -- specifically the two claims this batch corrected.

Each was verified by sabotage, not by going green — and the harness that does it is **tracked**, so
the proof is reproducible rather than asserted:

    python3 tools/lib/sabotage_matrix.py          # 12 mutations, each must turn one test red
    python3 tools/lib/sabotage_matrix.py --list   # inspect the cases, mutate nothing

`apps/test_sabotage_matrix.py` keeps that harness honest (anchors present, test ids real) without
running it, so `pytest apps/` stays free of side effects.
"""

import pathlib
import re
import unittest

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
DOCS = ROOT / "ops" / "docs"

MATRIX = DOCS / "specs" / "symoneural-control-plane-matrix.md"
CAPABILITY = DOCS / "ops" / "APPLICATION-MODEL-CAPABILITY-MATRIX.md"
BENCHMARKS = DOCS / "ops" / "MODEL-BENCHMARKS.md"
PARITY = DOCS / "ops" / "VLLM-BENCH-PARITY.md"
BOOTCAMP = DOCS / "specs" / "symoneural-bootcamp.md"
MIGRATION = DOCS / "ops" / "OPENAI-GPT-OSS-MIGRATION.md"

APPS = ROOT / "backend" / "apps"
MODELS = ROOT / "backend" / "models"
SCOUT = ROOT / "tools" / "bootcamp_scout.py"


def is_app_module_dir(path):
    """Is this directory an app module, as `tools/lib/bootcamp_scout.py` counts them?

    **This function exists because its first version was wrong in a way that only surfaced after
    the merge.** It excluded `__pycache__` and nothing else, while the comment above it claimed to
    match the Scout -- which excludes any `__`-prefixed *or* dot-prefixed name
    (`bootcamp_scout.py:189`). A stray `backend/.pytest_cache`, left behind by an earlier
    pytest run, was counted as an 18th app module, so the count test failed on `main` while passing
    in the worktree that happened not to have that directory.

    Two lessons, and the second is why this is a named function instead of an inline generator:

      * **a transient cache directory must never be able to move a published figure.** `17` is
        quoted by four documents; a leftover directory is not a product decision, and a test that
        lets one change the answer is measuring the filesystem's mood;
      * **"matches the Scout" has to be enforced, not asserted.** It was asserted -- in a comment,
        directly above a filter that did something else. `test_the_filter_matches_the_scouts_own_
        predicate` now pins the two together so they cannot drift again.
    """
    return (path.is_dir()
            and path.name != "__pycache__"
            and not path.name.startswith("."))

#: The whisper runtime both `voice` and `sigils` resolve. Absent on this box, which is the whole
#: point of `test_no_document_claims_asr_is_serving_while_its_runtime_is_absent`.
WHISPER_CLI = ROOT / "contrib" / "whisper.cpp" / "build" / "bin" / "whisper-cli"

#: vLLM lives outside the repo, so no in-repo search can find it -- which is how four documents
#: called it `absent` for three weeks. Detected by directory rather than by import: importing vLLM
#: costs seconds and pulls in torch, and this test only needs to know it is installed.
VLLM_VENV = pathlib.Path.home() / ".venvs" / "vllm"


def read(path):
    return path.read_text(encoding="utf-8")


class DocumentsExist(unittest.TestCase):
    def test_all_four_matrix_documents_are_present(self):
        for path in (MATRIX, CAPABILITY, BENCHMARKS, PARITY):
            with self.subTest(doc=path.name):
                self.assertTrue(path.is_file(), f"{path} is missing")


class CapabilityCellsNameRealThings(unittest.TestCase):
    """A reachability cell that names a module which does not exist is worse than no cell."""

    def test_every_app_module_named_in_the_capability_matrix_exists(self):
        text = read(CAPABILITY)
        # The row labels are `**`name`**`-style backticked module names in the leftmost column.
        named = set(re.findall(r"\*\*`([a-z_]+)`\*\*", text))
        # `api.py` is a file, not a package; every other name must be a directory under apps/.
        named.discard("api.py")
        self.assertTrue(named, "parsed no module names -- the parser broke, not the doc")
        for mod in sorted(named):
            with self.subTest(module=mod):
                self.assertTrue((APPS / mod).is_dir(),
                                f"capability matrix names backend/{mod}, which is not a directory")

    def test_every_source_line_citation_points_at_a_file_that_exists(self):
        """`sigils/render.py:86-89` is a checkable claim. An unresolvable path is a dead citation.

        Requires a `/` in the path on purpose: a bare `asr.py:106` is ambiguous across the tree,
        and this test caught exactly that in the first draft of the capability doc.
        """
        text = read(CAPABILITY)
        cites = set(re.findall(r"`((?:backend/)?[a-z_]+(?:/[a-z_0-9]+)+\.py):[0-9]", text))
        self.assertTrue(cites, "parsed no source citations")
        for cite in sorted(cites):
            with self.subTest(cite=cite):
                candidates = [ROOT / cite, ROOT / "backend" / cite, APPS / cite]
                self.assertTrue(any(c.is_file() for c in candidates),
                                f"citation {cite} resolves to no file on disk")


class CountsMatchTheTables(unittest.TestCase):
    """The "19 vs 20" class of bug: a number in prose that stopped matching the table under it."""

    def test_the_stated_instance_count_equals_the_number_of_matrix_rows(self):
        text = read(MATRIX)
        stated = re.search(r"\*\*(\d+) instances across (\d+) app modules\.?\*\*", text)
        self.assertIsNotNone(stated, "the matrix no longer states its instance count")
        claimed_instances = int(stated.group(1))

        section = text[text.index("## 4. The matrix"):text.index("## 5. What the Runtime")]
        # A data row starts with `| **Name**`; the header and separator do not.
        rows = re.findall(r"^\| \*\*", section, flags=re.M)
        self.assertEqual(claimed_instances, len(rows),
                         f"matrix claims {claimed_instances} instances but the table has {len(rows)} rows")

    def test_the_stated_app_module_count_equals_the_tree(self):
        text = read(MATRIX)
        stated = re.search(r"\*\*(\d+) instances across (\d+) app modules\.?\*\*", text)
        self.assertIsNotNone(stated)
        claimed_modules = int(stated.group(2))
        # Directories, which is how `tools/lib/bootcamp_scout.py` counts and therefore what every
        # document quotes. Measured 2026-09-04: 20 directories, of which only 18 hold an
        # `__init__.py` -- `ravencalc` and `remix` are not importable packages. Counting packages
        # here would silently disagree with the Scout by two, which is the drift this class exists
        # to catch, so the definition is pinned rather than left to taste.
        #
        # The filter lives in `is_app_module_dir` so that "transient directories do not count" is
        # one rule with one test behind it, rather than a condition repeated at each call site.
        actual = sorted(p.name for p in APPS.iterdir() if is_app_module_dir(p))
        self.assertEqual(claimed_modules, len(actual),
                         f"matrix claims {claimed_modules} app modules; the tree has {len(actual)}: {actual}")

    def test_transient_cache_directories_are_not_app_modules(self):
        """The post-merge failure, as a unit test: a leftover `.pytest_cache` made the count 18.

        Synthetic names on purpose -- creating a real directory under `backend/apps` would be a
        filesystem side effect in `pytest apps/`, which is precisely the kind of leftover that
        caused the bug. `pathlib.Path` needs no filesystem to answer `.name`, and `is_dir()` is
        supplied by a stub so the name filter is what gets tested.
        """
        class Dir:
            def __init__(self, name): self.name = name
            def is_dir(self): return True

        for name in (".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache", ".hypothesis",
                     ".DS_Store", ".ipynb_checkpoints", "__pycache__"):
            with self.subTest(directory=name):
                self.assertFalse(is_app_module_dir(Dir(name)),
                                 f"{name} must never be counted as an app module")

        for name in ("voice", "sigils", "ravencalc", "studio", "asicminer"):
            with self.subTest(directory=name):
                self.assertTrue(is_app_module_dir(Dir(name)),
                                f"{name} is a real app module and must be counted")

    def test_the_filter_matches_the_scouts_own_predicate(self):
        """The Scout is the source of the number every document quotes, so this test must not
        merely *claim* to agree with it. `bootcamp_scout.py:189` skips any name starting with `__`
        or `.`; if that line changes, this goes red rather than silently disagreeing."""
        src = SCOUT.read_text(encoding="utf-8")
        self.assertRegex(src, r'name\.startswith\(\s*"__"\s*\)',
                         "the Scout no longer skips dunder directories; re-derive the filter")
        self.assertRegex(src, r'name\.startswith\(\s*"\."\s*\)',
                         "the Scout no longer skips dot directories; re-derive the filter")

    def test_the_module_count_is_stable_against_whatever_is_on_disk_now(self):
        """Belt and braces: the live tree must produce exactly the published figure, and the
        failure message names the offender rather than only the count."""
        counted = sorted(p.name for p in APPS.iterdir() if is_app_module_dir(p))
        rejected = sorted(p.name for p in APPS.iterdir() if p.is_dir() and not is_app_module_dir(p))
        self.assertEqual(20, len(counted),
                         f"expected 20 app modules, counted {len(counted)}: {counted} "
                         f"(rejected as transient: {rejected})")


class DepthChartsKeepExactlyThreeOptions(unittest.TestCase):
    """Bootcamp §5 declares "exactly three primary options" per position. Measured 2026-08-23:
    19 positions, all 3. A fourth option is not a richer chart -- it means the format that makes
    positions comparable has been abandoned in one place and nowhere else."""

    def positions(self):
        text = read(BOOTCAMP)
        body = text[text.index("## 5. Depth charts"):text.index("## 6. What this chart")]
        return [s for s in re.split(r"\n### ", body)[1:]]

    def test_every_depth_chart_position_declares_exactly_three_options(self):
        positions = self.positions()
        self.assertGreaterEqual(len(positions), 19, "depth chart positions vanished")
        for section in positions:
            title = section.split("\n")[0].strip()
            with self.subTest(position=title[:48]):
                opts = sorted(set(re.findall(r"\*\*Option (\d)", section)))
                self.assertEqual(["1", "2", "3"], opts,
                                 f"{title[:48]!r} declares options {opts}, not exactly 1/2/3")


class BenchmarkFiguresAgreeWithTheirSource(unittest.TestCase):
    """MODEL-BENCHMARKS.md transcribes figures whose narrative lives in OPENAI-GPT-OSS-MIGRATION.md.

    Duplication across two files is how a figure gets carried forward and re-dated -- the one
    thing this repo says never to do. So the duplication is made safe by being enforced: every
    figure must appear in BOTH files, and editing one without the other goes red.
    """

    #: Rows shared by the ledger's §1 table and the narrative's benchmark table. Compared as
    #: whole rows, NOT as "does this number appear somewhere in the file" -- the first draft of
    #: this test did the latter and a deliberate mutation of the `generation` cell went GREEN,
    #: because `166.3` also occurs in prose two sections later. A substring search over a whole
    #: document cannot tell a table cell from a mention of it.
    ROW_LABELS = ("load", "peak VRAM", "prompt", "generation",
                  "tokens for a one-sentence answer", "wall clock")

    @staticmethod
    def numbers_in(text):
        return re.findall(r"[0-9][0-9,]*\.?[0-9]*", text)

    def row(self, text, label):
        """The numbers on the table row whose first cell is `label`, in order."""
        for line in text.splitlines():
            if not line.startswith("|"):
                continue
            cells = [c.strip().strip("*") for c in line.strip("|").split("|")]
            if cells and cells[0].strip("*").strip() == label:
                return [self.numbers_in(c) for c in cells[1:]]
        return None

    def test_every_benchmark_row_matches_its_narrative_source_cell_for_cell(self):
        ledger, narrative = read(BENCHMARKS), read(MIGRATION)
        for label in self.ROW_LABELS:
            with self.subTest(row=label):
                a, b = self.row(ledger, label), self.row(narrative, label)
                self.assertIsNotNone(a, f"row {label!r} missing from the benchmark ledger")
                self.assertIsNotNone(b, f"row {label!r} missing from its narrative source")
                self.assertEqual(a, b,
                                 f"row {label!r} disagrees between the ledger and its source: "
                                 f"{a} vs {b}")

    def test_the_probe_and_smoke_figures_appear_in_both_files(self):
        """These live in prose rather than a shared table, so presence is the honest check."""
        for fig in ("14,297", "14,229", "15,409", "164.4", "165.4", "454.0", "12,664", "5,261",
                    "16,303", "239"):
            with self.subTest(figure=fig):
                self.assertIn(fig, read(BENCHMARKS), f"{fig} missing from the ledger")
                self.assertIn(fig, read(MIGRATION), f"{fig} missing from its narrative source")

    def test_each_benchmark_section_attributes_its_figures_to_a_sha(self):
        """A figure with no SHA cannot be checked. This repo has published one that was never true
        of the commit beside it, so the SHA is not decoration.

        Requires the SHA on an explicit `SHA `<hex>`` attribution line rather than anywhere in the
        section: the first draft accepted the section HEADING's copy of the SHA, so deleting the
        attribution line entirely still passed.
        """
        text = read(BENCHMARKS)
        bounds = ("## 1. LLM benchmark", "## 2. Production-argv probes", "## 3. Candidate smoke",
                  "## 4. What is NOT measured")
        for i, heading in enumerate(bounds[:-1]):
            self.assertIn(heading, text, f"{heading} is gone")
            body = text[text.index(heading):text.index(bounds[i + 1])]
            with self.subTest(section=heading):
                self.assertRegex(body, r"\*\*SHA `[0-9a-f]{8}`",
                                 f"{heading} states figures with no `**SHA <hex>`` attribution")


class ClaimsContradictedByTheDiskFail(unittest.TestCase):
    """The two corrections this batch made, locked so they cannot be re-introduced."""

    def test_no_document_calls_vllm_absent_while_it_is_installed(self):
        if not VLLM_VENV.is_dir():
            self.skipTest(f"no vLLM venv at {VLLM_VENV}; nothing to contradict")
        installed = list(VLLM_VENV.glob("lib/*/site-packages/vllm")) or [VLLM_VENV / "vllm"]
        if not any(p.exists() for p in installed):
            self.skipTest("vLLM venv exists but holds no vllm package")

        offenders = []
        for doc in sorted(DOCS.rglob("*.md")):
            for i, line in enumerate(read(doc).splitlines(), 1):
                low = line.lower()
                if "vllm" not in low:
                    continue
                # Blockquote lines are skipped: a dated correction block has to be able to QUOTE
                # the false claim it is retracting, and flagging that quotation would make the
                # repo's own correction style untestable. This test caught its own author doing
                # exactly that, which is why the exemption is narrow -- blockquotes only.
                if line.lstrip().startswith(">"):
                    continue
                # Same principle, different punctuation: a line that RETRACTS the claim on
                # the same line is not asserting it. The blockquote rule above covers a
                # correction block; this covers a historical LEDGER, where the retraction
                # is a table cell beside the claim rather than prose beneath it --
                # ops/history/handoffs/GARRETT-MEMORY-REQUEST.md:146 reads
                #     | vLLM is not installed | `SUPERSEDED`. Present in its venv; ... |
                # which records that the claim was wrong. Flagging that would make the
                # repository unable to write down its own corrected mistakes, which is the
                # same failure the blockquote exemption exists to prevent.
                if any(w in line.upper() for w in ("SUPERSEDED", "RETRACTED", "CORRECTED",
                                                   "WAS WRONG", "NO LONGER TRUE")):
                    continue
                # "no service is running" / "candidate only" are TRUE and must stay allowed. So is
                # "a running vLLM SERVICE is absent" -- the distinction this whole correction is
                # about is package-absent (false) vs service-absent (true), and a check that
                # flagged the true half would push the docs back toward the conflation it fixed.
                if re.search(r"\b(service|process|port|unit|serving)\b", low):
                    continue
                if re.search(r"\bnot installed\b", low) or re.search(
                        r"vllm[^|\n]{0,80}\|\s*\*\*absent\*\*", low) or re.search(
                        r"maturity:\s*absent", low):
                    offenders.append(f"{doc.relative_to(ROOT)}:{i}: {line.strip()[:100]}")
        self.assertEqual([], offenders,
                         "vLLM is installed and importable; these lines still say otherwise:\n"
                         + "\n".join(offenders))

    def test_no_document_claims_asr_is_serving_while_its_runtime_is_absent(self):
        if WHISPER_CLI.is_file():
            self.skipTest("whisper-cli is present; the ASR claim would be legitimate")
        # Bootcamp only: it owns the depth chart, so it is the file where "proof: serving" would be
        # read as a capability claim. The other documents legitimately QUOTE the retracted wording
        # when explaining the correction, and blockquotes are skipped here for the same reason.
        offenders = []
        for doc in (BOOTCAMP,):
            for i, line in enumerate(read(doc).splitlines(), 1):
                low = line.lower()
                if line.lstrip().startswith(">"):
                    continue
                if ("asr" in low or "whisper" in low) and re.search(
                        r"\*\*proof\*\* serving", low):
                    offenders.append(f"{doc.relative_to(ROOT)}:{i}: {line.strip()[:100]}")
        self.assertEqual([], offenders,
                         f"{WHISPER_CLI} is absent, so ASR cannot be serving:\n" + "\n".join(offenders))

    def test_the_matrix_records_the_asr_runtime_as_absent(self):
        """Not just the absence of a false claim -- the presence of the true one."""
        if WHISPER_CLI.is_file():
            self.skipTest("whisper-cli is present")
        self.assertRegex(read(MATRIX), r"whisper\.cpp\*\* \*\*absent\*\*|`whisper\.cpp` \*\*absent\*\*",
                         "the matrix no longer records the ASR runtime as absent")


class WeightNamesResolve(unittest.TestCase):
    """Skips rather than fails where the weights are not present -- the convention
    `test_weight_names.py` already uses, and necessary because `backend/models` is gitignored and
    is empty in a fresh worktree."""

    #: The persona adapter lives under `training/`, not `backend/models` -- it is protected and
    #: reported separately -- so both roots are searched. Getting this wrong made the first draft
    #: of this test report a missing weight that was simply somewhere else.
    WEIGHT_ROOTS = (MODELS, ROOT / "training")

    def test_every_weight_filename_named_in_the_capability_matrix_exists(self):
        # Count only files with a weight extension. Keying the skip on "is the directory empty"
        # was wrong: in a worktree, `training/` holds tracked JSON and scripts while every actual
        # weight is gitignored and absent -- so the guard never fired and the test failed on a
        # clone that legitimately has no weights.
        suffixes = {".gguf", ".safetensors", ".bin", ".onnx"}
        present = set()
        for root in self.WEIGHT_ROOTS:
            if root.is_dir():
                present |= {p.name for p in root.rglob("*")
                            if p.is_file() and p.suffix in suffixes}
        if not present:
            self.skipTest("no weight files in this clone (backend/models is gitignored)")

        text = read(CAPABILITY)
        named = set(re.findall(r"`([a-z0-9._-]+\.(?:gguf|safetensors|bin|onnx))`", text))

        # Guard against the assertion going vacuous. The first draft of this test parsed ZERO
        # filenames -- the doc named weights by column header, not by filename -- so it passed
        # without checking anything. A test that cannot fail is worse than no test, because it
        # reports confidence it never earned.
        #
        # This counts what the PARSER found, before the present/absent split below. Counting the
        # present-only subset instead would mean the doc could satisfy the guard by shrinking:
        # marking a weight ABSENT would lower the number this checks, so documenting an absence
        # would weaken the parser check, which is backwards.
        self.assertGreaterEqual(len(named), 10,
                                f"parsed only {len(named)} weight filenames from the capability "
                                f"matrix; it should name at least 10 in full")

        # A weight the matrix marks **ABSENT** is a claim too, and the opposite one, so it is
        # checked in the opposite direction rather than skipped. Skipping would let the doc say
        # ABSENT about a file that is sitting right there -- the same class of untrue-but-green
        # statement this test was written to catch, only inverted.
        #
        # 2026-09-03: `symon-1.0-14b-q4_k_m.gguf` became the first of these. The doc had said
        # "on disk (8.99 GB) and manifested" while a filesystem-wide search found it nowhere,
        # and this assertion was what refused to go green over it.
        absent = {n for n in named
                  for line in text.splitlines()
                  if f"`{n}`" in line and "ABSENT" in line}
        for name in sorted(absent):
            with self.subTest(weight=name, direction="absent"):
                self.assertNotIn(name, present,
                                 f"capability matrix marks {name} ABSENT, but it is on disk "
                                 f"in {[str(r) for r in self.WEIGHT_ROOTS]}")
        named -= absent
        for name in sorted(named):
            with self.subTest(weight=name):
                self.assertIn(name, present,
                              f"capability matrix names {name}, absent from "
                              f"{[str(r) for r in self.WEIGHT_ROOTS]}")


class SafetyRatingsAreDerivedNotTyped(unittest.TestCase):
    """The matrix claims its Safety column is derived. This class is what makes that true.

    A review found four hand-typed cells that no test could catch, because nothing recomputed
    them. The worst was a straight contradiction: `public - none - read` read `S-med` on five rows
    and `S-low` on RavenCalc, under a rule that was not even a total function -- it had no cell for
    that triple at all, so six rows were decided by prose and two of them differently.

    So both halves are checked here: the ratings against the declared table, and the EXPOSURE
    inputs against `api.py`'s mount table, since exposure feeds every rating and was the least
    verified thing in the batch.
    """

    @staticmethod
    def clean(cell):
        """Strip bold, backticks and footnote superscripts -- markup is not data."""
        return re.sub(r"[*`¹²³⁴⁵⁶⁷⁸⁹⁰]", "", cell).strip()

    def derivation_table(self):
        """The (exposure, blast) -> rating lookup, parsed from section 2 rather than hardcoded."""
        text = read(MATRIX)
        body = text[text.index("### Safety rating"):text.index("### Data rating")]
        table = {}
        for line in body.splitlines():
            if not line.startswith("| **"):
                continue
            cells = [self.clean(c) for c in line.strip("|").split("|")]
            exposure = cells[0]
            for blast, rating in zip(("read", "write-local", "device-or-money"), cells[1:4]):
                table[(exposure, blast)] = rating
        return table

    def rows(self):
        """Each matrix row as (instance, exposure, gate, blast, safety)."""
        text = read(MATRIX)
        section = text[text.index("## 4. The matrix"):text.index("**20 instances")]
        out = []
        for line in section.splitlines():
            if not line.startswith("| **"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 6:
                continue
            triple = [self.clean(p) for p in cells[4].split("·")]
            # "public (all /api/*)" and the like -> the bare level
            exposure = triple[0].split("(")[0].strip()
            out.append((self.clean(cells[0]), exposure,
                        triple[1] if len(triple) > 1 else "",
                        triple[2] if len(triple) > 2 else "",
                        self.clean(cells[5])))
        return out

    def test_the_derivation_table_is_total(self):
        table = self.derivation_table()
        for exposure in ("none", "loopback", "public"):
            for blast in ("read", "write-local", "device-or-money"):
                with self.subTest(cell=(exposure, blast)):
                    self.assertIn((exposure, blast), table,
                                  "the safety rule has a hole; a hole is where hand-typing gets in")

    def test_every_row_states_a_complete_input_triple(self):
        for instance, exposure, gate, blast, _ in self.rows():
            with self.subTest(instance=instance):
                self.assertIn(exposure, ("none", "loopback", "public"), f"{instance}: bad exposure")
                self.assertIn(blast, ("read", "write-local", "device-or-money"),
                              f"{instance}: incomplete triple -- blast missing")
                self.assertTrue(gate, f"{instance}: gate missing")

    def test_every_safety_cell_matches_the_derivation_table(self):
        table = self.derivation_table()
        for instance, exposure, _gate, blast, safety in self.rows():
            with self.subTest(instance=instance):
                if safety == "S-blocked":
                    # The one documented override: a named open HIGH-n outranks the cell.
                    self.assertIn("SECURITY-AUDIT", read(MATRIX),
                                  "S-blocked used without the override being documented")
                    continue
                self.assertEqual(table[(exposure, blast)], safety,
                                 f"{instance}: {exposure} x {blast} derives "
                                 f"{table[(exposure, blast)]}, table says {safety}")

    #: instance -> (app module that must be mounted under /api/, expected exposure). `None` means
    #: the module must appear in NO include_router call. These are the three cells the review
    #: caught plus four controls, so a regression on either side goes red.
    MOUNTS = {
        "Voice — ASR": ("voice", "public"),
        "Streamer": ("streamer", "public"),
        "Project store": ("project", "public"),
        "Live": ("live", "public"),
        "Exp / plugin runtime": ("exp", "public"),
        "Miner — status": (None, "none"),
        "Coder": (None, "loopback"),
    }

    def test_exposure_agrees_with_the_mount_table_and_the_caddyfile(self):
        api = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
        caddy = (ROOT / "ops" / "Caddyfile").read_text(encoding="utf-8")
        # Caddy delegating the whole /api subtree is the premise that makes any /api mount public.
        self.assertRegex(caddy, r"handle /api/\*",
                         "ops/Caddyfile no longer delegates /api/* -- every 'public' cell needs re-deriving")

        mounted = dict(re.findall(r'include_router\(\s*(?:\w+\.)*(\w+)\.\w*router\w*'
                                  r'[^)]*?prefix="(/[^"]*)"', api, flags=re.S))
        by_row = {inst: (mod, exp) for inst, (mod, exp) in self.MOUNTS.items()}
        rows = {inst: exposure for inst, exposure, _, _, _ in self.rows()}

        for instance, (module, expected) in by_row.items():
            with self.subTest(instance=instance):
                self.assertIn(instance, rows, f"{instance} vanished from the matrix")
                self.assertEqual(expected, rows[instance],
                                 f"{instance}: matrix says exposure {rows[instance]!r}, "
                                 f"source says {expected!r}")
                if module:
                    self.assertIn(module, mounted,
                                  f"{module} is no longer mounted in api.py; exposure needs re-deriving")
                    self.assertTrue(mounted[module].startswith("/api/"),
                                    f"{module} is mounted at {mounted[module]}, not under /api/")

    def test_the_unmounted_miner_modules_really_have_no_router(self):
        api = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
        for module in ("cryptominer", "asicminer"):
            with self.subTest(module=module):
                self.assertNotRegex(api, rf"include_router\(\s*{module}\.",
                                    f"{module} is now mounted; the Miner row's 'none' is stale")

    def test_the_coder_data_path_is_loopback_by_construction(self):
        """Coder's rating is S-med rather than S-high only because /local is never proxied."""
        api = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
        caddy = (ROOT / "ops" / "Caddyfile").read_text(encoding="utf-8")
        self.assertIn("/local/coder/", api, "the coder mount moved; re-derive its exposure")
        self.assertNotRegex(api, r"include_router\(\s*coder\.",
                            "coder gained an /api router -- exposure becomes public and S-high")
        self.assertNotRegex(caddy, r"^\s*handle /local",
                            "ops/Caddyfile now proxies /local -- Coder's whole safety case is gone")


class ForbiddenModeStaysForbidden(unittest.TestCase):
    def test_off_the_record_is_listed_and_forbidden_not_available(self):
        """Requested as one mode among ten. Bootcamp §4a forbids it, so the matrix lists it as
        FORBIDDEN -- present in the table so its absence cannot read as an oversight."""
        text = read(MATRIX)
        self.assertIn("off-the-record", text, "the forbidden mode is not even listed")
        row = [ln for ln in text.splitlines() if "off-the-record" in ln and ln.startswith("|")]
        self.assertTrue(row, "off-the-record is mentioned but not in the modes table")
        self.assertRegex(" ".join(row), r"FORBIDDEN",
                         "off-the-record must be marked FORBIDDEN, not offered as available")


class CaveatsAreCarriedForward(unittest.TestCase):
    def test_every_new_document_carries_the_unaudited_commit_caveat(self):
        """The 404-commit gap is the standing caveat on every reading in this batch. A document
        that quietly drops it is claiming more confidence than the audit supports."""
        for doc in (MATRIX, CAPABILITY, BENCHMARKS, PARITY):
            with self.subTest(doc=doc.name):
                self.assertIn("404 commits", read(doc),
                              f"{doc.name} dropped the unaudited-range caveat")

    def test_every_new_document_states_the_commit_it_was_read_at(self):
        for doc in (MATRIX, CAPABILITY, BENCHMARKS, PARITY):
            with self.subTest(doc=doc.name):
                self.assertIn("507e09ee", read(doc), f"{doc.name} states no read-at commit")


if __name__ == "__main__":
    unittest.main()
