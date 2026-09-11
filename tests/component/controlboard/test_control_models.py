"""control/models/ -- the operator model-control surface.

The interesting property is not that these scripts run. It is that on a box with **zero**
learned-model payloads they say so, out loud, instead of returning an empty success that a
reader mistakes for a passing check. This repo has already published a model figure that was
never true of the machine it described -- "28 weight files / 17 unresolved / 78 GiB" quoted
from a docstring while the measured count was 0 -- so the tests below assert the reported
count against a live re-measurement rather than against any written number.

## What is deliberately NOT tested by running it

`models-finetune.sh --execute`, `models-activate.sh` and `models-verify.sh` take the GPU or
mutate the active model. The tests drive their refusal paths only. A test that actually
promoted a model to prove promotion works would be the most expensive passing test in the
repo.

## Wrapper discipline is a test, not a convention

`test_launchers_wrap_rather_than_reimplement` asserts each launcher names the authority it
delegates to. A launcher that grew its own model parsing would still pass every behavioural
test here while quietly becoming a second source of truth, which is the failure control/
exists to prevent.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
MODELS = ROOT / "control" / "models"

READ_LAUNCHERS = [
    "models-list.sh", "models-active.sh", "models-loaded.sh", "models-provenance.sh",
    "models-license.sh", "models-checksums.sh", "models-compat.sh", "models-adapters.sh",
    "models-rebrand.sh", "models-gpu.sh",
]
WRITE_LAUNCHERS = [
    "models-stage.sh", "models-verify.sh", "models-activate.sh", "models-rollback.sh",
    "models-release.sh", "models-finetune.sh",
]


def run(script, *args, timeout=120):
    return subprocess.run(["bash", str(MODELS / script), *args],
                          capture_output=True, text=True, timeout=timeout)


def measured_payload_count() -> int:
    """Count payloads independently of the launchers, so the assertion is not circular."""
    d = ROOT / "backend" / "models"
    if not d.is_dir():
        return 0
    n = 0
    for p in d.rglob("*"):
        if p.is_file() and "/hf/hub/" not in str(p) and p.stat().st_size > 0 \
           and p.suffix in {".gguf", ".safetensors", ".bin", ".pt"}:
            n += 1
    return n


class ControlModelsStructureTests(unittest.TestCase):
    def test_all_launchers_exist_and_are_executable(self):
        for name in READ_LAUNCHERS + WRITE_LAUNCHERS:
            p = MODELS / name
            self.assertTrue(p.is_file(), f"missing launcher: {name}")
            self.assertTrue(os.access(p, os.X_OK), f"not executable: {name}")

    def test_acquire_launcher_is_absent(self):
        """D-2 is unresolved, so no acquisition launcher may exist -- not even a stub."""
        self.assertFalse((MODELS / "models-acquire.sh").exists(),
                         "models-acquire.sh must not exist while D-2 is unresolved")

    def test_no_conversion_or_quantization_launcher(self):
        """Excluded by D-6."""
        for forbidden in ("models-convert.sh", "models-quantize.sh", "models-gguf.sh"):
            self.assertFalse((MODELS / forbidden).exists(), f"D-6 excludes {forbidden}")

    def test_launchers_wrap_rather_than_reimplement(self):
        """Each launcher must name the authority it delegates to."""
        # models-compat.sh legitimately wraps no MODEL authority -- runtime capability is
        # independent of model presence, which is why it can answer with zero payloads.
        # It still must name what it probes rather than inventing a capability claim.
        authorities = ("model_inventory", "symoneural-model-stage", "gpu-governor",
                       "train_lora", "PROVENANCE", "gpu.sh", "api/status", "LICENSE",
                       "nvidia-smi", "engines/", "training/adapter")
        for name in READ_LAUNCHERS + WRITE_LAUNCHERS:
            body = (MODELS / name).read_text()
            self.assertTrue(any(a in body for a in authorities),
                            f"{name} names no authority -- it may be reimplementing logic")


class PayloadReportingTests(unittest.TestCase):
    """Every launcher must report the measured payload count rather than imply a state.

    This class asserted `measured == 0` until 2026-09-03, with the failure message "a real
    payload appeared; A-1 assumptions must be re-verified". A real payload did appear -- six
    of them, restored from custody -- so the premise has been re-verified and the assertions
    are now written as invariants that hold at ANY count, including zero.

    That is the point the module docstring was already making: assert the reported count
    against a live re-measurement rather than against any written number. A test that
    hard-codes today's number is the same defect as a docstring that does, and it fails the
    moment the project succeeds at something.
    """

    def setUp(self):
        self.measured = measured_payload_count()

    def test_python_and_shell_measurements_agree(self):
        """Two independent counters of the same thing must not drift.

        `measured_payload_count()` here and `payload_count` in `_models_common.sh` walk
        `backend/models` with the same rules by hand. If they disagree, one of them is the
        wrong answer to "what is installed" and there is no way to tell which from output
        alone -- which is exactly the second-source-of-truth problem control/ exists to stop.
        """
        r = subprocess.run(
            ["bash", "-c",
             f'set +u; source "{MODELS}/_models_common.sh" >/dev/null 2>&1; payload_count'],
            capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), str(self.measured),
                         "shell payload_count and the Python re-measurement disagree")

    def test_list_reports_payload_count_matching_measurement(self):
        r = run("models-list.sh")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"LEARNED MODEL PAYLOADS: {self.measured}", r.stdout)

    def test_payload_state_wording_tracks_the_measurement(self):
        """The zero-state sentence must appear when the count is zero, and only then.

        Both directions matter. Missing it on an empty box reads as a failed command;
        printing it on a box with six payloads would be a false statement about the
        machine, which is the failure mode this file was written to catch.
        """
        r = run("models-list.sh")
        self.assertEqual(r.returncode, 0, r.stderr)
        if self.measured == 0:
            self.assertIn("no model installed", r.stdout,
                          "zero-payload state must be stated explicitly")
            self.assertIn("valid state", r.stdout, "absence must not read as an error")
        else:
            self.assertNotIn("no model installed", r.stdout,
                             f"{self.measured} payloads on disk, but the launcher still "
                             f"says no model is installed")

    def test_read_launchers_all_exit_zero_with_no_model(self):
        """'No model installed' is success, not failure."""
        for name in READ_LAUNCHERS:
            r = run(name)
            self.assertEqual(r.returncode, 0, f"{name} exited {r.returncode}: {r.stderr[:200]}")

    def test_checksums_reports_the_state_it_actually_found(self):
        """Zero objects is stated as such; a non-empty box must not claim there is nothing
        to verify. `models-checksums.sh` already branches on the count -- this asserts both
        arms, so restoring payloads cannot leave it printing the empty-box sentence."""
        r = run("models-checksums.sh")
        self.assertEqual(r.returncode, 0, r.stderr)
        if self.measured == 0:
            self.assertIn("no payload objects require verification", r.stdout)
        else:
            self.assertNotIn("no payload objects require verification", r.stdout,
                             f"{self.measured} payloads on disk, but checksums reports "
                             f"nothing requires verification")

    def test_compat_answerable_without_a_model(self):
        """Runtime capability is independent of model presence."""
        r = run("models-compat.sh")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("compute capability", r.stdout)


class ProvenanceNotPayloadTests(unittest.TestCase):
    """A provenance record must never be reported as an installed model."""

    def test_provenance_records_and_payloads_reported_separately(self):
        r = run("models-provenance.sh")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("records:", r.stdout)
        self.assertIn("LEARNED MODEL PAYLOADS:", r.stdout)
        self.assertIn("NOT evidence", r.stdout,
                      "must state that a record is not evidence of presence")

    def test_record_count_does_not_become_payload_count(self):
        """The payload line must carry the measured payload count, not the record count.

        This asserted the literal "0" was present in the payload line, which only worked
        while both numbers were 0 -- it would have passed just as happily if the record
        count had been printed as the payload count, since both read "0". Comparing the
        two parsed integers against an independent measurement is the assertion that
        actually catches the confusion the class is named after.
        """
        r = run("models-provenance.sh")
        self.assertEqual(r.returncode, 0, r.stderr)
        payload_line = [l for l in r.stdout.splitlines() if "LEARNED MODEL PAYLOADS" in l][0]
        self.assertIn(f"LEARNED MODEL PAYLOADS: {self.measured}", payload_line,
                      "the payload line must report the measured payload count")
        record_lines = [l for l in r.stdout.splitlines() if l.strip().startswith("records:")]
        self.assertTrue(record_lines, "provenance must report a record count or UNKNOWN")
        records = int(record_lines[0].split(":")[1].strip())
        self.assertGreater(records, 0,
                           "PROVENANCE.json holds records; reporting 0 means the manifest "
                           "shape was not recognised (it is a list under 'weights')")
        if records != self.measured:
            self.assertNotIn(f"LEARNED MODEL PAYLOADS: {records}", r.stdout,
                             "record count was printed as the payload count")

    def setUp(self):
        self.measured = measured_payload_count()

    def test_licence_reports_unverified_not_a_conclusion(self):
        r = run("models-license.sh")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("unlicensed", r.stdout.lower(),
                         "absence of a record must not be reported as 'unlicensed'")

    def test_active_selection_is_not_presence(self):
        r = run("models-active.sh")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("configuration, not presence", r.stdout)


class UnknownStateTests(unittest.TestCase):
    """ABSENT and UNKNOWN must not collapse into each other."""

    def test_missing_model_dir_reports_unknown_not_zero(self):
        """A model directory that cannot be read is UNKNOWN. Reporting 0 would claim a
        verified-empty box when the truth is that nothing was inspected."""
        r = subprocess.run(
            ["bash", "-c",
             f'set +u; source "{MODELS}/_models_common.sh" >/dev/null 2>&1; '
             f'MODELS_DIR=/nonexistent-a1-probe; payload_count'],
            capture_output=True, text=True)
        self.assertIn("UNKNOWN", r.stdout,
                      "a missing model directory must report UNKNOWN, not 0")
        self.assertNotEqual(r.stdout.strip(), "0",
                            "UNKNOWN collapsed into 0 -- absent and unknown must stay distinct")

    def test_present_model_dir_reports_a_number(self):
        """Control case: a readable directory yields a count, proving UNKNOWN is not constant."""
        r = subprocess.run(
            ["bash", "-c",
             f'set +u; source "{MODELS}/_models_common.sh" >/dev/null 2>&1; payload_count'],
            capture_output=True, text=True)
        self.assertRegex(r.stdout.strip(), r"^\d+$",
                         "a readable model directory must yield a numeric count")

class WriteModeRefusalTests(unittest.TestCase):
    """Write-mode launchers must refuse without explicit intent. None are run to completion."""

    def test_finetune_refuses_without_execute(self):
        """Must refuse cleanly. A crash also exits non-zero, so assert the refusal is
        deliberate -- an "unbound variable" traceback is not a safety guarantee."""
        r = run("models-finetune.sh")
        self.assertNotEqual(r.returncode, 0, "fine-tune must not start without --execute")
        combined = r.stdout + r.stderr
        self.assertNotIn("unbound variable", combined, "refused by crashing, not by design")
        self.assertNotIn("line ", r.stderr, "shell error leaked instead of a clean refusal")
        self.assertIn("--execute", combined, "refusal must say what is required")

    def test_finetune_never_echoes_corpus(self):
        r = run("models-finetune.sh")
        combined = r.stdout + r.stderr
        self.assertNotIn('{"', combined, "must never echo corpus contents")

    def test_verify_refuses_without_candidate(self):
        r = run("models-verify.sh")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("usage", (r.stdout + r.stderr).lower())

    def test_activate_refuses_without_candidate(self):
        r = run("models-activate.sh")
        self.assertNotEqual(r.returncode, 0)

    def test_release_refuses_without_surface(self):
        r = run("models-release.sh")
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
