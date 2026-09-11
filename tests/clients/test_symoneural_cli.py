"""`bin/symoneural-cli` -- the operator surface, held to the rules it prints.

AUDIT-SURFACE-2026-08-19 item 7: 981 lines and, when the item was filed, no tests. By the
time this file landed, `test_cli_upgrade.py` existed and owns the `upgrade` subcommand,
`sudo_argv` and the status verdict row end to end; nothing here repeats those. This file
covers everything else the audit's fix shape names -- `HERE`/`ROOT` resolution, the
subcommand table, and each command's no-device path -- plus the repo rules the CLI is the
most likely file to break.

What each part of this file catches:

  * **The parser table** (`SubcommandTableTests`). Twelve subcommands must dispatch to
    twelve handlers with the defaults the help text promises. Behavioural tests that call
    `cmd_*` directly cannot see a deleted `set_defaults` line or a renamed subcommand --
    argparse rejects the name before any code runs -- so these drive `main()` itself with
    the handlers stubbed.
  * **No-device degradation** (status, residency, chat, image, agent, tools, tool, state,
    mcp, `_stop-chat`, the transcript store). The CLI is what an operator reaches for when
    the box is broken, so a missing pidfile, a silent driver, absent weights or a
    half-written transcript must render as `none`/`?`/a named gap and a clean exit code,
    never a traceback. Everything runs hermetically: `smi`, `RUN`, `STATE`, the model
    paths and the HTTP layer are rebound to stubs and tmpdirs, so nothing touches
    nvidia-smi, systemd, the network, or the real `run/`.
  * **The measured arithmetic** (`ResidencyArithmeticTests`). The residency plan is
    computed, not asserted, so the tests feed known device readings and check the printed
    figures by hand: 16384 MiB total * (1 - 0.35) = 10.4 GiB of budget, 12288 MiB free
    leaves 1.6 GiB of headroom, and a weight file sized at a tenth of a second of the
    measured link must read `100 ms` whatever the measured constant currently is -- which
    is what catches a MiB-for-bytes slip or the theoretical PCIe rate substituted for the
    measured one. The GiB literals are pinned to `KV_RESERVE == 0.35`; a re-measure is
    supposed to fail here so the figures get re-derived rather than silently inherited.
  * **Repo rules, structurally** (`StructuralRuleTests`). Three rules from
    `.claude/CLAUDE.md` take root, the GPU or a second process to violate, so they are
    asserted against the source text instead of run: the governor is only ever invoked as
    `with <named surface>` and the word `release` appears nowhere (an unscoped release
    once destroyed a running fine-tune's lock); the CLI never spawns `llama-server`
    (`api.py` owns that process -- a second spawner races it for :8081 and the lease); and
    `cmd_ravencalc` never touches the governor or a subprocess (the CPU surface never
    queues; that asymmetry is the point of the subcommand). Structural assertions rot
    silently, so `test_the_regexes_in_this_file_still_match_the_cli` pins the match
    counts and fails first if a refactor makes the others vacuous.

## How the tests are built

The CLI has no `.py` suffix, so `load_cli()` compiles its text on every call rather
than importing it through a caching loader -- see that function for the stale-bytecode
trap that cost an hour, and note `test_cli_upgrade.py` does the same. Import has three side
effects -- the repo-root assert, a `sys.path` insert, and `symoneuralenv.promote()` --
all idempotent and safe to repeat, so every mutating class loads a FRESH module in
`setUp` and rebinds the module's *names* (`cli.smi = ...`,
`cli.subprocess = SimpleNamespace(...)`), never the shared modules behind them: the
first version of `test_cli_upgrade.py` stubbed `subprocess.run` itself and 27 tests in
apps/voice and apps/streamer failed, handed a stub they never asked for. Two exceptions are
taken deliberately and restored via `addCleanup`: `urllib.request.urlopen` (`api_open`
imports it function-locally, so a module-name rebinding cannot intercept it) and
`sys.modules["ravencalc"]` (what `import ravencalc` reads; injecting a fake there is
what makes the ravencalc tests pass both where sympy is absent and on the box, where it
is not).

Stdlib only, and every test passes with no GPU, no nvidia-smi, no running API, and no
root.
"""
from __future__ import annotations

import contextlib
import copy
import inspect
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
import urllib.error
from pathlib import Path

ROOT = next(_p for _p in Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
CLI_PATH = ROOT / "bin" / "symoneural-cli"
SRC = CLI_PATH.read_text(encoding="utf-8")

# `[str(GOVERNOR), "with", "chat", "--", ...]` -- the verb and the surface, as literals.
GOVERNOR_ARGV = re.compile(r'\[str\(GOVERNOR\),\s*"(\w+)",\s*"(\w+)"')

# The two sanctioned mentions of the LLM *server*: the built-yet probe, and the janitor's
# pkill. Pinned by their exact quoting rather than by the bare name, because after the
# engines were forked under our own names the bare string also appears in `LLM_BIN`'s path
# segment and inside `symoneural-llm-cli` -- and neither of those is the server.
SERVER_PROBE = re.compile(r"LLM_BIN / 'symoneural-llm'\)\.exists\(\)")
SERVER_PKILL = re.compile(r'\["pkill", "-f", "bin/symoneural-llm"\]')
SERVER_MENTION = re.compile(r"'symoneural-llm'|\"bin/symoneural-llm\"")

# The subcommand table as declared: direct `add_parser("name")` calls, plus the four that go
# through the `studio("name", ...)` helper, whose own `add_parser(name, ...)` takes a
# variable and is invisible to the first regex.
ADD_PARSER = re.compile(r'add_parser\(\s*"([a-z_-]+)"')
STUDIO_PARSER = re.compile(r'\bstudio\(\s*"([a-z]+)"')

#: `import-claude` is the fourteenth, added 2026-09-08. It migrates the owner's own
#: material out of the retired provider's state directory into first-party SyMoNeuRaL
#: state: memories, commands, skills, agents, MCP definitions, deny rules and plain
#: role/content turns. It writes nothing without `--apply`, refuses credentials, path
#: escapes and silent overwrites, and is idempotent. Behaviour is described by
#: symoneural-code/tests/test_import_claude.py, 42 tests.
KNOWN_SUBCOMMANDS = {"status", "residency", "upgrade", "chat", "image", "ravencalc",
                     "agent", "tools", "tool", "state", "repl", "mcp", "_stop-chat",
                     "import-claude"}

_MISSING = object()


def load_cli() -> types.ModuleType:
    """Import the CLI as a module, compiling the source on every call.

    It has no `.py` suffix, so the loader has to be explicit -- but a `SourceFileLoader`
    also *caches*, and that cache is the reason this reads and compiles the text instead.
    Importing an extensionless script writes `bin/__pycache__/symoneural-clicpython-313.pyc`
    beside the shipped file, and CPython validates that cache against the source mtime
    **truncated to whole seconds**. Edit the CLI and re-run inside the same second -- which a
    scripted mutate-run-restore loop does trivially -- and the loader hands back the previous
    bytecode with no error and no warning. That happened here: a deliberate mutation was
    reverted, the suite went red anyway, and the code under test was not the code on disk.
    A test suite whose whole job is to assert what the file says cannot be reading a copy of
    what it said a moment ago, so this path has no cache to be stale.
    """
    module = types.ModuleType("symoneural_cli_under_test")
    module.__file__ = str(CLI_PATH)
    exec(compile(CLI_PATH.read_text(), str(CLI_PATH), "exec"), module.__dict__)  # noqa: S102
    return module


def call(fn, args) -> tuple[int, str, str]:
    """(rc, stdout, stderr). StringIO has no tty, so `c()` emits no colour codes here."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = fn(args)
    return rc, out.getvalue(), err.getvalue()


@contextlib.contextmanager
def env_patch(**names):
    """Set (or, with None, remove) environment variables, restoring them exactly."""
    saved = {k: os.environ.get(k) for k in names}
    try:
        for k, v in names.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def line_with(needle: str, text: str) -> str:
    for line in text.splitlines():
        if needle in line:
            return line
    raise AssertionError(f"no line containing {needle!r} in:\n{text}")


def recorder(calls: list, rc_for=None):
    """A `subprocess.run` stand-in that records argv and answers with a chosen rc."""
    def run(argv, *_a, **_kw):
        argv = [str(x) for x in argv]
        calls.append(argv)
        rc = rc_for(argv) if rc_for else 0
        return subprocess.CompletedProcess(argv, rc)
    return run


def shim_subprocess(cli: types.ModuleType, run) -> None:
    """Rebind the module's `subprocess` NAME, never the shared module behind it -- the
    voice/tuner incident recorded in test_cli_upgrade.py is why."""
    cli.subprocess = types.SimpleNamespace(
        run=run, CompletedProcess=subprocess.CompletedProcess,
        SubprocessError=subprocess.SubprocessError,
        TimeoutExpired=subprocess.TimeoutExpired)


class LoadAndLayoutTests(unittest.TestCase):
    """The audit item's first named target: `HERE`/`ROOT` resolution."""

    def test_root_resolution_finds_this_repo(self):
        """The CLI's own comment says this calculation has been wrong four times and fails
        silently, because the wrong parent is usually a directory that exists. So the test
        computes the repo root independently (from this file, two levels up) and requires
        the CLI to have landed on the same one -- not merely on *a* directory."""
        cli = load_cli()
        # The client was promoted from bin/ to symoneural-code/bin/ on 2026-09-08, so HERE
        # is one level deeper. `bin/symoneural-cli` is now a symlink to it and still works.
        # The assertion that matters is unchanged and is the line below: whatever HERE is,
        # ROOT must be the real repo root -- which is what the promotion broke and what the
        # marker walk fixed.
        self.assertEqual(cli.HERE, ROOT / "symoneural-code" / "bin")
        self.assertEqual(cli.ROOT, ROOT)
        self.assertTrue((cli.ROOT / "backend" / "server.py").is_file())

    def test_state_dir_and_api_url_read_the_environment_at_import(self):
        """`SYMONEURAL_STATE_DIR` is the seam the packaged .deb's tests point at a tmpdir,
        and `SYMONEURAL_API_URL` is how an operator aims the studio subcommands at a spare
        port. Both are read at module scope, so losing either is invisible until someone's
        override silently stops overriding. Legacy `SYM_*` spellings are popped too, or
        `symoneuralenv.promote()` would faithfully copy them back over the gap."""
        with tempfile.TemporaryDirectory() as td:
            with env_patch(SYMONEURAL_STATE_DIR=td, SYM_STATE_DIR=None,
                           SYMONEURAL_API_URL="http://10.9.8.7:1234", SYM_API_URL=None):
                cli = load_cli()
                self.assertEqual(cli.STATE, Path(td))
                self.assertEqual(cli.DEFAULT_API, "http://10.9.8.7:1234")
        with env_patch(SYMONEURAL_STATE_DIR=None, SYM_STATE_DIR=None,
                       SYMONEURAL_API_URL=None, SYM_API_URL=None):
            cli = load_cli()
            self.assertEqual(cli.STATE, Path("/var/lib/symoneural"))
            self.assertEqual(cli.DEFAULT_API, "http://127.0.0.1:8800")


class PureRenderingTests(unittest.TestCase):
    def setUp(self):
        self.cli = load_cli()

    def test_colour_is_stripped_when_stdout_is_not_a_tty(self):
        """ANSI codes in piped output are what turn `symoneural-cli status | grep` and
        cron mail into garbage. Captured stdout is a StringIO, which honestly reports
        `isatty() == False`, so this asserts the bare text comes back bare."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(self.cli.c("held", self.cli.AMBER), "held")

    def test_colour_wraps_and_resets_on_a_tty(self):
        """The reset suffix is the half that matters: a colour opened and never closed
        bleeds into the operator's next prompt."""
        self.cli._tty = lambda: True
        self.assertEqual(self.cli.c("ok", self.cli.GREEN), "\033[32mok\033[0m")

    def test_one_line_flattens_collapses_and_states_its_size(self):
        """Tool results are rendered one per stream frame; an embedded newline would break
        the frame-per-line contract, and a silent truncation would hide that a result was
        4 KB. The clip must say how big the original was."""
        one = self.cli._one_line
        self.assertEqual(one("short", 50), "short")
        self.assertEqual(one("a\n b\tc", 50), "a b c")
        self.assertEqual(one("x" * 100, 10), "x" * 10 + "... (100 chars)")
        self.assertEqual(one({"a": 1}, 50), '{"a": 1}')


class MarkdownRenderTests(unittest.TestCase):
    """`render_markdown` -- the loop answers in markdown and this printed the source.

    Two rules are load-bearing here and both are asserted rather than assumed. The first is
    the repo's: a layout change may not drop data, which for a renderer means no truncation,
    no elision and no re-wrapping, and a link that keeps its target as well as its label.
    The second is narrower and is the one a refactor is likeliest to break: a pipe gets the
    text back UNCHANGED. The same string is what `--output-format json` carries and what the
    transcript under `run/` records, so a renderer that edits it for a terminal has edited
    the record too.
    """

    def setUp(self):
        self.cli = load_cli()
        self.cli._tty = lambda: True
        self.r = self.cli.render_markdown

    @staticmethod
    def plain(text: str) -> str:
        return re.sub(r"\x1b\[[0-9;]*m", "", text)

    def test_a_pipe_gets_the_answer_back_byte_for_byte(self):
        """The half of the contract that protects the record. Rendering adds colour and
        nothing else, so where colour cannot go, neither does rendering: stripping `**` for
        a pipe would edit the answer without putting anything on screen in its place."""
        self.cli._tty = lambda: False
        src = "# Title\n\n**bold** and `code`\n\n- a bullet\n"
        self.assertEqual(self.cli.render_markdown(src), src)

    def test_emphasis_becomes_a_terminal_attribute_and_the_markers_go(self):
        out = self.r("Some **bold** and *italic* here")
        self.assertIn(f"{self.cli.BOLD}bold{self.cli.OFF}", out)
        self.assertIn(f"{self.cli.ITALIC}italic{self.cli.OFF}", out)
        self.assertNotIn("**", out)
        self.assertEqual(self.plain(out), "Some bold and italic here")

    def test_a_code_span_keeps_its_contents_exactly_including_markup(self):
        """The reason code spans are lifted out before anything else runs. A span is where
        somebody writes `**not bold**` while explaining markdown, and it is the one place
        those four asterisks have to survive."""
        out = self.r("literally `**not bold**` please")
        self.assertIn("**not bold**", self.plain(out))
        self.assertIn(self.cli.AMBER, out)

    def test_a_link_keeps_both_its_label_and_its_target(self):
        """A url folded away behind a word is a citation the reader cannot check, which is
        the same data-loss rule the CSS side of this repo states as `no text-overflow`."""
        out = self.plain(self.r("see [the manual](https://symoneural.com/docs)"))
        self.assertIn("the manual", out)
        self.assertIn("https://symoneural.com/docs", out)

    def test_a_link_with_no_label_still_shows_its_target(self):
        """`[](url)` is a typo in the markdown, not a reason to print nothing."""
        self.assertIn("https://x.test/a", self.plain(self.r("here: [](https://x.test/a)")))

    def test_a_fenced_block_keeps_its_own_indentation_and_names_its_language(self):
        """Leading whitespace inside a fence is often the program's own, and in a language
        where it is syntax, eating it hands the reader something that does not run."""
        out = self.plain(self.r("```python\nif x:\n    return 1\n```"))
        self.assertIn("python", out)
        self.assertIn("    if x:", out)
        self.assertIn("        return 1", out)
        self.assertNotIn("```", out)

    def test_markup_inside_a_fence_is_left_alone(self):
        """A shell block full of `*` globs is not emphasis, and rendering it as emphasis
        would delete the glob."""
        out = self.plain(self.r("```sh\nrm *.tmp **/*.log\n```"))
        self.assertIn("rm *.tmp **/*.log", out)

    def test_headings_bullets_quotes_and_rules_each_render_as_themselves(self):
        out = self.plain(self.r("## Heading\n\n- one\n  - nested\n\n> quoted\n\n---"))
        self.assertIn("Heading", out)
        self.assertNotIn("##", out)
        self.assertIn("• one", out)
        self.assertIn("  • nested", out)          # the indent is the nesting; it stays
        self.assertIn("│ quoted", out)
        self.assertRegex(out, "─{4,}")

    def test_an_ordered_list_is_not_renumbered_or_rewritten(self):
        """The failure mode of a renderer that "handles" ordered lists: it renumbers, and
        then what the model said about step three is about a different step."""
        out = self.plain(self.r("1. first\n2. second\n7. seventh"))
        self.assertEqual(out.splitlines(), ["1. first", "2. second", "7. seventh"])

    def test_no_word_of_the_source_is_lost(self):
        """The blunt data-loss check, and the one that catches a clever future rule that
        drops something nobody thought to assert on. Every word in, every word out."""
        src = ("# Report\n\nA **measured** figure of `151 tok/s`, see [the manual](/docs).\n\n"
               "- vendor specification, not projected\n"
               "> published negative results too\n\n```sh\nnvidia-smi --query-gpu=name\n```\n")
        got = self.plain(self.r(src))
        for word in re.findall(r"[A-Za-z0-9/=.-]{2,}", re.sub(r"[*`#>\[\]()]", " ", src)):
            self.assertIn(word, got, f"{word!r} was dropped by the renderer")

    def test_an_unclosed_fence_still_shows_every_line(self):
        """A truncated stream can end mid-block. The block styling running to the end of the
        answer is what a markdown renderer does; losing the lines is not."""
        out = self.plain(self.r("text\n```\nline one\nline two"))
        self.assertIn("line one", out)
        self.assertIn("line two", out)

    def test_empty_input_comes_back_empty_rather_than_as_a_blank_line(self):
        self.assertEqual(self.r(""), "")


class StatusLineTests(unittest.TestCase):
    """`status_line` and `resolved_permissions`.

    The status line existed inline in `cmd_repl` and named the session, the turn, the depth
    and the model. It omitted the permission mode, which is the one setting on a session that
    decides whether a tool runs without anybody being asked -- an operator who typed
    `/permissions allow` forty turns earlier had nothing on screen to remind them. Extracted
    to a function so the line can be asserted without driving an interactive session, and so
    the mode shown and the mode enforced come from one resolution instead of two.
    """

    def setUp(self):
        self.cli = load_cli()

    def ns(self, **kw):
        base = {"permissions": "auto", "dangerously_allow_all": False, "allow_tool": []}
        return types.SimpleNamespace(**{**base, **kw})

    def test_the_permission_mode_is_on_the_line(self):
        line = self.cli.status_line("s", 2, 4, permissions="ask")
        self.assertEqual(line, "[s  turn 2  4 messages  perm ask]")

    def test_allow_is_never_quiet(self):
        """The state that most needs saying. If this line can be rendered without it, the
        most permissive session this client offers is also its least visible."""
        self.assertIn("perm allow", self.cli.status_line("s", 1, 2, permissions="allow"))

    def test_exemptions_are_named_when_there_are_any_and_absent_when_there_are_not(self):
        """A widened permission is worth a word; an empty list is noise on every line
        forever."""
        with_them = self.cli.status_line("s", 1, 2, permissions="ask",
                                        exempt=("run_command", "delete_path"))
        self.assertIn("exempt run_command, delete_path", with_them)
        self.assertNotIn("exempt", self.cli.status_line("s", 1, 2, permissions="ask"))

    def test_the_model_appears_only_when_one_was_chosen(self):
        self.assertIn("qwen-x", self.cli.status_line("s", 1, 2, model="qwen-x"))
        self.assertEqual(self.cli.status_line("s", 1, 2), "[s  turn 1  2 messages]")

    def test_one_message_is_not_one_messages(self):
        self.assertIn("1 message]", self.cli.status_line("s", 1, 1))
        self.assertIn("2 messages", self.cli.status_line("s", 1, 2))

    def test_dangerously_allow_all_outranks_the_permissions_flag(self):
        """Both flags can be passed. The report has to name the one in force, or the line
        says `deny` about a session running everything."""
        self.assertEqual(self.cli.resolved_permissions(
            self.ns(permissions="deny", dangerously_allow_all=True)), "allow")

    def test_auto_resolves_by_whether_there_is_a_terminal_to_ask_at(self):
        """`auto` is not a state, it is a question -- and the answer with nobody there must
        be deny. This is the client half of the loop's own no-failing-open rule."""
        self.cli.have_tty = lambda: True
        self.assertEqual(self.cli.resolved_permissions(self.ns()), "ask")
        self.cli.have_tty = lambda: False
        self.assertEqual(self.cli.resolved_permissions(self.ns()), "deny")

    def test_an_explicit_mode_is_passed_through_untouched(self):
        for mode in ("ask", "deny", "allow"):
            with self.subTest(mode=mode):
                self.assertEqual(
                    self.cli.resolved_permissions(self.ns(permissions=mode)), mode)

    def test_the_repl_reports_and_the_status_line_cannot_disagree(self):
        """Structural, because the alternative is driving a whole session. `/permissions`
        printed its own longhand resolution and the status line would have needed a second
        copy; the duplicated rule is what drifts, and it drifts silently in the direction of
        showing a safer mode than the one in force."""
        src = CLI_PATH.read_text()
        # `(?<!def )` because the definition line matches the call spelling exactly, and a
        # test that counts its own subject is how a structural assertion goes vacuous.
        calls = re.findall(r"(?<!def )resolved_permissions\(args\)", src)
        self.assertEqual(len(calls), 4,
                         "four callers must ask the shared resolver: the mode SENT to the "
                         "server in cmd_agent, the /permissions report, the status line, and "
                         "the launch splash")
        self.assertEqual(src.count("if have_tty() else"), 1,
                         "the auto resolution exists in more than one place again")


class DeviceProbeTests(unittest.TestCase):
    def setUp(self):
        self.cli = load_cli()
        self.calls: list[list[str]] = []

    def test_smi_asks_for_exactly_one_field_and_reads_the_first_line(self):
        """The query string is an nvidia-smi contract: `--format=csv,noheader,nounits` is
        what makes `float(smi(...))` in the residency plan safe. A second output line (a
        second GPU, a driver banner) must not leak into the value."""
        def run(argv, **kw):
            self.calls.append([str(x) for x in argv])
            return types.SimpleNamespace(stdout=" 16303 \nsecond-gpu\n")
        shim_subprocess(self.cli, run)
        self.assertEqual(self.cli.smi("memory.total"), "16303")
        self.assertEqual(self.calls, [["nvidia-smi", "--query-gpu=memory.total",
                                       "--format=csv,noheader,nounits"]])

    def test_smi_reads_empty_when_the_driver_will_not_say(self):
        """The docstring's promise: '' when the driver will not say. A box with no driver,
        a hung driver, or a driver that answers with nothing must degrade to '' -- the
        callers render that as '?' -- and never to a traceback."""
        cases = {
            "no binary": lambda argv, **kw: (_ for _ in ()).throw(FileNotFoundError()),
            "hung": lambda argv, **kw: (_ for _ in ()).throw(
                subprocess.TimeoutExpired("nvidia-smi", 10)),
            "silent": lambda argv, **kw: types.SimpleNamespace(stdout=""),
        }
        for name, fake in cases.items():
            with self.subTest(driver=name):
                shim_subprocess(self.cli, fake)
                self.assertEqual(self.cli.smi("memory.free"), "")

    def test_diffuse_binary_takes_the_one_name_this_fork_produces(self):
        """This used to accept two names, because the upstream project renamed its CLI
        mid-flight and a build from either side of that had a different filename. We build
        this engine ourselves now and `fork_engines.sh` sets the name, so there is exactly
        one and the fallback is gone -- a branch that can never fire is where a real miss
        hides. The old upstream names must NOT be accepted: finding one would mean the CLI
        is pointing at somebody else's build tree again."""
        with tempfile.TemporaryDirectory() as td:
            self.cli.DIFFUSE_BIN = Path(td)
            self.assertIsNone(self.cli.diffuse_binary())
            for stale in ("sd", "sd-cli"):
                (Path(td) / stale).touch()
            self.assertIsNone(self.cli.diffuse_binary(),
                              "an upstream engine name still satisfies the image probe")
            (Path(td) / "symoneural-diffuse").touch()
            self.assertEqual(self.cli.diffuse_binary().name, "symoneural-diffuse")


class RunStateDegradationTests(unittest.TestCase):
    """`run/` on the worst day: absent, stale, or corrupt, and the CLI still answers."""

    def setUp(self):
        self.cli = load_cli()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_dir = Path(self.tmp.name)

    def test_chat_running_reads_the_pidfile_defensively(self):
        """A pidfile is a claim, not a fact: the process may have died without cleanup, or
        the file may hold garbage from a partial write. Every bad state must read as 'not
        running' -- the alternative is `status` crashing on the exact box it exists to
        diagnose. The live case uses this test's own pid, which provably exists."""
        pidfile = self.run_dir / "chat.pid"
        self.cli.CHAT_PIDFILE = pidfile
        cases = {
            "no pidfile": (None, False),
            "garbage": ("not-a-pid", False),
            "stale pid": (str(2**31 - 1), False),   # far above pid_max: nothing owns it
            "live pid": (str(os.getpid()), True),
        }
        for name, (content, expected) in cases.items():
            with self.subTest(pidfile=name):
                if content is None:
                    pidfile.unlink(missing_ok=True)
                else:
                    pidfile.write_text(content)
                self.assertIs(self.cli.chat_running(), expected)

    def test_last_deploy_reads_the_first_line_or_nothing(self):
        """The verdict file is written by the .deb postinst and read back by two commands
        as history. Absent must read as '' (test_cli_upgrade.py asserts the row is then
        not rendered), and so must EMPTY: `''.splitlines()[0]` raises IndexError, which is
        exactly the crash the except clause names. Extra lines are somebody's future
        append; only the first is the verdict."""
        self.cli.STATE = self.run_dir
        self.assertEqual(self.cli.last_deploy(), "")
        (self.run_dir / "last-deploy").write_text("")
        self.assertEqual(self.cli.last_deploy(), "")
        (self.run_dir / "last-deploy").write_text("ok: 2026-08-20T09:00:00+0000\nnoise\n")
        self.assertEqual(self.cli.last_deploy(), "ok: 2026-08-20T09:00:00+0000")

    def test_stop_chat_is_safe_with_and_without_a_pidfile(self):
        """`_stop-chat` is the janitor, so it of all commands must work in every half-torn
        state: no pidfile still sweeps with pkill; a garbage pidfile is removed rather
        than crashed on; a real pid gets SIGTERM before the sweep. `os.kill` and
        `subprocess` are recorded stand-ins, so nothing is actually signalled."""
        pidfile = self.run_dir / "chat.pid"
        self.cli.CHAT_PIDFILE = pidfile
        kills: list[tuple[int, int]] = []
        self.cli.os = types.SimpleNamespace(kill=lambda pid, sig: kills.append((pid, sig)))
        calls: list[list[str]] = []
        shim_subprocess(self.cli, recorder(calls))

        with self.subTest(state="no pidfile"):
            rc, _, _ = call(self.cli.cmd_stop_chat, types.SimpleNamespace())
            self.assertEqual(rc, 0)
            self.assertEqual(kills, [])
            self.assertEqual(calls, [["pkill", "-f", "bin/symoneural-llm"]])

        with self.subTest(state="garbage pidfile"):
            pidfile.write_text("junk")
            rc, _, _ = call(self.cli.cmd_stop_chat, types.SimpleNamespace())
            self.assertEqual(rc, 0)
            self.assertEqual(kills, [])
            self.assertFalse(pidfile.exists(), "a corrupt pidfile must still be removed")

        with self.subTest(state="live pidfile"):
            pidfile.write_text("4242")
            rc, _, _ = call(self.cli.cmd_stop_chat, types.SimpleNamespace())
            self.assertEqual(rc, 0)
            self.assertEqual(kills, [(4242, 15)])
            self.assertFalse(pidfile.exists())


class StatusNoDeviceTests(unittest.TestCase):
    """`cmd_status` with no driver, no engines, no weights, and an empty run/."""

    def setUp(self):
        self.cli = load_cli()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.run_dir = t / "run"
        self.run_dir.mkdir()
        self.cli.smi = lambda field: ""
        self.cli.RUN = self.run_dir
        self.cli.STATE = t / "state"
        self.cli.LLM_BIN = t / "llm-bin"
        self.cli.DIFFUSE_BIN = t / "diffuse-bin"
        self.cli.CHAT_MODEL = t / "7b.gguf"
        self.cli.FLUX_UNET = t / "flux.gguf"

    def test_status_on_a_bare_box_reports_every_gap_and_exits_zero(self):
        """The whole point of `status` is the day things are missing. Silent driver reads
        as '?', no resident marker as 'none', no lock directory as 'free', unbuilt engines
        and absent weights by name -- rc 0 throughout, because reporting a broken box is
        this command succeeding. And with no verdict file there is no 'last deploy' row at
        all: an invented 'never deployed' would be a reading of a file that does not exist
        (test_cli_upgrade.py pins the written-verdict direction)."""
        rc, out, err = call(self.cli.cmd_status, None)
        self.assertEqual(rc, 0, err)
        self.assertIn("unknown", line_with("device", out))
        self.assertIn("? / ? MiB used", out)
        self.assertIn("? MiB free", out)
        self.assertIn("? W", line_with("power", out))
        self.assertIn("none", line_with("resident surface", out))
        self.assertIn("free", line_with("gpu lock", out))
        self.assertEqual(out.count("not built"), 2, out)
        self.assertEqual(out.count("weights missing"), 2, out)
        self.assertIn("always available", line_with("ravencalc", out))
        self.assertNotIn("last deploy", out)
        # "never deployed", not the bare word. `ravencalc` legitimately prints "never
        # queues" -- that is the CPU-only fact the surface exists to make visible -- and a
        # substring rule that forbids the word forbids the truth along with the invention.
        self.assertNotIn("never deployed", out.lower())

    def test_status_shows_the_lock_holder_and_resident_surface(self):
        """The lock directory and the resident marker are the two facts an operator needs
        before taking the card; rendering them wrongly is how a fine-tune gets stepped on."""
        (self.run_dir / "resident").write_text("chat\n")
        (self.run_dir / "gpu.lock.d").mkdir()
        rc, out, _ = call(self.cli.cmd_status, None)
        self.assertEqual(rc, 0)
        self.assertIn("chat", line_with("resident surface", out))
        self.assertIn("HELD", line_with("gpu lock", out))


class ResidencyArithmeticTests(unittest.TestCase):
    """The residency plan, recomputed here from stubbed device readings.

    Pinned to `KV_RESERVE == 0.35`; the first test says so explicitly, so a re-measured
    constant fails legibly at the constant rather than mysteriously at a string literal.
    """

    def setUp(self):
        self.cli = load_cli()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.cli.RUN = t / "run"
        self.cli.CHAT_MODEL = t / "7b.gguf"
        self.cli.FLUX_UNET = t / "flux.gguf"

    def stub_smi(self, **fields):
        table = {k.replace("_", "."): v for k, v in fields.items()}
        self.cli.smi = lambda field: table.get(field, "")

    def test_budget_and_headroom_from_known_readings(self):
        """budget = total * (1 - KV_RESERVE) and headroom = max(0, free - budget), checked
        against hand-derived literals: 16384 MiB is 16 GiB, 65% of it is 10.4 GiB, and
        12 GiB free leaves 1.6 GiB. Deriving the expectations from the module's own
        formula would pass no matter what the formula said."""
        self.assertEqual(self.cli.KV_RESERVE, 0.35,
                         "KV_RESERVE was re-measured; re-derive the literals below by hand")
        self.stub_smi(memory_total="16384", memory_free="12288")
        rc, out, _ = call(self.cli.cmd_residency, None)
        self.assertEqual(rc, 0)
        self.assertIn("12.0 GiB", line_with("free", out))
        self.assertIn("10.4 GiB", line_with("weights budget", out))
        self.assertIn("(35% reserved", line_with("weights budget", out))
        self.assertIn("1.6 GiB", line_with("headroom", out))
        self.assertIn("none", line_with("resident surface", out))

    def test_swap_cost_is_weight_bytes_over_the_measured_link(self):
        """A sparse file sized at exactly a tenth of a second of the measured H2D rate
        must read `chat 100 ms` -- whatever that constant currently is. Substituting the
        theoretical Gen 3 x8 rate (7.88 GB/s) would print 88 ms, and a MiB-for-bytes slip
        would print tens of seconds; both are wrong numbers on a site whose argument is
        that its numbers are measured. The absent image weights must simply not appear --
        no invented figure for a file that is not there."""
        self.stub_smi(memory_total="16384", memory_free="12288")
        with open(self.cli.CHAT_MODEL, "wb") as fh:
            fh.truncate(int(self.cli.MEASURED_H2D_GBS * 1e8))
        rc, out, _ = call(self.cli.cmd_residency, None)
        self.assertEqual(rc, 0)
        self.assertIn("chat 100 ms", line_with("swap cost", out))
        self.assertIn("over the measured", line_with("swap cost", out))
        self.assertNotIn("image", out)

    def test_no_driver_reads_zero_not_a_crash(self):
        """`float('' or 0)` is the deliberate degrade: a silent driver plans with zeros
        and exits 0, because the command must work on the day the driver is the problem.

        The silence is STUBBED. Without the stub this read the real `nvidia-smi` and so
        asserted "0.0 GiB" against a live card -- green on a box with no driver, red here
        with 4.3 GiB of real headroom, and in neither case testing the degrade path it
        names. A test whose verdict depends on the hardware it is meant to be simulating
        the absence of is not testing anything.
        """
        self.stub_smi()          # every field "" -- exactly what a silent driver returns
        rc, out, _ = call(self.cli.cmd_residency, None)
        self.assertEqual(rc, 0)
        self.assertIn("0.0 GiB", line_with("headroom", out))
        self.assertIn("none", line_with("resident surface", out))


class TranscriptStoreTests(unittest.TestCase):
    """The agent thread on disk: hostile names, half-written files, unwritable run/."""

    def setUp(self):
        self.cli = load_cli()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_dir = Path(self.tmp.name)
        self.cli.RUN = self.run_dir

    def test_transcript_path_neutralises_hostile_session_names(self):
        """The session name becomes a filename under run/. Separators must not survive --
        `--session ../../etc` writing outside run/ is the defect -- and a name that
        sanitises to nothing must fall back to `default` rather than writing
        `agent-.json`."""
        cases = {
            "notes": "agent-notes.json",
            "a/b c": "agent-a-b-c.json",
            "../../etc": "agent-etc.json",
            "": "agent-default.json",
            "***": "agent-default.json",
        }
        for session, filename in cases.items():
            with self.subTest(session=session):
                path = self.cli.transcript_path(session)
                self.assertEqual(path.name, filename)
                self.assertEqual(path.parent, self.run_dir,
                                 "a session name escaped the run/ directory")

    def test_transcript_read_survives_every_malformed_file(self):
        """The file is fed straight back to the endpoint as `history`; a half-written or
        hand-edited entry would come back as a 422 from far away. Malformed reads as
        empty -- losing the thread must not take the turn down with it -- and entries
        without a string role AND content are dropped one by one, not wholesale."""
        path = self.run_dir / "agent-x.json"
        good = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]
        cases = {
            "missing file": (None, []),
            "invalid json": ("{not json", []),
            "not a list": (json.dumps({"role": "user"}), []),
            "mixed entries": (json.dumps([good[0], {"role": 1, "content": "x"},
                                          {"role": "user"}, "junk", good[1]]), good),
        }
        for name, (content, expected) in cases.items():
            with self.subTest(file=name):
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_text(content)
                self.assertEqual(self.cli.transcript_read(path), expected)

    def test_transcript_write_reports_failure_and_never_raises(self):
        """The answer has already arrived when the write happens; an unwritable run/ must
        cost a stderr warning, not the exit code. The happy path must round-trip through
        `transcript_read`, or the thread silently stores what it cannot replay."""
        messages = [{"role": "user", "content": "q"}]
        blocked = self.run_dir / "not-a-dir"
        blocked.write_text("a file where a directory is needed")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.cli.transcript_write(blocked / "deep" / "t.json", messages)  # must not raise
        self.assertIn("could not record", err.getvalue())

        path = self.run_dir / "agent-ok.json"
        self.cli.transcript_write(path, messages)
        self.assertEqual(self.cli.transcript_read(path), messages)


class TokenGateTests(unittest.TestCase):
    def setUp(self):
        self.cli = load_cli()

    def test_require_token_refuses_with_the_exact_gate_hint(self):
        """GATE_HINT is word for word what `/api/studio/state` says about the same gate;
        the CLI drifting into different advice about one switch is the defect. The refusal
        must also say where the real token lives, or the hint is a scavenger hunt."""
        with env_patch(SYMONEURAL_STUDIO_TOKEN=None, SYM_STUDIO_TOKEN=None):
            rc, out, err = call(lambda _: self.cli.require_token(), None)
        self.assertFalse(rc)
        self.assertIn(self.cli.GATE_HINT, err)
        self.assertIn("/etc/symoneural/api.env", err)

    def test_the_token_is_read_and_never_printed(self):
        """`studio_token`'s docstring: never printed, only sent. A token echoed to a
        terminal ends up in scrollback and paste buffers."""
        sentinel = "tok-3f7a-do-not-print"
        with env_patch(SYMONEURAL_STUDIO_TOKEN=sentinel):
            rc, out, err = call(lambda _: self.cli.require_token(), None)
        self.assertTrue(rc)
        self.assertNotIn(sentinel, out + err)
        self.assertEqual(out + err, "", "a successful gate check must be silent")


class GateRowSaysTheSwitchNotTheToken(unittest.TestCase):
    """The splash's gate line, after NO API KEYS (2026-09-11).

    The four tests these replaced asserted the three-state token gate: exported, missing,
    and loopback-bypassed. All three collapsed when the gate went, and leaving the line
    unasserted would let it drift back to describing something that does not exist.
    """

    def _row(self, **env):
        import os
        from unittest import mock
        cli = load_cli()
        with mock.patch.dict(os.environ, env, clear=False):
            for k in ("SYMONEURAL_STUDIO_ENABLED",):
                if k not in env:
                    os.environ.pop(k, None)
            return cli.gate_row()[0]

    def test_switched_on_says_no_token_is_required(self):
        row = self._row(SYMONEURAL_STUDIO_ENABLED="1")
        self.assertIn("no token required", row)

    def test_switched_off_names_the_one_switch_that_works(self):
        row = self._row()
        self.assertIn("SYMONEURAL_STUDIO_ENABLED", row)

    def test_it_never_tells_the_operator_to_export_a_token(self):
        """The failure this guards: a status line that sends somebody to set a variable
        nothing reads, which costs an afternoon and looks like a configuration problem."""
        for env in ({}, {"SYMONEURAL_STUDIO_ENABLED": "1"}):
            self.assertNotIn("_TOKEN", self._row(**env))


class SplashTests(unittest.TestCase):
    """The launch dashboard, and the one assertion that matters most is a negative.

    `splash_lines` is pure so this can check the OUTPUT rather than the terminal: the token's
    value must not be able to reach it. A renderer that prints cannot be asserted on without
    capturing stdout, and "no secret in the output" is exactly the property worth a test.
    """

    GATE_KEYS = ("SYMONEURAL_STUDIO_TOKEN", "SYMONEURAL_STUDIO_LOCAL_BYPASS",
                 "SYMONEURAL_STUDIO_ENABLED")
    SECRET = "s3cret-value-that-must-never-be-printed"

    def _render(self, **env):
        kw = {k: None for k in self.GATE_KEYS}
        kw.update(env)
        with env_patch(**kw):
            cli = load_cli()
            return cli.splash_lines("http://127.0.0.1:8800", "sess-1",
                                    "/home/google/Symoneural", "auto", 3)

    def _plain(self, rows):
        return re.sub(r"\033\[[0-9]*m", "", "\n".join(rows))

    # -- the negative --------------------------------------------------------------------

    def test_the_token_value_never_reaches_the_output(self):
        """The whole point. `studio_token()` returns the secret, so a splash that formats it
        by accident would leak it into every terminal, every screenshot and every asciinema
        recording of a launch. The NAME may appear -- it is a hint -- the value may not."""
        out = self._plain(self._render(SYMONEURAL_STUDIO_TOKEN=self.SECRET))
        self.assertNotIn(self.SECRET, out)
        self.assertNotIn("s3cret", out)

    def test_no_local_path_scheme_or_env_file_leaks(self):
        """Three classes the security audit forbids in anything user-facing: editor URL
        schemes, a `.env` path, and a raw secret. Checked in every gate state, because a
        renderer with a branch can leak in one branch only."""
        for env in ({}, {"SYMONEURAL_STUDIO_TOKEN": self.SECRET},
                    {"SYMONEURAL_STUDIO_LOCAL_BYPASS": "1",
                     "SYMONEURAL_STUDIO_ENABLED": "1"}):
            out = self._plain(self._render(**env))
            for forbidden in ("file://", "vscode://", "pycharm://", ".env"):
                with self.subTest(env=sorted(env), forbidden=forbidden):
                    self.assertNotIn(forbidden, out)

    # -- the three gate states, which is what #88 changed ---------------------------------





    # -- shape ---------------------------------------------------------------------------

    def test_the_rows_a_dashboard_owes_an_operator_are_all_present(self):
        out = self._plain(self._render())
        for row in ("version", "mode", "api", "cwd", "session", "gate", "permissions"):
            with self.subTest(row=row):
                line_with(row, out)                     # raises if missing
        self.assertIn("/help", out)
        self.assertIn("/status", out)
        self.assertIn("/exit", out)

    def test_no_empty_queue_sections_are_printed(self):
        """There is no job queue behind this client, so `Working:` / `Needs input:` /
        `Completed:` headers would be three decorative rows. The rack rules forbid a status
        that is not a reading; this is the same rule one layer down."""
        out = self._plain(self._render())
        for header in ("Working:", "Needs input:", "Completed:"):
            with self.subTest(header=header):
                self.assertNotIn(header, out)

    def test_the_thread_row_appears_only_when_the_thread_has_messages(self):
        with env_patch(**{k: None for k in self.GATE_KEYS}):
            cli = load_cli()
            empty = self._plain(cli.splash_lines("u", "s", "/c", "auto", 0))
            one = self._plain(cli.splash_lines("u", "s", "/c", "auto", 1))
            many = self._plain(cli.splash_lines("u", "s", "/c", "auto", 4))
        self.assertNotIn("thread", empty)
        self.assertIn("1 message", one)
        self.assertIn("4 messages", many)              # plural agreement, not "1 messages"

    def test_the_product_name_is_cased_exactly(self):
        out = self._plain(self._render())
        self.assertIn("SyMoNeuRaL Code", out)
        for wrong in ("Symoneural Code", "SYMONEURAL Code", "symoneural code"):
            with self.subTest(wrong=wrong):
                self.assertNotIn(wrong, out)

    def test_version_degrades_to_dev_rather_than_raising(self):
        """`repo_version` reads `.git` directly. Pointed at a tree with no `.git` it must
        answer `dev`, because a splash that raises is a client that will not open."""
        cli = load_cli()
        with tempfile.TemporaryDirectory() as td:
            keep = cli.ROOT
            try:
                cli.ROOT = Path(td)
                self.assertEqual(cli.repo_version(), "dev")
            finally:
                cli.ROOT = keep


class ApiPlumbingTests(unittest.TestCase):
    """`api_open`/`api_json` against a faked `urllib.request.urlopen`.

    `api_open` imports urllib.request inside the function, so the house rule of rebinding
    the CLI module's names cannot intercept it; the real module attribute is patched and
    restored via addCleanup instead, which is the narrow exception the module docstring
    declares.
    """

    def setUp(self):
        self.cli = load_cli()

    def patch_urlopen(self, fake):
        import urllib.request
        real = urllib.request.urlopen
        urllib.request.urlopen = fake
        self.addCleanup(setattr, urllib.request, "urlopen", real)

    def test_api_open_sends_both_token_spellings_and_joins_urls(self):
        """Two defects, both found the hard way elsewhere in this repo: a trailing slash
        on `--url` must not produce `//api/...`, and the legacy `X-Sym-Token` header must
        ride along until the deployed API is known to read the new name -- the CLI and the
        API are upgraded at different moments, and a freshly upgraded CLI 401ing against a
        token that is plainly correct is the worst failure to diagnose."""
        seen = {}
        self.patch_urlopen(lambda req, timeout=None: seen.update(req=req, timeout=timeout))
        with env_patch(SYMONEURAL_STUDIO_TOKEN="tok-abc"):
            self.cli.api_open("/api/studio/state", base="http://box:8800/",
                              method="POST", body={"a": 1}, timeout=9.0)
        req = seen["req"]
        self.assertEqual(req.full_url, "http://box:8800/api/studio/state")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.data, b'{"a": 1}')
        self.assertEqual(seen["timeout"], 9.0)
        headers = {k.lower(): v for k, v in req.header_items()}
        self.assertEqual(headers.get("x-symoneural-token"), "tok-abc")
        self.assertEqual(headers.get("x-sym-token"), "tok-abc",
                         "the legacy header compat shim was dropped; see the comment in "
                         "api_open before doing that deliberately")
        self.assertEqual(headers.get("content-type"), "application/json")

    def test_api_json_turns_http_errors_into_results(self):
        """The router answers `denied` and `unknown_tool` as 4xx JSON, and those bodies
        are the useful part; an exception here would throw away the server's own
        explanation. A non-JSON error body must still come back labelled, not raise a
        second error while reporting the first."""
        def fake(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 403, "denied", None,
                                         io.BytesIO(b'{"error": "denied"}'))
        self.patch_urlopen(fake)
        with env_patch(SYMONEURAL_STUDIO_TOKEN=None, SYM_STUDIO_TOKEN=None):
            self.assertEqual(self.cli.api_json("/x", base="http://b"),
                             (403, {"error": "denied"}))

            def fake_html(req, timeout=None):
                raise urllib.error.HTTPError(req.full_url, 502, "bad", None,
                                             io.BytesIO(b"<html>gateway fell over</html>"))
            self.patch_urlopen(fake_html)
            status, obj = self.cli.api_json("/x", base="http://b")
        self.assertEqual(status, 502)
        self.assertEqual(obj, {"error": "<html>gateway fell over</html>"})

    def test_api_json_unreachable_is_status_zero_and_says_how_to_start_one(self):
        """No API at all is status 0, a value HTTP cannot produce, so callers can tell
        'refused' from 'connection never happened'. `unreachable()` must then print the
        one command that fixes it; an error with no next step is half an error."""
        def fake(req, timeout=None):
            raise urllib.error.URLError("connection refused")
        self.patch_urlopen(fake)
        with env_patch(SYMONEURAL_STUDIO_TOKEN=None, SYM_STUDIO_TOKEN=None):
            status, obj = self.cli.api_json("/x", base="http://b")
        self.assertEqual(status, 0)
        self.assertEqual(obj["error"], "unreachable")
        rc, out, err = call(lambda _: self.cli.unreachable("http://b", obj), None)
        self.assertEqual(rc, 1)
        self.assertIn("no API at http://b", err)
        self.assertIn("uvicorn server:app", err)


class StateCommandTests(unittest.TestCase):
    def setUp(self):
        self.cli = load_cli()

    def args(self, **kw):
        return types.SimpleNamespace(**{"url": "http://cli.test", "json": False,
                                        "why": False, **kw})

    def test_state_unreachable_exits_one_with_the_start_hint(self):
        """The wiring from api_json's status-0 convention to the unreachable() advice; a
        regression here reports a dead API as an empty-but-healthy one."""
        self.cli.api_json = lambda path, **kw: (0, {"error": "unreachable",
                                                    "detail": "refused"})
        rc, out, err = call(self.cli.cmd_state, self.args())
        self.assertEqual(rc, 1)
        self.assertIn("no API at http://cli.test", err)

    def test_state_renders_a_gated_off_stack_honestly(self):
        """A box with the switch off is OFF, not broken: the exact GATE_HINT must appear
        (the words are shared with the endpoint so the two cannot drift), the absent
        workspace must name the variable that sets it, and a down backend must say `down`
        -- with its stated reason only under --why. Rendering any of these as a crash or a
        blank is the 'confidently specific and false' class the CLI's own comments war
        against."""
        obj = {"enabled": False, "workspace": {}, "tools": 26, "max_steps": 8,
               "inference": {"backends": {"llama": {"up": False,
                                                    "detail": "socket closed"}}},
               "render_ui": {}, "lease": {}, "workflows": []}
        self.cli.api_json = lambda path, **kw: (200, obj)

        with self.subTest(mode="plain"):
            rc, out, _ = call(self.cli.cmd_state, self.args())
            self.assertEqual(rc, 0)
            self.assertIn("off", line_with("surface", out))
            self.assertIn(self.cli.GATE_HINT, out)
            self.assertIn("not found -- set SYMONEURAL_STUDIO_ROOT", out)
            self.assertIn("26", line_with("tools", out))
            self.assertIn("down", line_with("inference llama", out))
            self.assertNotIn("socket closed", out)
            self.assertIn("not held", line_with("gpu lease", out))
            self.assertIn("none", line_with("workflows", out))

        with self.subTest(mode="--why"):
            rc, out, _ = call(self.cli.cmd_state, self.args(why=True))
            self.assertEqual(rc, 0)
            self.assertIn("socket closed", out)

        with self.subTest(mode="--json"):
            rc, out, _ = call(self.cli.cmd_state, self.args(json=True))
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(out), obj)


class ToolsCommandTests(unittest.TestCase):
    """`cmd_tools` against a controlled registry.

    The real `local_registry()` imports the backend package, which needs httpx; patching
    it keeps these deterministic both here (no httpx) and on the box (26 real tools).
    """

    SPECS = [{"type": "function", "function": {"name": "fs_read"}},
             {"type": "function", "function": {"name": "fs_write"}},
             {"type": "function", "function": {"name": "net_get"}}]

    def setUp(self):
        self.cli = load_cli()
        tool = types.SimpleNamespace
        self.registry = types.SimpleNamespace(
            TOOLS={
                "fs_read": tool(name="fs_read", group="fs", dangerous=False,
                                description="Read a file.",
                                parameters={"type": "object",
                                            "properties": {
                                                "path": {"type": "string",
                                                         "description": "which file"},
                                                "depth": {"type": "integer"}},
                                            "required": ["path"]}),
                "fs_write": tool(name="fs_write", group="fs", dangerous=True,
                                 description="Write a file.", parameters={}),
                "net_get": tool(name="net_get", group="net", dangerous=False,
                                description="Fetch a URL.", parameters={}),
            },
            tool_specs=lambda: list(self.SPECS))
        self.cli.local_registry = lambda: self.registry

    def args(self, **kw):
        return types.SimpleNamespace(**{"name": None, "group": None, "json": False,
                                        "remote": False, "url": "http://cli.test", **kw})

    def test_tools_lists_by_group_and_counts_the_writers(self):
        """The listing is what an operator scans before handing the model a tool; the
        `writes` flag and the writer count are the safety-relevant part, and a tool that
        writes losing its flag is the defect."""
        rc, out, _ = call(self.cli.cmd_tools, self.args())
        self.assertEqual(rc, 0)
        self.assertIn("Read a file.", line_with("fs_read", out))
        self.assertTrue(line_with("fs_write", out).endswith("writes"))
        self.assertNotIn("writes", line_with("net_get", out))
        self.assertIn("3 tools, 1 of which write", out)
        self.assertIn("this checkout", out)

    def test_tools_single_view_marks_optional_parameters(self):
        """The required/optional marker is what the schema view exists for -- reading it
        wrongly is a 422 later, blamed on the server."""
        rc, out, _ = call(self.cli.cmd_tools, self.args(name="fs_read"))
        self.assertEqual(rc, 0)
        self.assertNotIn("optional", line_with("path", out))
        self.assertIn("optional", line_with("depth", out))
        self.assertIn("which file", out)

    def test_tools_json_is_the_specs_verbatim(self):
        """--json promises 'the OpenAI tool-spec shape, exactly as it goes into the
        request the model sees'. Prettifying or re-keying it here would make the CLI's
        output untrustworthy as a debugging artefact."""
        rc, out, _ = call(self.cli.cmd_tools, self.args(json=True))
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out), self.SPECS)

    def test_tools_unknown_name_or_group_fails_cleanly(self):
        """A typo must be a named miss with rc 1, not an empty listing that reads as 'the
        registry is empty' -- which on this stack is a real, different condition."""
        for kw, message in ((dict(name="ghost"), "no tool named 'ghost'"),
                            (dict(group="ghost"), "no tools in group 'ghost'")):
            with self.subTest(**kw):
                rc, _, err = call(self.cli.cmd_tools, self.args(**kw))
                self.assertEqual(rc, 1)
                self.assertIn(message, err)

    def test_tools_import_failure_names_the_error_and_the_remote_fallback(self):
        """The registry import costs the backend's dependencies; on a box without them
        the command must report the real ImportError and point at `--remote`, never
        pretend an empty registry. `--remote` itself is gated on the token first."""
        def broken():
            raise ImportError("No module named 'httpx'")
        self.cli.local_registry = broken
        rc, _, err = call(self.cli.cmd_tools, self.args())
        self.assertEqual(rc, 1)
        self.assertIn("cannot import the registry: ImportError", err)
        self.assertIn("tools --remote", err)
        with self.subTest(remote="without a token"):
            with env_patch(SYMONEURAL_STUDIO_TOKEN=None, SYM_STUDIO_TOKEN=None):
                rc, _, err = call(self.cli.cmd_tools, self.args(remote=True))
            self.assertEqual(rc, 2)


class ToolCommandTests(unittest.TestCase):
    def setUp(self):
        self.cli = load_cli()
        self.sent: list[dict] = []

    def args(self, **kw):
        return types.SimpleNamespace(**{"name": "echo", "arg": [], "body": None,
                                        "json": False, "timeout": 300.0,
                                        "url": "http://cli.test", **kw})

    def fake_api(self, status, obj):
        def api_json(path, **kw):
            self.sent.append({"path": path, **kw})
            return status, obj
        self.cli.api_json = api_json

    def test_tool_requires_a_token(self):
        """The route is the operator surface with no model in the path; reaching it
        tokenless must stop at the gate, before any request leaves the box."""
        self.fake_api(200, {"ok": True})
        with env_patch(SYMONEURAL_STUDIO_TOKEN=None, SYM_STUDIO_TOKEN=None):
            rc, _, err = call(self.cli.cmd_tool, self.args())
        self.assertEqual(rc, 2)
        self.assertEqual(self.sent, [], "a tokenless call still sent a request")

    def test_tool_rejects_malformed_arguments_before_any_request(self):
        """Argument errors are the caller's, exit 2, and must be caught locally --
        shipping them to the server turns a typo into a network round-trip and a less
        specific error."""
        self.fake_api(200, {"ok": True})
        cases = {
            "body not json": dict(body="{broken"),
            "body not an object": dict(body='"a string"'),
            "arg without equals": dict(arg=["novalue"]),
        }
        with env_patch(SYMONEURAL_STUDIO_TOKEN="t"):
            for name, kw in cases.items():
                with self.subTest(case=name):
                    rc, _, err = call(self.cli.cmd_tool, self.args(**kw))
                    self.assertEqual(rc, 2, err)
            self.assertEqual(self.sent, [], "a malformed call still sent a request")

    def test_tool_values_arrive_as_themselves_and_the_result_prints(self):
        """`key=value` pairs are parsed as JSON when they parse: numbers, booleans, null
        and nested objects must arrive typed, layered over --body, with the literal
        string fallback for everything else. Sending "3" where 3 was meant is a schema
        422 the operator cannot see from their own command line."""
        self.fake_api(200, {"ok": True, "result": "fine", "elapsed_s": 0.02})
        with env_patch(SYMONEURAL_STUDIO_TOKEN="t"):
            rc, out, err = call(self.cli.cmd_tool, self.args(
                body='{"a": 1, "n": 0}',
                arg=["n=3", "flag=true", "nothing=null", "s=plain", 'j={"k": 1}']))
        self.assertEqual(rc, 0)
        self.assertEqual(self.sent[0]["path"], "/api/studio/tool/echo")
        self.assertEqual(self.sent[0]["method"], "POST")
        self.assertEqual(self.sent[0]["body"],
                         {"a": 1, "n": 3, "flag": True, "nothing": None,
                          "s": "plain", "j": {"k": 1}})
        self.assertIn("fine", out)
        self.assertIn("echo ok", err)

    def test_tool_unknown_tool_and_server_errors_are_named_misses(self):
        """404/unknown_tool must read as 'no tool named X' with the discovery hint, and
        any other non-200 must surface the status and body -- both rc 1, neither a
        traceback."""
        with env_patch(SYMONEURAL_STUDIO_TOKEN="t"):
            with self.subTest(error="unknown_tool"):
                self.fake_api(404, {"error": "unknown_tool", "available": ["a", "b"]})
                rc, _, err = call(self.cli.cmd_tool, self.args(name="ghost"))
                self.assertEqual(rc, 1)
                self.assertIn("no tool named 'ghost'", err)
                self.assertIn("2 available", err)
            with self.subTest(error="server 500"):
                self.fake_api(500, {"error": "boom"})
                rc, _, err = call(self.cli.cmd_tool, self.args())
                self.assertEqual(rc, 1)
                self.assertIn("HTTP 500", err)
            with self.subTest(error="tool failed"):
                self.fake_api(200, {"ok": False, "error": "denied"})
                rc, _, err = call(self.cli.cmd_tool, self.args())
                self.assertEqual(rc, 1)
                self.assertIn("echo failed: denied", err)


class FakeSSE:
    """A `urlopen` response: a context manager that iterates byte lines."""

    def __init__(self, frames, junk=()):
        self.lines = list(junk) + [b"data: " + json.dumps(f).encode() + b"\n"
                                   for f in frames]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self.lines)


class AgentCommandTests(unittest.TestCase):
    """`cmd_agent` with the SSE stream faked at `api_open`."""

    ANSWER = [{"event": "backend", "name": "llama", "url": "http://127.0.0.1:8081"},
              {"event": "thinking", "text": "considering"},
              {"event": "tool_call", "name": "fs_read", "arguments": {"path": "x"}},
              {"event": "tool_result", "result": "contents"},
              {"event": "answer", "text": "The answer."},
              {"event": "done", "steps": 2, "tools_used": 1, "seconds": 0.5}]

    def setUp(self):
        self.cli = load_cli()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_dir = Path(self.tmp.name)
        self.cli.RUN = self.run_dir
        self.sent: list[dict] = []

    def args(self, **kw):
        return types.SimpleNamespace(**{
            "query": ["hi"], "session": "t", "cont": False, "history_limit": 20,
            "no_save": False, "forget": False, "max_steps": None, "model": None,
            "context": None, "output_format": "text", "verbose": False,
            "timeout": 900.0, "url": "http://cli.test",
            # Pinned rather than left to `auto`, which resolves by opening /dev/tty: under
            # pytest that succeeds in a terminal and fails in CI, so an `auto` default here
            # would make the request body differ between the two and this suite would pass
            # or fail depending on who ran it.
            "permissions": "deny", "dangerously_allow_all": False, "allow_tool": None,
            **kw})

    def stream(self, frames, junk=()):
        def api_open(path, *, base, method="GET", body=None, accept=None, timeout=None):
            self.sent.append({"path": path, "body": body, "accept": accept})
            return FakeSSE(frames, junk)
        self.cli.api_open = api_open

    def test_forget_clears_the_thread_without_a_token(self):
        """--forget is local file hygiene and is deliberately ordered before the token
        gate: deleting your own transcript must not require the server's secret. Both
        directions print what happened, including the message count being discarded."""
        with env_patch(SYMONEURAL_STUDIO_TOKEN=None, SYM_STUDIO_TOKEN=None):
            with self.subTest(state="nothing recorded"):
                rc, out, _ = call(self.cli.cmd_agent, self.args(forget=True))
                self.assertEqual(rc, 0)
                self.assertIn("nothing recorded", out)
            with self.subTest(state="thread exists"):
                path = self.cli.transcript_path("t")
                path.write_text(json.dumps([{"role": "user", "content": "a"},
                                            {"role": "assistant", "content": "b"}]))
                rc, out, _ = call(self.cli.cmd_agent, self.args(forget=True))
                self.assertEqual(rc, 0)
                self.assertIn("(2 messages)", out)
                self.assertFalse(path.exists())

    def test_an_empty_query_refuses_before_any_request(self):
        self.stream(self.ANSWER)
        with env_patch(SYMONEURAL_STUDIO_TOKEN="t"):
            rc, _, err = call(self.cli.cmd_agent, self.args(query=[]))
        self.assertEqual(rc, 2)
        self.assertIn("nothing to ask", err)
        self.assertEqual(self.sent, [])

    def test_the_stream_renders_and_the_turn_is_recorded(self):
        """One whole good turn: every frame kind renders, keepalives and torn JSON lines
        are skipped without dying (an SSE stream over a flaky link WILL deliver both), the
        request body carries only the parameters that were set -- a flag the endpoint
        ignores is a lie with a help string -- and the exchange lands on disk for the next
        `-c`."""
        junk = [b": keepalive\n", b"event: message\n", b"\n", b"data: {torn\n"]
        self.stream(self.ANSWER, junk)
        with env_patch(SYMONEURAL_STUDIO_TOKEN="t"):
            rc, out, err = call(self.cli.cmd_agent, self.args())
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.sent[0]["path"], "/api/studio/agent")
        self.assertEqual(self.sent[0]["body"], {"query": "hi", "permissions": "deny"},
                         "unset options must not be sent at all -- but the permission mode "
                         "is never unset: omitting it takes the endpoint's default, which "
                         "is `allow`, so a client that stays quiet has silently chosen to "
                         "run run_command without asking")
        self.assertEqual(self.sent[0]["accept"], "text/event-stream")
        self.assertIn("fs_read", line_with("call", out))
        self.assertIn("The answer.", out)
        self.assertIn("done", out)
        recorded = self.cli.transcript_read(self.cli.transcript_path("t"))
        self.assertEqual(recorded, [{"role": "user", "content": "hi"},
                                    {"role": "assistant", "content": "The answer."}])

    def test_a_failed_turn_exits_nonzero_and_is_never_recorded(self):
        """'Half a turn is worse than none': an error frame must fail the exit code and
        keep the exchange out of the thread -- even when an answer frame arrived first,
        because replaying a poisoned turn as history breaks every later turn."""
        cases = {
            "error only": [{"event": "error", "code": "llm_down", "detail": "x"},
                           {"event": "done", "steps": 0}],
            "answer then error": [{"event": "answer", "text": "partial"},
                                  {"event": "error", "code": "tool_crashed",
                                   "detail": "y"}],
        }
        for name, frames in cases.items():
            with self.subTest(turn=name):
                self.stream(frames)
                with env_patch(SYMONEURAL_STUDIO_TOKEN="t"):
                    rc, _, err = call(self.cli.cmd_agent, self.args(session=name))
                self.assertEqual(rc, 1)
                self.assertIn("error", err)
                self.assertFalse(self.cli.transcript_path(name).exists(),
                                 "a failed turn was recorded into the thread")

    def test_an_unknown_event_is_shown_not_swallowed(self):
        """The renderer's own comment: a renderer that silently ignores an event it does
        not know is how a terminal ends up quieter than the thing it is watching. A frame
        kind the loop grows later must print as raw JSON."""
        self.stream([{"event": "mystery", "z": 1},
                     {"event": "answer", "text": "The answer."},
                     {"event": "done", "steps": 1}])
        with env_patch(SYMONEURAL_STUDIO_TOKEN="t"):
            rc, out, _ = call(self.cli.cmd_agent, self.args())
        self.assertEqual(rc, 0)
        self.assertIn('"mystery"', out)

    def test_the_history_window_never_starts_on_an_assistant_turn(self):
        """--history-limit clips the wire, and a window that opens on an assistant
        message asks the model to continue a reply to a question it cannot see, so the
        clip must advance to the first user turn. The full thread stays on disk -- only
        what is SENT is windowed -- and the note must state both numbers."""
        thread = [{"role": "user", "content": "u1"}, {"role": "assistant", "content": "a1"},
                  {"role": "user", "content": "u2"}, {"role": "assistant", "content": "a2"},
                  {"role": "user", "content": "u3"}, {"role": "assistant", "content": "a3"}]
        path = self.cli.transcript_path("h")
        path.write_text(json.dumps(thread))
        self.stream(self.ANSWER)
        with env_patch(SYMONEURAL_STUDIO_TOKEN="t"):
            rc, _, err = call(self.cli.cmd_agent,
                              self.args(session="h", cont=True, history_limit=5))
        self.assertEqual(rc, 0)
        self.assertEqual(self.sent[0]["body"]["history"], thread[2:],
                         "the window did not advance to the first user message")
        self.assertIn("last 4 of 6", err)
        recorded = self.cli.transcript_read(path)
        self.assertEqual(len(recorded), 8, "the on-disk thread must keep every turn")
        self.assertEqual(recorded[:6], thread)

    def test_no_save_and_the_two_json_output_modes(self):
        """--no-save must leave no file; --output-format json is one object with the
        verdict; stream-json is one frame per line and no trailing object. Scripts parse
        these, so the shapes are contracts."""
        with env_patch(SYMONEURAL_STUDIO_TOKEN="t"):
            with self.subTest(mode="--no-save"):
                self.stream(self.ANSWER)
                rc, _, _ = call(self.cli.cmd_agent, self.args(session="n", no_save=True))
                self.assertEqual(rc, 0)
                self.assertFalse(self.cli.transcript_path("n").exists())
            with self.subTest(mode="json"):
                self.stream(self.ANSWER)
                rc, out, _ = call(self.cli.cmd_agent,
                                  self.args(session="j", output_format="json"))
                self.assertEqual(rc, 0)
                obj = json.loads(out)
                self.assertEqual(obj["answer"], "The answer.")
                self.assertTrue(obj["ok"])
                self.assertEqual(len(obj["events"]), len(self.ANSWER))
            with self.subTest(mode="stream-json"):
                self.stream(self.ANSWER)
                rc, out, _ = call(self.cli.cmd_agent,
                                  self.args(session="s", output_format="stream-json"))
                self.assertEqual(rc, 0)
                lines = [json.loads(l) for l in out.strip().splitlines()]
                self.assertEqual(lines, self.ANSWER)


class ChatCommandTests(unittest.TestCase):
    """`cmd_chat` up to, and never across, the GPU boundary: subprocess is a recorder."""

    def setUp(self):
        self.cli = load_cli()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.cli.LLM_BIN = t / "bin"
        self.cli.CHAT_MODEL = t / "7b.gguf"
        self.cli.CHAT_MODEL_HEAVY = t / "14b.gguf"
        self.cli.CHAT_ADAPTER = t / "adapter.gguf"
        self.calls: list[list[str]] = []
        shim_subprocess(self.cli, recorder(self.calls))

    def args(self, **kw):
        return types.SimpleNamespace(**{"prompt": "hi", "max_tokens": 7,
                                        "temperature": 0.5, "heavy": False,
                                        "no_adapter": False, **kw})

    def build_engine(self, heavy_weights=False, adapter=False):
        self.cli.LLM_BIN.mkdir(parents=True, exist_ok=True)
        (self.cli.LLM_BIN / "symoneural-llm-cli").touch()
        self.cli.CHAT_MODEL.touch()
        if heavy_weights:
            self.cli.CHAT_MODEL_HEAVY.touch()
        if adapter:
            self.cli.CHAT_ADAPTER.touch()

    def test_missing_engine_and_weights_degrade_with_the_path_named(self):
        """The no-device path: an unbuilt engine and absent weights are rc 1 with the gap
        named -- including the heavy tier naming the 14B file, because 'weights missing'
        without saying WHICH weights sends the operator to re-download the wrong 4 GiB."""
        with self.subTest(missing="engine"):
            rc, _, err = call(self.cli.cmd_chat, self.args())
            self.assertEqual(rc, 1)
            self.assertIn("not built", err)
        self.build_engine()
        self.cli.CHAT_MODEL.unlink()
        with self.subTest(missing="7B weights"):
            rc, _, err = call(self.cli.cmd_chat, self.args())
            self.assertEqual(rc, 1)
            self.assertIn(str(self.cli.CHAT_MODEL), err)
        with self.subTest(missing="14B weights"):
            self.cli.CHAT_MODEL.touch()
            rc, _, err = call(self.cli.cmd_chat, self.args(heavy=True))
            self.assertEqual(rc, 1)
            self.assertIn(str(self.cli.CHAT_MODEL_HEAVY), err)
        self.assertEqual(self.calls, [], "a degraded path still spawned something")

    def test_an_empty_prompt_refuses_without_spawning(self):
        """`args.prompt or sys.stdin.read()` means an empty stdin must be caught here;
        anything less and the governor holds the card for a prompt that never comes."""
        self.build_engine()
        real_stdin = sys.stdin
        sys.stdin = io.StringIO("")
        self.addCleanup(lambda: setattr(sys, "stdin", real_stdin))
        rc, _, err = call(self.cli.cmd_chat, self.args(prompt=None))
        self.assertEqual(rc, 2)
        self.assertIn("nothing to say", err)
        self.assertEqual(self.calls, [])

    def test_chat_takes_the_card_only_through_the_governor(self):
        """The argv IS the contract: `gpu-governor.sh with chat -- llama-cli ...`, single
        turn (`-no-cnv -st`, the pair that prevents an interactive hang inside a governor
        hold), the adapter attached exactly when it exists and is wanted, and never on
        the 14B it was not trained against -- llama.cpp would fail the rank/shape check
        at load, inside the lock."""
        self.build_engine(heavy_weights=True, adapter=True)
        gov = str(self.cli.GOVERNOR)

        with self.subTest(tier="7B with adapter"):
            rc, _, _ = call(self.cli.cmd_chat, self.args())
            self.assertEqual(rc, 0)
            argv = self.calls[-1]
            self.assertEqual(argv[:4], [gov, "with", "chat", "--"])
            self.assertEqual(argv[4], str(self.cli.LLM_BIN / "symoneural-llm-cli"))
            self.assertEqual(argv[argv.index("-m") + 1], str(self.cli.CHAT_MODEL))
            self.assertIn("-no-cnv", argv)
            self.assertIn("-st", argv)
            self.assertEqual(argv[argv.index("-n") + 1], "7")
            self.assertEqual(argv[argv.index("--lora") + 1], str(self.cli.CHAT_ADAPTER))

        with self.subTest(tier="7B, adapter declined"):
            call(self.cli.cmd_chat, self.args(no_adapter=True))
            self.assertNotIn("--lora", self.calls[-1])

        with self.subTest(tier="14B never takes the adapter"):
            call(self.cli.cmd_chat, self.args(heavy=True))
            argv = self.calls[-1]
            self.assertEqual(argv[:4], [gov, "with", "chat", "--"])
            self.assertEqual(argv[argv.index("-m") + 1], str(self.cli.CHAT_MODEL_HEAVY))
            self.assertNotIn("--lora", argv)


class ImageCommandTests(unittest.TestCase):
    def setUp(self):
        self.cli = load_cli()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = Path(self.tmp.name)
        self.cli.DIFFUSE_BIN = self.t / "bin"
        for name in ("FLUX_UNET", "FLUX_VAE", "FLUX_CLIP", "FLUX_T5"):
            setattr(self.cli, name, self.t / f"{name.lower()}.bin")
        self.calls: list[list[str]] = []
        shim_subprocess(self.cli, recorder(self.calls))

    def args(self, **kw):
        return types.SimpleNamespace(**{"prompt": "a raven", "output": str(self.t / "o" / "out.png"),
                                        "steps": 4, "size": 512, "seed": 7,
                                        "clip_on_cpu": True, **kw})

    def test_missing_engine_and_each_absent_weight_is_listed(self):
        """FLUX is four files; failing on the first missing one hides the other three and
        turns one download round-trip into four. All absentees must be listed at once."""
        with self.subTest(missing="engine"):
            rc, _, err = call(self.cli.cmd_image, self.args())
            self.assertEqual(rc, 1)
            self.assertIn("not built", err)
        self.cli.DIFFUSE_BIN.mkdir(parents=True)
        (self.cli.DIFFUSE_BIN / "symoneural-diffuse").touch()
        self.cli.FLUX_UNET.touch()
        self.cli.FLUX_CLIP.touch()
        with self.subTest(missing="two of four weight files"):
            rc, _, err = call(self.cli.cmd_image, self.args())
            self.assertEqual(rc, 1)
            self.assertIn(str(self.cli.FLUX_VAE), err)
            self.assertIn(str(self.cli.FLUX_T5), err)
            self.assertNotIn(str(self.cli.FLUX_UNET), err)
        self.assertEqual(self.calls, [], "a degraded path still spawned something")

    def test_image_takes_the_card_only_through_the_governor(self):
        """Same rule as chat, plus the schnell-specific flags that keep 15.92 GiB enough:
        cfg-scale 1.0 (a distilled model degrades above it), --vae-tiling and
        --diffusion-fa (what makes 768 fit at all), and te=cpu for the text encoder. A
        'cleanup' dropping any of these OOMs or degrades quietly on the real card."""
        self.cli.DIFFUSE_BIN.mkdir(parents=True)
        (self.cli.DIFFUSE_BIN / "symoneural-diffuse").touch()
        for name in ("FLUX_UNET", "FLUX_VAE", "FLUX_CLIP", "FLUX_T5"):
            getattr(self.cli, name).touch()
        rc, out, _ = call(self.cli.cmd_image, self.args())
        self.assertEqual(rc, 0)
        argv = self.calls[-1]
        self.assertEqual(argv[:4], [str(self.cli.GOVERNOR), "with", "image", "--"])
        self.assertEqual(argv[4], str(self.cli.DIFFUSE_BIN / "symoneural-diffuse"))
        self.assertEqual(argv[argv.index("--cfg-scale") + 1], "1.0")
        self.assertEqual(argv[argv.index("-W") + 1], "512")
        self.assertEqual(argv[argv.index("-H") + 1], "512")
        self.assertEqual(argv[argv.index("--seed") + 1], "7")
        self.assertEqual(argv[argv.index("--backend") + 1], "te=cpu")
        self.assertIn("--vae-tiling", argv)
        self.assertIn("--diffusion-fa", argv)
        self.assertNotIn(".png", out,
                         "no file was produced, so no success line may claim one")


class RavenCalcCommandTests(unittest.TestCase):
    """`cmd_ravencalc` with the engine module injected via sys.modules.

    `import ravencalc` needs sympy, which this sandbox does not have and the box does;
    injecting a fake is the only shape that is deterministic in both places, and it also
    lets the refusal path run without constructing a real refused request. The injection
    is saved and restored exactly, per the module docstring.
    """

    def setUp(self):
        self.cli = load_cli()
        self._saved = sys.modules.get("ravencalc", _MISSING)
        self.addCleanup(self._restore)

    def _restore(self):
        if self._saved is _MISSING:
            sys.modules.pop("ravencalc", None)
        else:
            sys.modules["ravencalc"] = self._saved

    def inject(self, result=None, refuse=None, record=None):
        mod = types.ModuleType("ravencalc")

        class RavenCalcError(Exception):
            def as_record(self):
                return {"error": "refused", "detail": str(self)}

        def run_request(doc):
            if record is not None:
                record.append(doc)
            if refuse is not None:
                raise RavenCalcError(refuse)
            return result

        mod.RavenCalcError = RavenCalcError
        mod.run_request = run_request
        sys.modules["ravencalc"] = mod

    def args(self, **kw):
        return types.SimpleNamespace(**{"operation": "integrate", "expression": "x**2",
                                        "variable": None, "point": None, "json": False,
                                        **kw})

    def test_the_request_document_is_versioned_and_minimal(self):
        """The schema tag is the wire contract with the engine, and optional fields must
        be absent rather than null -- ravencalc validates its input, and a `"variable":
        null` it never asked for is a refusal the operator did not earn."""
        record: list[dict] = []
        self.inject(result={"input": {"text": "x"}, "result": {"text": "x"}}, record=record)
        with self.subTest(options="none"):
            call(self.cli.cmd_ravencalc, self.args())
            self.assertEqual(record[-1], {"schema": "ravencalc/request/v1",
                                          "operation": "integrate",
                                          "expression": "x**2"})
        with self.subTest(options="variable and point"):
            call(self.cli.cmd_ravencalc, self.args(operation="limit", variable="x",
                                                   point="0"))
            self.assertEqual(record[-1], {"schema": "ravencalc/request/v1",
                                          "operation": "limit", "expression": "x**2",
                                          "variable": "x", "point": "0"})

    def test_a_result_renders_with_its_check_and_engine(self):
        """The check line is the honesty feature: `verified` only when the engine says it
        performed and passed the check, `unconfirmed` when it performed one and cannot
        say -- collapsing those two is claiming a verification that did not happen.
        `x**3/3` mirrors the frontend suite's calc assertion on purpose."""
        result = {"input": {"text": "Integral(x**2, x)"}, "result": {"text": "x**3/3"},
                  "check": {"performed": True, "passed": True, "how": "differentiated back"},
                  "engine": "sympy", "exact": True}
        with self.subTest(check="passed"):
            self.inject(result=result)
            rc, out, _ = call(self.cli.cmd_ravencalc, self.args())
            self.assertEqual(rc, 0)
            self.assertIn("x**3/3", out)
            self.assertIn("verified", out)
            self.assertIn("differentiated back", out)
            self.assertIn("exact", out)
        with self.subTest(check="performed but unconfirmed"):
            unconfirmed = dict(result, check={"performed": True})
            self.inject(result=unconfirmed)
            rc, out, _ = call(self.cli.cmd_ravencalc, self.args())
            self.assertEqual(rc, 0)
            self.assertIn("unconfirmed", out)
        with self.subTest(check="--json is the whole record"):
            self.inject(result=result)
            rc, out, _ = call(self.cli.cmd_ravencalc, self.args(json=True))
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(out), result)

    def test_a_refusal_prints_and_exits_one(self):
        """Refusals are results with reasons, not crashes: text mode relays the reason on
        stderr, json mode emits the engine's own record so scripts can branch on it."""
        with self.subTest(mode="text"):
            self.inject(refuse="no pricing questions")
            rc, _, err = call(self.cli.cmd_ravencalc, self.args())
            self.assertEqual(rc, 1)
            self.assertIn("refused: no pricing questions", err)
        with self.subTest(mode="--json"):
            self.inject(refuse="no pricing questions")
            rc, _, err = call(self.cli.cmd_ravencalc, self.args(json=True))
            self.assertEqual(rc, 1)
            self.assertEqual(json.loads(err),
                             {"error": "refused", "detail": "no pricing questions"})

    def test_a_missing_engine_reads_as_an_error_not_a_crash(self):
        """`None` in sys.modules makes `import ravencalc` raise, which is what a box
        without sympy looks like; the command must say so and exit 1, because the CPU
        surface being absent is a fact to report, not an excuse to traceback."""
        sys.modules["ravencalc"] = None
        rc, _, err = call(self.cli.cmd_ravencalc, self.args())
        self.assertEqual(rc, 1)
        self.assertIn("ravencalc is not importable", err)


class McpCommandTests(unittest.TestCase):
    """`cmd_mcp` on a checkout with no venv, which is the no-device path here: the venv
    is the one place FastMCP may live, and the registry import is stubbed for the same
    determinism reason as in ToolsCommandTests."""

    def setUp(self):
        self.cli = load_cli()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cli.ROOT = Path(self.tmp.name)          # no .venv anywhere beneath it
        tool = types.SimpleNamespace
        self.cli.local_registry = lambda: types.SimpleNamespace(
            TOOLS={"a": tool(group="fs"), "b": tool(group="net")})

    def args(self, **kw):
        return types.SimpleNamespace(**{"serve": False, "http": None, "json": False, **kw})

    def test_mcp_info_degrades_without_the_venv_and_never_prints_the_token(self):
        """Reports the gap instead of guessing: fastmcp `not installed`, the switch not
        set in this shell, and still a parseable client wiring block whose token is the
        `<secret>` placeholder -- with a real token in the environment, printing it into
        a config a user will paste somewhere is the leak this pins shut."""
        sentinel = "tok-do-not-echo-9c4"
        with env_patch(SYMONEURAL_STUDIO_TOKEN=sentinel, SYMONEURAL_STUDIO_ENABLED=None,
                       SYM_STUDIO_ENABLED=None):
            rc, out, err = call(self.cli.cmd_mcp, self.args())
        self.assertEqual(rc, 0)
        self.assertIn("not installed", line_with("fastmcp", out))
        self.assertIn("is not 1 in this shell", line_with("switch", out))
        self.assertIn("2 in fs, net", line_with("tools", out))
        wiring = json.loads(out.split("a client wires it as:", 1)[1])
        env = wiring["mcpServers"]["symoneural-studio"]["env"]
        self.assertEqual(env["SYMONEURAL_STUDIO_TOKEN"], "<secret>")
        self.assertNotIn(sentinel, out + err)

    def test_mcp_json_reports_readiness_honestly(self):
        rc, out, _ = call(self.cli.cmd_mcp, self.args(json=True))
        self.assertEqual(rc, 0)
        obj = json.loads(out)
        self.assertIs(obj["venv_ready"], False)
        self.assertIsNone(obj["fastmcp"])
        self.assertEqual(obj["tools"], 2)
        self.assertEqual(obj["groups"], ["fs", "net"])

    def test_mcp_serve_without_the_venv_prints_the_venv_commands(self):
        """The build instructions must name the venv's own pip by full path and say the
        system interpreter is off limits -- the pinned serving environment is the repo
        rule a helpful copy-paste would otherwise break first."""
        rc, _, err = call(self.cli.cmd_mcp, self.args(serve=True))
        self.assertEqual(rc, 1)
        self.assertIn("never into the system", err)
        self.assertIn(".venv/bin/pip", err)
        self.assertIn("requirements.txt", err)


class SubcommandTableTests(unittest.TestCase):
    """`main()` driven with every handler stubbed: the audit item's second named target."""

    # (module attribute, subcommand, minimal argv tail)
    TABLE = [
        ("cmd_status", "status", []),
        ("cmd_residency", "residency", []),
        ("cmd_upgrade", "upgrade", []),
        ("cmd_chat", "chat", ["hi"]),
        ("cmd_image", "image", ["hi"]),
        ("cmd_ravencalc", "ravencalc", ["integrate", "x**2"]),
        ("cmd_agent", "agent", []),
        ("cmd_tools", "tools", []),
        ("cmd_tool", "tool", ["echo"]),
        ("cmd_state", "state", []),
        ("cmd_mcp", "mcp", []),
        ("cmd_stop_chat", "_stop-chat", []),
    ]

    def setUp(self):
        self.cli = load_cli()
        self._argv = sys.argv
        self.addCleanup(lambda: setattr(sys, "argv", self._argv))

    def test_every_subcommand_dispatches_to_its_handler_with_its_defaults(self):
        """A deleted `set_defaults(fn=...)` or a renamed subcommand is invisible to tests
        that call handlers directly -- argparse rejects the name before any code runs --
        so this drives main() and asserts the dispatch AND the documented defaults, which
        are promises the help text makes (chat 512 tokens at 0.7, image 4 steps at
        768/seed 42, agent thread `default` clipped at 20, tool's longer 300 s timeout)."""
        hit = {}

        def stub(name):
            def fn(args):
                hit["name"], hit["args"] = name, args
                return 42
            return fn

        for attr, name, _tail in self.TABLE:
            setattr(self.cli, attr, stub(name))
        for attr, name, tail in self.TABLE:
            with self.subTest(subcommand=name):
                sys.argv = ["symoneural-cli", name, *tail]
                self.assertEqual(self.cli.main(), 42)
                self.assertEqual(hit["name"], name)
        args = hit["args"]  # _stop-chat, no options -- now spot-check the documented ones
        sys.argv = ["symoneural-cli", "chat", "hi"]
        self.cli.main()
        self.assertEqual((hit["args"].max_tokens, hit["args"].temperature), (512, 0.7))
        self.assertFalse(hit["args"].heavy)
        sys.argv = ["symoneural-cli", "image", "hi"]
        self.cli.main()
        self.assertEqual((hit["args"].steps, hit["args"].size, hit["args"].seed),
                         (4, 768, 42))
        sys.argv = ["symoneural-cli", "agent"]
        self.cli.main()
        self.assertEqual((hit["args"].session, hit["args"].history_limit,
                          hit["args"].output_format, hit["args"].timeout),
                         ("default", 20, "text", 900.0))
        self.assertEqual(hit["args"].url, self.cli.DEFAULT_API)
        sys.argv = ["symoneural-cli", "tool", "echo"]
        self.cli.main()
        self.assertEqual(hit["args"].timeout, 300.0)

    def test_bad_invocations_exit_two_including_a_top_level_json(self):
        """argparse contract plus one deliberate design decision: `--json` belongs to the
        subcommands, because a top-level `--json` would parse and then do nothing --
        ravencalc has its own and never speaks HTTP. The comment in main() says so; this
        makes it a failure to regress rather than a comment to ignore."""
        for argv in (["symoneural-cli", "bogus"],
                     ["symoneural-cli", "--json", "state"],
                     ["symoneural-cli", "ravencalc", "transmogrify", "x"]):
            with self.subTest(argv=" ".join(argv[1:]) or "(none)"):
                sys.argv = argv
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    with self.assertRaises(SystemExit) as cm:
                        self.cli.main()
                self.assertEqual(cm.exception.code, 2)

    def test_a_bare_invocation_with_no_terminal_is_still_exit_two_with_usage(self):
        """This case used to be argparse's, via `required=True`, and it raised SystemExit.
        It is now `main()`'s own, because a bare invocation WITH a terminal opens a session
        -- so it returns 2 rather than raising, and `sys.exit(main())` at the bottom of the
        file makes the process exit code identical either way.

        The mechanism changing is not the point; the point is that the behaviour must not.
        A script running `symoneural-cli "$CMD"` with CMD unset depended on exit 2 and
        usage, and if it got a client reading stdin instead it would block forever, in
        cron, with no output. Under pytest stdin is not a terminal, which is exactly the
        condition being asserted -- so this test would also catch the guard being keyed to
        the wrong stream.
        """
        sys.argv = ["symoneural-cli"]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.cli.main()
        self.assertEqual(code, 2)
        self.assertIn("usage:", err.getvalue())
        self.assertIn("not a terminal", err.getvalue())
        self.assertEqual(out.getvalue(), "", "usage must go to stderr, not stdout")


@unittest.skipUnless(shutil.which("script"), "util-linux `script` is what allocates the pty")
class ApprovePromptTests(unittest.TestCase):
    """`approve()` itself, driven through a real terminal.

    `PermissionGateTests` patches this function away and says why: it tests what the client
    DOES with a verdict. That left the half that produces the verdict with no coverage at all
    -- the prompt text, the four keys, the re-ask, and what happens when the terminal goes
    away -- in the one function where a wrong default is a command running that nobody agreed
    to. It cannot be reached by patching stdin, because it deliberately opens `/dev/tty`
    instead (in `agent "..."` stdin may be a pipe carrying the query, and in the repl it is
    the transcript; neither is a human). So this class allocates an actual pty with
    util-linux `script`, the same instrument the node suite uses for the isatty fork, and
    feeds keystrokes to it.
    """

    DRIVER = (
        "import json, sys, types\n"
        "path = sys.argv[1]\n"
        "m = types.ModuleType('cli'); m.__file__ = path\n"
        "exec(compile(open(path).read(), path, 'exec'), m.__dict__)\n"
        "print('VERDICT=' + m.approve(sys.argv[2], json.loads(sys.argv[3]), sys.argv[4]))\n"
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.driver = Path(self.tmp.name) / "drive_approve.py"
        self.driver.write_text(self.DRIVER)

    def ask(self, keys, *, name="run_command", arguments=None, reason="dangerous in the registry"):
        """Returns `(verdict, screen)`. `keys` is typed at the pty; '' is the terminal closing."""
        arguments = {"cmd": "rm -rf /tmp/x"} if arguments is None else arguments
        inner = " ".join([sys.executable, str(self.driver), str(CLI_PATH), name,
                          json.dumps(json.dumps(arguments)), json.dumps(reason)])
        r = subprocess.run(["script", "-qec", inner, "/dev/null"], input=keys,
                           capture_output=True, text=True, timeout=60)
        # A pty turns colour back on, so it has to come off again before anything is matched.
        screen = re.sub(r"\x1b\[[0-9;]*m", "", r.stdout + r.stderr)
        found = re.search(r"VERDICT=(\w+)", screen)
        return (found.group(1) if found else None), screen

    def test_the_prompt_names_the_tool_the_reason_and_all_four_keys(self):
        verdict, screen = self.ask("y\n")
        self.assertEqual(verdict, "yes")
        self.assertIn("permission required", screen)
        self.assertIn("run_command", screen)
        self.assertIn("dangerous in the registry", screen)
        for key, word in (("[y]", "es once"), ("[n]", "o, tell the model"),
                          ("[a]", "lways this session"), ("[q]", "uit the turn")):
            self.assertIn(key, screen, f"the {key} key is not offered")
            self.assertIn(word, screen)

    def test_every_key_maps_to_the_verdict_it_prints(self):
        """All four, typed as the letter and as the word, because APPROVE_KEYS accepts both and
        a table with an entry nobody exercises is a table with a typo waiting in it."""
        for keys, want in (("y\n", "yes"), ("yes\n", "yes"), ("n\n", "no"), ("no\n", "no"),
                           ("a\n", "always"), ("always\n", "always"),
                           ("q\n", "quit"), ("quit\n", "quit"),
                           ("  Y  \n", "yes"), ("N\n", "no")):
            with self.subTest(typed=keys.strip() or "<enter>"):
                verdict, screen = self.ask(keys)
                self.assertEqual(verdict, want, screen[-400:])

    def test_a_bare_return_approves_once_which_is_the_documented_default(self):
        """Pinned deliberately rather than left to the table. `APPROVE_KEYS` maps "" to yes, so
        Enter approves this one call -- that is a real decision, it is what `[y]es once` being
        listed first announces, and a future edit that flips it to a refusal or to a re-ask
        should have to change this test and say so in the message."""
        verdict, _ = self.ask("\n")
        self.assertEqual(verdict, "yes")

    def test_an_unrecognised_key_re_asks_instead_of_guessing_what_was_meant(self):
        verdict, screen = self.ask("maybe\nn\n")
        self.assertEqual(verdict, "no")
        self.assertIn("y, n, a or q", screen)

    def test_the_terminal_going_away_mid_question_refuses(self):
        """The default when there is nobody left to ask. `readline()` returning nothing is a
        closed terminal, and the only safe reading of a question that was never answered is
        no -- an approval inferred from silence is the worst possible place for one."""
        verdict, screen = self.ask("")
        self.assertEqual(verdict, "no")
        self.assertIn("no answer; refusing", screen)

    def test_the_arguments_are_printed_in_full_and_never_elided(self):
        """The layout rule, in the one place it is a safety property rather than a preference.
        A truncated argument line means a human approved a command they had not read, so a
        long value must wrap rather than end in an ellipsis."""
        cmd = "rm -rf /tmp/" + "d" * 200
        verdict, screen = self.ask("y\n", arguments={"cmd": cmd, "cwd": "/home/google/Symoneural"})
        self.assertEqual(verdict, "yes")
        self.assertNotIn("\u2026", screen)
        self.assertNotIn("...", screen)
        # The pty wraps at its width, so the comparison has to survive a line break landing
        # anywhere in the value -- including inside `rm -rf`, which is why the whitespace comes
        # out of BOTH sides rather than only out of the screen.
        flat = re.sub(r"\s+", "", screen)
        self.assertIn(re.sub(r"\s+", "", cmd), flat,
                      "the command a human is approving was not shown in full")
        self.assertIn("/home/google/Symoneural", screen)


class PermissionGateTests(unittest.TestCase):
    """The gate, from the client's side. The rule being protected is one sentence: what runs
    is the argument object that was displayed, chosen by nobody after it was displayed."""

    GATE = [{"event": "backend", "name": "llama", "url": "http://127.0.0.1:8081"},
            {"event": "permission_required", "name": "run_command",
             "arguments": {"cmd": "rm -rf /tmp/x"}, "call_id": "c1",
             "reason": "run_command is marked dangerous in the tool registry",
             "dropped": ["write_file"],
             "pending": [{"role": "assistant", "content": "",
                          "tool_calls": [{"id": "c1"}]}]},
            {"event": "done", "steps": 1, "tools_used": 0, "awaiting_permission": True}]
    AFTER = [{"event": "backend", "name": "llama", "url": "http://127.0.0.1:8081"},
             {"event": "answer", "text": "Removed."},
             {"event": "done", "steps": 1, "tools_used": 0, "seconds": 0.1}]

    def setUp(self):
        self.cli = load_cli()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cli.RUN = Path(self.tmp.name)
        self.sent: list[dict] = []
        self.ran: list[dict] = []
        # Two segments: the gated one, then whatever comes after the answer is given.
        segments = [self.GATE, self.AFTER]

        def api_open(path, *, base, method="GET", body=None, accept=None, timeout=None):
            self.sent.append(copy.deepcopy(body))
            return FakeSSE(segments[min(len(self.sent) - 1, len(segments) - 1)])
        self.cli.api_open = api_open

        # `(status, body)`, because that is what the real `api_json` returns. This fake used to
        # answer a bare dict, and the difference is not cosmetic: the code under test bound the
        # call straight to `result` and shipped `[200, {...}]` to the model as the tool's output,
        # with the status folded in as element 0 -- and every test here stayed green, because the
        # fake agreed with the mistake. A stub that does not match the signature it stands in for
        # tests the stub. The status is settable so the refused-by-the-router path has a way in.
        self.tool_status = 200
        self.tool_body: dict = {"ok": True, "stdout": ""}

        def api_json(path, *, base, method="GET", body=None, timeout=None, **kw):
            self.ran.append({"path": path, "body": copy.deepcopy(body)})
            return self.tool_status, dict(self.tool_body)
        self.cli.api_json = api_json

    def args(self, **kw):
        return types.SimpleNamespace(**{
            "query": ["clean up"], "session": "g", "cont": False, "history_limit": 20,
            "no_save": False, "forget": False, "max_steps": None, "model": None,
            "context": None, "output_format": "text", "verbose": False,
            "timeout": 900.0, "url": "http://cli.test", "permissions": "ask",
            "dangerously_allow_all": False, "allow_tool": None, **kw})

    def answer(self, verdict):
        """Patch the prompt, not stdin: `approve()` reads /dev/tty on purpose and there is no
        controlling terminal to give it under pytest. What is being tested here is what the
        client DOES with a verdict, which is the half that can be wrong."""
        self.cli.approve = lambda name, arguments, reason="": verdict

    def test_approving_runs_the_arguments_that_were_displayed_and_not_a_fresh_choice(self):
        """The whole reason the client executes the tool itself. Re-issuing the turn with
        run_command merely permitted would let the model pick its arguments again at
        temperature, so the command that ran could differ from the one a human read. This
        asserts the exact object round-trips from the frame to POST /tool."""
        self.answer("yes")
        with env_patch(SYMONEURAL_STUDIO_TOKEN="t"):
            rc, out, err = call(self.cli.cmd_agent, self.args())
        self.assertEqual(rc, 0, err)
        self.assertEqual([r["path"] for r in self.ran], ["/api/studio/tool/run_command"])
        self.assertEqual(self.ran[0]["body"], {"arguments": {"cmd": "rm -rf /tmp/x"}})
        self.assertIn("Removed.", out)

    def test_the_approved_tool_reaches_the_model_as_its_own_body_not_as_a_status_pair(self):
        """What the model is handed after a human approves. `api_json` answers `(status, body)`,
        and the client bound that tuple straight to the result, so the transcript carried
        `[200, {"ok": true, ...}]` -- an array where an object belongs, with the HTTP status as
        element 0. Nothing caught it because the fake in this file returned a bare dict and so
        agreed with the mistake. The assertion is on the JSON the model actually reads."""
        self.answer("yes")
        self.tool_body = {"ok": True, "stdout": "gone\n"}
        with env_patch(SYMONEURAL_STUDIO_TOKEN="t"):
            rc, out, err = call(self.cli.cmd_agent, self.args())
        self.assertEqual(rc, 0, err)
        told = json.loads(self.sent[1]["resume"][1]["content"])
        self.assertEqual(told, {"ok": True, "stdout": "gone\n"},
                         "the model must read the tool's own body, not a [status, body] pair")
        self.assertNotIsInstance(told, list, "a status pair leaked into the transcript")

    def test_a_call_the_router_refuses_reaches_the_model_as_a_failure(self):
        """A 4xx is a JSON body here, not an exception -- `denied` and `unknown_tool` come back
        with an error status and an ordinary body. So the status is the only thing that says the
        call failed, and dropping it handed the model a refusal shaped exactly like output. It
        would then reason from a tool it believes ran."""
        self.answer("yes")
        self.tool_status, self.tool_body = 403, {"error": "denied",
                                                 "detail": "run_command is not enabled"}
        with env_patch(SYMONEURAL_STUDIO_TOKEN="t"):
            rc, out, err = call(self.cli.cmd_agent, self.args())
        self.assertEqual(rc, 0, err)
        told = json.loads(self.sent[1]["resume"][1]["content"])
        self.assertEqual(told["error"], "denied")
        self.assertEqual(told["tool"], "run_command")
        self.assertIn("not enabled", told["detail"])

    def test_the_resumed_request_carries_the_pending_messages_then_the_tool_result(self):
        """Order is the assertion. `resume` goes AFTER the user query, and inside it the
        assistant message that made the call must precede the result it is the call for --
        a result with no call ahead of it is a transcript the template cannot render."""
        self.answer("yes")
        with env_patch(SYMONEURAL_STUDIO_TOKEN="t"):
            call(self.cli.cmd_agent, self.args())
        self.assertEqual(len(self.sent), 2, "the turn should have taken two requests")
        self.assertNotIn("resume", self.sent[0])
        resume = self.sent[1]["resume"]
        self.assertEqual(resume[0]["role"], "assistant")
        self.assertEqual(resume[1]["role"], "tool")
        self.assertEqual(resume[1]["tool_call_id"], "c1")
        self.assertEqual(resume[1]["name"], "run_command")
        self.assertEqual(self.sent[1]["query"], self.sent[0]["query"],
                         "the query must not be restated or altered on resume")

    def test_refusing_runs_nothing_and_tells_the_model_a_person_said_no(self):
        """A refusal must reach the model as a refusal. An empty result would have it reason
        from a tool it believes succeeded, and a bare error would invite an immediate retry
        of the exact call that was just declined."""
        self.answer("no")
        with env_patch(SYMONEURAL_STUDIO_TOKEN="t"):
            rc, out, err = call(self.cli.cmd_agent, self.args())
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.ran, [], "nothing may execute after a refusal")
        told = json.loads(self.sent[1]["resume"][1]["content"])
        self.assertEqual(told["error"], "not_permitted")
        self.assertIn("declined", told["detail"])
        self.assertIn("Do not retry", told["detail"])

    def test_always_exempts_that_tool_for_the_rest_of_the_invocation_only(self):
        """`always` is per-invocation and is never written to disk. A persisted always is a
        decision made once and applied forever by a file nobody re-reads."""
        self.answer("always")
        with env_patch(SYMONEURAL_STUDIO_TOKEN="t"):
            call(self.cli.cmd_agent, self.args())
        self.assertEqual(self.sent[1]["allow"], ["run_command"])
        self.assertFalse(list(Path(self.tmp.name).glob("*allow*")),
                         "an exemption must not be persisted anywhere under run/")

    def test_quitting_stops_the_turn_without_running_it_and_is_not_an_error(self):
        """Ending a turn at the gate is a decision, not a failure: exit 0, nothing executed,
        and no second request -- a resumed segment after a quit would be the client asking
        the model to carry on with a turn its operator just stopped."""
        self.answer("quit")
        with env_patch(SYMONEURAL_STUDIO_TOKEN="t"):
            rc, out, err = call(self.cli.cmd_agent, self.args())
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.ran, [])
        self.assertEqual(len(self.sent), 1)
        self.assertIn("turn ended at the gate", out)

    def test_the_dropped_calls_after_the_gated_one_are_named_not_silently_lost(self):
        """The model chose those calls as a set. Running the tail of a set whose head was
        never approved is a decision nobody made, so the server drops them -- and the client
        has to say so, or a tool the model asked for vanishes with no trace on screen."""
        self.answer("no")
        with env_patch(SYMONEURAL_STUDIO_TOKEN="t"):
            _, out, _ = call(self.cli.cmd_agent, self.args())
        self.assertIn("write_file", out)
        self.assertIn("not run and not approved", out)

    def test_auto_asks_with_a_terminal_and_refuses_without_one(self):
        """The one branch that must never resolve the third way. With nobody to ask, the
        honest modes are "refuse and say so" and "stop"; "assume yes because the room is
        empty" is the failure this whole mechanism exists to prevent."""
        self.answer("no")
        for tty, expected in ((True, "ask"), (False, "deny")):
            with self.subTest(tty=tty):
                self.sent.clear()
                self.cli.have_tty = lambda t=tty: t
                with env_patch(SYMONEURAL_STUDIO_TOKEN="t"):
                    call(self.cli.cmd_agent, self.args(permissions="auto"))
                self.assertEqual(self.sent[0]["permissions"], expected)

    def test_dangerously_allow_all_is_the_only_way_to_reach_allow_by_accident(self):
        """It overrides the mode rather than being one of its choices, so that nothing can
        arrive at `allow` by defaulting: `auto` cannot resolve to it and an unset flag
        cannot imply it."""
        self.answer("no")
        with env_patch(SYMONEURAL_STUDIO_TOKEN="t"):
            call(self.cli.cmd_agent, self.args(permissions="auto",
                                               dangerously_allow_all=True))
        self.assertEqual(self.sent[0]["permissions"], "allow")


class StructuralRuleTests(unittest.TestCase):
    """Rules that need root, the GPU or a second process to violate, read from the source.

    Each assertion states what it would catch; the vacuity guard below pins the match
    counts so none of these can rot into asserting nothing.
    """

    def setUp(self):
        self.cli = load_cli()

    def test_neither_cli_harness_imports_through_a_caching_loader(self):
        """The trap that made this test exist. `SourceFileLoader` writes bytecode next to
        the shipped script and validates it against the source mtime **truncated to whole
        seconds**, so a change and a re-run inside one second silently execute the previous
        compile. A mutation was reverted here and the suite stayed red against code that was
        no longer on disk -- the exact failure this whole file is built to make impossible.
        Both harnesses now read and compile the text every call; this stops either of them
        drifting back. Comments are stripped first so that the sentence you are reading
        cannot satisfy the rule it describes."""
        for name in ("test_symoneural_cli.py", "test_cli_upgrade.py"):
            src = (Path(__file__).parent / name).read_text()
            code = "\n".join(line.split("#")[0] for line in src.splitlines())
            code = re.sub(r'"""(?:.|\n)*?"""', "", code)
            # Spelled in halves on purpose: the needle is the third rule in this file to
            # have gone red on its own explanation, and a docstring strip does not reach a
            # string literal.
            needle = "SourceFile" + "Loader"
            self.assertNotIn(needle, code,
                             f"{name} imports the CLI through a caching loader again; it "
                             "will run stale bytecode on a same-second edit")
            self.assertIn("compile(", code,
                          f"{name} no longer compiles the source it claims to test")

    def test_loading_the_cli_leaves_no_bytecode_beside_the_shipped_script(self):
        """The observable half of the rule above, and the cheaper one to trust: whatever the
        loader is, importing the CLI must not deposit a `.pyc` in `bin/`. That directory
        holds three executables that get installed; a cache file appearing in it is both the
        stale-code hazard and build detritus in a source tree."""
        load_cli()
        cache = CLI_PATH.parent / "__pycache__"
        # Absence, not before-and-after: `setUp` has already loaded the CLI by the time this
        # body runs, so a caching loader would have written its file before the first line
        # here could look. The first draft of this test compared the two and passed happily
        # with the trap reinstalled -- an assertion that cannot fail is the thing this suite
        # is least allowed to contain.
        stale = sorted(q.name for q in cache.glob(CLI_PATH.name + "*")) if cache.is_dir() else []
        self.assertEqual(stale, [],
                         f"bytecode for the CLI is sitting in {cache}; it must be compiled "
                         "in memory, not cached against a one-second mtime")

    def test_the_governor_is_never_asked_for_a_bare_release(self):
        """CLAUDE.md: never call a bare `gpu-governor.sh release` -- an unscoped release
        once destroyed a running fine-tune's lock from a shutdown hook. Every governor
        argv in the CLI must be the `with <surface>` form, whose whole point is that it
        always releases, scoped, even on crash; and the word `release` must not appear at
        all. (If a comment ever legitimately needs the word, narrow this to argv
        literals; today its absence is total and the simplest thing to hold.)"""
        for verb, surface in GOVERNOR_ARGV.findall(SRC):
            self.assertEqual(verb, "with", f"a governor call that is not `with`: {verb}")
            self.assertIn(surface, {"chat", "image"},
                          f"governor surface {surface!r} is not a known surface; if a "
                          "new surface is real, add it here deliberately")
        self.assertNotRegex(SRC, r"\brelease\b",
                            "the word `release` entered the CLI; releases are the "
                            "governor's job, scoped by `with`, never the CLI's")

    def test_the_cli_never_spawns_the_llm_server(self):
        """`api.py` owns the LLM server inside `gpu.hold(\"chat\")`; a second spawner races
        it for :8081 and the lease. The CLI may mention the binary exactly twice -- the
        built-yet probe in `cmd_status` and the janitor's pkill in `cmd_stop_chat` -- and
        `cmd_chat` must run the one-shot `symoneural-llm-cli` instead."""
        mentions = [l for l in SRC.splitlines() if SERVER_MENTION.search(l)]
        self.assertEqual(len(mentions), 2, mentions)
        for line in mentions:
            self.assertTrue(SERVER_PROBE.search(line) or SERVER_PKILL.search(line),
                            f"an unsanctioned LLM-server mention: {line.strip()!r}")
        self.assertIn('"symoneural-llm-cli"', inspect.getsource(self.cli.cmd_chat))

    def test_ravencalc_never_touches_the_governor_or_a_subprocess(self):
        """CLAUDE.md: RavenCalc deliberately never takes the lock -- CPU-only and
        never queues is the asymmetry the CLI exists to make visible. A governor hold or
        any subprocess appearing in this function is that property lost."""
        src = inspect.getsource(self.cli.cmd_ravencalc)
        self.assertNotIn("GOVERNOR", src)
        self.assertNotIn("subprocess", src)

    def test_the_status_verdict_renders_only_from_a_written_file(self):
        """The behavioural halves live in `test_cli_upgrade.py` (row absent, row present);
        this pins the SHAPE that makes them true -- the row prints only under
        `if verdict:` -- and that no wording like 'never deployed' exists to be printed,
        because an invented row would be a reading of a file that does not exist."""
        src = inspect.getsource(self.cli.cmd_status)
        self.assertIn("verdict = last_deploy()", src)
        self.assertRegex(src, r"if verdict:",
                         "the verdict row lost its written-file guard")
        # Comments stripped first. `bin/symoneural-cli:161` explains the rule by quoting
        # the very phrase the rule bans, so a raw-source match indicts the explanation.
        # The rule is about wording that can be PRINTED, which a comment cannot be.
        code = "\n".join(l.split("#", 1)[0] for l in SRC.lower().splitlines())
        self.assertNotIn("never deployed", code)

    def test_upgrade_check_returns_before_the_root_check(self):
        """--check promises 'without root and without deploying'. If the euid test ever
        moves above it, a non-root `--check` re-execs sudo -- a dry run that escalates,
        and (the way this suite would first notice) an execvp that replaces the test
        process mid-run."""
        src = inspect.getsource(self.cli.cmd_upgrade)
        self.assertLess(src.index("if args.check:"), src.index("os.geteuid()"))

    def test_the_bare_invocation_guard_reads_stdin_and_not_the_colour_helper(self):
        """`_tty()` reads stdout and decides about colour. The session guard has to ask
        about stdin. The two are one keystroke apart, both are called `tty`, and swapping
        them is silent: `symoneural-cli > file` in a cron job would then open a prompt on
        a stdin nobody is holding, which is a hang and not an error.

        Comments stripped first, for the same reason the deploy-wording rule above does it:
        `main()` explains this rule by naming the helper it bans, so a raw-source match
        indicts the explanation. This test went red on its own first run for exactly that.
        """
        src = inspect.getsource(self.cli.main)
        code = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
        self.assertIn("sys.stdin.isatty()", code)
        self.assertNotIn("_tty()", code)

    def test_declared_subcommands_are_exactly_the_known_fourteen(self):
        """Pinned in both directions: a new subcommand must arrive with tests (this fails
        until it is added here), and one quietly vanishing is a removal someone has to mean.

        `repl` was the thirteenth and did exactly what this test is for. `import-claude` is
        the fourteenth and did it again on 2026-09-08 -- it went red on the addition and
        stayed red until the behaviour was described beside KNOWN_SUBCOMMANDS.
        """
        declared = set(ADD_PARSER.findall(SRC)) | set(STUDIO_PARSER.findall(SRC))
        self.assertEqual(declared, KNOWN_SUBCOMMANDS)

    def test_the_regexes_in_this_file_still_match_the_cli(self):
        """The guard against every structural test above passing vacuously. Reformat the
        CLI so a pattern stops matching and the loops iterate nothing, the absence checks
        check absence in the wrong haystack, and everything stays green -- this fails
        first and names the pattern that went blind."""
        self.assertTrue(CLI_PATH.is_file(), f"{CLI_PATH} is gone")
        self.assertGreater(len(SRC), 25_000, "the CLI shrank to a stub; SRC is not it")
        self.assertEqual(len(GOVERNOR_ARGV.findall(SRC)), 2,
                         "GOVERNOR_ARGV no longer matches the two `with` invocations")
        self.assertEqual(len([l for l in SRC.splitlines() if SERVER_MENTION.search(l)]), 2,
                         "the LLM-server mention count moved; re-audit the contexts")
        self.assertEqual(len(ADD_PARSER.findall(SRC)), 9,
                         "direct add_parser() count moved; update KNOWN_SUBCOMMANDS "
                         "and the dispatch TABLE together")
        self.assertEqual(len(STUDIO_PARSER.findall(SRC)), 5,
                         "studio() subcommand count moved; same instruction")
        for fn in (self.cli.cmd_status, self.cli.cmd_upgrade, self.cli.cmd_chat,
                   self.cli.cmd_ravencalc):
            self.assertGreater(len(inspect.getsource(fn)), 200,
                               f"{fn.__name__} source went missing under inspect")


if __name__ == "__main__":
    unittest.main()
