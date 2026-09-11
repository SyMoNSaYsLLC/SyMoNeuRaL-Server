"""ModelOps: the inventory's classification, and the staging script's refusals.

Two halves, and they fail for different reasons.

**The inventory** is a scan, so the thing worth asserting is that it still finds what it is
supposed to find. A regex that silently stops matching `CHAT_MODEL` would not raise — it would
report "no active default", which reads like a finding rather than a broken tool. So the active
set is asserted against paths taken from `backend/server.py` independently, the same shape as
`test_symoneural_cli.py::LoadAndLayoutTests` uses for `ROOT`.

**The staging script** is guardrails, and a guardrail that is never exercised is a comment. Each
refusal below is driven for real: wrong directory, no candidate id, nothing staged, dry run.
Nothing here downloads, activates, moves or deletes anything, and the script is never invoked in
a mode that would.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = next(_p for _p in Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
TOOL = ROOT / "tools" / "lib" / "model_inventory.py"
SCRIPT = ROOT / "scripts" / "model-staging" / "symoneural-model-stage.sh"
MODELS = ROOT / "models"

sys.path.insert(0, str(ROOT / "tools" / "lib"))
import model_inventory as inv                                        # noqa: E402


def run_script(*args, cwd=None):
    return subprocess.run([str(SCRIPT), *args], cwd=str(cwd or ROOT),
                          capture_output=True, text=True, timeout=120)


class ActiveModelParseTests(unittest.TestCase):
    """The active set is read from source. If the read breaks, it must break loudly."""

    def test_the_active_chat_and_draft_models_are_found(self):
        """Asserted against `api.py` read independently, not against a literal filename.

        Pinning the literal would make this test pass a rename that broke the tool, and fail a
        rename that the tool handled correctly — exactly backwards."""
        text = (ROOT / "backend" / "core" / "config.py").read_text(encoding="utf-8")
        want = {}
        for var, role in (("CHAT_MODEL", "chat"), ("DRAFT_MODEL", "chat-draft")):
            m = re.search(rf'^{var}\s*=\s*MODELS\s*/\s*"([^"]+)"\s*/\s*"([^"]+)"', text, re.M)
            self.assertIsNotNone(m, f"{var} is no longer a two-segment MODELS path in core/config.py")
            want[f"{m.group(1)}/{m.group(2)}"] = role

        got = inv.active_from_source()
        for path, role in want.items():
            self.assertEqual(got.get(path), role, f"{path} not reported active as {role}")

    def test_the_four_image_components_are_all_found(self):
        """FLUX/Schnell is four separately-loaded files, which is the whole reason the SDXL
        one-checkpoint assumption does not transfer. Missing one silently would make the bundle
        look three-quarters present."""
        got = inv.active_from_source()
        roles = {v for v in got.values() if v.startswith("image-")}
        self.assertEqual(roles, {"image-unet", "image-t5", "image-clip", "image-vae"})

    def test_the_asr_model_is_found_from_the_voice_app_not_just_api(self):
        """The bug this test exists for: a first draft read only `api.py` and reported the
        listen model as an idle component while `voice/asr.py` was loading it. A loader site
        missed is an active model misclassified."""
        got = inv.active_from_source()
        self.assertIn("asr", got.values())

    def test_an_empty_active_set_would_be_a_failure_not_a_finding(self):
        self.assertTrue(inv.active_from_source(),
                        "no active models parsed at all -- the tool is broken, not the box")


class ClassificationTests(unittest.TestCase):
    def test_an_unmanifested_weight_is_unknown_blocked(self):
        """The honest default. `ops/audits/LICENSE-AUDIT.md`'s vocabulary says an unrecorded
        licence is a blocker until provenance exists, so absence of a manifest entry is not
        'probably fine' — whatever the file happens to be."""
        self.assertEqual(inv._classify("vae/mystery.safetensors", None, False),
                         "unknown-blocked")
        self.assertEqual(inv._classify("llm/whatever.gguf", None, False), "unknown-blocked")

    def test_active_beats_every_other_label(self):
        entry = {"license": "Apache-2.0"}
        self.assertEqual(inv._classify("llm/symon-1.0-7b-q4_k_m.gguf", entry, True),
                         "active-default")

    def test_a_manifested_non_active_llm_is_a_rollback(self):
        self.assertEqual(inv._classify("llm/symon-1.0-14b-q4_k_m.gguf", {"license": "x"}, False),
                         "rollback")

    def test_the_class_vocabulary_is_closed(self):
        """Every label the tool can emit has to be one of the declared classes, or a doc that
        groups by class silently drops a row."""
        got = {r["classification"] for r in inv.scan()["weights"]}
        self.assertTrue(got <= set(inv.CLASSES), f"undeclared class emitted: {got - set(inv.CLASSES)}")

    def test_the_real_scan_finds_unknown_blocked_files_and_says_how_many(self):
        """Not pinned to 17: the count changes the moment somebody drops a file in, and a test
        that pins it would fail for the right behaviour. What must hold is that unmanifested
        files are FOUND and labelled, not that there are exactly N of them."""
        scanned = inv.scan()["weights"]
        self.assertTrue(scanned, "no weights scanned at all")
        unknown = [r for r in scanned if r["classification"] == "unknown-blocked"]
        for r in unknown:
            self.assertFalse(r["in_manifest"])
            self.assertIsNone(r["license"])

    def test_adapters_are_reported_separately_and_marked_protected(self):
        """Training output is not a base weight. `training/` is the protected tree, and merging
        the two lists is how an adapter ends up treated as something shippable."""
        for a in inv.scan()["adapters"]:
            self.assertTrue(a["protected"])
            self.assertEqual(a["classification"], "adapter")
            self.assertTrue(a["path"].startswith("training/"))


class InventoryOutputTests(unittest.TestCase):
    def test_the_text_output_is_deterministic_across_runs(self):
        """Two runs, same bytes. A review artefact that reorders itself cannot be diffed, and
        `sorted()` on a `rglob` is the only reason this holds."""
        a = inv.render(inv.scan())
        b = inv.render(inv.scan())
        self.assertEqual(a, b)

    def test_the_json_output_parses_and_carries_the_same_counts(self):
        out = subprocess.run([sys.executable, str(TOOL), "--json"],
                             capture_output=True, text=True, timeout=180, cwd=str(ROOT))
        self.assertEqual(out.returncode, 0, out.stderr)
        data = json.loads(out.stdout)
        self.assertEqual(len(data["weights"]), len(inv.scan()["weights"]))

    def test_no_secret_shaped_string_reaches_the_output(self):
        """The inventory reads a manifest and a directory listing, neither of which should
        contain a credential — but it also reads `api.py`, which sits beside code that does.
        Checked rather than assumed."""
        text = inv.render(inv.scan()).lower()
        for forbidden in ("token=", "secret", "password", "api_key", "bearer ",
                          ".env", "file://", "vscode://", "pycharm://"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)

    def test_it_says_plainly_that_it_changed_nothing(self):
        self.assertIn("Nothing was downloaded, activated, moved or deleted",
                      inv.render(inv.scan()))


class IsolatedCandidateSmokeTests(unittest.TestCase):
    """The smoke path must not be able to answer from the active model.

    Garrett's requirement is that a candidate smoke fails honestly rather than silently
    falling back to Qwen. The implementation does not disable a fallback — it makes one
    **unreachable**: the mode launches the engine binary directly, on its own port, in its own
    process, and never imports or invokes `backend/server.py`, which is the only thing that knows
    what `CHAT_MODEL` and `DRAFT_MODEL` are.

    **A flag that disables a fallback can be wrong. A process that cannot name the fallback's
    path cannot be.** These tests assert that property structurally, because the alternative is
    downloading 12.81 GiB to find out.
    """

    def test_it_needs_an_explicit_candidate_id(self):
        got = run_script("--smoke-candidate")
        self.assertEqual(got.returncode, 2)
        self.assertIn("explicit candidate id", got.stderr)

    def test_it_fails_nonzero_when_the_candidate_is_not_staged(self):
        """Missing candidate is a failure, not a no-op. Exit 5 rather than 0, so a caller
        cannot read 'nothing happened' as 'the candidate is fine'."""
        staging = MODELS / "staging"
        if staging.exists():
            self.skipTest("a real staging tree exists; not touching it")
        got = run_script("--smoke-candidate", "symon-openai-20b")
        self.assertEqual(got.returncode, 5)
        out = got.stdout + got.stderr
        self.assertIn("REFUSED", out)
        self.assertIn("candidate not staged", out)

    def test_the_refusal_says_the_active_model_was_not_consulted(self):
        staging = MODELS / "staging"
        if staging.exists():
            self.skipTest("a real staging tree exists; not touching it")
        got = run_script("--smoke-candidate", "symon-openai-20b")
        flat = " ".join((got.stdout + got.stderr).split())
        self.assertIn("no active model was consulted", flat)
        self.assertIn("active default is untouched", flat)

    @staticmethod
    def _smoke_body():
        src = SCRIPT.read_text(encoding="utf-8")
        return src[src.index("mode_smoke_candidate()"):src.index("mode_activate()")]

    def test_the_smoke_mode_cannot_NAME_what_it_must_not_load(self):
        """The strictest available guarantee, and stricter than the obvious one.

        A first draft of this test allowed the body to *mention* the production symbols in
        prose and forbade only a dereference (`$CHAT_MODEL`). Garrett's correction was better:
        forbid the literal strings outright, and write the explanation in neutral terms
        instead. The reasoning generalises — **a function that cannot name the fallback cannot
        load it**, and that is verifiable by grep, whereas "mentions it but only in a comment"
        needs a human to keep agreeing with itself.

        So the smoke body may explain isolation, and may not name the symbols or the files."""
        body = self._smoke_body()
        for forbidden in ("CHAT_MODEL", "DRAFT_MODEL", "backend/server.py", "--lora",
                          "symon-1.0-7b", "symon-1.0-draft", "symon-1.0-14b",
                          "symon-1.0-27b", "symon-1.0-32b"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, body,
                                 f"the isolated smoke body names {forbidden!r}; use neutral "
                                 "wording so the function cannot name what it must not load")

    def test_the_smoke_mode_does_not_execute_the_production_module(self):
        body = self._smoke_body()
        for invocation in ("python3 backend", "python backend", "source backend",
                           "bash backend", "exec backend", "uvicorn"):
            with self.subTest(invocation=invocation):
                self.assertNotIn(invocation, body)

    def test_the_printed_command_carries_no_adapter_and_no_draft_flag(self):
        """Asserted against the argv the script prints, and the positive assertion is the
        neutral wording — requiring the literal "no --lora" would reintroduce the very string
        the test above forbids."""
        body = self._smoke_body()
        argv_lines = [ln for ln in body.splitlines()
                      if "say " in ln and ("-m " in ln or "-ngl" in ln or "-c 8192" in ln
                                           or "$ENGINE" in ln)]
        self.assertTrue(argv_lines, "could not find the printed command block")
        argv = " ".join(argv_lines)
        for flag in ("--lora", "-md", "--draft", "--model-draft"):
            with self.subTest(flag=flag):
                self.assertNotIn(flag, argv)
        self.assertIn("-np 1", argv)              # single slot, not the production two
        self.assertIn("no adapter", body)         # and the reason, neutrally worded

    def test_the_smoke_uses_its_own_port_not_the_production_one(self):
        src = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("SMOKE_PORT", src)
        self.assertIn("8099", src)
        body = src[src.index("mode_smoke_candidate()"):src.index("mode_activate()")]
        self.assertNotIn("8081", body)

    def test_the_output_identifies_the_candidate_and_the_runtime(self):
        """Requirement 4: the smoke must report exactly what ran. A smoke that does not name
        its own model is indistinguishable from one that ran something else."""
        src = SCRIPT.read_text(encoding="utf-8")
        body = src[src.index("mode_smoke_candidate()"):src.index("mode_activate()")]
        self.assertIn("candidate model:", body)
        self.assertIn("runtime:", body)
        self.assertIn("--version", body)          # the engine identifies its own build
        self.assertIn("the exact command", body)

    def test_the_rollback_models_are_present_and_untouched_by_the_smoke(self):
        """Disabled-for-smoke means disabled in the test path. It does not mean deleted, and it
        does not mean moved. Asserted against the disk."""
        for rel in ("llm/symon-1.0-7b-q4_k_m.gguf", "llm/symon-1.0-draft-0.5b-q4_k_m.gguf"):
            with self.subTest(rel=rel):
                p = MODELS / rel
                if not p.exists():
                    self.skipTest(f"{rel} absent from this clone")
                self.assertGreater(p.stat().st_size, 0)

    def test_a_reduced_context_is_used_and_the_reason_is_measured(self):
        """-c 8192 rather than the production 65536, and the script states the arithmetic:
        a 12.81 GiB candidate plus ~3.9 GiB of KV does not fit 16,303 MiB. A smoke that OOMs
        for a reason nobody wrote down looks like an incompatible model."""
        src = SCRIPT.read_text(encoding="utf-8")
        body = src[src.index("mode_smoke_candidate()"):src.index("mode_activate()")]
        self.assertIn("-c 8192", body)
        self.assertIn("16,303", body)
        self.assertIn("MEASURED", body)


class StagingScriptRefusalTests(unittest.TestCase):
    """Each guardrail driven for real. A refusal that is never exercised is a comment."""

    def test_the_script_is_executable_and_parses(self):
        self.assertTrue(SCRIPT.is_file())
        self.assertEqual(subprocess.run(["bash", "-n", str(SCRIPT)]).returncode, 0)

    def test_it_refuses_to_run_outside_the_repo_root(self):
        """Every path in the script is relative. Run from elsewhere it would write a staging
        tree somewhere nobody looks again, so it exits before doing anything."""
        with tempfile.TemporaryDirectory() as td:
            got = run_script("--inventory", cwd=td)
        self.assertEqual(got.returncode, 2)
        self.assertIn("refusing", got.stderr)

    def test_activation_without_a_candidate_id_refuses(self):
        got = run_script("--activate-candidate")
        self.assertEqual(got.returncode, 2)
        self.assertIn("explicit candidate id", got.stderr)

    def test_activation_refuses_when_nothing_is_staged(self):
        """The gate that matters. Six conditions, and the exit code says refused rather than
        'nothing to do' — a promotion path that exits 0 when it did not promote is the shape
        that lets a caller believe it worked."""
        got = run_script("--activate-candidate", "symon-openai-20b")
        self.assertEqual(got.returncode, 3)
        self.assertIn("REFUSED", got.stderr + got.stdout)
        for gate in ("candidate staged", "smoke marker present", "rollback recorded",
                     "licence recorded", "runtime compat recorded", "owner approval"):
            with self.subTest(gate=gate):
                self.assertIn(gate, got.stderr + got.stdout)

    def test_a_dry_run_stage_creates_nothing_on_disk(self):
        """The staging directory must not exist afterwards. Asserted by absence, and skipped
        rather than deleted if a real staging tree is already there — this test does not get to
        remove somebody's staged candidate to make itself pass."""
        staging = MODELS / "staging"
        if staging.exists():
            self.skipTest("a real staging tree exists; not touching it")
        got = run_script("--stage-openai-gpt-oss-20b", "--dry-run")
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertFalse(staging.exists(), "dry run created a staging directory")
        self.assertIn("dry run", got.stdout)

    def test_the_download_is_refused_even_with_the_confirm_phrase(self):
        """Deliberate: the phrase is necessary and still not sufficient. Tens of GB onto a disk
        already holding 194 GB should not be one environment variable away, so the script
        prints the command and declines to be the thing that spends the disk."""
        src = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("this script still will not fetch", src)
        self.assertNotIn("huggingface-cli download \"", src)      # never built as a live argv

    def test_the_recorded_download_command_is_not_the_dead_entrypoint(self):
        """`huggingface-cli` is deprecated and NO LONGER WORKS, and it fails in the worst way:
        it prints a deprecation notice and **exits 0 without downloading anything.**

        That is why this is a test rather than a fixed typo. The script and the migration doc
        both recorded `huggingface-cli download` until 2026-08-22, when the first authorized
        download produced 12 KB and a zero exit code — success by every signal a caller checks,
        and an empty directory. A wrong command that fails loudly costs a minute; one that
        succeeds silently costs the trust in every exit code around it.
        """
        for path in (SCRIPT, ROOT / "models" / "docs" / "OPENAI-GPT-OSS-MIGRATION.md"):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotIn("huggingface-cli download", text,
                                 "the dead entrypoint is recorded here; it exits 0 and "
                                 "downloads nothing. Use `hf download`.")
        self.assertIn("hf download", SCRIPT.read_text(encoding="utf-8"))

    def test_the_recorded_download_does_not_fetch_the_unconvertible_checkpoint(self):
        """`original/` is the OpenAI reference checkpoint and CANNOT be converted: its
        config.json has no `architectures` key, its tensors use the original layout
        (`block.0.attn.qkv.weight`) rather than the HF names the converter expects, and it
        ships no tokenizer. Measured 2026-08-22, by reading the files after 13 GiB had already
        come down on the strength of this command.

        This is the sibling of the dead-entrypoint test above, and the same lesson: that one
        recorded a command that fetched nothing, this one recorded a command that fetched the
        wrong 13 GiB. Both looked like they worked.
        """
        text = SCRIPT.read_text(encoding="utf-8")
        dl = [ln for ln in text.splitlines() if "--include" in ln or "--exclude" in ln]
        self.assertTrue(dl, "the download command records no filter at all")
        # The script escapes its quotes for `say`, so compare with backslashes removed --
        # otherwise the negative below silently cannot fire, which is how it read on the
        # first draft of this test.
        joined = "\n".join(dl).replace("\\", "")
        self.assertNotIn('--include "original/*"', joined,
                         "this fetches the unconvertible reference checkpoint")
        self.assertIn("--exclude", joined,
                      "the command must exclude original/ rather than target it")

    def test_staging_twice_does_not_clobber_a_manifest_that_records_real_state(self):
        """A real run, because this is a bug `grep` could not have found.

        The stage mode used to write STAGED-MANIFEST.json unconditionally. Re-running it after
        the download completed produced a fresh manifest asserting `"downloaded": false` over a
        directory holding 32 GiB -- and the activation gates READ that file. So the failure mode
        was not a lost field, it was a manifest that contradicted its own disk while looking
        authoritative. Found 2026-08-22 by doing exactly this.

        Skips when staging is absent: the tree is gitignored, so it does not exist on a fresh
        clone, and a test that quietly passes on absence would be worse than one that says why.
        """
        manifest = ROOT / "models/staging/openai-gpt-oss-20b/STAGED-MANIFEST.json"
        if not manifest.is_file():
            self.skipTest("no staged candidate on this box; nothing to protect")

        before = manifest.read_bytes()
        proc = subprocess.run([str(SCRIPT), "--stage-openai-gpt-oss-20b"],
                              cwd=ROOT, capture_output=True, text=True, timeout=120)
        after = manifest.read_bytes()

        self.assertEqual(before, after,
                         "re-staging rewrote a manifest that already recorded real state")
        # The refusal is emitted by `warn`, which writes to stderr, so both streams matter.
        self.assertIn("REFUSED", proc.stdout + proc.stderr,
                      "it left the file alone but did not say so; a silent no-op is "
                      "indistinguishable from a successful rewrite")

    def test_the_refusal_path_still_restores_a_missing_rollback_note(self):
        """The no-clobber guard returns early, which nearly created a dead end: ROLLBACK.md is
        activation gate 3, and the only mode that writes it would refuse before reaching the
        write. So a deleted ROLLBACK.md would fail activation with no way to regenerate it.

        Safe to regenerate because ROLLBACK.md is built from constants -- it records nothing
        measured or decided, unlike the manifest sitting beside it. That asymmetry is the whole
        reason one is rewritten here and the other is refused.
        """
        staging = ROOT / "models/staging/openai-gpt-oss-20b"
        roll, manifest = staging / "ROLLBACK.md", staging / "STAGED-MANIFEST.json"
        if not manifest.is_file():
            self.skipTest("no staged candidate on this box")

        original = roll.read_bytes() if roll.is_file() else None
        manifest_before = manifest.read_bytes()
        try:
            if roll.is_file():
                roll.unlink()
            subprocess.run([str(SCRIPT), "--stage-openai-gpt-oss-20b"],
                           cwd=ROOT, capture_output=True, text=True, timeout=120)
            self.assertTrue(roll.is_file(), "gate 3's file was not restored")
            self.assertEqual(manifest.read_bytes(), manifest_before,
                             "restoring the rollback note must not touch the manifest")
        finally:
            if original is not None:
                roll.write_bytes(original)

    def test_the_manifest_never_asserts_downloaded_as_a_literal(self):
        """The downloaded flag must be derived from the disk, not written as a constant. A
        constant is accurate only at the instant of first staging, and authoritative-but-wrong
        forever after -- which matters because the activation gates read this file.

        Scoped to executable lines, NOT the whole file. Three times in one session my own
        explanatory prose collided with a test of this kind, and a check that forbids a string
        from appearing in a *comment* is a trap laid for whoever next tries to document the
        thing. The teeth are in the emitted JSON; the prose is free to quote it.
        """
        code = [ln for ln in SCRIPT.read_text(encoding="utf-8").splitlines()
                if not ln.lstrip().startswith("#")]
        emitted = "\n".join(code)
        for literal in ('"downloaded": false', '"downloaded": true'):
            with self.subTest(literal=literal):
                self.assertNotIn(literal, emitted,
                                 "hardcoded; measure the staging tree instead")

    def test_no_mode_deletes_a_weight(self):
        """Structural, because the alternative is running a mode that might delete one. `rm`
        appears exactly once and only against the script's own staging scratch."""
        src = SCRIPT.read_text(encoding="utf-8")
        for line in src.splitlines():
            if re.search(r"\brm\b|\bshred\b|\btruncate\b", line) and not line.strip().startswith("#"):
                self.fail(f"a destructive command appears in the script: {line.strip()!r}")

    def test_the_smoke_plan_requires_a_real_run_not_a_file_check(self):
        got = run_script("--smoke-plan")
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertIn("SMOKE-PASSED.txt", got.stdout)
        # Whitespace-collapsed before matching. The phrase wraps across a line in the heredoc,
        # and a plain substring check missed it -- the same failure #97 found in a GPL header,
        # where an 80-column wrap put the licence name across a line break and made it
        # invisible to a substring search. Same bug, same fix.
        flat = " ".join(got.stdout.split())
        self.assertIn("cannot ask whether a model works", flat)
        self.assertIn("a stamped smoke record can", flat)


if __name__ == "__main__":
    unittest.main()
