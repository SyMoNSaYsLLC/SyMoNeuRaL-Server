#!/usr/bin/env python3
"""Render run/progress.html — the one page Garrett bookmarks to see where everything stands.

Sources, all read-only:
  * PROJECT-TASKS.md          — the canonical task list (marker chars are the status: ◼ done,
                              ◻ pending, ▶ in progress) and the "## Suite readings (latest)"
                              section this script defines the shape of;
  * GARRETT-REQUESTS.md     — the request ledger (mode 600, never committed; the page renders
                              counts and titles, never the file itself);
  * AUDIT-SURFACE-2026-08-19.md — item headings carry their status token after "N.";
  * GARRETT-INBOX.md        — only for whether "## v3 MILESTONE" exists at a line start;
  * git rev-parse           — HEAD short SHA, "no-git" when the root is not a repository
                              (a fresh clone's tarball, or the test suite's tmp roots).

The output is one self-contained file: inline CSS, no external fetches, file:// friendly,
<meta refresh> every 60 s. Deterministic by construction — the ONLY clock read lands on the
single line marked id="generated-at", which the regression test strips before comparing runs.
Missing sources degrade to a labelled note, never a crash: the page must render on the worst
day, because that is the day Garrett looks at it.

Discipline (from the standing rule): every update to PROJECT-TASKS.md, GARRETT-REQUESTS.md or
the audit surface re-runs this script in the same step. The page is never more than one
state-change stale.
"""
from __future__ import annotations

import argparse
import html
import re
import subprocess
import time
from pathlib import Path

TASK_ROW = re.compile(r"^([◼◻▶⊘]) ((?:\(unnumbered[^)]*\))|#\d+) — (.+)$")
SHA_IN_TEXT = re.compile(r"`([0-9a-f]{7,40})`")
SUITE_ROW = re.compile(r"^- ([^:]+): (.+?) @ `([0-9a-f]{7,40})`$")
AUDIT_HEAD = re.compile(r"^#{2,3}\s*(\d+)\.\s+(.*)$")
REQUEST_HEAD = re.compile(r"^## (R-\d+) — (.+)$")
#: A ledger entry cites the task that carries it out as `#41`. Two digits minimum would be
#: wrong -- numbering starts at 11 but the next block could be #9 if one is ever reused.
#:
#: **Any `#NN` anywhere in an entry's prose reads as "carried".** That is deliberate -- the
#: citation is usually in a sentence, not in a field -- but it means a `#NN` written for any
#: other reason silently takes the entry off the intake list, which is the one surface that
#: exists to stop work going missing. R-171 was filed with `for #97` in its `source:` line,
#: meaning "found while working on 97", and vanished. It was found by looking for it, not by
#: any warning. If an entry needs to mention a task without claiming to be carried by it,
#: write the number without the hash.
TASK_REF = re.compile(r"#\d+")

#: How deep the request ledger should ever get. Garrett: "our request ledger should hardly
#: ever exceed 3 or 4 items". Not a limit that rejects anything -- a health reading. The
#: ledger is the inbox between "Garrett said it" and "it is a task"; if it is deep, the drain
#: has stopped.
LEDGER_TARGET = 4

QUESTION_HEAD = re.compile(r"^## (Q\d+) — (.+)$")

MARKER_STATE = {"◼": "done", "◻": "pending", "▶": "in progress", "⊘": "cancelled"}

#: A task row may carry a `resolve: OLD -> NEW` line in its indented detail block. When it
#: does, the marker in the file is IGNORED and the state is read off the filesystem instead.
#:
#: This is what is left of the phase tracker, and it is the half that was worth keeping.
#: The tracker itself was deleted 2026-08-20 on Garrett's instruction -- "this phase tracker
#: is bullshit fix it or get rid of it and just put task in the task" -- and he was right for
#: a reason worth writing down: every one of its Phase 2 steps was an ALIAS of a task that
#: already existed (2.1 was #31, 2.2 was #26, ... 2.10 was #24), so the page rendered the same
#: ten items twice and the working agreements forbid a second state document. The steps that
#: were NOT aliases are now tasks #50-#55 and #38/#46/#48/#49.
#:
#: What the tracker did better than the task list was resolve a folder move against the disk
#: rather than against a marker somebody has to remember to flip. That property now belongs to
#: the task row itself.
RESOLVE = re.compile(r"^\s*resolve:\s*(\S*)\s*->\s*(\S+)\s*$")

#: A task row may also declare `check:` lines — one predicate each, all answerable from the
#: filesystem in microseconds. The task's completion percentage is passed/declared.
#:
#: Garrett asked for "an automated status % on each coder-task". The honest way to compute one
#: is to make the task say what "done" consists of and then count how much of that is true.
#: The dishonest way is to estimate, and the working agreements forbid it outright: no
#: decorative status indicators, every figure labelled measured or projected. A percentage
#: nobody can check is the same dishonest pixel as a fake activity LED.
#:
#: So a task with NO checks renders "—", never 0%. An unmeasured task is not an unstarted
#: task, and collapsing those two would make the page lie in the direction of pessimism —
#: which is still lying.
#:
#:   check: exists <path>            true when the repo-relative path is present
#:   check: absent <path>            true when it is not
#:   check: grep <pattern> -- <path> true when the pattern occurs in that file
#:   check: ngrep <pattern> -- <path> true when it does NOT — "this text is gone" is half
#:                                    the definition of done for every rename task
#:   check: maxcount <n> <pattern> -- <path>  true when the pattern occurs at most n times
CHECK = re.compile(r"^\s*check:\s*(exists|absent|grep|ngrep|maxcount)\s+(.+?)\s*$")

#: `owner: coder` | `owner: garrett`, on a detail line. Garrett, 2026-08-20: *"rename Task -
#: Coder task to project task and then label the task coder or garrett"*. The old filename
#: asserted a single owner for a list that has always held both, which is how an item only
#: Garrett can do ends up reading as unstarted coder work.
#:
#: A detail line rather than the glyph row, so `TASK_ROW` is unchanged and the label sits
#: beside `resolve:` and `check:` in the same syntax. On the row is a defensible alternative
#: and it is one sed away if that reads better.
#:
#: Unlabelled means `coder`. That default is the safe direction: it claims work for me rather
#: than parking it on Garrett, and the standing authority rule is already FIX, not FILE.
OWNER = re.compile(r"^\s*owner:\s*(coder|garrett)\s*$", re.M | re.I)

#: `[ ]` or `[x]` on an indented detail line — the review handoff for a Garrett-owned task.
#: Garrett: *"the ones assigned to me give me a checkbox that once i update the file with the
#: answer i can check it and you will know to review"*.
#:
#: Ticking it sets the state to `ready for review`, which is deliberately NOT `done`: see
#: parse_tasks. It must stay indented — `tools/lib/archive_tasks.py` ends a task block at any
#: non-blank column-zero line, so an unindented checkbox would truncate its own task.
CHECKBOX = re.compile(r"^\s*\[([ xX])\]\s", re.M)

#: `note: <text>` on an indented detail line — a comment on a task, from whoever is reading it.
#: Garrett: *"and i need a comments box for the the project tasks"*.
#:
#: Deliberately the dumbest possible storage. One comment is one line in the task's own detail
#: block, so a comment lives beside the thing it is about, survives in `git log` with the rest
#: of the task, and needs no second file to fall out of sync with. Append-only falls out of
#: that for free: writing a comment adds a line and touches nothing already written, so two
#: people commenting cannot overwrite each other and no generator run can eat a comment.
#:
#: Same indentation rule as CHECKBOX, and it matters more here because comments are the one
#: field where a human types free prose: an unindented one would end its own task block for
#: `tools/lib/archive_tasks.py` and take every detail line under it out of the task.
NOTE = re.compile(r"^[ \t]+note:[ \t]*(.*)$", re.M)


def run_check(kind: str, arg: str, root: Path) -> bool:
    """One `check:` predicate against the disk. Never raises: an unreadable file is a
    failed check, not a crashed page — the generator runs on a timer with nobody watching."""
    try:
        if kind == "exists":
            return (root / arg).exists()
        if kind == "absent":
            return not (root / arg).exists()
        if kind in ("grep", "ngrep"):
            pattern, _, path = arg.partition(" -- ")
            target = root / path.strip()
            if not target.is_file():
                # A missing file fails BOTH forms on purpose. "The bad string is absent from
                # a file that does not exist" is technically true and useless: it would let a
                # rename task reach 100% by deleting the file it was supposed to edit.
                return False
            hit = re.search(pattern.strip(), target.read_text(errors="replace")) is not None
            return hit if kind == "grep" else not hit
        if kind == "maxcount":
            n, _, rest = arg.partition(" ")
            pattern, _, path = rest.partition(" -- ")
            target = root / path.strip()
            if not target.is_file():
                return False
            found = len(re.findall(pattern.strip(), target.read_text(errors="replace"),
                                   re.M))
            return found <= int(n)
    except OSError:
        return False
    return False


def disk_state(old: str, new: str, root) -> str:
    """Did this move happen? Asked of the filesystem, which cannot be out of date."""
    old_here = (root / old).exists() if old else False
    new_here = (root / new).exists() if new else False
    # Both present is the honest "in progress": the move has started, the old path remains.
    # Neither present is pending, NOT done -- an absent destination is not evidence of a
    # completed move, and reading it as one would mark every unstarted task complete.
    if new_here and not old_here:
        return "done"
    if new_here and old_here:
        return "in progress"
    return "pending"


CSS = """
:root { --bg:#0d1117; --panel:#161b22; --line:#30363d; --fg:#e6edf3; --dim:#8b949e;
        --ok:#3fb950; --warn:#d29922; --run:#58a6ff; --bad:#f85149;
        /* Table surfaces. Kept as tokens rather than literals in the rules below, because a
           header ground and a zebra band that drift apart is how a table starts looking
           assembled instead of designed. */
        --head:#1c2129; --zebra:#12171e; --hover:#1b222c; }
* { box-sizing:border-box; }
body { background:var(--bg); color:var(--fg); margin:0; padding:1.2rem;
       font:15px/1.5 -apple-system,"Segoe UI",Roboto,sans-serif; max-width:1100px;
       margin-inline:auto; }
h1 { font-size:1.35rem; margin:.2rem 0 .1rem; }
h2 { font-size:1.05rem; margin:1.6rem 0 .5rem; border-bottom:1px solid var(--line);
     padding-bottom:.25rem; }
p  { margin:.3rem 0; }
.dim { color:var(--dim); }
.mono { font-family:ui-monospace,Menlo,Consolas,monospace; font-size:.92em; }
.scroll { overflow-x:auto; border:1px solid var(--line); border-radius:6px; }
table { border-collapse:collapse; width:100%; }
th,td { text-align:left; padding:.5rem .7rem; border-bottom:1px solid var(--line);
        vertical-align:top; }
/* A header that reads as a header. Garrett, 2026-08-20: *"make the table look like a real
   table"*. Small caps, tracked out, on its own ground and stuck to the top of the scroll box,
   so a long list still tells you what column you are in when you are forty rows down. */
thead th { position:sticky; top:0; z-index:1; background:var(--head);
           color:var(--fg); font-weight:600; font-size:.76rem; letter-spacing:.09em;
           text-transform:uppercase; white-space:nowrap;
           border-bottom:2px solid var(--line); }
th { color:var(--dim); font-weight:600; }
/* Zebra banding on the ENTRY rows only, and the band is emitted from Python rather than
   selected for. Every entry MAY render as a pair -- the row and its detail row underneath --
   but only when it has a detail to show, so the pairing is irregular and any positional
   selector bands the wrong rows. `:nth-of-type` was the first attempt and is worse than it
   looks: it counts every `tr` sibling and ignores the `:not(.det)` qualifying it, so it was
   striping by raw row position in a table whose rows come in ones and twos. The renderer
   knows which entry it is on; it tags the entry and its detail row together. */
table.grid tbody tr.band td { background:var(--zebra); }
table.grid tbody tr:not(.det) td { border-bottom:0; }
table.grid tbody tr.det td { border-bottom:1px solid var(--line); }
table.grid tbody tr:hover td { background:var(--hover); }
table.grid tbody tr:not(.det):hover + tr.det td { background:var(--hover); }
/* Fixed widths for the short columns so the one column carrying a sentence gets the rest of
   the table, instead of every column negotiating for space against the longest cell in it. */
.c-act { width:11rem; } .c-ref { width:5.5rem; } .c-typ { width:6rem; }
.c-own { width:7rem; }  .c-sta { width:7rem; } .c-pct { width:6.5rem; }
/* The why-column carries a paragraph, and it was the only column with no width at all --
   which left it and "What it is" both fighting for the remainder. Given one, so the
   title column stops being squeezed by however long a reason happens to be. Width, never
   text-overflow: an ellipsis on a reason is the data loss the rules bar outright. */
.c-why { width:26rem; } .why { white-space:normal; }
/* The comments box. Full width under its task rather than in a column of its own -- see the
   renderer note. Quiet until you are in it: the thread reads as text, and the control row is
   dim until focus, so 39 empty boxes down the page do not shout over the tasks. */
.notes { padding:.15rem 0 .35rem 0; }
ul.thread { margin:0 0 .4rem 1.1rem; padding:0; }
ul.thread li { margin:.12rem 0; color:var(--fg); white-space:pre-wrap; }
.nonote { margin:0 0 .35rem 0; font-style:italic; }
.addnote textarea { width:100%; box-sizing:border-box; background:var(--bg); color:var(--fg);
                    border:1px solid var(--line); border-radius:4px; padding:.35rem .5rem;
                    font:inherit; resize:vertical; }
.addnote textarea:focus, .addnote .who:focus { outline:1px solid var(--run); }
.noterow { display:flex; gap:.4rem; align-items:center; margin-top:.3rem; }
.addnote .who { background:var(--bg); color:var(--dim); border:1px solid var(--line);
                border-radius:4px; padding:.2rem .4rem; font:inherit; }
.notemsg { font-size:.85em; }
.badge { display:inline-block; padding:0 .5em; border-radius:.7em; font-size:.85em;
         border:1px solid var(--line); white-space:nowrap; }
.s-done { color:var(--ok); }  .s-pending { color:var(--warn); }
.s-in-progress { color:var(--run); } .s-open { color:var(--bad); }
.s-other { color:var(--dim); }
/* Cancelled and no-move are struck through, not merely greyed: at a glance the eye has to be
   able to tell "closed, nobody is doing this" from "not started yet". They read the same in
   plain text, which is exactly how three cancelled steps sat on this page as pending work. */
.s-cancelled, .s-no-move { color:var(--dim); text-decoration:line-through; }
ul { margin:.3rem 0 .3rem 1.2rem; padding:0; }
li { margin:.15rem 0; }
/* Health readings, not task states: these colour whole sentences about whether a record is
   keeping its own promise. `.phase`/`.steps` used to live here and went with the phase
   tracker on 2026-08-20 — see RESOLVE for why the tracker was deleted rather than fixed. */
p.s-ok   { color:var(--ok); }
p.s-warn { color:var(--warn); }
p.s-bad  { color:var(--bad); }
span.s-bad { color:var(--bad); font-family:ui-monospace,Menlo,Consolas,monospace;
             font-size:.85em; }
/* A dot, not a sentence. `read from disk` beside every resolved row was five words of the same
   five words repeated down the page; the mark qualifies the reading it sits next to and the
   title attribute carries the explanation for anyone who wonders what it means. */
.disk { color:var(--dim); font-size:.7em; vertical-align:.15em; margin-left:.3em;
        cursor:help; }
.num { white-space:nowrap; }
/* The denominator. `0%` alone cannot distinguish "nothing done" from "four checks declared,
   none passing yet", and only the second is true of a task that has just been written. */
.frac { color:var(--dim); font-size:.8em; margin-left:.4em;
        font-family:ui-monospace,Menlo,Consolas,monospace; }
/* The percentage cell. The bar sits BEHIND the number rather than beside it, so a narrow
   column still shows both, and the number is always readable at any width — a bar alone
   would be a decorative indicator, which the working agreements bar outright. */
.pct { position:relative; display:inline-block; min-width:4.2rem; padding:.05rem .3rem;
       border:1px solid var(--line); border-radius:3px; overflow:hidden; }
.bar { position:absolute; inset:0 auto 0 0; opacity:.28; }
.bar-ok { background:var(--ok); } .bar-warn { background:var(--warn); }
.bar-bad { background:var(--bad); }
.pctn { position:relative; font-family:ui-monospace,Menlo,Consolas,monospace;
        font-size:.85em; }
/* The barrier block. Garrett: "ledgers with no task shall be labelled with barriers", and
   before it "shall be highest priority". Priority is the position -- it renders above the task
   table; the label is what says why. Colour and a word, deliberately NOT hazard stripes or a
   texture: the working agreements bar decorative indicators, and both of these reflect a real
   state (recorded, no task number) rather than dressing one up. */
.alarm { border:1px solid var(--bad); border-left:4px solid var(--bad); border-radius:4px;
         padding:.6rem .9rem; margin:1rem 0; background:rgba(220,80,80,.06); }
.barrier-head { margin:0 0 .4rem 0; font-size:1.05em; }
.barrier { display:inline-block; padding:0 .45em; border-radius:3px; background:var(--bad);
           color:#fff; font-family:ui-monospace,Menlo,Consolas,monospace; font-size:.8em;
           letter-spacing:.06em; }
/* A ticked box is Garrett saying "this should become work" -- it is waiting on me, not on
   him, so it reads in the running colour rather than the warning one. */
.ready { color:var(--run); font-family:ui-monospace,Menlo,Consolas,monospace; font-size:.85em; }
.s-ready-for-review { color:var(--run); }
/* Dropped is Garrett's delete: recorded, struck through, no longer counted. There is NO
   sibling state beside it -- an earlier pass added "frozen" for the ledger's `held` entries
   and he rejected it outright: "i never gave you instruction of 'frozen' items". He defined
   two actions, tick and delete, and a state that accepts neither takes the decision off him. */
.dropped { display:inline-block; padding:0 .45em; border-radius:3px; border:1px solid var(--dim);
           color:var(--dim); font-family:ui-monospace,Menlo,Consolas,monospace; font-size:.8em; }
tr.gone td { opacity:.45; }
tr.gone .ttl { text-decoration:line-through; }
/* The two controls. Garrett, 2026-08-20: "just add some js to the page please so i can delete
   and check the box". Same size, same row, adjacent -- they are the same gesture with opposite
   meanings, and putting the destructive one somewhere else would make it harder to reach than
   the one he uses more often, not safer. */
.ctl { font: inherit; font-size:.82em; letter-spacing:.02em; line-height:1;
       padding:.35em .7em; margin-right:.3em; border-radius:4px; cursor:pointer;
       border:1px solid var(--dim); background:transparent; color:var(--fg);
       transition:border-color .12s, color .12s, background-color .12s; }
.ctl:hover { border-color:var(--fg); background:rgba(127,127,127,.10); }
.ctl:focus-visible { outline:2px solid var(--run); outline-offset:1px; }
/* The two actions are not peers, so they are not styled as peers. Ready is the one Garrett
   uses most and reads as the affirmative; Drop is destructive and says so on hover, in the
   colour the page already uses for failure. Before this they were `[x]` and `[-]` in a mono
   font, and he had to ask which one deleted. */
.ctl.on { border-color:var(--run); color:var(--run); }
.ctl.del { color:var(--dim); }
.ctl.del:hover { border-color:var(--bad); color:var(--bad); background:rgba(255,90,90,.10); }
.ctl[disabled] { opacity:.35; cursor:not-allowed; }
/* The brief -- my last thought on why this is not already a task -- and the one place to go to
   move it forward. A sub-row rather than two more columns: a table wide enough to hold a
   sentence per row scrolls sideways, and the working agreements bar clipping it instead. */
tr.det td { padding-top:0; border-top:0; font-size:.92em; }
.brief { color:var(--fg); margin:0 0 .2rem 0; }
.brief b { color:var(--dim); font-weight:600; }
.gowhere { color:var(--dim); }
.gowhere a { color:var(--run); }
#wire { margin:.6rem 0; }
#wire code { background:rgba(127,127,127,.15); padding:.1em .35em; border-radius:3px; }
"""


def parse_args():
    default_root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=default_root)
    ap.add_argument("--out", type=Path, default=None,
                    help="default: <root>/run/progress.html")
    return ap.parse_args()


def head_sha(root: Path) -> str:
    try:
        r = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "no-git"
    except OSError:
        return "no-git"


def parse_tasks(text: str, root: Path | None = None) -> list[dict]:
    """Every marker row plus its indented detail block; SHA read from either.

    A row carrying `resolve: OLD -> NEW` has its state read from the disk instead of from
    its marker, and is flagged so the page can say which rows answer for themselves.
    """
    tasks, current = [], None
    for line in text.splitlines():
        m = TASK_ROW.match(line)
        if m:
            current = {"state": MARKER_STATE[m.group(1)], "id": m.group(2),
                       "title": m.group(3), "detail": ""}
            tasks.append(current)
        elif current is not None and line.startswith((" ", "\t")):
            current["detail"] += line + "\n"
        elif line.strip() == "":
            continue
        else:
            current = None
    for t in tasks:
        m = SHA_IN_TEXT.search(t["title"]) or SHA_IN_TEXT.search(t["detail"])
        t["sha"] = m.group(1) if m else ""
        t["from_disk"] = False
        t["checks"] = None          # None means "declared none", which is NOT zero passed
        t["owner"] = "coder"        # unlabelled work is mine; see OWNER
        t["box"] = None             # None means no checkbox on this task at all
        # Comments, oldest first, exactly as typed. Append-only by construction: each is its
        # own line, so a new one can never land on top of an older one, and nothing here is
        # ever rewritten by a generator. `note:` stays on EVERY line of a multi-line comment
        # for two reasons — an unindented continuation would end the task block for
        # `archive_tasks.py` and silently truncate the task, and a continuation reading
        # `owner: garrett` would be parsed as a directive instead of as somebody's words.
        # ...and then GROUPED back into comments for the page. `note:` on every line is a
        # storage rule, not a reading rule: one comment hand-wrapped over eight lines was
        # rendering as eight bullet points, so the longest and most useful notes on the
        # handover artefact came out as a column of sentence fragments. A new comment starts
        # at a leading date, which is the format the box writes and the format CLAUDE.md
        # documents; anything else continues the one above it.
        t["notes"] = group_notes(m.group(1).rstrip() for m in NOTE.finditer(t["detail"]))

        o = OWNER.search(t["detail"])
        if o:
            t["owner"] = o.group(1).lower()
        b = CHECKBOX.search(t["detail"])
        if b:
            t["box"] = b.group(1).lower() == "x"
            # Garrett, 2026-08-20: "once i update the file with the answer i can check it and
            # you will know to review". A tick is a HANDOFF, not a completion — it says the
            # ball is back with me. Wiring it as a check: instead would push the percentage to
            # 100, which flips the state to done, which lets the archiver move the task off
            # the list before anybody read the answer: the exact inverse of what was asked.
            if t["box"] and t["state"] not in ("done", "cancelled"):
                t["state"] = "ready for review"

        if root is None:
            continue
        checks = []
        for line in t["detail"].splitlines():
            r = RESOLVE.match(line)
            if r:
                old, new = r.group(1), r.group(2)
                # A resolve is EVIDENCE, not a verdict. It used to read
                # `t["state"] = disk_state(...)` unconditionally, and because the
                # percentage rule below can only ever *set* `done` and never withhold it,
                # one satisfied `resolve:` closed the task no matter how many `check:`
                # lines were still red. #74 was archived that way on 2026-08-21 with
                # `ngrep /studio/comfy -- backend/server.py` failing on three occurrences and
                # `grep ComfyUI -- LICENSES.md` never written: a `git mv` of the launcher
                # satisfied the move, and forty-odd unmet checks went with it. CLAUDE.md
                # names this exact failure -- "a check that can pass without the work being
                # finished is worse than no check, since it will archive the task".
                #
                # So the resolve may hold a task OPEN (a half-done move is real information
                # and `disk_state` is the only thing that can see it), and may never close
                # one. Closing goes through the same all-checks-pass gate as everything
                # else, using the two derived checks appended just below.
                moved = disk_state(old, new, root)
                if moved != "done":
                    t["state"] = moved
                t["from_disk"] = True
                # A move is two facts: the destination arrived and the source left. Counting
                # them separately is what makes a half-done move read as 50% instead of
                # rounding to one side of a boolean.
                if new:
                    checks.append((f"exists {new}", run_check("exists", new, root)))
                if old:
                    checks.append((f"absent {old}", run_check("absent", old, root)))
                continue
            c = CHECK.match(line)
            if c:
                checks.append((f"{c.group(1)} {c.group(2)}",
                               run_check(c.group(1), c.group(2), root)))
        if checks:
            t["checks"] = checks
            t["pct"] = round(100 * sum(1 for _, ok in checks if ok) / len(checks))
            # A closed task is closed regardless of what its checks say; a cancelled one is
            # not measured against checks it will never satisfy. `ready for review` is in this
            # list for the same reason the tick is not a check: a task waiting on my reading of
            # Garrett's answer must not auto-close underneath that reading.
            if t["state"] not in ("done", "cancelled", "ready for review") and t["pct"] == 100:
                t["state"] = "done"
    return tasks


def parse_suites(text: str) -> list[tuple[str, str, str]]:
    rows, inside = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line.startswith("## Suite readings")
            continue
        if inside:
            m = SUITE_ROW.match(line)
            if m:
                rows.append((m.group(1), m.group(2), m.group(3)))
    return rows


def parse_questions(text: str) -> list[dict]:
    """AUDIT.md: `## Qn — ...` blocks, each with an `A:` line Garrett fills in.

    Answered is simply "the A: line has text after it". Deliberately that dumb: any cleverer
    rule (does the answer name an option? is it long enough?) would let the page disagree with
    what Garrett can plainly see he typed.
    """
    qs, current = [], None
    for line in text.splitlines():
        m = QUESTION_HEAD.match(line)
        if m:
            current = {"id": m.group(1), "title": m.group(2).strip(), "answer": ""}
            qs.append(current)
        elif current is not None and line.startswith("A:"):
            current["answer"] = line[2:].strip()
    return qs


#: INTAKE.md, the one assignment surface. Defined here rather than in `tools/build/build_intake.py`
#: so the writer and the reader share one definition of the format — two copies of a format
#: regex is exactly how the marker character `⊘` came to be missing from one of them.
INTAKE_HEAD = re.compile(r"^## (A-[A-Z0-9]+) \[(\w+)\] — (.+)$")
#: Three states in one control, because Garrett acts on an entry in exactly one place:
#: `[ ]` open, `[x]` ready to become a task, `[-]` unnecessary — his delete. 2026-08-20:
#: *"a delete button if i decide its unnecessary"*, and *"either delete them or check the box
#: after updating the document specified"* — delete and tick are the same gesture with the
#: same reach, so they are the same character position rather than two separate controls.
INTAKE_BOX = re.compile(r"^\[([ xX\-])\]")
INTAKE_TASK = re.compile(r"^task:\s*(#\d+.*)$")
INTAKE_FROM = re.compile(r"^from:\s*(.+)$")
INTAKE_OWNER = re.compile(r"^owner:\s*(\w+)\s*$")
INTAKE_BRIEF = re.compile(r"^brief:\s*(.+)$")
INTAKE_EDIT = re.compile(r"^edit:\s*(.+)$")
INTAKE_ANSWER = re.compile(r"^A:\s*(.*)$")
#: `blocked: <reason>` — the SPECIFIC thing stopping this assignment becoming a task.
#: Garrett, 2026-08-20: *"need to add column to intake for specific barrier on why its not a
#: task yet"*. The word BARRIER on its own says an item is stuck without saying on what, which
#: is the same defect as a percentage with no checks behind it: a label standing in for the
#: reading it is supposed to summarise. A barrier with no stated reason is now visibly missing
#: one, rather than looking complete.
INTAKE_BLOCKED = re.compile(r"^blocked:\s*(.+)$")


def parse_intake(text: str) -> list[dict]:
    """Assignments. An assignment with no `task:` line is a BARRIER — see build().

    Garrett, 2026-08-20: *"that way you only work on task and i just work on checking the box
    saying i believe its ready to move to task"*. So `box` is his signal, not a measurement:
    ticked means "I believe this is ready to become work", and the only thing that clears the
    barrier is a task number.
    """
    items, cur = [], None
    for line in text.splitlines():
        m = INTAKE_HEAD.match(line)
        if m:
            cur = {"id": m.group(1), "kind": m.group(2), "title": m.group(3).strip(),
                   "box": False, "dropped": False, "task": "", "src": "",
                   "owner": "coder", "brief": "", "edit": "", "answer": "",
                   "blocked": ""}
            items.append(cur)
            continue
        if cur is None:
            continue
        for rx, key, conv in ((INTAKE_BOX, "box", lambda v: v.lower() == "x"),
                              (INTAKE_TASK, "task", str.strip),
                              (INTAKE_FROM, "src", str.strip),
                              (INTAKE_OWNER, "owner", str.lower),
                              (INTAKE_BRIEF, "brief", str.strip),
                              (INTAKE_EDIT, "edit", str.strip),
                              (INTAKE_BLOCKED, "blocked", str.strip),
                              (INTAKE_ANSWER, "answer", str.strip)):
            g = rx.match(line)
            if g:
                if rx is INTAKE_BOX:
                    cur["dropped"] = g.group(1) == "-"
                cur[key] = conv(g.group(1))
                break
    return items


def parse_audit(text: str) -> list[dict]:
    items = []
    for line in text.splitlines():
        m = AUDIT_HEAD.match(line)
        if not m:
            continue
        rest = m.group(2)
        if rest.startswith("DONE"):
            bucket = "done"
        elif rest.startswith("OPEN"):
            bucket = "open"
        else:
            bucket = "other"   # SCOPE / LOW / GARRETT-ONLY / NOT MINE — labelled, not hidden
        name = rest.split(" — ", 1)[1] if " — " in rest else rest
        items.append({"n": m.group(1), "bucket": bucket,
                      "label": rest.split(" — ", 1)[0], "name": name})
    return items


# The ledger's status vocabulary, mapped to the bucket each status renders in. Held as data
# rather than the prefix loop this replaces, because two of these are not work at all:
# `adopted` is a standing rule with nothing to do, and `superseded` is closed-without-doing.
# Bucketing either as `captured` would file it under "un-actioned" and invite the next
# iteration to action it.
#
# `held` is why this table exists. Garrett froze R-11, R-52 and R-98 on 2026-08-20. The loop
# here previously fell through to `captured` for any status it did not recognise, so a frozen
# entry rendered as ordinary open work — the page would have advertised, as available, exactly
# the three items he had just told me not to touch. Unknown statuses now raise instead: the
# ledger's vocabulary and this parser are one contract, and a silent default is what let them
# drift apart.
STATUS_BUCKETS = {
    "done": "done",
    "declined": "declined",
    "superseded": "superseded",
    "adopted": "adopted",
    "held": "held",
    "queued": "queued",
    "in-progress": "in-progress",
    "captured": "captured",
}

# Garrett, 2026-08-20: *"they are either done, task or intake"*. That is the whole state
# space, and it is a completeness claim: every entry in the ledger is in exactly one of three
# states, and no entry is in none of them.
#
#   done    the bucket says it is finished, withdrawn or replaced       -> the record
#   task    not finished, and it names the task carrying it             -> PROJECT-TASKS.md
#   intake  not finished, and nothing is carrying it                    -> INTAKE.md
#
# `pending` is not a fourth state here -- it is what a task's own marker says once the entry
# has reached PROJECT-TASKS.md, alongside `in progress` and `ready for review`. Those describe
# how far a task has got; these three describe WHERE an item lives. A ledger entry reading
# `status: in-progress` with no task number is still `intake` by this rule and that is
# deliberate: nothing on the task list is carrying it, so no amount of claimed progress makes
# it visible as work.
#
# CLOSED_BUCKETS is the first of those three. Everything else splits on whether the entry
# names a task, so there is nowhere for an entry to fall through to.
#
# This replaces an OPEN_BUCKETS list that named four of the eight statuses, plus an `exempt`
# set that let `adopted` and `held` count as covered without naming any task. Between them
# those two rules put 19 entries -- 15 adopted, 3 held, 1 superseded-with-no-successor -- in
# no state at all: not done, not carried, and not on the intake list either. They were not
# hidden by a bug; each rule was defensible on its own, and the gap only appears when you ask
# the three-state question of every row at once.
#
# `superseded` is closed rather than intake because the entry that replaced it is itself
# somewhere in these three states -- the work did not vanish, it moved.
CLOSED_BUCKETS = ("done", "declined", "superseded")

# `adopted` is the fourth way to be closed, and the only conditional one. A standing rule is
# not work -- there is no task to write for "default is FIX, not FILE" -- so forcing every
# adopted entry onto the intake list asks Garrett to tick something that has no next step. But
# `adopted` alone is also how 15 entries went missing: the word asserts the rule landed
# somewhere without saying where, and an assertion nobody can check is the same shape as the
# stale figures the honesty rules exist to stop.
#
# So: adopted closes IF AND ONLY IF it names the file the rule now lives in. That makes the
# claim checkable -- open the path, read the rule -- and it degrades honestly, because an
# adopted entry with no pointer falls back to intake and shows up on Garrett's surface until
# somebody writes the rule down. The pointer is what turns "adopted" from a disposition into
# a fact about the repository.
RULE_POINTER = re.compile(r"\b[\w./-]+\.(?:md|py|sh|css|js|mjs|toml|service|timer)\b")


def _prose(entry: dict) -> str:
    """Status and body as one searchable string, with the newline the parser dropped.

    `status` is stored stripped of its trailing newline and `body` starts at the next line, so
    a bare `+` glues the last word of the status onto the first word of the body. That is not
    cosmetic: `RULE_POINTER` ends in `\\b`, and `...in GUARDRAILS.md` matched when the status
    was searched alone and stopped matching the moment the body was appended, because `md` was
    then followed by a word character instead of by end-of-string. R-111 names its file and
    still read as intake. Any pattern anchored at the end of the status line has the same
    failure, which is why this is a function and not a `+` at each call site.
    """
    return entry["status"] + "\n" + entry["body"]


def _adopted_is_recorded(entry: dict) -> bool:
    return bool(RULE_POINTER.search(_prose(entry)))


def parse_requests(text: str) -> list[dict]:
    entries, current = [], None
    for line in text.splitlines():
        m = REQUEST_HEAD.match(line)
        if m:
            current = {"id": m.group(1), "title": m.group(2), "status": "", "body": ""}
            entries.append(current)
        elif current is not None and line.startswith("status:") and not current["status"]:
            current["status"] = line[len("status:"):].strip()
        elif current is not None:
            current["body"] += line + "\n"
    for e in entries:
        s = e["status"].lower()
        for token, bucket in STATUS_BUCKETS.items():
            if s.startswith(token):
                e["bucket"] = bucket
                break
        else:
            raise ValueError(
                f"{e['id']}: status {e['status']!r} begins with none of "
                f"{sorted(STATUS_BUCKETS)}. Add the new status to STATUS_BUCKETS (and to "
                "CLOSED_BUCKETS if it means the item is finished) rather than letting it "
                "render as something it is not. This used to fall back to `captured` "
                "silently, which is how the ledger's vocabulary and this parser drifted "
                "apart in the first place.")
    for e in entries:
        # Three states, assigned here and nowhere else, so there is exactly one place to read
        # the rule from. `held` is NOT exempt: an entry Garrett stopped is still an entry
        # nobody is holding, which is a decision waiting on him and is what intake is for.
        # `adopted` is exempt only when it says where the rule was written down -- see
        # RULE_POINTER above for why the pointer, and not the word, is what closes it.
        e["closed"] = (e["bucket"] in CLOSED_BUCKETS
                       or (e["bucket"] == "adopted" and _adopted_is_recorded(e)))
        e["covered"] = e["closed"] or bool(TASK_REF.search(_prose(e)))
        e["state"] = ("done" if e["closed"]
                      else "task" if e["covered"]
                      else "intake")
    return entries


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def pct_cell(t: dict) -> str:
    """The percentage column. An em dash where there is nothing to measure — see CHECK.

    The bar states the fraction it was computed from, not just the percentage. `0%` beside an
    empty bar is the least informative thing this page can say about a task: it reads as
    "nothing done" when it means "four declared checks, none passing yet", and those are
    different reports. `0/4` says which.
    """
    if not t["checks"]:
        return ('<span class="dim" title="no machine checks declared — an unmeasured task is '
                'not a 0% task">no checks</span>')
    pct, n = t["pct"], len(t["checks"])
    passing = sum(1 for _, ok in t["checks"] if ok)
    tip = "\n".join(("PASS  " if ok else "FAIL  ") + label for label, ok in t["checks"])
    cls = "ok" if pct == 100 else ("warn" if pct else "bad")
    return (f'<span class="pct" title="{esc(tip)}">'
            f'<span class="bar bar-{cls}" style="width:{pct}%"></span>'
            f'<span class="pctn">{pct}%</span></span>'
            f'<span class="frac">{passing}/{n}</span>')


def badge(state: str) -> str:
    cls = "s-" + state.replace(" ", "-")
    return f'<span class="badge {cls}">{esc(state)}</span>'


#: `2026-08-20 garrett — ...` at the start of a note line. The date is what makes a new
#: comment distinguishable from a continuation of the one above, and it is what the comment
#: box writes, so the two halves agree by construction rather than by convention.
NOTE_HEAD = re.compile(r"^\d{4}-\d{2}-\d{2}\b")


def group_notes(lines) -> list[str]:
    """Consecutive `note:` lines -> one comment per entry, joined with spaces.

    A comment is stored one line per physical line because an unindented continuation would
    end the task block for `archive_tasks.py` and silently truncate the task. That is a
    storage constraint and it had leaked into the render: eight `note:` lines that were one
    hand-wrapped paragraph became eight bullets, and #73's comment read as fifteen unrelated
    fragments on the one page that is supposed to be the handover.

    A leading date starts a new comment. Anything before the first dated line is its own
    comment rather than being dropped -- notes predate the box and not all of them are dated,
    and losing an undated comment to make the grouping tidy is the one outcome worse than
    bad line breaks.
    """
    out: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        if NOTE_HEAD.match(line) or not out:
            out.append(line)
        else:
            out[-1] = out[-1] + " " + line.strip()
    return out


def note_cell(t: dict) -> str:
    """The comments box for one task: the thread so far, then somewhere to add to it.

    Garrett, 2026-08-20: *"and i need a comments box for the the project tasks"*. It renders
    on every task, including tasks with no comments yet — a box you have to find is a box
    nobody uses, and the empty state is the one that has to invite the first comment.

    The thread is plain text, never markdown. A comment is somebody's words about a task, and
    a stray backtick or underscore in them must not restyle the page or, worse, silently
    disappear from it. `esc` is the whole formatting rule.
    """
    out = ['<div class="notes">']
    if t["notes"]:
        out.append('<ul class="thread">')
        for n in t["notes"]:
            out.append(f"<li>{esc(n)}</li>")
        out.append("</ul>")
    else:
        out.append('<p class="dim nonote">No comments on this task yet.</p>')
    # `name` is what the appended line gets attributed to, and it is a plain text field rather
    # than anything resembling a login: this page is a bookmark on one box, and pretending to
    # authenticate a comment on it would be a decorative security control — the same dishonesty
    # the site rules bar for a status LED.
    out.append(
        f'<div class="addnote" data-id="{esc(t["id"])}">'
        f'<textarea rows="2" placeholder="Add a comment on {esc(t["id"])}…"></textarea>'
        f'<div class="noterow"><input class="who" value="garrett" '
        f'aria-label="who is commenting" size="10">'
        f'<button class="ctl">Comment</button>'
        f'<span class="notemsg dim"></span></div></div>')
    out.append("</div>")
    return "".join(out)


#: A leading repo-relative path in a `from:` or `edit:` line — `GARRETT-REQUESTS.md R-98`,
#: `symoneural.env — set SPOTIFY_CLIENT_SECRET`, `backend/server.py:1545`.
DOC_PATH = re.compile(r"^([\w./-]+\.\w+)(?::(\d+))?(.*)$", re.S)


def doc_link(spec: str) -> str:
    """Make the document in a `from:`/`edit:` line clickable. Garrett, 2026-08-20:
    *"maybe even hyperlink me useful information"*.

    The page lives in `run/`, so a repo file is one directory up. That relative href is what
    makes this work under `file://` as well as over http — the link resolves against wherever
    the page was opened from, and the page is opened from inside the repo either way. An
    absolute path would work in exactly one of the two.

    A line whose first token is not a path renders as plain text rather than as a broken link.
    """
    m = DOC_PATH.match(spec.strip())
    if not m:
        return esc(spec)
    path, line, rest = m.group(1), m.group(2), m.group(3)
    label = path + (f":{line}" if line else "")
    # No #L anchor: browsers do not honour one on a text/plain or text/markdown response, so
    # it would look like a promise the link does not keep. The number is in the label instead.
    return f'<a class="mono" href="../{esc(path)}">{esc(label)}</a>{esc(rest)}'


#: The two controls, wired. Kept as one string rather than assembled per row so there is
#: exactly one copy of the request shape on the page.
#:
#: Why `/local/` and not `/api/`: `ops/Caddyfile` proxies `handle /api*` to the gateway, so
#: anything under /api is on the public internet. INTAKE.md restates GARRETT-REQUESTS.md,
#: which is mode 600 and uncommitted — a public write handle on it is not a risk worth taking
#: for a checkbox. A path matching NO `handle` block falls through to `handle { file_server }`,
#: which looks for a file called `local/intake` in the webroot and 404s without ever asking the
#: API. So this route is reachable from this box and from nowhere else, and `api.py` re-checks
#: that for itself rather than trusting the proxy config to stay this way.
#:
#: Opened as file:// the fetch cannot reach it, so the buttons say what to type instead. The
#: page is Garrett's bookmark and has always been file:// friendly; degrading to the manual
#: edit keeps that true rather than making the bookmark depend on the API being up.
INTAKE_JS = """<script>
(function () {
  var API = "/local/intake";
  var wire = document.getElementById("wire");
  var live = location.protocol !== "file:";
  wire.innerHTML = live
    ? 'Buttons write to <code>INTAKE.md</code> directly. <code>[x]</code> sends it to the '
      + 'task list; <code>[&minus;]</code> drops it as unnecessary.'
    : 'Opened from disk, so the buttons cannot write. Either open '
      + '<code>http://127.0.0.1:8800/local/progress</code> on this box, or edit '
      + '<code>INTAKE.md</code> by hand — click a button and it will tell you the exact line.';

  function apply(id, set) {
    var row = document.getElementById("row-" + id);
    if (!row) return;
    if (set === "-") {
      // Drop REMOVES the row. Garrett, 2026-08-20: *"i click drop and it doesnt remove from
      // intake list"* -- it used to grey the row and strike the title, on the reasoning that
      // deleting a row hides the evidence. The evidence is in review/RETIRED-ASSIGNMENTS.md,
      // which is written before INTAKE.md is; a row that stays after you drop it just reads
      // as a button that did not work.
      var det = row.nextElementSibling;
      if (det && det.classList.contains("det")) det.remove();
      row.remove();
      return;
    }
    {
      row.querySelectorAll("button[data-set=x]").forEach(function (b) {
        b.classList.toggle("on");
      });
    }
  }

  // `button.ctl[data-set]`, not `button.ctl`: the comments box reuses the same button styling
  // and would otherwise be picked up by this handler and POSTed to the intake endpoint as an
  // assignment tick with an undefined id.
  document.querySelectorAll("button.ctl[data-set]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var id = btn.dataset.id, set = btn.dataset.set;
      if (set === "-" && !confirm("Drop " + id + " as unnecessary?")) return;
      if (!live) {
        wire.innerHTML = 'Edit <code>INTAKE.md</code>, find <code>## ' + id
          + '</code>, and set the line under it to <code>[' + set + ']</code>.';
        return;
      }
      btn.disabled = true;
      fetch(API, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({id: id, set: set})
      }).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      }).then(function () {
        apply(id, set);
        wire.innerHTML = 'Saved <code>' + id + '</code> as <code>[' + set
          + ']</code> in INTAKE.md.';
        if (set !== "-") btn.disabled = false;
      }).catch(function (e) {
        btn.disabled = false;
        wire.innerHTML = 'Could not save <code>' + id + '</code> (' + e.message
          + '). Edit <code>INTAKE.md</code> and set its box to <code>[' + set + ']</code>.';
      });
    });
  });

  // The comments box. Same live/file:// split as the buttons above and for the same reason:
  // the page is a bookmark that has to keep working when the API is down, so the failure mode
  // is being told the line to type, never a control that silently does nothing.
  document.querySelectorAll(".addnote").forEach(function (box) {
    var id = box.dataset.id;
    var ta = box.querySelector("textarea");
    var who = box.querySelector(".who");
    var btn = box.querySelector("button");
    var msg = box.querySelector(".notemsg");

    function append(line) {
      var ul = box.parentNode.querySelector("ul.thread");
      if (!ul) {
        var empty = box.parentNode.querySelector(".nonote");
        ul = document.createElement("ul");
        ul.className = "thread";
        if (empty) empty.replaceWith(ul); else box.parentNode.insertBefore(ul, box);
      }
      var li = document.createElement("li");
      li.textContent = line;           // textContent, not innerHTML: a comment is never markup
      ul.appendChild(li);
    }

    btn.addEventListener("click", function () {
      var text = ta.value.trim();
      if (!text) { ta.focus(); return; }
      var author = (who.value || "garrett").trim();
      if (!live) {
        msg.textContent = "Opened from disk — add an INDENTED line "
          + "'note: " + author + " — " + text + "' under " + id + " in PROJECT-TASKS.md.";
        return;
      }
      btn.disabled = true;
      msg.textContent = "saving…";
      fetch("/local/tasknote", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({id: id, who: author, text: text})
      }).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      }).then(function (d) {
        append(d.line || text);
        ta.value = "";
        msg.textContent = "saved to PROJECT-TASKS.md";
        btn.disabled = false;
      }).catch(function (e) {
        btn.disabled = false;
        msg.textContent = "could not save (" + e.message
          + ") — add it by hand as an indented 'note:' line under " + id + ".";
      });
    });
  });
})();
</script>"""


def build(root: Path) -> str:
    tasks_file = root / "PROJECT-TASKS.md"
    intake_file = root / "INTAKE.md"
    ledger_file = root / "GARRETT-REQUESTS.md"
    audit_file = root / "AUDIT-SURFACE-2026-08-19.md"
    inbox_file = root / "GARRETT-INBOX.md"

    # `root` is not optional in practice: without it every `resolve:` line is silently
    # ignored and the disk-resolved rows fall back to their markers, which is a no-op that
    # looks exactly like a working feature.
    tasks = parse_tasks(tasks_file.read_text(), root) if tasks_file.exists() else []
    suites = parse_suites(tasks_file.read_text()) if tasks_file.exists() else []
    audit = parse_audit(audit_file.read_text()) if audit_file.exists() else []
    requests = parse_requests(ledger_file.read_text()) if ledger_file.exists() else None
    assignments = parse_intake(intake_file.read_text()) if intake_file.exists() else []
    # The archive is read so the page can still report the two exits. Once promotion moves a
    # carried entry off INTAKE.md, an empty list is the CORRECT state, and a page that could
    # only count what was still on the list would report the healthy end state and the
    # never-generated one with the same "0" and no way to tell them apart.
    retired_file = root / "review" / "RETIRED-ASSIGNMENTS.md"
    retired = parse_intake(retired_file.read_text()) if retired_file.exists() else []
    questions_file = root / "AUDIT.md"
    questions = (parse_questions(questions_file.read_text())
                 if questions_file.exists() else None)
    milestone_hit = bool(inbox_file.exists() and
                         re.search(r"^## v3 MILESTONE", inbox_file.read_text(), re.M))
    audit_done_file = (root / "AUDIT-DONE-2026-08-19.md").exists()
    sha = head_sha(root)
    task_by_id = {t["id"]: t for t in tasks}

    out = []
    out.append("<!DOCTYPE html>")
    out.append('<html lang="en"><head><meta charset="utf-8">')
    out.append('<meta http-equiv="refresh" content="60">')
    out.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    out.append("<title>Symoneural progress</title>")
    out.append(f"<style>{CSS}</style></head><body>")

    # Header — the one line with a clock on it carries the marker id the test strips.
    out.append("<h1>Symoneural — where everything stands</h1>")
    out.append(f'<p id="generated-at" class="dim">generated '
               f'{time.strftime("%Y-%m-%d %H:%M:%S %Z")} — auto-refreshes every 60&thinsp;s'
               "</p>")
    open_tasks = [t for t in tasks if t["state"] not in ("done", "cancelled")]
    out.append(f'<p>HEAD <span class="mono">{esc(sha)}</span> &middot; '
               f'<strong>{len(open_tasks)}</strong> tasks open</p>')

    # Garrett, 2026-08-20: "ledgers with no task shall be highest priority", then "ledgers
    # with no task shall be labelled with barriers". Priority alone is a sort order; a barrier
    # is a claim about the work. An assignment that was recorded and never carried is the worst
    # thing this page can report -- worse than late work, because nobody is even holding it --
    # and it blocks the task list from being read as a complete account of what is outstanding.
    #
    # Labelled, not textured. Hazard stripes would be decoration, and the working agreements bar
    # decorative indicators outright; the word BARRIER and the alarm colour carry the meaning,
    # and both reflect a real state (recorded, no task number).
    # Three things are NOT barriers, and each for its own reason:
    #   * carried    -- it names a task, so it is being held; that is the whole exit.
    #   * dropped    -- he marked it `[-]` unnecessary. Recorded, not outstanding.
    # A dropped assignment still RENDERS, struck through. Removing it from the page entirely
    # would make his decision indistinguishable from an item that was never recorded.
    barriers = [a for a in assignments if not a["task"] and not a["dropped"]]
    ready = [a for a in barriers if a["box"]]
    # There is deliberately NO summary block here. Garrett, 2026-08-20: "i dont need a bullshit
    # list at the top and a full list at the bottom i just need the full list in one location
    # with working check boxes". A banner listing the first twelve barriers above a table
    # listing all of them is the same duplicate-listing mistake that killed the phase tracker,
    # rebuilt at a smaller scale -- and it puts the copy you cannot act on above the one you
    # can. The one list carries the BARRIER label per row instead.

    out.append("<h2>Tasks — PROJECT-TASKS.md, the canonical list</h2>")
    measured = [t for t in tasks if t["checks"]]
    out.append(f'<p class="dim">{len(measured)} of {len(tasks)} tasks declare machine '
               "checks and carry a real percentage. The rest read <em>no checks</em>, because "
               "an unmeasured task is not a 0% task. A percentage here is passing checks over "
               "declared checks — hover it to see them.</p>")
    if tasks:
        # Only render a column that says something different on different rows. Garrett,
        # 2026-08-20, on a screenshot of this table: *"this looks like 3rd grader coding"* —
        # and it did: an SHA column empty in all 39 rows, and a status column reading `pending`
        # in all 39. Two of the five columns were pure furniture, which pushed the wording (the
        # only column anyone reads) to the far right past a field of em dashes.
        #
        # Computed, not deleted. When a task is marked done or a SHA lands, that column has
        # something to say and comes back on its own. A hard-coded four-column table would go
        # stale the first time the data changed, which is the same class of mistake as a
        # carried-forward figure.
        show_sha = any(t["sha"] for t in tasks)
        show_state = len({t["state"] for t in tasks}) > 1
        # `any(owner)` was wrong here and rendered the exact furniture column the note above
        # says it removed: `parse_tasks` defaults every task to `coder`, so the test could
        # never be False and all 39 rows read the same word. A column earns its width by
        # DIFFERING across rows, which is what `show_state` measures and what this now does.
        show_owner = len({t.get("owner") or "coder" for t in tasks}) > 1
        head = ['<th class="c-ref">Task</th>']
        if show_state:
            head.append('<th class="c-sta">Status</th>')
        head.append('<th class="num c-pct">Progress</th>')
        if show_owner:
            head.append('<th class="c-own">Assigned to</th>')
        if show_sha:
            head.append('<th class="c-ref">Commit</th>')
        head.append("<th>What it is</th>")
        # Comments are NOT a column. Garrett asked for a comments box on the tasks, and the
        # first draft of this gave it a `Notes` column -- in the same table he had just called
        # unprofessional, for being too wide to read. A column holding a conversation is that
        # mistake with a worse cell: it either truncates the thread or it pushes the wording
        # off-screen. The assignment table already solved this with a paired detail row, so
        # comments render there, full width, under the task they are about.
        ncol = len(head)
        out.append('<div class="scroll"><table class="grid"><thead><tr>'
                   + "".join(head) + "</tr></thead><tbody>")
        # Numeric order, always. Garrett, 2026-08-20: "you need to make your programming
        # consistent; this is not consistent" -- and he was reading a table where #64 sat
        # between #58 and #59 because rows rendered in FILE order, and a task appended to the
        # file lands wherever it was typed. File order is an accident of editing; task order is
        # what a reader expects a numbered list to be in. Unnumbered rows sort last rather than
        # crashing the key, and keep their relative order.
        def task_key(t: dict) -> tuple:
            m = re.match(r"#(\d+)", t["id"])
            return (0, int(m.group(1))) if m else (1, 0)

        for n, t in enumerate(sorted(tasks, key=task_key)):
            # A row that answers for itself says so. Nobody has to trust that somebody
            # remembered to flip this marker, because nobody set it. It is a mark against the
            # progress cell, not a phrase beside the status: it qualifies the reading, and as
            # running prose in its own column it was repeated down the page as noise.
            disk = (' <span class="disk" title="state resolved from the filesystem, not from '
                    'a marker somebody set by hand">&#9679;</span>' if t["from_disk"] else "")
            row = [f'<td class="mono">{esc(t["id"])}</td>']
            if show_state:
                row.append(f"<td>{badge(t['state'])}</td>")
            row.append(f'<td class="num">{pct_cell(t)}{disk}</td>')
            if show_owner:
                row.append(f'<td class="dim">{esc(t.get("owner") or "coder")}</td>')
            if show_sha:
                row.append(f'<td class="mono">{esc(t["sha"]) if t["sha"] else ""}</td>')
            row.append(f'<td class="ttl">{esc(t["title"])}</td>')
            # The band is tagged here and repeated on the detail row, so a task and its
            # comments always share a ground. See the CSS note: a positional selector cannot
            # do this, because whether a row has a partner depends on the data.
            band = " band" if n % 2 else ""
            out.append(f'<tr class="ent{band}">' + "".join(row) + "</tr>")
            out.append(f'<tr class="det{band}"><td colspan="{ncol}">'
                       + note_cell(t) + "</td></tr>")
        out.append("</tbody></table></div>")
    else:
        out.append('<p class="dim">PROJECT-TASKS.md not found — nothing to render.</p>')

    # ONE list, with checkboxes. Garrett, 2026-08-20: "we need to somehow merge this request
    # ledger questions for garrett audit surface and anything other than project task into one
    # systematic assignment", then "all this should be merged into a list with check boxes".
    #
    # This replaces three panels that each listed the same condition -- written down, not being
    # worked -- in a different vocabulary, which is how one item came to appear in two of them
    # under two names. Requests, questions and findings are all assignments now; the ledger,
    # AUDIT.md and the audit surface stay as records, and INTAKE.md is the reading.
    out.append("<h2>Assignments — INTAKE.md, the one list</h2>")
    # Three states, and they must not collapse into one "0". Garrett, 2026-08-20: *"push
    # intake.md to task"* -- the page was reading "28 assignments, 0 barriers, 28 promoted to
    # tasks" and then listing all 28 with Ready and Drop buttons, which asks him to triage work
    # already under way. Promotion now takes a carried entry off the list, so EMPTY IS THE
    # HEALTHY END STATE and has to read as one.
    promoted = [a for a in retired if a["task"]]
    dropped_n = len([a for a in retired if a["dropped"]])
    if not intake_file.exists():
        out.append('<p class="dim">INTAKE.md not present. Run '
                   "<span class=\"mono\">python3 tools/build/build_intake.py</span>.</p>")
    elif not assignments:
        out.append(f'<p><strong>Nothing waiting.</strong> Every assignment recorded has been '
                   f"carried to a task or dropped — {len(promoted)} promoted, {dropped_n} "
                   "dropped — so this list is empty, which is the end state it is supposed to "
                   "reach. The task list above is the live record; the exits are kept in "
                   '<span class="mono">review/RETIRED-ASSIGNMENTS.md</span> with the task '
                   "number each one went to.</p>")
    else:
        out.append(f'<p>{len(assignments)} waiting &middot; '
                   f'<strong>{len(barriers)}</strong> '
                   f'{"barrier" if len(barriers) == 1 else "barriers"} (no task) &middot; '
                   f'<strong>{len(ready)}</strong> ticked ready &middot; '
                   f"{len(promoted)} already promoted to tasks and off this list.</p>")
        out.append('<p class="dim">The flow is one line: <span class="mono">assignment '
                   "&rarr; (answer, if it is a question) &rarr; [x] ready &rarr; task #NN"
                   "</span>. Ticking a box is the whole protocol — it says <em>this should "
                   "become work</em>, and nothing else on this page asks anything of Garrett. "
                   "Until a box is ticked I work only from the task list above.</p>")
        out.append('<p id="wire" class="dim">Buttons write to INTAKE.md through the API on '
                   "this box. Checking&nbsp;this&hellip;</p>")
        # Column names are for the person reading, not for the dict keys behind them. These
        # were `ready / id / kind / assignment / owner / task` -- five of the six were the
        # variable name, and `ready` labelled a column of buttons that are not a readiness
        # reading but the control that sets one. Garrett, 2026-08-20: *"replacing 'ready' 'id'
        # 'kind' 'assignment' 'owner' 'task' with more proper labeling"*.
        out.append('<div class="scroll"><table class="grid"><thead><tr>'
                   '<th class="c-act">Action</th>'
                   '<th class="c-ref">Ref</th>'
                   '<th class="c-typ">Type</th>'
                   "<th>What it is</th>"
                   '<th class="c-own">Assigned to</th>'
                   '<th class="c-sta">Status</th>'
                   # The seventh column had no header. Six `<th>` sat over seven `<td>`, so
                   # the why-cell was an unlabelled column and its contents read as a stray
                   # note rather than as an answer to a question. Garrett: *"reason not
                   # recorded this gave me no information; fix it to provide information"* --
                   # part of what gave him no information was that nothing said what the
                   # column was for. A value with no header is not a reading.
                   '<th class="c-why">Why it is not a task yet</th>'
                   "</tr></thead><tbody>")
        # Dropped entries are not rendered. `tools/build/build_intake.py` also stops writing them to
        # INTAKE.md, so in the steady state there are none here to skip -- this is the window
        # between a Drop click, which writes `[-]` immediately, and the generator run two
        # minutes later that moves the entry to the archive. Without it the page would put the
        # row back for those two minutes, which is the behaviour Garrett reported as broken.
        # `enumerate`, because `n` was not bound here at all. The zebra banding below read
        # the `n` left over from the task loop several hundred lines up -- so it was constant
        # across every row and the banding had never once alternated, and on a tree with no
        # tasks the generator died with `UnboundLocalError`. Found by a test that built a
        # ledger and no task list, which is exactly the shape nothing had ever generated.
        for n, a in enumerate(sorted((x for x in assignments if not x["dropped"]),
                        key=lambda x: (bool(x["task"]), not x["box"], x["kind"], x["id"]))):
            gone = False
            exit_cell = (f'<span class="mono">{esc(a["task"])}</span>' if a["task"]
                         else '<span class="barrier">BARRIER</span>')

            # EVERY row gets controls. Garrett, 2026-08-20: *"action buttons went away on
            # intake"* -- and they had, because carried entries were rendering a dash instead
            # of buttons on the reasoning that a carried entry is a task now and the task list
            # is where it is acted on. That reasoning stopped being true the moment the last
            # barrier was cleared: with all 28 entries carried, the Action column was 28 dashes
            # and there was no way to change your mind about a mapping from the page at all.
            #
            # Ready on a carried row reads as its state rather than as an offer, since the
            # thing it asks for has already happened.
            #
            # The buttons read `Ready` and `Drop`, not `[x]` and `[-]`. Garrett, 2026-08-20:
            # *"is the x delete or the - delete? Why would you not make this more
            # professional"*. He is right and the question is the proof: `[x]` and `[-]` are
            # the markdown this page WRITES, not language anyone reads, and the destructive
            # one was the quieter of the two. A control whose meaning has to be guessed is
            # worse than no control when one of the two guesses discards an item. The markdown
            # characters stay in `data-set`, where the endpoint needs them and nobody has to
            # interpret them.
            on = " on" if (a["box"] or a["task"]) else ""
            rdy = ("already carried by a task" if a["task"]
                   else "mark ready — it becomes a numbered task")
            drp = ("drop the assignment — its task stays on the task list" if a["task"]
                   else "not needed — drop it from the list")
            ctl = (f'<button class="ctl{on}" data-id="{esc(a["id"])}" data-set="x" '
                   f'title="{rdy}">Ready</button>'
                   f'<button class="ctl del" data-id="{esc(a["id"])}" data-set="-" '
                   f'title="{drp}">Drop</button>')

            # Why it is not a task yet, in its own column. An entry that IS a task is not
            # blocked on anything, so the cell says so rather than repeating the task number
            # already in the Status column. A barrier with no `blocked:` line renders as a
            # visible gap on purpose: the missing reason is the finding.
            if a["task"]:
                why = '<span class="dim">not blocked</span>'
            elif a["blocked"]:
                why = esc(a["blocked"])
            else:
                why = '<span class="s-warn">reason not recorded</span>'
            ans = ""
            if a["kind"] == "question":
                ans = ('<span class="s-ok"> answered</span>' if a["answer"]
                       else '<span class="s-warn"> awaiting answer</span>')
            cls = "gone" if gone else ""
            band = "band" if n % 2 else ""
            rowcls = (" ".join(x for x in ("ent", cls, band) if x)).strip()
            out.append(f'<tr class="{rowcls}" id="row-{esc(a["id"])}"><td>{ctl}</td>'
                       f'<td class="mono">{esc(a["id"])}</td>'
                       f'<td class="dim">{esc(a["kind"])}</td>'
                       f'<td class="ttl">{esc(a["title"])}{ans}</td>'
                       f'<td class="dim">{esc(a["owner"])}</td><td>{exit_cell}</td>'
                       f'<td class="why">{why}</td></tr>')

            # The sub-row: why it is not a task yet, and the one place to go to change that.
            # Garrett, 2026-08-20: "i just need each A-# with whatever your last thought was
            # when not taking it straight to task", "as well as the location of the document i
            # need to update to get it moving forward". A row that says only what an item is
            # tells him nothing he can act on; these two lines are the entire reason the page
            # is worth opening, so they render inline rather than behind a hover or a fold.
            det = []
            if a["brief"]:
                det.append(f'<p class="brief"><b>Why this is not a task yet:</b> '
                           f'{esc(a["brief"])}</p>')
            if a["edit"]:
                det.append(f'<p class="gowhere"><b>To move it forward:</b> '
                           f'{doc_link(a["edit"])}</p>')
            # NO `from:` fallback. Garrett, 2026-08-20: *"the from: 'Audit-surface shit' i
            # better never see that file again I want context from the chat"*. He is right, and
            # the fallback was the tell that a brief was missing: naming the scratch file an
            # item was scraped out of is not context, it is a citation of my own working
            # notes. An assignment with no brief now renders with nothing under it, which reads
            # as the gap it is instead of dressing the gap up as information.
            if det:
                dcls = (" ".join(x for x in ("det", cls, band) if x)).strip()
                out.append(f'<tr class="{dcls}"><td></td>'
                           f'<td colspan="6">{"".join(det)}</td></tr>')
        out.append("</tbody></table></div>")
        out.append(INTAKE_JS)

    # No "Sources" panel. Garrett, 2026-08-20: "what is this i didnt ask for this?" -- and he
    # was right twice over. He asked for ONE list; a counts panel beside it is the same
    # duplicate-listing instinct that produced the phase tracker and then the top banner, back
    # for a third time in a smaller costume. The ledger, AUDIT.md and the audit surface are
    # records that feed INTAKE.md; every item they hold is already a row in the table above,
    # and a second summary of them is not a reading, it is clutter.
    #
    # The one figure that was worth keeping -- ledger depth against its target of four -- is
    # task #58, where it is work rather than decoration.

    # Only when there is something to read. It used to render a heading and a "no section
    # found" line, which is a permanent apology for a section nobody asked for -- and Garrett
    # read exactly that empty placeholder before asking what it was doing there. A reading with
    # no data is not a reading.
    if suites:
        out.append("<h2>Suites — latest readings, each anchored to its tree</h2>")
        out.append('<div class="scroll"><table><tr><th>suite</th><th>reading</th>'
                   "<th>SHA</th></tr>")
        for name, reading, s in suites:
            out.append(f'<tr><td class="mono">{esc(name)}</td><td>{esc(reading)}</td>'
                       f'<td class="mono">{esc(s)}</td></tr>')
        out.append("</table></div>")

    out.append("</body></html>")
    return "\n".join(out) + "\n"


def main():
    args = parse_args()
    out = args.out or (args.root / "run" / "progress.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(args.root))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
