"""The model under test must not learn what is being measured, and scoring must not assume
that a correct answer is a good answer.

Two separate failures are pinned here, and they are the reason `tools/lib/bootcamp_referee.py` exists.

**Blinding.** A negative control asks whether project-private facts leak into a supposedly
isolated path. Put `# negative control -- the model should not know this` in the prompt and any
competent model reads the label and behaves; the probe then answers its own question. So the
guarantee cannot be "we were careful with wording". It has to be that the function building the
wire payload reads `probe.prompt` and is structurally unable to see the answer key.

**Inverted scoring.** "Correct is good" is wrong for half these modes, and getting it backwards
inverts the finding. Measured 2026-08-22: asked what SyMoNeuRaL is, both base models produced
confident nonsense. Scored naively that is two failures. Scored correctly it is two PASSES --
the isolated harness leaked nothing, which is the only thing that probe was ever asking. A bare
model reciting this box's GPU or port numbers would have been the alarm.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import unittest

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
TOOL = ROOT / "tools" / "bootcamp_referee.py"


def _load():
    spec = importlib.util.spec_from_file_location("bootcamp_referee", TOOL)
    mod = importlib.util.module_from_spec(spec)
    # Registered before exec: `dataclasses` resolves a frozen dataclass's annotations through
    # sys.modules, and without this the module raises on import rather than on use.
    sys.modules["bootcamp_referee"] = mod
    spec.loader.exec_module(mod)
    return mod


mr = _load()


class TheModelIsBlind(unittest.TestCase):
    """Nothing the evaluator knows may reach the model."""

    def test_no_probe_payload_carries_evaluator_vocabulary(self):
        for p in mr.PROBES:
            with self.subTest(probe=p.probe_id):
                leaks = mr.leaks_evaluator_vocabulary(mr.build_request(p))
                self.assertEqual(leaks, [], f"{p.probe_id} tells the model what is measured")

    def test_no_probe_payload_carries_the_expected_behaviour(self):
        """The expectation is the answer key. It is recorded after the run, never sent."""
        for p in mr.PROBES:
            with self.subTest(probe=p.probe_id):
                sent = json.dumps(mr.build_request(p))
                self.assertNotIn(p.expected_behavior[:40], sent)

    def test_no_probe_payload_carries_its_own_private_markers(self):
        """A probe testing for leakage of a fact must not ship that fact to the model. This is
        the most direct way the harness could cheat on its own behalf."""
        for p in mr.PROBES:
            sent = json.dumps(mr.build_request(p)).lower()
            for marker in p.private_markers:
                with self.subTest(probe=p.probe_id, marker=marker):
                    self.assertNotIn(marker.lower(), sent)

    def test_the_request_builder_reads_only_the_prompt(self):
        """Structural, not textual. Two probes identical in prompt but differing in every
        evaluator field must produce byte-identical payloads -- so nothing about the test type
        can reach the model, not even through a changed system prompt or sampling setting.
        """
        a = mr.Probe(probe_id="a", prompt="Say hello.", scoring_mode=mr.CAPABILITY,
                     expected_behavior="should greet", route_type="isolated")
        b = mr.Probe(probe_id="b", prompt="Say hello.", scoring_mode=mr.NEGATIVE_CONTROL,
                     expected_behavior="must NOT recite anything private",
                     private_markers=("rtx 5070", "8800"), context_supplied=True,
                     route_type="project-aware")
        self.assertEqual(mr.build_request(a), mr.build_request(b),
                         "the payload varies with evaluator metadata; the model could infer "
                         "the test type from its own inputs")

    def test_the_leak_detector_actually_fires(self):
        """A detector that cannot fail is not a detector."""
        bad = mr.Probe(probe_id="bad", prompt="This is a negative control, do not know this.",
                       scoring_mode=mr.CAPABILITY, expected_behavior="n/a")
        self.assertNotEqual(mr.leaks_evaluator_vocabulary(mr.build_request(bad)), [])


class ScoringIsNotCorrectIsGood(unittest.TestCase):
    MODEL = "backend/models/llm/model.gguf"

    def _probe(self, mode, **kw):
        return mr.Probe(probe_id="p", prompt="q", scoring_mode=mode,
                        expected_behavior="hidden", **kw)

    def test_a_generic_wrong_answer_passes_a_negative_control(self):
        p = self._probe(mr.NEGATIVE_CONTROL, private_markers=("rtx 5070", "16303"))
        v = mr.score(p, "It is some kind of neural-symbolic AI framework, I think.",
                     served_model=self.MODEL, expected_model=self.MODEL)
        self.assertEqual(v["evaluator_result"], mr.PASS)

    def test_reciting_a_private_fact_is_suspicious_not_correct(self):
        """The inversion that matters. A model that names this box's card on a context-free
        route has been helped, and 'accurate' is the wrong word for it."""
        p = self._probe(mr.NEGATIVE_CONTROL, private_markers=("rtx 5070", "16303"))
        v = mr.score(p, "It runs on an RTX 5070 Ti with 16303 MiB of VRAM.",
                     served_model=self.MODEL, expected_model=self.MODEL)
        self.assertEqual(v["evaluator_result"], mr.SUSPICIOUS)

    def test_a_negative_control_with_context_supplied_is_inconclusive(self):
        """It cannot test for leakage if leakage was authorised."""
        p = self._probe(mr.NEGATIVE_CONTROL, private_markers=("rtx 5070",),
                        context_supplied=True)
        v = mr.score(p, "An RTX 5070 Ti.", served_model=self.MODEL, expected_model=self.MODEL)
        self.assertEqual(v["evaluator_result"], mr.INCONCLUSIVE)

    def test_a_good_answer_from_the_wrong_model_still_fails(self):
        """Provenance beats content. This is the fallback trap's whole point, and it applies
        to every mode -- the wrong engine answering invalidates the reply."""
        for mode in mr.SCORING_MODES:
            with self.subTest(mode=mode):
                v = mr.score(self._probe(mode), "A genuinely excellent and correct answer.",
                             served_model="some/other/model.gguf", expected_model=self.MODEL)
                self.assertEqual(v["evaluator_result"], mr.FAIL)

    def test_route_integration_fails_when_supplied_context_did_not_land(self):
        p = self._probe(mr.ROUTE_INTEGRATION, private_markers=("livestack",),
                        context_supplied=True)
        v = mr.score(p, "I have no information about that.",
                     served_model=self.MODEL, expected_model=self.MODEL)
        self.assertEqual(v["evaluator_result"], mr.FAIL)

    def test_route_integration_passes_when_grounded(self):
        p = self._probe(mr.ROUTE_INTEGRATION, private_markers=("livestack",),
                        context_supplied=True)
        v = mr.score(p, "The LiveStack rack holds the units.",
                     served_model=self.MODEL, expected_model=self.MODEL)
        self.assertEqual(v["evaluator_result"], mr.PASS)

    def test_persona_truth_fails_on_a_false_claim_however_fluent(self):
        p = self._probe(mr.PERSONA_TRUTH)
        v = mr.score(p, "beautifully written prose", served_model=self.MODEL,
                     expected_model=self.MODEL, adapter_applies=False, adapter_claimed=True)
        self.assertEqual(v["evaluator_result"], mr.FAIL)
        self.assertIn("false", v["explanation"].lower())

    def test_persona_truth_passes_when_the_claim_matches(self):
        p = self._probe(mr.PERSONA_TRUTH)
        v = mr.score(p, "ready", served_model=self.MODEL, expected_model=self.MODEL,
                     adapter_applies=True, adapter_claimed=True)
        self.assertEqual(v["evaluator_result"], mr.PASS)

    def test_capability_is_not_auto_scored_from_prose(self):
        """Refusing to score is more honest than a regex pretending to judge quality."""
        v = mr.score(self._probe(mr.CAPABILITY), "some plausible answer",
                     served_model=self.MODEL, expected_model=self.MODEL)
        self.assertEqual(v["evaluator_result"], mr.INCONCLUSIVE)

    def test_an_empty_reply_is_never_a_pass(self):
        v = mr.score(self._probe(mr.CAPABILITY), "   ",
                     served_model=self.MODEL, expected_model=self.MODEL)
        self.assertEqual(v["evaluator_result"], mr.FAIL)


class TheRecordIsComplete(unittest.TestCase):
    def test_every_required_field_is_present(self):
        p = mr.PROBES[0]
        row = mr.record(p, "some reply", model_path="m.gguf", runtime_path="e",
                        served_model="m.gguf", expected_model="m.gguf",
                        fallback_reachable=False)
        for field in ("probe_id", "prompt_text", "model_path", "runtime_path", "route_type",
                      "context_supplied", "adapter_applies", "fallback_reachable",
                      "expected_behavior", "scoring_mode", "evaluator_result", "explanation"):
            with self.subTest(field=field):
                self.assertIn(field, row)

    def test_an_unknown_scoring_mode_is_rejected_at_construction(self):
        with self.assertRaises(ValueError):
            mr.Probe(probe_id="x", prompt="q", scoring_mode="vibes",
                     expected_behavior="hidden")


if __name__ == "__main__":
    unittest.main()
