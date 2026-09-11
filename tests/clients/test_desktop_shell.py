"""`desktop/shell.py` -- the desktop window, and the one claim it exists to make.

`desktop/README.md` chose GTK3 + VTE over a web view for a single reason: a web client is a
second implementation of the permission gate, and `approve()` in `bin/symoneural-cli` opens
`/dev/tty` rather than reading stdin -- deliberately, because in `agent "..."` stdin may be a
pipe carrying the query and in the repl it is the transcript, and neither absence means there
is nobody at the keyboard. The window's whole job is therefore to hand the real client a real
controlling terminal.

**That claim has exactly one honest test and `WindowSmokeTests` is it**: launch the window,
type `/permissions` into it, and read what the client says the mode resolves to. `auto`
resolves to `ask` when there is a terminal and `deny` when there is not, so `auto -> ask` on
screen is the pty, observed from the far side of it. Every other invocation of this client in
this repo -- every pipe, every `subprocess.run`, the node suite's own repl tests -- reads
`deny`, which is what makes the one reading that says `ask` worth something.

Nothing here is stubbed: it is the real `Vte.Terminal`, the real `spawn_async`, the real
`bin/symoneural-code`, and the text is read back out of the terminal widget. The window is
launched once for the class, because a GTK main loop per assertion would cost ten seconds each
and prove the same thing.

It **skips** without a display or without the GTK/VTE typelibs, rather than failing. A window
test on a headless box is a missing instrument, not a broken program -- and the skip says
which so nobody reads it as a pass. `StructuralRuleTests` below needs neither and always runs;
it is the half that catches the window growing a second session, a second gate, or an API call
of its own, which is the failure this whole design is arranged to prevent.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import signal
import time
import tokenize
import unittest
from pathlib import Path

ROOT = next(_p for _p in Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
SHELL = ROOT / "desktop" / "shell.py"
ENTRY = ROOT / "desktop" / "symoneural-code.desktop"


def strip_prose(src: str) -> str:
    """The source with comments and docstrings taken out.

    What is left is code, which is what a "this must not be here" assertion has to be about.
    A docstring saying *this file handles no transcripts* contains the word `transcript`, so a
    test reading the raw text is satisfied -- or in that case defeated -- by the file's own
    account of itself.

    A string that is the whole of a statement is a docstring or a bare comment-string; a string
    used as a value is code and stays, because `"/api/status"` passed to something is exactly
    the kind of line these tests exist to catch.
    """
    kept: list[str] = []
    standalone = True                   # the next STRING begins a statement of its own
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and standalone:
            continue
        if tok.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
                            tokenize.DEDENT, tokenize.ENCODING):
            standalone = False
            kept.append(tok.string)
        elif tok.type in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
            standalone = True
            kept.append("\n")
    return " ".join(kept)


def why_not_a_window() -> str:
    """The reason a window cannot be opened here, or '' if one can."""
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        return "no DISPLAY and no WAYLAND_DISPLAY: there is no display server to open onto"
    try:
        import gi                                            # noqa: F401
        gi.require_version("Gtk", "3.0")
        gi.require_version("Vte", "2.91")
        from gi.repository import Gtk, Vte                    # noqa: F401
    except (ImportError, ValueError) as exc:
        return f"python3-gi / gir1.2-vte-2.91 not available here: {exc}"
    return ""


NO_WINDOW = why_not_a_window()



def _offscreen_display():
    """Start a throwaway X server and return (popen, display), or (None, None).

    This test is deliberately un-stubbed -- a real `Vte.Terminal`, a real `spawn_async`, the
    real `bin/symoneural-code` -- and that is worth keeping. What is not worth keeping is
    where the window lands. On 2026-09-08 the owner watched a window titled "SyMoNeuRaL Code"
    appear on his desktop every time the suite ran, and then watched KWin raise
    `kwin_killer_helper` against it when the client inside was slow to answer. From the
    outside that is indistinguishable from software launching itself unbidden on his machine.

    Xvfb is installed here, so the window goes onto a display nobody is looking at. The test
    keeps every assertion and every real component; only the pixels move. If Xvfb is absent
    this returns (None, None) and the test falls back to whatever DISPLAY it was given, which
    is the previous behaviour rather than a skip -- a missing virtual display is a reason to
    be visible, not a reason to stop checking.
    """
    if not shutil.which("Xvfb"):
        return None, None
    for n in range(99, 110):                      # :0 is the person's; start well clear of it
        if os.path.exists(f"/tmp/.X11-unix/X{n}"):
            continue
        disp = f":{n}"
        proc = subprocess.Popen(
            ["Xvfb", disp, "-screen", "0", "1024x768x24", "-nolisten", "tcp"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break                             # died; try the next number
            if os.path.exists(f"/tmp/.X11-unix/X{n}"):
                return proc, disp
            time.sleep(0.1)
        proc.terminate()
    return None, None


def _reap(win) -> None:
    """Destroy the window AND make sure its child is dead.

    `shell.py:231` documents the intended mechanism -- *"let the child get its SIGHUP from
    the pty closing"* -- and that is right for a window a person closes. It is not sufficient
    for a test, and the difference showed up on the owner's desktop rather than in the suite:
    KWin kept raising `kwin_killer_helper -windowname "SyMoNeuRaL Code"`, its force-quit
    dialog for a window that has stopped answering pings. Measured from an htop capture on
    2026-09-08, three of those helpers at once against one hung client.

    The path there: `setUpClass` waits up to 30 s for the client banner, and when the client
    is slow or wedged the deadline fires, `Gtk.main_quit()` returns, `win.destroy()` disposes
    the widgets -- and the child is still running, still holding the pty. An orphan holding a
    pty behind a destroyed window is exactly what KWin reports as not responding. The suite
    passed either way, which is why this survived: the test's own assertions had already been
    read before teardown.

    So the test reaps what the test spawned, rather than delegating it to a signal that only
    arrives on the tidy path. SIGTERM first because the client has an exit path worth taking,
    SIGKILL after a short grace because a wedged client is the case this exists for.
    """
    pid = getattr(win, "pid", None)
    try:
        win.destroy()
    except Exception:
        pass
    if not pid:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return                      # already gone; nothing to chase
        except PermissionError:
            return
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            try:
                if os.waitpid(pid, os.WNOHANG) != (0, 0):
                    return
            except ChildProcessError:
                return                  # VTE reaped it, which shell.py says it does
            except OSError:
                return
            time.sleep(0.05)


@unittest.skipIf(NO_WINDOW, NO_WINDOW)

class WindowSmokeTests(unittest.TestCase):
    """One real window, one real child, read back through the terminal widget."""

    screen = ""
    pid = None
    label = ""

    _xvfb = None
    _display_was = None

    @classmethod
    def setUpClass(cls):
        import importlib.util

        # Point at a throwaway display BEFORE gi/Gtk is touched -- Gtk connects on first use
        # and will not follow a DISPLAY changed afterwards.
        # OPT-IN, NOT OPT-OUT. This is the third attempt at stopping this test putting a
        # window on the owner's desktop, and the first two each relied on something
        # working: first on the child taking SIGHUP when the pty closed, then on Xvfb
        # starting. Xvfb is installed and `_offscreen_display()` returns a display when
        # called directly, and a window still appeared during a suite run -- so the
        # mechanism is not understood, and continuing to reason about it while windows keep
        # opening on somebody's screen is the wrong trade.
        #
        # The default is now that this class does not run. A window check that has to be
        # asked for costs coverage on one test. A window appearing unbidden on the owner's
        # machine costs his confidence in what this repo does when he is not watching,
        # which is worth more than the check.
        #
        #     SYMONEURAL_TEST_WINDOW=1 python3 -m pytest apps/test_desktop_shell.py
        #
        # With it set, the window still goes to a throwaway display when Xvfb will start.
        if os.environ.get("SYMONEURAL_TEST_WINDOW") != "1":
            raise unittest.SkipTest(
                "SYMONEURAL_TEST_WINDOW is not 1. This test opens a real window and runs "
                "the real client inside it, so it does not run by default -- set that "
                "variable to run it deliberately")

        cls._xvfb, disp = _offscreen_display()
        if disp:
            cls._display_was = os.environ.get("DISPLAY")
            os.environ["DISPLAY"] = disp
        elif os.environ.get("SYMONEURAL_TEST_ALLOW_VISIBLE_WINDOW") != "1":
            # No throwaway display available. The previous behaviour was to fall back to
            # whatever DISPLAY was given, which on this box is the owner's desktop -- and a
            # window appearing there unbidden is the complaint that started this. Skipping
            # is the safer default: an un-run window check costs coverage, a window on
            # somebody's screen costs their trust in what the machine is doing. Set
            # SYMONEURAL_TEST_ALLOW_VISIBLE_WINDOW=1 to opt back in deliberately.
            raise unittest.SkipTest(
                "no offscreen display available (Xvfb missing or would not start) and "
                "SYMONEURAL_TEST_ALLOW_VISIBLE_WINDOW is not 1, so this will not open a "
                "window on the active display")

        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Vte", "2.91")
        from gi.repository import GLib, Gtk, Vte

        spec = importlib.util.spec_from_file_location("symoneural_shell", SHELL)
        shell = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(shell)
        cls.shell = shell

        win = shell.Window([], cwd=ROOT)
        win.show_all()
        win.start()
        win.term.grab_focus()

        def screen_now() -> str:
            out = win.term.get_text_format(Vte.Format.TEXT)
            return (out[0] if isinstance(out, tuple) else out) or ""

        # **Wait for each step rather than guessing how long it takes.** This drove the child
        # at fixed delays -- type at 1400 ms, read at 4200 ms -- and that is a race, not a
        # schedule: the client needs about 700 ms to print its banner on an idle box and
        # longer on a busy one, so on a loaded machine the screen was sampled before the
        # answer arrived. Measured 2026-08-21: four of five consecutive runs failed that way,
        # and the same five passed with nothing changed but the timing. A window test that
        # only passes when the machine is quiet reports load, not correctness.
        #
        # Every assertion below is unchanged and none is weakened. The deadline is still hard,
        # so a client that never answers still fails -- it just fails after waiting
        # for it rather than before. The common case also got faster, because this
        # stops as soon as the text is there.
        deadline = time.monotonic() + 30.0
        state = {"typed": False}

        def pump():
            if time.monotonic() > deadline:
                Gtk.main_quit()
                return False
            text = screen_now()
            # `/permissions` and NOT `/exit`. The client exiting cleanly destroys the window --
            # which is correct behaviour and is asserted separately below without a display --
            # and it took the scrollback with it before the first version of this test could
            # read it. Typed only once the banner proves the client is listening; typing into
            # a child that has not finished starting drops the keystrokes silently.
            if not state["typed"]:
                if "/help for the commands" in text:
                    win.term.feed_child(b"/permissions\r")
                    state["typed"] = True
                return True
            if "permissions: auto ->" in text:
                Gtk.main_quit()
                return False
            return True

        GLib.timeout_add(100, pump)
        Gtk.main()
        # Read once, after the loop stops, so every assertion sees the same instant -- and
        # read BEFORE destroy(), which disposes the widgets and would return empty strings.
        cls.screen = screen_now()
        cls.pid = getattr(win, "pid", None)
        cls.label = win.status.get_text()
        _reap(win)

    @classmethod
    def tearDownClass(cls):
        if cls._xvfb is not None:
            cls._xvfb.terminate()
            try:
                cls._xvfb.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls._xvfb.kill()
        if cls._display_was is None:
            os.environ.pop("DISPLAY", None)
        else:
            os.environ["DISPLAY"] = cls._display_was

    def test_the_child_is_spawned_and_the_client_greets_from_inside_the_window(self):
        """Spawn first, because everything else is downstream of it. This is also the assertion
        that caught `GLib.SpawnFlags.DO_NOT_REAP_CHILD`: VTE reaps the child itself, so the flag
        made `vte_pty_spawn_with_fds_async` fail its own runtime check and spawn nothing,
        leaving a black window and one warning on a stderr that a desktop launcher discards."""
        self.assertIsNotNone(self.pid, "no child was spawned")
        self.assertIn("SyMoNeuRaL Code", self.screen)
        # "local session", not "interactive session": the splash was rewritten to the aligned
        # two-column form ("Six rows of bootstrap text was the complaint this splash answers")
        # and this string went with it. What is being asserted is unchanged -- that the real
        # client greeted from inside the window, rather than the window drawing a prompt of
        # its own -- so only the literal moves.
        self.assertIn("local session", self.screen)

    def test_auto_resolves_to_ask_inside_the_window_which_is_the_pty(self):
        """**The reason this file exists.** `auto` is not a state, it is a question answered by
        whether `have_tty()` can open `/dev/tty`, and the answer is `deny` in every piped
        invocation in this repo. Reading `ask` here is the controlling terminal, observed from
        the far side of it -- and it is the whole justification for VTE over a web view, since
        a browser has no `/dev/tty` and would need a second answer to who the human is.

        The measured limit of this check, so nobody reads it as stronger than it is: mutating
        the spawn to `Vte.PtyFlags.NO_CTTY` does **not** turn it red, and that is a property of
        the launcher, not a hole in the test. `bin/symoneural-code` is a bash script, and a
        session leader with no controlling terminal acquires one the moment it opens a terminal
        device -- so bash takes the pty back on the way to `exec`, under either flag. Probed
        both ways round: `python3` spawned directly reads `CTTY no [Errno 6]` under `NO_CTTY`
        and `/dev/tty` under `DEFAULT`, while the same probe behind `bash -c` reads `/dev/tty`
        under both, with stdin closed as well. A ctty is per session; once anything in the
        session claims it, every process there has it.

        What does turn this red is the fault class it is actually here for: replacing the VTE
        spawn with `subprocess.Popen` on pipes and feeding the output into the widget -- a
        terminal that only looks like one, which is exactly what a web view would be. That
        mutation fails this test and three of its neighbours. The other half of the
        discrimination was read on the same tree: `printf '/permissions\n/exit\n' |
        bin/symoneural-cli repl` prints `auto -> deny`. Same client, same command, two answers,
        and the pty is the whole difference between them."""
        # `permissions  auto -> ask`, aligned columns, no colon. The arrow is the part that
        # matters and it is still required; matched by regex so a column-width change cannot
        # turn a security assertion red again.
        self.assertRegex(self.screen, r"permissions\s+auto -> ask",
                     "the client found no controlling terminal in its own window, which means "
                     "the permission prompt cannot be shown to the person using it")
        self.assertNotIn("auto -> deny", self.screen)

    def test_the_status_bar_reports_the_child_and_claims_nothing_else(self):
        """No decorative indicators, which is a repo rule about pages and is no weaker about
        windows. The bar carries the launcher, the pid and the cwd -- three facts -- and there
        is no connection light, because this window holds no connection."""
        self.assertIn("symoneural-code", self.label)
        self.assertIn(str(self.pid), self.label)
        self.assertIn(str(ROOT), self.label)

    def test_the_window_hosts_the_client_rather_than_reimplementing_its_prompt(self):
        """The client's own banner is on screen, so what the user is talking to is the client:
        its session id, its transcript path, its token warning. A window that had reimplemented
        any of this would show its own words instead."""
        self.assertRegex(self.screen, r"session\s+code-\d{8}-\d{6}")
        # `agent-code-` is gone: session ids are `code-<date>-<time>` now, which the regex
        # above already pins in full. Asserting a dead prefix as well would only pin the old
        # naming scheme, not the property this test is named for.
        self.assertIn("/help", self.screen)


class ExitBehaviourTests(unittest.TestCase):
    """`on_child_exited`, called directly. No display needed and none used: the decision it
    encodes is a two-branch rule about whether the scrollback survives, and driving a real
    window to a crash to test it would be slower and prove less."""

    def setUp(self):
        if NO_WINDOW:
            self.skipTest(NO_WINDOW)
        import importlib.util
        spec = importlib.util.spec_from_file_location("symoneural_shell_exit", SHELL)
        self.shell = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.shell)
        self.win = self.shell.Window([], cwd=ROOT)      # constructed, never shown or spawned

    def tearDown(self):
        if getattr(self, "win", None) is not None:
            _reap(self.win)

    def test_a_clean_exit_closes_the_window(self):
        closed = []
        self.win.destroy = lambda *_: closed.append(True)
        self.win.on_child_exited(self.win.term, 0)
        self.assertTrue(closed, "a session that ended cleanly left its window behind")

    def test_a_failed_exit_keeps_the_window_and_says_the_scrollback_is_kept(self):
        """The scrollback is where the reason is. A client that failed and a window that
        vanished is a bug report nobody can write."""
        closed = []
        self.win.destroy = lambda *_: closed.append(True)
        self.win.on_child_exited(self.win.term, 1)
        self.assertFalse(closed, "the window closed over a non-zero exit, taking the reason")
        self.assertIn("exited", self.win.status.get_text())
        self.assertIn("kept", self.win.status.get_text())

    def test_closing_the_window_is_not_gated_behind_a_dialog(self):
        """`False` lets the close proceed. A turn in flight is abandoned, which is exactly what
        Ctrl-C in the session does, and `cmd_agent` writes the thread only after a complete
        answer -- so there is nothing half-recorded for a confirmation dialog to protect."""
        self.assertFalse(self.win.on_delete())


class StructuralRuleTests(unittest.TestCase):
    """The rules that make this window a window. Asserted against the source because each one
    is about code that must NOT be there, and absent code cannot be exercised.

    Every negative test below reads `cls.code`, which is the source with **comments and
    docstrings removed**, and that is not tidiness. The first version read the raw text and
    went red on `agent-` -- a phrase inside the module docstring, in the sentence explaining
    that this file handles no transcripts. Prose about not doing a thing is the exact trap
    `PROJECT-TASKS.md` records for the grep checks one surface over: a pattern that a sentence
    can satisfy is a pattern measuring the wrong thing, and here it would have been satisfied
    by the documentation of its own compliance. Strip the prose and the assertion is about code.

    Structural assertions rot silently, so the last test here pins the positive facts the
    others depend on and fails first if a rewrite makes them vacuous.
    """

    @classmethod
    def setUpClass(cls):
        cls.src = SHELL.read_text()
        cls.code = strip_prose(cls.src)

    def test_the_shell_spawns_the_launcher_and_owns_no_engine(self):
        self.assertIn("LAUNCHER = ROOT / \"bin\" / \"symoneural-code\"", self.src)
        self.assertIn("spawn_async", self.src)

    def test_the_shell_never_speaks_to_the_api_itself(self):
        """It has no idea what the API is; it spawns a child that does. An HTTP call from here
        is the first half of a second client, and the second half follows because the first one
        needs somewhere to display what it got."""
        for forbidden in ("urllib", "requests", "httpx", "api_json", "/api/", "WebSocket"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.code)

    def test_the_shell_implements_no_permission_prompt_of_its_own(self):
        """`approve()` is the gate and there is exactly one. A dialog here would be a second
        one, on a window that cannot see the arguments the client is about to run."""
        for forbidden in ("MessageDialog", "def approve", "APPROVE_KEYS", "not_permitted"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.code)

    def test_the_shell_implements_no_session_store_of_its_own(self):
        """One implementation of "resume a thread". Two would drift, and the way that drift
        shows up is a session you can open one way and not the other -- which is the argument
        `bin/symoneural-code`'s own header already makes for itself."""
        for forbidden in ("agent-", "transcript", "json.load", "session_id"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.code)

    def test_plain_ctrl_c_is_left_to_the_child(self):
        """Ctrl-C is how a turn is abandoned without leaving the session, so the window must not
        take it. The window's own bindings are all Ctrl-Shift or zoom, and `on_key` returns
        False for anything else."""
        keys = self.src.split("def on_key")[1]
        self.assertIn("if not ctrl:", keys)
        self.assertIn("return False", keys)
        self.assertNotIn('key in ("C", "c") and not shift', keys)
        # Copy and paste are both behind shift, or plain Ctrl-C would be stolen from the child.
        for line in keys.splitlines():
            if 'key in ("C", "c")' in line or 'key in ("V", "v")' in line:
                self.assertIn("shift and", line, f"an unshifted binding steals a key: {line}")

    def test_no_ellipsis_or_truncation_is_applied_to_anything_the_client_prints(self):
        """The repo bars `text-overflow: ellipsis` on a detail line as data loss with extra
        steps, and the reason generalises past CSS: an Apache-2.0 attribution cut to `...7B-Ins...`
        is a licence condition cut. A terminal wraps; nothing here may clip."""
        self.assertNotIn("ellipsize", self.code)
        self.assertNotIn("set_max_width_chars", self.code)
        self.assertNotIn("\u2026", self.code)

    def test_the_desktop_entry_launches_this_file_and_does_not_claim_to_be_a_terminal(self):
        """`Categories=Development`. `TerminalEmulator` was there and was withdrawn: this
        renders IN a terminal, but the thing it IS, is a coding agent, and claiming otherwise
        puts it in a menu as somewhere to open a shell."""
        entry = ENTRY.read_text()
        self.assertIn("desktop/shell.py", entry)
        self.assertIn("Terminal=false", entry)
        self.assertNotIn("TerminalEmulator;", entry.split("Categories=")[1].splitlines()[0])
        self.assertIn("Name=SyMoNeuRaL Code", entry)

    def test_the_positive_facts_the_negative_tests_rely_on_are_still_present(self):
        """The rot check. Every test above asserts an absence, and an absence is also what you
        get from a file that was renamed, emptied or rewritten -- so this pins the presences.
        If this fails, the negative results above mean nothing and must be re-read."""
        self.assertGreater(len(self.src), 4000, "shell.py is too small to be the window")
        self.assertEqual(len(re.findall(r"Vte\.Terminal\(\)", self.src)), 1)
        self.assertEqual(len(re.findall(r"def on_key", self.src)), 1)
        self.assertEqual(len(re.findall(r"def on_child_exited", self.src)), 1)
        self.assertIn("gi.require_version(\"Vte\", \"2.91\")", self.src)


if __name__ == "__main__":
    unittest.main()
