"""tools/build_progress.py, held to its two promises: deterministic, and driven by the rows.

The page is Garrett's bookmark (run/progress.html); its regression contract from the spec:
  * byte-identical output on an unchanged tree — idempotence, EXCLUDING the one marked
    generated-at line, the only clock read in the whole script;
  * every task number in PROJECT-TASKS.md renders — and the mutation form of that claim:
    delete a row from a temp copy of the tree and the number disappears from the output,
    proving the table derives from the parsed rows and not from anything static.

The generator is run via subprocess (never imported): it is a tool, not a module of the
serving path, and --root/--out exist precisely so tests can point it at temp trees without
touching the real run/progress.html. Temp roots are not git repositories, which also
exercises the "no-git" header arm the spec demands for fresh clones.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "tools" / "build_progress.py"
INTAKE_GENERATOR = ROOT / "tools" / "build_intake.py"
TASK_ROW = re.compile(r"^([◼◻▶]) ((?:\(unnumbered[^)]*\))|#\d+) — (.+)$", re.M)
SOURCES = ("PROJECT-TASKS.md", "GARRETT-REQUESTS.md", "AUDIT-SURFACE-2026-08-19.md",
           "GARRETT-INBOX.md")


def run_generator(root: Path, out: Path) -> str:
    r = subprocess.run(
        [sys.executable, str(GENERATOR), "--root", str(root), "--out", str(out)],
        capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise AssertionError(f"generator failed rc={r.returncode}\n{r.stderr}")
    return out.read_text()


def run_intake(root: Path) -> None:
    """Build INTAKE.md in a temp root.

    The ledger no longer reaches the page directly: it is one of three sources merged into
    INTAKE.md, which is what build_progress.py renders. So a test about how a ledger entry
    appears has to run BOTH generators, in the order the systemd unit runs them. Asserting on
    build_progress.py alone would be asserting on a stage the data no longer passes through.
    """
    r = subprocess.run([sys.executable, str(INTAKE_GENERATOR), "--root", str(root)],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise AssertionError(f"build_intake failed rc={r.returncode}\n{r.stderr}")


def strip_generated_line(html: str) -> str:
    return "\n".join(l for l in html.splitlines() if 'id="generated-at"' not in l)


def copy_tree(dst: Path, skip: str | tuple[str, ...] | None = None):
    skipped = (skip,) if isinstance(skip, str) else (skip or ())
    for name in SOURCES:
        src = ROOT / name
        if src.exists() and name not in skipped:
            shutil.copy(src, dst / name)


class DeterministicOnAnUnchangedTree(unittest.TestCase):

    def test_two_runs_differ_only_on_the_generated_at_line(self):
        with tempfile.TemporaryDirectory() as td:
            a = run_generator(ROOT, Path(td) / "a.html")
            b = run_generator(ROOT, Path(td) / "b.html")
        self.assertIn('id="generated-at"', a, "the marked clock line is the contract")
        self.assertEqual(strip_generated_line(a), strip_generated_line(b),
                         "output varies on an unchanged tree beyond the generated-at line")


class TheRowsDriveTheRender(unittest.TestCase):

    def test_every_task_number_in_the_canonical_list_renders(self):
        text = (ROOT / "PROJECT-TASKS.md").read_text()
        ids = [m.group(2) for m in TASK_ROW.finditer(text)]
        # The floor used to be a literal 20, which rotted the moment Garrett consolidated
        # forty-three tasks into five on 2026-08-20 -- a legitimate list became a failing
        # test. Count the marker lines independently instead: "extraction went blind" means
        # the regex found fewer rows than there are rows, and that is true at any list length.
        marker_lines = [l for l in text.splitlines()
                        if l[:1] in "\u25fc\u25fb\u25b6\u2298" and l[1:2] == " "]
        self.assertTrue(marker_lines, "no task markers in the canonical list at all")
        self.assertEqual(len(ids), len(marker_lines),
                         "task-row extraction went blind: "
                         f"{len(marker_lines)} marker lines but {len(ids)} rows parsed")
        with tempfile.TemporaryDirectory() as td:
            page = run_generator(ROOT, Path(td) / "p.html")
        for tid in ids:
            self.assertIn(f">{tid}<", page.replace("&#x27;", "'"),
                          f"task {tid} is in PROJECT-TASKS.md but not on the page")
        # The two sections the page is, and the ONLY two. Each name that used to be here --
        # "Phase tracker", "Request ledger", "Audit surface", "Suites" -- was a separate panel
        # listing work in its own vocabulary, and every one of them was removed on Garrett's
        # instruction: "i dont need a bullshit list at the top and a full list at the bottom i
        # just need the full list in one location". Asserting they are ABSENT is the same
        # contract inverted, and it is the one that stops them growing back.
        for anchor in ("Tasks — PROJECT-TASKS.md", "Assignments — INTAKE.md"):
            self.assertIn(anchor, page)
        for gone in ("Phase tracker", "Request ledger", "Audit surface"):
            self.assertNotIn(gone, page,
                             f"the {gone!r} panel is back — one list, in one location")
        self.assertIn('http-equiv="refresh"', page)

    def test_deleting_a_row_from_a_temp_copy_deletes_it_from_the_page(self):
        """The mutation check: one row removed from a copied tree → it goes, its neighbour stays.

        This is what proves the table is parsed, not pasted: a generator that embedded a
        stale snapshot of the task list would keep rendering the deleted row and go green
        above while lying here.

        The victim and the control are read out of the fixture rather than named. They were
        hard-coded as #24 and #23 and both numbers left the list in the 2026-08-20
        consolidation, so the test failed for a reason that had nothing to do with the
        generator. A mutation test that names its own fixture rows can only be broken by the
        thing it is testing.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            copy_tree(root)
            tasks = root / "PROJECT-TASKS.md"
            lines = tasks.read_text().splitlines()
            rows = [(i, m.group(2)) for i, l in enumerate(lines)
                    if (m := TASK_ROW.match(l))]
            self.assertGreaterEqual(len(rows), 2,
                                    "need two rows to delete one and keep the other")
            (victim_i, victim), (_, control) = rows[0], rows[1]
            kept = [l for i, l in enumerate(lines) if i != victim_i]
            self.assertNotIn(victim, [m.group(2) for l in kept
                                      if (m := TASK_ROW.match(l))],
                             f"the {victim} row survived the deletion; fixture is wrong")
            tasks.write_text("\n".join(kept) + "\n")
            page = run_generator(root, root / "p.html")
        self.assertNotIn(f">{victim}<", page,
                         "a deleted row still renders — the table is static")
        self.assertIn(f">{control}<", page,
                      "the control row vanished with it — over-deletion")

    def test_missing_ledger_and_missing_git_degrade_to_labels(self):
        """The worst day still renders. Missing sources are a label, never a traceback."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            copy_tree(root, skip="GARRETT-REQUESTS.md")
            run_intake(root)
            page = run_generator(root, root / "p.html")
        self.assertIn("no-git", page, "a temp root is not a repo; the header must say so")
        self.assertIn("Assignments — INTAKE.md", page,
                      "the section vanished with its ledger; it has two other sources")
        self.assertNotIn(">A-R", page,
                         "request assignments rendered from a ledger that is not there")

    def test_no_intake_file_says_so_rather_than_rendering_an_empty_section(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            copy_tree(root)
            page = run_generator(root, root / "p.html")   # deliberately no run_intake
        self.assertIn("INTAKE.md not present", page)
        self.assertIn("build_intake.py", page, "the note must name the command that fixes it")


LEDGER = """# GARRETT-REQUESTS.md

## R-1 — a held one
status: {held}

## R-2 — a captured one
status: captured — ordinary open work

## R-3 — a superseded one
status: superseded(the ground moved under it)

## R-4 — an adopted one
status: adopted

## R-5 — a done one
status: done(abc1234)
"""


def run_raw(root: Path, out: Path):
    return subprocess.run(
        [sys.executable, str(GENERATOR), "--root", str(root), "--out", str(out)],
        capture_output=True, text=True, timeout=60)


#: The real audit surface is skipped in every ledger fixture below. INTAKE.md merges three
#: sources, so leaving it in makes the barrier count 13 audit findings plus whatever the
#: ledger contributes — and an assertion about ledger behaviour that moves whenever somebody
#: edits an unrelated file is an assertion that will be deleted rather than fixed.
LEDGER_FIXTURE_SKIP = ("GARRETT-REQUESTS.md", "AUDIT-SURFACE-2026-08-19.md")


def render_ledger(td: str, held_status: str) -> str:
    root = Path(td)
    copy_tree(root, skip=LEDGER_FIXTURE_SKIP)
    (root / "GARRETT-REQUESTS.md").write_text(LEDGER.format(held=held_status))
    run_intake(root)
    return run_generator(root, root / "p.html")


def barrier_count(page: str) -> int:
    # `barriers?` because the page agrees in number and says "1 barrier". This helper pinned the
    # plural spelling and three tests went red the moment the page read correctly -- a check on
    # wording standing in for a check on the number.
    m = re.search(r"<strong>(\d+)</strong> barriers?\b", page)
    if not m:
        raise AssertionError("the page states no barrier count")
    return int(m.group(1))


def row_of(page: str, aid: str) -> str:
    m = re.search(rf'<tr[^>]*id="row-{re.escape(aid)}">(.*?)</tr>', page, re.S)
    return m.group(1) if m else ""


class EveryLedgerEntryIsDoneOrTaskOrIntake(unittest.TestCase):
    """Garrett, 2026-08-20: *"they are either done, task or intake"* — a completeness claim.

    Every entry in the ledger is in exactly one of three states and none is in none of them.
    That is stronger than it sounds, and it is what this class exists to hold: the rule it
    replaced named four "open" statuses and exempted two others from needing a task, and
    between them those two defensible-looking rules left 19 entries in no state at all —
    not finished, not carried by any task, and not on the intake list either.

    This class was `HeldEntriesRenderAsFrozenAndNeverAsDone`, asserting on a `[FROZEN]` marker
    and `Un-actioned (N)` counts in a ledger panel. The panel went when the three intake panels
    became one Assignments table; the marker went when Garrett rejected the state behind it —
    *"i never gave you instruction of 'frozen' items"*. He had defined two actions, tick and
    delete, and a page state that accepts neither takes the decision off him.
    """

    def test_a_held_entry_is_an_ordinary_assignment(self):
        with tempfile.TemporaryDirectory() as td:
            page = render_ledger(td, "held(2026-08-20, awaiting re-scope)")
        row = row_of(page, "A-R1")
        self.assertTrue(row, "the held entry is in no state at all — the gap is back")
        self.assertIn("<button", row,
                      "a held entry carries no control, so it can be neither ticked nor "
                      "dropped; that is the invented third state, back again")
        self.assertNotIn("FROZEN", page, "the rejected state name is back on the page")

    def test_adopted_and_superseded_split_correctly(self):
        """`adopted` with no pointer is intake — the word claims the rule landed somewhere and
        does not say where, which is an assertion nobody can check. `superseded` is done: the
        work did not vanish, it moved to the entry that replaced it.
        """
        with tempfile.TemporaryDirectory() as td:
            page = render_ledger(td, "held(2026-08-20, awaiting re-scope)")
        self.assertTrue(row_of(page, "A-R4"),
                        "a bare `adopted` closed the entry — that is the word being trusted "
                        "instead of checked, and it is how 15 entries went missing")
        self.assertEqual(row_of(page, "A-R3"), "",
                         "a superseded entry is closed — its successor holds the work")
        self.assertEqual(row_of(page, "A-R5"), "", "a done entry is not an assignment")

    def test_an_adopted_rule_closes_once_it_names_where_it_lives(self):
        """The mutation that separates the pointer rule from a bucket rule.

        Only R-4's status changes, and only by gaining a path. If the entry still renders as an
        assignment the pointer is being ignored; if the bare form in the test above ALSO closed,
        the bucket is doing the work and the pointer is decoration.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            copy_tree(root, skip=LEDGER_FIXTURE_SKIP)
            (root / "GARRETT-REQUESTS.md").write_text(
                LEDGER.format(held="done(deadbee)").replace(
                    "status: adopted",
                    "status: adopted — recorded in .claude/CLAUDE.md"))
            run_intake(root)
            page = run_generator(root, root / "p.html")
        self.assertEqual(row_of(page, "A-R4"), "",
                         "an adopted rule that names the file it lives in is a checkable "
                         "fact about the repo, not an open decision")
        self.assertEqual(barrier_count(page), 1,
                         "R-2 is the only barrier left once the adopted rule is recorded")

    def test_a_pointer_at_the_very_end_of_the_status_line_still_counts(self):
        """The concatenation bug, pinned by position rather than by content.

        `status` and `body` were joined with a bare `+`, so the last word of the status ran
        into the first word of the body with no separator. `RULE_POINTER` ends in `\\b`, so a
        filename sitting at the end of the status line — the most natural place to write one —
        was the one place it could not be seen. R-111 read `recorded durably in GUARDRAILS.md`
        and rendered as intake anyway. The fixture puts the path last on purpose; move it into
        the middle of the sentence and this test stops testing anything.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            copy_tree(root, skip=LEDGER_FIXTURE_SKIP)
            (root / "GARRETT-REQUESTS.md").write_text(
                LEDGER.format(held="done(deadbee)").replace(
                    "## R-4 — an adopted one\nstatus: adopted\n",
                    "## R-4 — an adopted one\n"
                    "status: adopted — recorded in GUARDRAILS.md\n"
                    "trailing body text that follows the status line\n"))
            run_intake(root)
            page = run_generator(root, root / "p.html")
        self.assertEqual(row_of(page, "A-R4"), "",
                         "the pointer was at the end of the status line, which is where the "
                         "bare `+` hid it")

    def test_the_three_states_are_exhaustive(self):
        """The completeness claim itself, asserted against the parser rather than the page."""
        sys.path.insert(0, str(ROOT / "tools"))
        from build_progress import parse_requests
        entries = parse_requests((ROOT / "GARRETT-REQUESTS.md").read_text())
        self.assertGreater(len(entries), 100, "ledger parse went blind")
        for e in entries:
            self.assertIn(e["state"], ("done", "task", "intake"),
                          f"{e['id']} is in no state: status {e['status']!r}")
        counted = sum(len([e for e in entries if e["state"] == s])
                      for s in ("done", "task", "intake"))
        self.assertEqual(counted, len(entries), "an entry is in two states at once")

    def test_an_entry_that_names_a_task_is_not_also_an_assignment(self):
        """The anti-duplication rule: carried work lives on the task list, once."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            copy_tree(root, skip=LEDGER_FIXTURE_SKIP)
            (root / "GARRETT-REQUESTS.md").write_text(
                LEDGER.format(held="captured — carried by #41"))
            run_intake(root)
            page = run_generator(root, root / "p.html")
        self.assertEqual(row_of(page, "A-R1"), "",
                         "an entry naming #41 is on the task list; listing it here too is "
                         "the duplicate-listing failure the one-list rule exists to end")

    def test_a_dropped_assignment_leaves_the_list_and_lands_in_the_archive(self):
        """Garrett's delete. `[-]` removes the entry from the list and from the page.

        REWRITTEN 2026-08-20. This test used to assert the opposite -- that a dropped entry
        stayed on the page struck through -- on the reasoning that a decision leaving no trace
        is indistinguishable from an item that was never recorded. Garrett overrode it by
        reporting the behaviour as a bug: *"i click drop and it doesnt remove from intake
        list"*. He is right about the surface, and the original concern is still right about
        the evidence, so the trace moved rather than disappearing: the entry is asserted into
        `review/RETIRED-ASSIGNMENTS.md` below, which is the dedicated folder he asked for.

        Both halves are asserted on purpose. Off-the-page alone would be deletion; in-the-file
        alone would be the bug he reported.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # The audit surface has to go too, or its thirteen findings arrive as barriers and
            # the count this test reads is measuring the real repo instead of the fixture.
            copy_tree(root, skip=LEDGER_FIXTURE_SKIP)
            (root / "GARRETT-REQUESTS.md").write_text(
                LEDGER.format(held="done(deadbee)"))
            run_intake(root)
            intake = root / "INTAKE.md"
            before = barrier_count(run_generator(root, root / "a.html"))
            intake.write_text(intake.read_text().replace(
                "## A-R2 [request] — a captured one\n[ ]",
                "## A-R2 [request] — a captured one\n[-]"))
            run_intake(root)                     # the drop must survive regeneration
            page = run_generator(root, root / "b.html")
            after = intake.read_text()
            archive = (root / "review" / "RETIRED-ASSIGNMENTS.md")
            archived = archive.read_text() if archive.exists() else ""
            # A second regeneration, because the failure mode this guards is a delayed one:
            # the archive used to be rebuilt from INTAKE.md alone, so an entry that had left
            # the list survived exactly one more run before the rewrite dropped it.
            run_intake(root)
            still = archive.read_text() if archive.exists() else ""
        # Two, not one: R-2 is captured, and R-4's bare `adopted` names no file, so it is
        # intake as well. Both are barriers; the drop below is applied to R-2 only.
        self.assertEqual(before, 2, "fixture: R-2 and R-4 are the barriers before the drop")
        self.assertEqual(barrier_count(page), 1,
                         "dropping R-2 must take exactly one off the count — R-4 is untouched "
                         "and must stay on it, or delete is removing more than it was aimed at")
        self.assertEqual(row_of(page, "A-R2"), "",
                         "a dropped entry must leave the page — Garrett clicked Drop and the "
                         "row stayed, which reads as a button that does not work")
        self.assertNotIn("## A-R2 ", after,
                         "a dropped entry must leave INTAKE.md, not merely stop counting")
        self.assertIn("## A-R2 ", archived,
                      "dropping must ARCHIVE, never delete — this is the only copy of "
                      "anything Garrett typed on the entry")
        self.assertIn("## A-R2 ", still,
                      "the archive must survive the next regeneration; it used to be rebuilt "
                      "from a source that no longer held the entry, so it ate itself")

    def test_an_unknown_status_fails_the_build_instead_of_rendering(self):
        """The silent fallback this replaces is exactly how a frozen item read as available."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            copy_tree(root, skip="GARRETT-REQUESTS.md")
            (root / "GARRETT-REQUESTS.md").write_text(
                LEDGER.format(held="marinating — a status nobody declared"))
            r = run_raw(root, root / "p.html")
        self.assertNotEqual(r.returncode, 0, "an undeclared status rendered anyway")
        self.assertIn("STATUS_BUCKETS", r.stderr, "the failure must name the fix")


if __name__ == "__main__":
    unittest.main()


def run_intake_stderr(root: Path) -> str:
    """build_intake.py's warnings, for the checks that report rather than fail.

    Separate from `run_intake` because that helper treats stderr as a failure report and
    discards it on success. `check_task_pointers` warns on a zero exit by design -- see its
    docstring -- so the only way to assert on it is to keep stderr from a successful run.
    """
    r = subprocess.run([sys.executable, str(INTAKE_GENERATOR), "--root", str(root)],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise AssertionError(f"build_intake failed rc={r.returncode}\n{r.stderr}")
    return r.stderr


class EveryTaskPointerResolves(unittest.TestCase):
    """`task: #NN` must name exactly one task, and be reported when it does not.

    The gap this closes: `TASK_REF` only ever asked whether a reference was PRESENT. Both the
    barrier count in build_intake.py and `covered` in build_progress.py read "has a `task:`
    line" as "is being carried", so a pointer at a task number that does not exist renders as
    carried work -- a barrier wearing a task's clothes, invisible exactly where the count
    claims to be complete.

    Not hypothetical: `7fcc96d` numbered 58 assignments and reused #60-#63, which had already
    been spent on tasks archived in the same window, and nothing reported it.
    """

    TASKS = ("# tasks\n\n"
             "◻ #1 — first thing\n"
             "        owner: coder\n\n"
             "◻ #2 — second thing\n"
             "        owner: coder\n\n")

    INTAKE = ("# INTAKE.md\n\n---\n\n**Requests**\n\n"
              "## A-R1 [request] — an entry that points somewhere\n"
              "[ ]\n"
              "from: GARRETT-REQUESTS.md R-1\n"
              "owner: coder\n"
              "task: {ref}\n\n")

    def _root(self, td: str, tasks: str, ref: str) -> Path:
        root = Path(td)
        (root / "PROJECT-TASKS.md").write_text(tasks)
        (root / "INTAKE.md").write_text(self.INTAKE.format(ref=ref))
        return root

    def test_a_pointer_at_a_task_that_exists_is_silent(self):
        """The control. Without this the test below passes on a check that always warns."""
        with tempfile.TemporaryDirectory() as td:
            err = run_intake_stderr(self._root(td, self.TASKS, "#1 — first thing"))
        self.assertNotIn("WARNING", err,
                         "a pointer at a task that exists must not be reported — a check that "
                         "warns on the healthy case gets muted and then catches nothing")

    def test_a_pointer_at_a_task_in_neither_file_is_reported(self):
        with tempfile.TemporaryDirectory() as td:
            err = run_intake_stderr(self._root(td, self.TASKS, "#99 — never written"))
        self.assertIn("A-R1", err, "the assignment carrying the dead pointer must be named")
        self.assertIn("#99", err, "the number that does not resolve must be named")

    def test_a_number_used_by_two_tasks_is_reported(self):
        """Number reuse. The pointer resolves two ways, so following it is a coin toss."""
        reused = self.TASKS + "◻ #1 — a second thing wearing the same number\n        owner: coder\n\n"
        with tempfile.TemporaryDirectory() as td:
            err = run_intake_stderr(self._root(td, reused, "#1 — first thing"))
        self.assertIn("#1", err, "the duplicated number must be named")
        self.assertIn("resolves 2 ways", err,
                      "the assignment must be told its pointer is ambiguous, not merely that "
                      "some task number somewhere is duplicated")

    def test_a_closed_task_still_counts_as_resolved(self):
        """An assignment whose task is finished is a normal state, not a barrier."""
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td, self.TASKS, "#7 — done and filed")
            (root / "review").mkdir()
            (root / "review" / "CLOSED-TASKS.md").write_text(
                "# closed\n\n◼ #7 — done and filed\n        owner: coder\n\n")
            err = run_intake_stderr(root)
        self.assertNotIn("#7", err,
                         "a pointer at a CLOSED task is resolved — reporting it would push "
                         "every finished assignment back onto the barrier list")


    def test_a_pointer_at_a_folded_task_resolves_through_the_folds_line(self):
        """The 2026-08-20 consolidation, and the 27 warnings it produced for a day.

        58 tasks were folded into #73-#77 and the mapping was written on the surviving tasks'
        own `Folds #NN #NN` lines -- the right place for it, since a fold is a fact about the
        task that did the folding. Nothing read it, so 27 assignments pointed at numbers that
        no longer existed and every run printed a warning naming each one.

        Those 27 were carried all along; the warnings were an unread mapping, not 27 hidden
        barriers. Which is exactly why this needs a test either way: 27 lines of noise on
        every run is how the two genuine warnings underneath them stop being read.
        """
        tasks = ("# tasks\n\n"
                 "◻ #10 — the surviving task\n"
                 "        owner: coder\n"
                 "        Folds #3 #4 #5. Read those blocks before working any part.\n\n")
        with tempfile.TemporaryDirectory() as td:
            err = run_intake_stderr(self._root(td, tasks, "#4 — folded away"))
        self.assertNotIn("WARNING", err,
                         "a pointer at a folded task is carried by the task that folded it; "
                         "warning on it would report 27 false barriers instead of reading the "
                         "mapping that is already on disk")

    def test_a_pointer_at_nothing_is_still_reported_when_folds_lines_exist(self):
        """The control for the above. A resolver that swallows everything catches nothing."""
        tasks = ("# tasks\n\n"
                 "◻ #10 — the surviving task\n"
                 "        owner: coder\n"
                 "        Folds #3 #4 #5.\n\n")
        with tempfile.TemporaryDirectory() as td:
            err = run_intake_stderr(self._root(td, tasks, "#88 — folded by nobody"))
        self.assertIn("#88", err)
        self.assertIn("`Folds` line", err,
                      "the warning must say the fold map was consulted, or the next reader "
                      "re-derives that themselves")


class AHandWrappedCommentRendersAsOneComment(unittest.TestCase):
    """`note:` on every line is a storage rule. It had leaked into the render.

    A multi-line comment must keep the `note:` prefix on every line, because an unindented
    continuation ends the task block for `archive_tasks.py` and silently truncates the task.
    The page read each of those lines as a separate comment, so #73's one hand-wrapped
    paragraph rendered as fifteen bullet points of sentence fragments -- on the artefact whose
    whole job is that the next agent can pick the project up without missing a beat.
    """

    TASKS = ("# tasks\n\n"
             "◻ #1 — a task with a wrapped comment\n"
             "        owner: coder\n"
             "        note: 2026-08-20 garrett — this sentence was hand-wrapped across\n"
             "        note: three physical lines and is one comment.\n"
             "        note: 2026-08-21 garrett — and this is a second, separate one.\n\n")

    def _page(self, td: str, tasks: str) -> str:
        root = Path(td)
        (root / "PROJECT-TASKS.md").write_text(tasks)
        return run_generator(root, root / "out.html")

    def test_continuation_lines_join_the_comment_above_them(self):
        with tempfile.TemporaryDirectory() as td:
            page = self._page(td, self.TASKS)
        items = re.findall(r"<li>(.*?)</li>", page, re.S)
        thread = [i for i in items if "garrett" in i]
        self.assertEqual(len(thread), 2,
                         f"two dated comments must render as two, not five: {thread}")
        self.assertIn("across three physical lines", " ".join(thread[0].split()),
                      "the continuation must be joined to the comment it continues, with a "
                      "space — concatenating without one welds the last word to the first")

    def test_an_undated_comment_is_not_dropped(self):
        """Notes predate the comment box and not all of them carry a date.

        Losing one to make the grouping tidy is the only outcome worse than bad line breaks:
        the file is append-only precisely so that nothing anybody typed can disappear.
        """
        tasks = ("# tasks\n\n"
                 "◻ #1 — a task whose first note has no date\n"
                 "        owner: coder\n"
                 "        note: an older comment with no date on it\n"
                 "        note: 2026-08-21 garrett — a dated one after it\n\n")
        with tempfile.TemporaryDirectory() as td:
            page = self._page(td, tasks)
        self.assertIn("an older comment with no date on it", page)
        self.assertIn("a dated one after it", page)


class HandTypedFieldsSurviveRegeneration(unittest.TestCase):
    """`blocked:` was parsed and never written back, so every reason typed on it vanished.

    Fourth occurrence in this repo of a generator eating a field it can read. The visible
    symptom was Garrett reading the page: *"reason not recorded this gave me no information;
    fix it to provide information"* -- the why-column had nothing to show because anything
    put there survived until the next two-minute rebuild and no further.

    `brief:` and `edit:` were already round-tripping and are asserted here beside it, because
    the bug is about the parse table and the emitter drifting apart, and a test that pins only
    the field that broke does not notice the next one.
    """

    LEDGER = ("# GARRETT-REQUESTS.md\n\n"
              "## R-1 — a request nobody has ticked\n"
              "status: captured\n"
              "blocked: waiting on a tick, nothing technical in the way\n"
              "brief: the engine half exists; the interactive half does not\n"
              "edit: INTAKE.md — tick the box on A-R1\n"
              "Some prose about the request.\n\n")

    def _root(self, td: str) -> Path:
        root = Path(td)
        (root / "GARRETT-REQUESTS.md").write_text(self.LEDGER)
        (root / "PROJECT-TASKS.md").write_text("# tasks\n\n")
        return root

    def test_the_ledgers_reason_reaches_intake_and_survives_a_second_run(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            run_intake(root)
            first = (root / "INTAKE.md").read_text()
            for field, why in (("blocked:", "the why-column's reason"),
                               ("brief:", "why it is not a task yet"),
                               ("edit:", "where to go to change that")):
                self.assertIn(field, first, f"{why} never reached INTAKE.md at all")
            self.assertIn("waiting on a tick", first)
            # The bug was in the SECOND run: parsed on the way in, dropped on the way out.
            run_intake(root)
            second = (root / "INTAKE.md").read_text()
            self.assertEqual(first, second,
                             "regeneration changed the file, which is the bug: a field the "
                             "parser reads and the emitter omits is deleted one run later")

    def test_the_page_shows_the_reason_instead_of_reason_not_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            run_intake(root)
            page = run_generator(root, root / "out.html")
        self.assertIn("waiting on a tick", page,
                      "the barrier row must carry the reason from the ledger")
        self.assertNotIn("reason not recorded", page,
                         "a row whose source states a reason must not render the warning — "
                         "that flag is for a genuinely unrecorded reason, and printing it "
                         "over a recorded one is what made the page worthless to read")


class PromotionIsAnExitFromTheIntakeSurface(unittest.TestCase):
    """An assignment that became a task leaves the list. Garrett: *"push intake.md to task"*.

    The page he was reading said "28 assignments &middot; 0 barriers &middot; 28 promoted to
    tasks" and then listed all 28 anyway, each with a Ready and a Drop button. Every one was
    already on the task list. INTAKE.md calls itself "the queue in front of the work", and a
    queue that everything passes through and nothing ever leaves is not a queue -- it is a
    second copy of the task list that asks him to triage work already under way.

    Promotion is the same exit Drop already had: off the list, into the archive, nothing lost.
    """

    def _promote(self, root: Path, aid: str, task: str) -> None:
        intake = root / "INTAKE.md"
        intake.write_text(intake.read_text().replace(
            f"## {aid} [request] — a captured one\n[ ]",
            f"## {aid} [request] — a captured one\n[ ]\ntask: {task}"))

    def test_a_promoted_entry_leaves_the_list_and_keeps_its_task_number(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            copy_tree(root, skip=LEDGER_FIXTURE_SKIP)
            (root / "GARRETT-REQUESTS.md").write_text(LEDGER.format(held="done(deadbee)"))
            run_intake(root)
            before = barrier_count(run_generator(root, root / "a.html"))
            self._promote(root, "A-R2", "#41 — the one carrying it")
            run_intake(root)
            page = run_generator(root, root / "b.html")
            intake_after = (root / "INTAKE.md").read_text()
            archive = root / "review" / "RETIRED-ASSIGNMENTS.md"
            archived = archive.read_text() if archive.exists() else ""
            # Twice more, because the failure this guards is delayed: the archive is rebuilt
            # from a source that no longer holds the entry, and it used to eat itself that way.
            run_intake(root)
            run_intake(root)
            still = archive.read_text() if archive.exists() else ""
            back = (root / "INTAKE.md").read_text()

        self.assertEqual(before, 2, "fixture: R-2 and R-4 are the barriers before promotion")
        self.assertNotIn("## A-R2 ", intake_after,
                         "an entry carried by a task must leave INTAKE.md — leaving it on the "
                         "list is what put 28 already-tasked rows in front of Garrett")
        self.assertEqual(row_of(page, "A-R2"), "",
                         "a promoted entry must leave the page too, or the buttons still ask "
                         "him to triage work that is already under way")
        self.assertEqual(barrier_count(page), 1,
                         "promoting R-2 must take exactly one off the barrier count and leave "
                         "R-4, which nothing carries, still on it")
        self.assertIn("#41", archived,
                      "the archive must record WHERE it went; without the task number this is "
                      "a deletion with a filing cabinet around it")
        self.assertIn("#41", still, "the archive must survive later runs, not eat itself")
        self.assertNotIn("## A-R2 ", back,
                         "a promoted entry must not reappear on the list — its source still "
                         "lists it, so only reading the archive back keeps it gone")

    def test_an_empty_list_reads_as_finished_not_as_missing(self):
        """Empty is the healthy end state and must not render as the never-generated one."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            copy_tree(root, skip=LEDGER_FIXTURE_SKIP)
            # Every entry done: the ledger contributes no assignments at all.
            (root / "GARRETT-REQUESTS.md").write_text(
                "# GARRETT-REQUESTS.md\n\n## R-1 — a done one\nstatus: done(abc1234)\n")
            run_intake(root)
            page = run_generator(root, root / "p.html")
        self.assertIn("Nothing waiting", page,
                      "an empty list must say it is finished")
        self.assertNotIn("INTAKE.md not present", page,
                         "the healthy end state must not be reported as a missing file — they "
                         "are different conditions and one of them needs somebody to act")


class AResolveIsEvidenceNotAVerdict(unittest.TestCase):
    """A `resolve:` line may hold a task open. It may not close one on its own.

    `tools/build_progress.py` used to read the disk for a `resolve: OLD -> NEW` line and
    assign the answer straight to `t["state"]`. Because the percentage rule underneath it can
    only ever *set* `done` and never withhold it, a satisfied move closed the task no matter
    how many `check:` lines were still red.

    That is not hypothetical. On 2026-08-21 a `git mv scripts/comfyui.sh
    scripts/symoneural-ui.sh` -- one item out of five on task #74 -- satisfied that task's
    single `resolve:` line, and `archive_tasks.py` moved all 330 lines of it to
    `review/CLOSED-TASKS.md` two minutes later with the verdict "resolved against the
    filesystem". Eleven of its forty-six checks were failing at the time, including
    `ngrep /studio/comfy -- backend/api.py` against three live occurrences.

    CLAUDE.md names this species directly: "Choose checks where 100% genuinely means done --
    a check that can pass without the work being finished is worse than no check, since it
    will archive the task." A resolve that *overrides* checks is the strongest possible form
    of that bug, because it does not merely pass vacuously, it silences everything else.
    """

    def _parse(self, block: str, root: Path):
        sys.path.insert(0, str(ROOT / "tools"))
        try:
            import build_progress
        finally:
            sys.path.pop(0)
        return build_progress.parse_tasks(block, root)

    def test_a_satisfied_move_does_not_close_a_task_with_a_failing_check(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "new.sh").write_text("moved\n")     # resolve: destination arrived
            # `old.sh` deliberately absent -> the move reads as done on the disk.
            block = ("◻ #1 — a move plus an unmet requirement\n"
                     "        resolve: old.sh -> new.sh\n"
                     "        check: exists never-written.md\n")
            t = self._parse(block, root)[0]

            self.assertTrue(t["from_disk"],
                            "the row still answers from the filesystem; only the verdict moved")
            self.assertEqual(
                [ok for _, ok in t["checks"]], [True, True, False],
                "expected the two derived move checks green and the declared check red")
            self.assertLess(t["pct"], 100)
            self.assertNotEqual(
                t["state"], "done",
                "a satisfied `resolve:` closed a task whose `check:` line is red -- this is "
                "the #74 archive bug, and archive_tasks.py will move the block on the next "
                "two-minute tick")

    def test_a_resolve_alone_still_closes_a_task_that_declares_nothing_else(self):
        """The fix must not break the case the feature exists for."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "new.sh").write_text("moved\n")
            block = "◻ #2 — a plain move\n        resolve: old.sh -> new.sh\n"
            t = self._parse(block, root)[0]
            self.assertEqual(t["pct"], 100)
            self.assertEqual(t["state"], "done")

    def test_a_half_done_move_reads_as_in_progress_not_as_pending(self):
        """`disk_state` is the only thing that can see a move that has started. Keeping its
        answer when it is NOT `done` is why the fix demotes rather than deletes it."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "old.sh").write_text("still here\n")
            (root / "new.sh").write_text("arrived\n")
            block = "◻ #3 — a half-done move\n        resolve: old.sh -> new.sh\n"
            t = self._parse(block, root)[0]
            self.assertEqual(t["state"], "in progress")
            self.assertEqual(t["pct"], 50, "destination arrived, source did not leave")
