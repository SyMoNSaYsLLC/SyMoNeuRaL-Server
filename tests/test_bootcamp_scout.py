"""The Bootcamp Scout's measured roster must be measured, and must exclude other people's code.

`tools/bootcamp_scout.py` supplies every FACT in
`docs/specs/symoneural-bootcamp.md` -- which app owns which routes, which weights are
on disk, which architecture each one is, which model is the serving default. The document
supplies the judgements. That split only works if the facts are actually read off the disk.

The bug worth pinning: the first run of that scanner reported `sigils` at 4,185 Python files
and `studio` at 3,442, and attributed env flags like `PIP_NO_COLOR`, `XDG_CONFIG_HOME` and
`NUMBA_DUMP_LLVM` to SyMoNeuRaL apps. All of it came from vendored site-packages underneath
them. A depth chart built on that would have stated, authoritatively, that the Studio app gates on
`ANTHROPIC_API_KEY` -- when it is an SDK vendored inside it that reads that variable. Numbers
that wrong are worse than absent numbers, because they read as measurements.
"""
from __future__ import annotations

import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "bootcamp_scout.py"


def _load():
    spec = importlib.util.spec_from_file_location("bootcamp_scout", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class VendoredCodeIsNotOurs(unittest.TestCase):
    def setUp(self):
        self.cm = _load()

    def test_vendored_paths_are_recognised(self):
        for p in ("backend/studio/x/site-packages/foo/bar.py",
                  "backend/sigils/.venv/lib/thing.py",
                  "archive/vendor-sdks/sdk/mod.py",
                  "backend/a/node_modules/b/c.py",
                  "backend/a/__pycache__/b.pyc",
                  "backend/a/thing.dist-info/RECORD.py"):
            with self.subTest(path=p):
                self.assertTrue(self.cm.is_vendored(pathlib.Path(p)))

    def test_our_own_modules_are_not_flagged_as_vendored(self):
        for p in ("backend/studio/routes.py", "backend/voice/asr.py",
                  "backend/server.py", "backend/ravencalc/engine.py"):
            with self.subTest(path=p):
                self.assertFalse(self.cm.is_vendored(pathlib.Path(p)))

    def test_no_app_reports_an_implausible_file_count(self):
        """A SyMoNeuRaL app is tens of files, not thousands. Thousands means the vendor
        filter broke, and the failure is silent -- the survey still prints a number."""
        s = self.cm.survey()
        for name, app in s["apps"].items():
            with self.subTest(app=name):
                self.assertLess(app["py_files"], 300,
                                f"{name} reports {app['py_files']} own .py files; "
                                "the vendor filter is not holding")

    def test_foreign_env_flags_are_separated_not_attributed(self):
        """Flags a vendored SDK reads are recorded separately, never as the app's own."""
        s = self.cm.survey()
        for name, app in s["apps"].items():
            for flag in app["env_flags"]:
                with self.subTest(app=name, flag=flag):
                    self.assertTrue(
                        flag.startswith(("SYMONEURAL", "SYMON_", "DJ_")),
                        f"{name} claims {flag} as its own flag")


class TheSpineIsActuallyMeasured(unittest.TestCase):
    def setUp(self):
        self.cm = _load()

    def test_the_serving_default_is_read_from_the_source_not_hardcoded(self):
        """If this tool hardcoded the default, the depth chart could not catch a promotion."""
        got = self.cm.serving_defaults()
        self.assertIn("CHAT_MODEL", got)
        self.assertIn("symon-1.0-7b-q4_k_m.gguf", got["CHAT_MODEL"])
        # Quote-agnostic on purpose. The first version of this assertion looked only for a
        # double-quoted literal and a single-quoted hardcode walked straight past it -- the
        # check could not fire, which is worse than not having it.
        src = TOOL.read_text(encoding="utf-8")
        code = "\n".join(ln for ln in src.splitlines()
                         if not ln.lstrip().startswith(("#", '"""', "*")))
        for weight in ("symon-1.0-7b-q4_k_m.gguf", "symon-1.0-draft-0.5b-q4_k_m.gguf"):
            with self.subTest(weight=weight):
                self.assertNotIn(weight, code,
                                 "the tool names a current default as a literal; it must "
                                 "READ the value so a promotion cannot slip past the depth chart")

    def test_the_architecture_reader_agrees_with_the_serving_module(self):
        """Two independent copies of the same reader, deliberately. They must not disagree --
        a depth chart saying `qwen2` while the serving code says otherwise is the whole failure
        this design is trying to avoid."""
        chat = ROOT / "backend/models/llm/symon-1.0-7b-q4_k_m.gguf"
        if not chat.is_file():
            self.skipTest("chat weight absent on this box")
        self.assertEqual(self.cm.gguf_arch(chat), "qwen2")

    def test_the_architecture_reader_is_total(self):
        for junk in (ROOT / "nope.gguf", TOOL, ROOT):
            with self.subTest(path=str(junk)):
                self.assertIsNone(self.cm.gguf_arch(junk))

    def test_routes_are_parsed_from_the_ast_not_grepped(self):
        found = self.cm.routes_in(ROOT / "backend/server.py")
        self.assertTrue(found, "no routes parsed out of api.py at all")
        for r in found:
            self.assertIn(r["method"], {"GET", "POST", "PUT", "PATCH", "DELETE", "WEBSOCKET"})
            self.assertTrue(r["path"].startswith("/"), f"not a path: {r['path']!r}")

    def test_the_survey_reports_the_candidate_as_staged(self):
        """gpt-oss must show up as staged, never as a serving default."""
        s = self.cm.survey()
        cand = [w for w in s["weights"] if "openai-gpt-oss" in w["path"]]
        if not cand:
            self.skipTest("candidate not staged on this box")
        for w in cand:
            self.assertTrue(w["staged"], f"{w['path']} is not marked staged")
        gguf = [w for w in cand if w["path"].endswith(".gguf")]
        if gguf:
            self.assertEqual(gguf[0]["arch"], "gpt-oss")
        self.assertNotIn("staging", s["serving_defaults"].get("CHAT_MODEL", ""),
                         "a serving default points into the staging tree")


if __name__ == "__main__":
    unittest.main()
