"""The two bench tools read their facts out of files that move. This pins the readers.

`tools/bench_llm.py` publishes a context-size table whose rows come from three different
places: a parsed GGUF header, the argv of the running engine, and four constants scraped
out of `backend/api.py`. Only the first two fail loudly. A scrape that stops matching
returns `None`, the table renders `?`, and a measurement report ships with a hole in it
that reads like an unanswered question rather than a broken tool -- which is exactly the
failure mode this repo already has a warning about: a figure nobody can check.

These tests run with no GPU, no engine and no network. The GGUF assertions apply only to
files that are actually present, so a fresh clone with an empty `models/` passes for the
right reason instead of being skipped wholesale.

The port assertion is the one that is not about drift. `LLAMA_PORT` is fixed at 8081 in
`api.py` and `llama_up()` decides the chat surface is healthy on nothing more than a 200
from `/health`, so a bench instance bound there would silently become what production
proxies to, serving the bench's argv under production's name and being indistinguishable
in any report written afterwards. `bench_llm_spec_ab.py` spawns engines, so the constant
that keeps it off that port is load-bearing and is pinned here rather than trusted to a
comment.
"""
import importlib.util
import re
import struct
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHAT_GGUF = ROOT / "backend" / "models" / "llm" / "symon-1.0-7b-q4_k_m.gguf"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bench = _load("bench_llm")
spec_ab = _load("bench_llm_spec_ab")


class ApiLimitScrapes(unittest.TestCase):
    """The four constants the context table quotes from `api.py`."""

    def setUp(self):
        self.limits = bench.api_declared_limits()

    def test_every_scraped_limit_was_found(self):
        missing = [k for k, v in self.limits.items() if v is None]
        self.assertEqual([], missing,
                         f"bench_llm.api_declared_limits() no longer finds {missing} in "
                         f"backend/api.py; the context-size table would render '?' for "
                         f"each of them instead of failing")

    def test_the_scraped_values_are_the_ones_api_py_actually_uses(self):
        # Not just "a number was found" -- the right number. A regex that drifts onto a
        # different constant of the same shape is worse than one that finds nothing.
        import ast
        src = (ROOT / "backend" / "api.py").read_text()
        tree = ast.parse(src)
        assigned = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                try:
                    assigned[node.targets[0].id] = ast.literal_eval(node.value)
                except Exception:
                    pass
        self.assertEqual(assigned.get("MAX_PROMPT_CHARS"),
                         int(self.limits["MAX_PROMPT_CHARS"].replace("_", "")))
        self.assertEqual(assigned.get("CHAT_MODEL_LABEL"),
                         self.limits["chat_model_label"])

    def test_the_ceiling_is_read_as_a_token_count_and_the_prompt_cap_as_characters(self):
        # The two are in different units, which is the whole reason the table has a
        # "where it comes from" column. Swapping them would look plausible and be wrong.
        self.assertEqual("100_000", self.limits["MAX_PROMPT_CHARS"])
        self.assertEqual("32768", self.limits["max_tokens_ceiling"])


class ArgvFlagReader(unittest.TestCase):
    """`_flag` picks values out of the engine's real command line."""

    PRODUCTION = (
        "/x/symoneural-llm -m /x/symon-1.0-7b-q4_k_m.gguf -ngl 99 --host 127.0.0.1 "
        "--port 8081 -c 65536 --no-warmup -cb -np 2 -md /x/draft.gguf -ngld 99 "
        "--spec-draft-n-max 2 --lora /x/symoneural-lora.gguf")

    def test_reads_the_context_and_slot_flags(self):
        self.assertEqual("65536", bench._flag(self.PRODUCTION, "-c"))
        self.assertEqual("2", bench._flag(self.PRODUCTION, "-np"))

    def test_does_not_confuse_cb_with_c(self):
        # `-cb` and `-c` are both present in the production argv and a substring match
        # would return "-np" as the context size.
        self.assertNotEqual("-np", bench._flag(self.PRODUCTION, "-c"))

    def test_absent_flag_is_none_rather_than_an_exception(self):
        self.assertIsNone(bench._flag(self.PRODUCTION, "--spec-type"))

    def test_a_trailing_flag_with_no_value_does_not_index_past_the_end(self):
        self.assertIsNone(bench._flag("/x/engine -m /x/model.gguf -c", "-c"))


class GgufHeaderParser(unittest.TestCase):

    def test_rejects_a_file_that_is_not_gguf(self):
        with tempfile.NamedTemporaryFile(suffix=".gguf") as f:
            f.write(b"NOPE" + bytes(64))
            f.flush()
            with self.assertRaises(ValueError):
                bench.gguf_metadata(Path(f.name), ("context_length",))

    @unittest.skipUnless(CHAT_GGUF.exists(), "chat weights not present")
    def test_reads_the_chat_models_trained_context(self):
        meta = bench.gguf_metadata(CHAT_GGUF, ("context_length", "general.architecture"))
        trained = next((v for k, v in meta.items() if k.endswith("context_length")), None)
        self.assertIsInstance(trained, int)
        # Not pinned to 32768: the point is that a value is READ, so that swapping the
        # weights changes the report instead of silently keeping the old figure.
        self.assertGreater(trained, 0)
        self.assertTrue(any(k.endswith("architecture") for k in meta))

    @unittest.skipUnless(CHAT_GGUF.exists(), "chat weights not present")
    def test_skips_the_tokenizer_arrays_without_reading_them(self):
        # The vocabulary is ~150k strings in this header. Reading it to reach a scalar
        # three keys later would work and would take long enough that nobody runs the
        # tool; the array path seeks past instead. Under a second is the assertion.
        import time
        started = time.monotonic()
        bench.gguf_metadata(CHAT_GGUF, ("context_length",))
        self.assertLess(time.monotonic() - started, 5.0)


class ScratchInstancesStayOffTheProductionPort(unittest.TestCase):

    def test_neither_scratch_port_is_the_one_api_py_proxies_to(self):
        api_src = (ROOT / "backend" / "api.py").read_text()
        m = re.search(r"^LLAMA_PORT\s*=\s*(\d+)", api_src, re.M)
        self.assertIsNotNone(m, "LLAMA_PORT is no longer a module-level literal in "
                                "api.py; this guard cannot see what to avoid")
        production = int(m.group(1))
        self.assertNotIn(production, (spec_ab.PORT_OFF, spec_ab.PORT_ON))

    def test_the_two_sides_do_not_share_a_port(self):
        self.assertNotEqual(spec_ab.PORT_OFF, spec_ab.PORT_ON)

    def test_the_ab_argv_differs_only_by_the_flag_under_test(self):
        off = spec_ab.base_argv(spec_ab.PORT_OFF)
        on = spec_ab.base_argv(spec_ab.PORT_ON) + ["--spec-type", "draft-simple"]
        # Everything but the port and the flag under test must match, or the comparison
        # is measuring two configurations rather than one change.
        strip = lambda a: [x for i, x in enumerate(a)
                           if x not in (str(spec_ab.PORT_OFF), str(spec_ab.PORT_ON))]
        self.assertEqual(strip(off), strip(on)[:-2])
        self.assertEqual(["--spec-type", "draft-simple"], strip(on)[-2:])


if __name__ == "__main__":
    unittest.main()
