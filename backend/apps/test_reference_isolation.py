"""`external/` is read-only material. Nothing in it may execute. Enforce that.

The standing owner rule, quoted verbatim in `tools/index_references.py`:

    "we cannot use code in references its for reference only we must rebrand if we
     want to use it"

That rule has been written down since 2026-08 and enforced by nobody. The consolidation on
2026-09-08 moved 46 upstream OSS trees, TensorRT-LLM, ComfyUI-Installs, bentoml,
ninjatraining, Toolchains, Platforms and the vendor agent material into `external/`, which
makes the surface it governs much larger than the day it was written -- and a rule whose only
enforcement is that somebody remembers it is not a rule, it is a hope.

**Why this test exists at all.** On 2026-09-08 an htop capture filtered on `symoneural` showed
about thirty lines of a language runtime and read, reasonably, as third-party code executing
on the box. It was not: one process, thread-expanded, and the process was
`symoneural-llm`, first-party, loopback-bound. But *nothing could answer the question*
without hand-inspecting `/proc`, and "I checked and it's fine" is precisely the assurance this
repo has learned not to accept. So the answer is a check that fails.

Two rules, because there are two ways in:

  * **Static** -- no tracked source may hand a path under `external/` to anything that
    executes. This catches the case where a convenient upstream binary gets wired in and
    nobody notices until it is load-bearing.
  * **Runtime** -- no live process may have its executable or working directory under
    `external/` or `archive/`. This catches the case where somebody ran it by hand.

The runtime rule reads `/proc`, so it measures this box as it is now rather than what any
document claims. That is deliberate: the failure this repo keeps repeating is trusting a
written state over a measured one.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Directories whose contents must never execute. `archive/` joins `external/` because the
# consolidation put session transcripts, build evidence and weight staging there: nothing in
# it is ours to run either, and a build tree that starts serving is the September 1 failure.
NO_EXEC_DIRS = ("external", "archive")

# Suffixes worth reading. Kept narrow on purpose -- this walks tracked files only, so it is
# bounded by the index rather than by the disk.
SUFFIXES = (".py", ".sh", ".bash", ".service", ".yaml", ".yml", ".toml", ".json", ".mk")

# A path under external/ or archive/ handed to something that runs it. The verbs are the
# ones this repo actually uses: subprocess, os.exec*, systemd ExecStart, and shell invocation
# by absolute path.
#
# The path must sit inside a **quoted** token, and that quote is doing real work. Two earlier
# drafts of this pattern failed on prose instead of code:
#
#   backend/api.py:194            a comment recording that this was fixed on 2026-08-20
#   apps/coder/test_coder.py:342  a docstring listing disk usage: "external/ (8.5 GB)"
#
# Neither executes anything. Whole-line comments are stripped before matching, but a
# docstring is not a comment to the tokeniser, so prose survives that pass -- and an
# unquoted mention in a sentence is exactly what prose looks like, while a real exec
# argument is a string literal. Requiring the quote separates them without an exempt list,
# which matters because an exempt list is how a guard quietly stops guarding.
_DIRS = "|".join(NO_EXEC_DIRS)

# Two patterns, because the quote requirement below is right for Python and wrong for
# systemd. `ExecStart=` was originally an alternative inside CALLS_EXEC and could therefore
# never fire: a unit file writes `ExecStart=/path/to/thing` with no quotes anywhere on the
# line, so the trailing `["'][^"'\n]*` could not match and the branch was dead code. Caught
# by a synthetic control -- an ExecStart line pointing into archive/ -- which the guard
# reported as MISSED after the first commit of this file. A branch that cannot fire is worse
# than a missing one, because the code reads as covered.
UNIT_EXEC = re.compile(r"^\s*Exec(?:Start|StartPre|StartPost|Reload|Stop)\s*=.*?"
                       r"(?:%s)/" % _DIRS, re.MULTILINE)

CALLS_EXEC = re.compile(
    r"(?:subprocess\.(?:run|Popen|call|check_call|check_output)"
    r"|os\.(?:exec[lv]p?e?|system|spawn\w+))"
    # A shell-invocation branch (`bash|sh|exec|python3 <path>`) was tried and removed. `sh`
    # matches the tail of `du -sh`, which is how `tools/fork_render_ui.sh` -- the script that
    # forked ComfyUI into engines/ -- got reported for measuring a directory it is allowed to
    # read. Three false positives from one branch, against a class of violation the runtime
    # check below already catches by looking at what is actually executing. Removed rather
    # than exempted: the /proc walk is the stronger half of this test anyway.
    r"[^\n]{0,160}?"
    r"[\"'][^\"'\n]*(?:%s)/" % _DIRS,
    re.MULTILINE,
)

# This file necessarily names the pattern it forbids, and so does the consolidation record and
# the handoff that explains it. Documentation about a rule is not a breach of it.
EXEMPT = (
    "backend/apps/test_reference_isolation.py",
    "tools/index_references.py",          # indexes external/ by reading frontmatter only
    "docs/",
    ".claude/",
)


COMMENT = re.compile(r"^\s*(#|//|--|\*|/\*|>)")


def _code_only(text: str) -> str:
    """Drop whole-line comments before matching.

    `backend/api.py` explains at line 194 that the GPU engines *"pointed into external/
    until 2026-08-20, which broke two standing rules at once"* -- a comment recording that
    the violation was fixed. The first version of this test read that as the violation and
    failed on the file that documents the rule. Prose about a breach is not a breach, and a
    guard that cannot tell the difference gets exempted into uselessness within a week.

    Whole-line only. A trailing comment after real code is left in, because code that execs
    reference material and then explains itself is still code that execs reference material.
    """
    return "\n".join("" if COMMENT.match(ln) else ln for ln in text.splitlines())


def _tracked_sources():
    """Tracked files with an interesting suffix, as repo-relative paths.

    `git ls-files` rather than a walk: `external/` and `archive/` are ignored and hold
    hundreds of gigabytes, and a walk would read them to prove nothing reads them.
    """
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"],
                         capture_output=True, text=True, timeout=120)
    for rel in out.stdout.split("\0"):
        if not rel or not rel.endswith(SUFFIXES):
            continue
        if any(rel.startswith(x) for x in EXEMPT):
            continue
        yield rel, ROOT / rel


class ReferenceMaterialDoesNotExecute(unittest.TestCase):
    """No tracked source wires a path under external/ or archive/ into an exec."""

    def test_no_tracked_source_executes_reference_material(self):
        offenders = {}
        for rel, path in _tracked_sources():
            try:
                text = path.read_text(errors="replace")
            except OSError:
                continue
            code = _code_only(text)
            hits = sorted({m.group(0).strip()[:110]
                           for pat in (CALLS_EXEC, UNIT_EXEC)
                           for m in pat.finditer(code)})
            if hits:
                offenders[rel] = hits
        self.assertEqual(
            offenders, {},
            "these hand a path under external/ or archive/ to something that runs it. "
            "The standing rule is that reference material is read-only: rebrand it into "
            "engines/ via tools/fork_engines.sh, or adopt it via "
            "`tools/index_references.py adopt`, but do not execute it where it lies")


class NothingUnderReferencesIsRunning(unittest.TestCase):
    """Measured, not documented: walk /proc and look at what is actually executing."""

    @staticmethod
    def _live_offenders():
        forbidden = tuple(str(ROOT / d) + os.sep for d in NO_EXEC_DIRS)
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            for what in ("exe", "cwd"):
                try:
                    target = os.readlink(f"/proc/{entry}/{what}")
                except OSError:
                    continue                      # gone, or not ours to read; either is fine
                if target.startswith(forbidden):
                    try:
                        cmd = pathlib.Path(f"/proc/{entry}/cmdline").read_bytes()
                        cmd = cmd.replace(b"\0", b" ").decode(errors="replace").strip()
                    except OSError:
                        cmd = "<exited>"
                    yield f"pid {entry} ({what}={target}): {cmd[:160]}"
                    break

    def test_no_live_process_runs_from_reference_or_archive_material(self):
        live = sorted(self._live_offenders())
        self.assertEqual(
            live, [],
            "a process is executing from reference or archive material. This is the thing "
            "the owner rule forbids outright. Stop it, then either rebrand the code into "
            "engines/ or run the first-party equivalent instead")

    def test_the_probe_can_actually_see_a_process(self):
        """A guard that can see nothing always passes, so prove it sees something.

        `test_no_live_process...` returning an empty list is only evidence if the walk works
        at all. In a container with a masked `/proc`, or under a hardening policy that blocks
        `readlink` on `exe`, it would return empty for the wrong reason and read as a pass
        forever. So resolve this interpreter's own executable the same way.
        """
        me = os.readlink(f"/proc/{os.getpid()}/exe")
        self.assertTrue(me, "cannot read /proc/self/exe, so the runtime guard above proves "
                            "nothing on this host and must not be trusted here")


if __name__ == "__main__":
    unittest.main()
