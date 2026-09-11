"""The chat surface must not claim a persona adapter it is not running.

Every status surface used to ask `CHAT_ADAPTER.exists()` and present the answer as though it
meant "the adapter is in use". Those are different questions, and on 2026-08-22 the gap became
concrete: launching the production argv with the qwen2 persona adapter against the gpt-oss
candidate exits 1 --

    llama_adapter_lora_init: failed to apply lora adapter: model arch and LoRA arch mismatch

-- so a mismatch does not degrade the surface, it stops it from starting. And had the launch
been guarded without the status surfaces being fixed too, the rack unit would have gone on
advertising "+ persona adapter" and `/api` returning `"adapter": true` for an adapter the engine
had refused to load. That is a product describing itself falsely, which is the single thing this
repo exists to prevent.

`adapter_applies()` is the fix. These tests hold the line in both directions: it must stay TRUE
for the shipping configuration (so this was not a silent behaviour change), and it must go FALSE
the moment the chat model's architecture stops matching the adapter's.

Definitions are lifted out of api.py by AST and executed in an empty namespace -- the pattern
`test_studio_models.py` established -- so no decorator runs, no app object is built, and no
import at the top of api.py executes.
"""
from __future__ import annotations

import ast
import pathlib
import unittest

BACKEND = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
ROOT = BACKEND.parent
API_PY = BACKEND / "backend" / "server.py"
TREE = ast.parse(API_PY.read_text(encoding="utf-8"))
SRC = API_PY.read_text(encoding="utf-8")

QWEN_CHAT = ROOT / "models/llm/symon-1.0-7b-q4_k_m.gguf"
QWEN_DRAFT = ROOT / "models/llm/symon-1.0-draft-0.5b-q4_k_m.gguf"
ADAPTER = ROOT / "training/adapter/symoneural-lora.gguf"
CANDIDATE = ROOT / "models/staging/openai-gpt-oss-20b/symon-openai-20b.gguf"


def _funcs(*names: str) -> dict:
    """Execute just the named top-level functions from api.py in an empty namespace."""
    wanted = [n for n in TREE.body
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    missing = set(names) - {n.name for n in wanted}
    assert not missing, f"{API_PY} no longer defines {sorted(missing)}"
    ns: dict = {}
    exec(compile(ast.Module(body=wanted, type_ignores=[]), str(API_PY), "exec"), ns)
    return ns


def _const(name: str):
    """Read a simple top-level literal assignment out of api.py."""
    for node in TREE.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"{API_PY} does not assign a literal {name}")


class AdapterTruth(unittest.TestCase):
    """The predicate, in both directions. The FALSE case is the one that matters."""

    def setUp(self):
        self.ns = _funcs("_gguf_arch", "adapter_applies")
        self.ns["CHAT_MODEL"] = QWEN_CHAT
        self.ns["CHAT_ADAPTER"] = ADAPTER

    def test_the_adapter_applies_to_the_model_that_is_actually_shipping(self):
        """TRUE today, or this was a silent regression rather than a fix.

        A guard that turned the persona off for the live configuration would be a worse bug
        than the one it replaced, and it would be invisible: chat would keep answering.
        """
        if not (QWEN_CHAT.exists() and ADAPTER.exists()):
            self.skipTest("chat model or adapter absent on this box")
        self.assertEqual(self.ns["_gguf_arch"](QWEN_CHAT), "qwen2")
        self.assertEqual(self.ns["_gguf_arch"](ADAPTER), "qwen2")
        self.assertTrue(self.ns["adapter_applies"](),
                        "the shipping adapter must still be applied to the shipping model")

    def test_a_foreign_architecture_model_does_not_get_the_persona_adapter(self):
        """FALSE against gpt-oss. This is the test the whole change exists for.

        Measured, not hypothetical: with this adapter the candidate exits 1 on an arch
        mismatch. Before the fix, every status surface would still have said `adapter: true`.
        """
        if not (CANDIDATE.exists() and ADAPTER.exists()):
            self.skipTest("candidate or adapter absent on this box")
        self.assertEqual(self.ns["_gguf_arch"](CANDIDATE), "gpt-oss")
        self.ns["CHAT_MODEL"] = CANDIDATE
        self.assertFalse(self.ns["adapter_applies"](),
                         "a qwen2 adapter must never be claimed for a gpt-oss model")

    def test_unknown_architecture_counts_as_no(self):
        """Asymmetric on purpose. Not applying a good adapter costs the persona and still
        serves; applying a bad one takes the surface down. So uncertainty resolves to no."""
        self.ns["CHAT_MODEL"] = ROOT / "does-not-exist.gguf"
        self.assertFalse(self.ns["adapter_applies"]())

    def test_reading_an_architecture_never_raises(self):
        """Every caller is a status surface or a launch decision. Neither may crash over
        metadata, so the reader is total: garbage in, None out."""
        ga = self.ns["_gguf_arch"]
        for junk in (ROOT / "nope.gguf", API_PY, ROOT, ROOT / "README.md"):
            with self.subTest(path=str(junk)):
                self.assertIsNone(ga(junk))


class NoSurfaceStillGuessesFromFileExistence(unittest.TestCase):
    """Structural: `.exists()` must not be the basis of an adapter claim anywhere."""

    def test_adapter_claims_all_route_through_the_predicate(self):
        """`CHAT_ADAPTER.exists()` is permitted only inside the predicate itself and in the
        branch that logs why the adapter was skipped. Anywhere else it is the old bug."""
        # The predicate's own line range comes from the AST, not from a hardcoded window: a
        # numeric range would silently start exempting real offenders the moment code above
        # it grew, which is the failure mode of a check that looks like it is working.
        span = None
        for node in TREE.body:
            if isinstance(node, ast.FunctionDef) and node.name == "adapter_applies":
                span = (node.lineno, node.end_lineno)
        self.assertIsNotNone(span, "adapter_applies() is gone")

        offenders = []
        for i, line in enumerate(SRC.splitlines(), 1):
            if "CHAT_ADAPTER.exists()" not in line:
                continue
            stripped = line.strip()
            if stripped.startswith("#"):          # prose about the bug is fine
                continue
            if span[0] <= i <= span[1]:           # the predicate's own body
                continue
            if stripped.startswith("elif CHAT_ADAPTER.exists():"):
                continue                          # the "on disk but not applicable" log
            offenders.append(f"{i}: {stripped}")
        self.assertEqual(offenders, [],
                         "these read file existence and present it as adapter state")

    def test_the_launch_argv_guards_the_lora_flag(self):
        self.assertIn('if adapter_applies():\n            argv += ["--lora"', SRC,
                      "--lora must be gated on the predicate, not on the file existing")

    def test_a_skipped_adapter_is_logged_rather_than_silent(self):
        """A surface quietly serving without its persona, and a log that never mentions it,
        is how this would go unnoticed for weeks."""
        self.assertIn("persona adapter NOT applied", SRC)


class TheActiveDefaultIsStillQwen(unittest.TestCase):
    """gpt-oss is a benchmarked candidate. Nothing here promotes it."""

    def test_the_chat_model_is_the_qwen_file(self):
        self.assertIn('CHAT_MODEL = MODELS / "llm" / "symon-1.0-7b-q4_k_m.gguf"', SRC)

    def test_no_staging_path_is_wired_into_a_default(self):
        """The candidate lives in staging and must not be referenced by a serving default."""
        for node in TREE.body:
            if not isinstance(node, ast.Assign):
                continue
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in {"CHAT_MODEL", "DRAFT_MODEL"}:
                    self.assertNotIn("staging", ast.unparse(node.value),
                                     f"{t.id} points into staging")
                    self.assertNotIn("openai", ast.unparse(node.value).lower(),
                                     f"{t.id} names the candidate")

    def test_the_rollback_target_exists_on_disk(self):
        """Qwen is the rollback precisely because it never stopped being the default."""
        for p in (QWEN_CHAT, QWEN_DRAFT):
            with self.subTest(path=p.name):
                if not p.parent.exists():
                    self.skipTest("weights not present on this box")
                self.assertTrue(p.is_file(), f"rollback weight missing: {p}")

    def test_chat_model_and_its_label_change_together(self):
        """The label is what the rack unit and the site display. A label naming the wrong
        model is the one kind of wrong this project cannot ship, and the failure is silent --
        the surface keeps working while describing a model it is not running.

        This test is the pin: change CHAT_MODEL and it fails until the label is changed too.
        """
        self.assertEqual(_const("CHAT_MODEL_LABEL"), "SymonChat S1-7B")
        self.assertIn("symon-1.0-7b", SRC.split("CHAT_MODEL = ")[1].split("\n")[0],
                      "CHAT_MODEL changed but CHAT_MODEL_LABEL still says 7B")

    def test_the_rack_unit_label_is_not_hardcoded_beside_the_adapter_claim(self):
        self.assertIn("spec=CHAT_MODEL_LABEL", SRC)


class NothingElseMoved(unittest.TestCase):
    """This change touches the chat adapter decision. It must touch nothing else."""

    def test_the_image_stack_paths_are_untouched(self):
        for name in ("symoneural-image-unet-q4_k.gguf", "symoneural-image-t5-q8_0.gguf",
                     "symoneural-image-clip.safetensors", "symoneural-image-vae.safetensors"):
            with self.subTest(name=name):
                self.assertIn(name, SRC, "an image component vanished from api.py")

    def test_no_commercial_switch_was_introduced(self):
        for token in ("SYMONEURAL_COMMERCIAL", "COMMERCIAL_MODE", "ENABLE_BILLING"):
            with self.subTest(token=token):
                self.assertNotIn(token, SRC)

    def test_the_draft_model_default_is_unchanged(self):
        self.assertIn('DRAFT_MODEL = MODELS / "llm" / "symon-1.0-draft-0.5b-q4_k_m.gguf"', SRC)


if __name__ == "__main__":
    unittest.main()
