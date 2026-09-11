#!/usr/bin/env python3
"""Build INTAKE.md — the one assignment surface, merged from every non-task source.

Garrett, 2026-08-20: *"we need to somehow merge this request ledger questions for garrett
audit surface and anything other than project task into one systematic assignment that flows
with the question, barriers, and requirements to push it to task"*, then the division of
labour that gives it its shape: *"that way you only work on task and i just work on checking
the box saying i believe its ready to move to task"*.

So there are exactly two surfaces, and each has one owner:

    INTAKE.md         assignments.  Garrett's surface.  He ticks a box.
    PROJECT-TASKS.md  tasks.        My surface.         I do the work.

and exactly one flow between them:

    assignment  ->  (answer, if it is a question)  ->  [x] ready  ->  task #NN

An assignment carrying no `task:` line is a **barrier**: recorded, uncarried, and blocking the
task list from being read as a complete account of what is outstanding. That is the whole
vocabulary. A request, an unanswered question and an open audit finding were three different
words for the same condition — written down, not being worked — spread across three files with
three formats, which is how the same item came to sit in two of them under different names.

WHY THIS IS GENERATED RATHER THAN HAND-WRITTEN
Migrating ~150 ledger entries, 27 audit items and 9 questions by hand would be accurate exactly
once, and the sources keep moving. So this regenerates the skeleton from the sources on the same
timer as the page, and MERGES Garrett's edits back over the top. What is regenerated is the
title, source and kind; what is preserved is everything he can type:

    [x] / [ ]   the checkbox — his signal that it is ready to become a task
    task: #NN   the exit, written when it is promoted
    A: ...      the answer to a question
    any prose   free text under an entry, kept verbatim

An entry whose source disappears leaves this list and is archived to
`review/RETIRED-ASSIGNMENTS.md`. Off the list, never deleted: deleting something Garrett
ticked would silently discard the one action this file asks of him.
"""
import argparse
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_progress import (  # noqa: E402  (path set above)
    AUDIT_HEAD, TASK_REF, TASK_ROW, parse_audit, parse_questions, parse_requests,
)

#: The title is optional so that ONE parser reads both files. `review/RETIRED-ASSIGNMENTS.md`
#: writes `## A-R22 [retired]` with no title, and until the archive was read back it was being
#: rebuilt every run from a source that no longer contained the entries — so an archived item
#: survived exactly one further run before the rewrite dropped it. Making this optional is what
#: lets the archive be an input as well as an output, which is what stops that.
ENTRY_HEAD = re.compile(r"^## (A-[A-Z0-9]+) \[(\w+)\](?: — (.+))?$")
#: `[ ]` open, `[x]` ready to become a task, `[-]` unnecessary. See INTAKE_BOX in
#: build_progress.py for why delete is a box state rather than a separate control.
BOX = re.compile(r"^\[([ xX\-])\]")
TASK_LINE = re.compile(r"^task:\s*(#\d+.*)$")
ANSWER_LINE = re.compile(r"^A:\s*(.*)$")
#: Hand-authored and therefore first-class: `brief:` is my last thought on why an item is not
#: already a task, `edit:` is where Garrett goes to change that. These are PRESERVED fields,
#: not regenerated ones -- an unrecognised line falls into `prose`, which renders after
#: `task:`, so treating them as prose would let hand-written content drift position between
#: runs and show up as churn in the run-twice diff.
BRIEF_LINE = re.compile(r"^brief:\s*(.*)$")
EDIT_LINE = re.compile(r"^edit:\s*(.*)$")
#: `blocked:` — the specific thing stopping an entry becoming a task, for the page's
#: "Why not a task yet" column. Preserved, not regenerated, for the same reason as the two
#: above: it is a judgement somebody wrote, and a generated version of it would be a guess.
BLOCKED_LINE = re.compile(r"^blocked:\s*(.*)$")
# The `**Requests**` / `**Questions**` / `**Findings**` band between sections. Anchored to the
# three kinds rather than to `**...**` generally, so a bold sentence someone writes in an
# entry's prose is still prose.
SECTION = re.compile(r"^\*\*(?:Question|Request|Finding)s\*\*$")

#: The preamble that used to head a `## Retired` section at the foot of this file, before
#: retirement moved out to `review/RETIRED-ASSIGNMENTS.md`. Recognised on the way IN, and no
#: longer written on the way out — so any surviving copies wash out on the next run instead of
#: being read as prose belonging to whichever entry happened to be last.
#:
#: Three of them had stacked up under A-FI9. Same bug as SECTION above, third occurrence: a
#: generator that re-reads its own output must recognise EVERYTHING it has ever emitted, not
#: just what it emits today. Retiring the section without retiring its parser left the sentence
#: with no owner, and an unowned line in this file is by definition something Garrett typed.
RETIRED_NOTE = re.compile(r"^Source no longer lists these\.")

HEADER = """# INTAKE.md — the one assignment surface

Everything that is not yet a task lives here: requests, questions, audit findings. One format,
one vocabulary, one exit.

**The flow.** `assignment` → *(answer, if it is a question)* → `[x] ready` → `task: #NN`

**Two surfaces, two owners.** This file is Garrett's: he ticks a box to say an item is ready
to become work. `PROJECT-TASKS.md` is mine: I do what is on it. Nothing else is asked of him
here, and nothing on this file is work — it is the queue in front of the work.

**A barrier is an assignment with no `task:` line.** It was recorded and never carried, which
is what stops the task list being readable as a complete account of what is outstanding.
Barriers render above everything on `run/progress.html`.

**How to use it.** Find your entry, type an answer on the `A:` line if it has one, and change
`[ ]` to `[x]`. That is the whole protocol. The next run picks it up, and it becomes a numbered
task on `PROJECT-TASKS.md`.

**An entry leaves this list the moment it becomes a task.** That is the point of the list: what
is left on it is what still needs a decision from you, so a carried item lingering here is
just the task list again with buttons on it. Promoted entries move to
`review/RETIRED-ASSIGNMENTS.md` carrying the task number they went to, and the task itself is
the live record from then on. An empty list is the correct and expected end state.

This file is regenerated by `tools/build/build_intake.py` on the same timer as the progress page.
The skeleton comes from the sources; your ticks, answers, task numbers and prose are merged
back over the top and are never overwritten. Nothing is ever deleted — an entry whose source
goes away drops off this list and is archived to `review/RETIRED-ASSIGNMENTS.md` with
everything you typed on it.

---
"""

KIND_ORDER = {"question": 0, "request": 1, "finding": 2}


def slug(kind: str, ident: str) -> str:
    """Stable id per source item. Stability is the whole contract: it is what lets a tick
    survive regeneration, so it must never be derived from the title, which gets reworded."""
    ident = re.sub(r"[^A-Z0-9]", "", ident.upper())
    letter = kind[0].upper()
    # Do not double the letter when the source id already starts with it: question `Q1` is
    # `A-Q1`, not `A-QQ1`. Cosmetic, but these ids are what Garrett types next to a tick.
    return "A-" + (ident if ident.startswith(letter) else letter + ident)


def parse_existing(path: Path) -> dict:
    """Everything Garrett can type, per entry id. Regenerating without this would wipe it."""
    if not path.exists():
        return {}
    kept, cur = {}, None
    for line in path.read_text().splitlines():
        m = ENTRY_HEAD.match(line)
        if m:
            cur = {"box": False, "dropped": False, "task": "", "answer": "",
                   "brief": "", "edit": "", "blocked": "", "prose": [],
                   "title": m.group(3) or ""}
            kept[m.group(1)] = cur
            continue
        if cur is None:
            continue
        b = BOX.match(line)
        if b:
            cur["box"] = b.group(1).lower() == "x"
            cur["dropped"] = b.group(1) == "-"
            continue
        for rx, key in ((TASK_LINE, "task"), (ANSWER_LINE, "answer"),
                        (BRIEF_LINE, "brief"), (EDIT_LINE, "edit"),
                        (BLOCKED_LINE, "blocked")):
            g = rx.match(line)
            if g:
                cur[key] = g.group(1).strip()
                break
        else:
            # Everything this generator emits itself must be skipped on the way back in, or
            # regeneration re-emits it as if Garrett had typed it. SECTION is the one that got
            # away: `**Requests**` was read as prose belonging to the last question and written
            # out again below it, so the file grew one spurious header per run — fifteen of
            # them had piled up under A-Q9 by the time this was caught. A round-trip generator
            # has to recognise its own output, and a header is output.
            if line.startswith(("from:", "owner:", "frozen:", "needs:")) \
                    or line.startswith("## ") or line.startswith("---") \
                    or SECTION.match(line) or RETIRED_NOTE.match(line):
                continue
            cur["prose"].append(line)
    # Trailing blanks are ours too — the entry separator. Left in, they accumulate exactly
    # like the headers did, just invisibly.
    for k in kept.values():
        while k["prose"] and not k["prose"][-1].strip():
            k["prose"].pop()
    return kept


def gather(root: Path) -> list[dict]:
    """Every open item from every source, in one shape."""
    out = []

    audit_md = root / "AUDIT.md"
    if audit_md.exists():
        text = audit_md.read_text()
        for q in parse_questions(text):
            out.append({"id": slug("question", q["id"]), "kind": "question",
                        "title": q["title"], "src": f"AUDIT.md {q['id']}",
                        "owner": "garrett", "answer": q["answer"]})

    ledger = root / "GARRETT-REQUESTS.md"
    if ledger.exists():
        for e in parse_requests(ledger.read_text()):
            # Only entries that are still open AND name no task. One that already names a task
            # is not an assignment any more -- it is being carried, and repeating it here would
            # rebuild the duplicate-listing problem this file exists to end.
            #
            # `held` entries are ORDINARY assignments. An earlier pass rendered them as a
            # third state, "frozen", with no controls -- Garrett, 2026-08-20: *"i never gave
            # you instruction of 'frozen' items"*. He is right: he defined exactly two actions,
            # tick and delete, and inventing a state that accepts neither takes the decision
            # off him. `held` is a fact about the ledger's history, not a page state; it
            # belongs in the entry's brief, where it informs his choice instead of pre-empting
            # it.
            if e["state"] == "intake":
                # The ledger entry's own `brief:`/`blocked:`/`edit:` lines, carried across.
                # They were not, and the consequence was reported by Garrett looking at the
                # page: *"reason not recorded this gave me no information; fix it to provide
                # information"*. He was reading a row whose source held several paragraphs
                # about exactly why the item was not a task -- the page was not hiding the
                # reason, nothing ever handed it the reason. An assignment surface whose one
                # job is to let him decide, rendering a warning where the decision-relevant
                # sentence belongs, is the failure and not the flag.
                #
                # Explicit fields, and deliberately NOT scraped out of the prose. A scrape
                # would put a sentence in front of him that nobody wrote for him, and it
                # would always succeed -- so the day a brief is genuinely missing it would
                # print something anyway. Absent stays visibly absent.
                fields = ledger_fields(e["body"])
                out.append({"id": slug("request", e["id"].replace("-", "")),
                            "kind": "request", "title": e["title"],
                            "src": f"GARRETT-REQUESTS.md {e['id']}",
                            "owner": "coder", "answer": "",
                            "brief": fields["brief"], "edit": fields["edit"],
                            "blocked": fields["blocked"]})

    surface = root / "AUDIT-SURFACE-2026-08-19.md"
    if surface.exists():
        stext = surface.read_text()
        # The audit surface records its own dispositions in prose; a finding already named by a
        # task is carried and is skipped for the same reason as above.
        for item in parse_audit(stext):
            if item["bucket"] not in ("open", "other"):
                continue
            body = item_body(stext, item["n"])
            if TASK_REF.search(body):
                continue
            out.append({"id": slug("finding", "I" + item["n"]), "kind": "finding",
                        "title": f"item {item['n']} — {item['name']}",
                        "src": f"AUDIT-SURFACE-2026-08-19.md item {item['n']}",
                        "owner": "coder", "answer": ""})

    out.sort(key=lambda a: (KIND_ORDER.get(a["kind"], 9), a["id"]))
    return out


def ledger_fields(body: str) -> dict:
    """`brief:`, `blocked:` and `edit:` out of a ledger entry's body.

    First occurrence of each wins, and only at column zero: a `blocked:` inside a quoted line
    is somebody's words, not a directive, which is the same distinction `note:` continuation
    lines have to make in `PROJECT-TASKS.md`.

    Returns empty strings rather than raising. A ledger entry written before these fields
    existed is not malformed, it just has nothing to say here -- and the page rendering that
    absence honestly is the point.
    """
    got = {"brief": "", "blocked": "", "edit": ""}
    for line in body.splitlines():
        for key in got:
            pre = key + ":"
            if not got[key] and line.startswith(pre):
                got[key] = line[len(pre):].strip()
    return got


def item_body(text: str, n: str) -> str:
    """The prose under one audit item heading, so a task reference inside it can be seen."""
    lines, keep, body = text.splitlines(), False, []
    for line in lines:
        m = AUDIT_HEAD.match(line)
        if m:
            keep = m.group(1) == n
            continue
        if keep:
            if line.startswith("## "):
                break
            body.append(line)
    return "\n".join(body)


def render(assignments: list[dict], kept: dict) -> str:
    out = [HEADER]
    # Same two exclusions as the page, and they must stay the same two: a barrier count here
    # that disagrees with the one on run/progress.html is two readings of one number, which is
    # the failure the single-state-document rule exists to prevent.
    barriers = [a for a in assignments
                if not kept.get(a["id"], {}).get("task")
                and not kept.get(a["id"], {}).get("dropped")]
    ready = [a for a in barriers if kept.get(a["id"], {}).get("box")]

    # Singular when there is one. The count is the first thing on the page and "1 barriers"
    # reads as a generator talking to itself rather than a report anybody wrote -- which is
    # the wrong impression for the one figure here that is supposed to make somebody act.
    noun = "barrier" if len(barriers) == 1 else "barriers"
    out.append(f"\n**{len(barriers)} {noun}** — assignments with no task. "
               f"**{len(ready)}** of them are ticked ready and waiting on me to promote.\n")

    last_kind = None
    for a in assignments:
        k = kept.get(a["id"], {})
        if a["kind"] != last_kind:
            # A rule and a bold line rather than a heading: `##` is the entry level, and a
            # section heading at the same level would parse as an entry with no id.
            out.append(f"\n---\n\n**{a['kind'].title()}s**\n")
            last_kind = a["kind"]
        out.append(f"## {a['id']} [{a['kind']}] — {a['title']}")
        out.append("[-]" if k.get("dropped") else ("[x]" if k.get("box") else "[ ]"))
        out.append(f"from: {a['src']}")
        out.append(f"owner: {a['owner']}")
        # Hand-authored, so what is on disk WINS over the generated default. The default exists
        # only so a new entry never renders with an empty `why not a task` line; the moment one
        # is written by hand, regeneration must not touch it.
        brief = k.get("brief") or a.get("brief", "")
        edit = k.get("edit") or a.get("edit", "")
        if brief:
            out.append(f"brief: {brief}")
        if edit:
            out.append(f"edit: {edit}")
        # `blocked:` was PARSED and never written back, so every hand-typed reason survived
        # exactly until the next generator run and then vanished -- and the page's why-column
        # went back to "reason not recorded" with no trace of what had been there. Fourth
        # occurrence in this repo of a generator eating a field it can read; the rule is that
        # anything in the parse table above has to appear here too.
        blocked = k.get("blocked") or a.get("blocked", "")
        if blocked:
            out.append(f"blocked: {blocked}")
        if a["kind"] == "question":
            out.append(f"A: {k.get('answer') or a.get('answer') or ''}".rstrip())
        if k.get("task"):
            out.append(f"task: {k['task']}")
        prose = "\n".join(k.get("prose", [])).strip("\n")
        if prose:
            out.append(prose)
        out.append("")

    return "\n".join(out).rstrip("\n") + "\n"


def render_retired(kept: dict, seen: set) -> str | None:
    """Entries whose source no longer lists them, for the archive file. None if there are none.

    Garrett, 2026-08-20: *"retired items can move to a dedicated folder and drop of the list"*.
    They used to sit in a `## Retired` section at the foot of INTAKE.md, and that was wrong in
    the way he photographed: an entry that got RESOLVED -- its ledger status now names a task,
    or names the file its rule was written into -- came back as `retired — source no longer
    present` with the title gone and a BARRIER label still on it. Resolving an item made it
    look more alarming than leaving it alone, which is exactly backwards.

    Off the list, but not deleted. An entry may carry a tick, an answer or a brief, and
    discarding the one action this file asks of Garrett would be the worst thing it could do.
    `review/` is where this repo already puts things that are finished but not forgotten --
    `CLOSED-TASKS.md` is the same idea for tasks -- so the archive goes beside it rather than
    inventing a second convention.
    """
    retired = sorted(i for i in kept if i not in seen)
    if not retired:
        return None
    out = ["# RETIRED-ASSIGNMENTS.md — assignments that are finished with the intake surface",
           "",
           "Written by `tools/build/build_intake.py`. An entry lands here by one of three exits, and "
           "the fields below say which: it carries a `task:` line, so it was **promoted** and "
           "the task is the live record now; it carries `[-]`, so Garrett **dropped** it; or "
           "its source stopped listing it, having resolved it elsewhere. Nothing here is "
           "outstanding — that is what leaving INTAKE.md means — but ticks, answers, task "
           "numbers and briefs are preserved verbatim, because they were typed by hand and "
           "this file is the only copy left.",
           ""]
    for i in retired:
        k = kept[i]
        # The title goes in. Without it the archive was a list of bare ids, which is a record
        # only in the sense that a filing cabinet with no labels is a record.
        title = k.get("title") or ""
        out.append(f"## {i} [retired]" + (f" — {title}" if title else ""))
        out.append("[-]" if k.get("dropped") else ("[x]" if k.get("box") else "[ ]"))
        # Every hand-authored field, same as a live entry. Retiring an item must not be a
        # quiet way of losing the sentence explaining why it was never taken to task.
        for key, label in (("brief", "brief"), ("edit", "edit"),
                           ("answer", "A"), ("task", "task")):
            if k.get(key):
                out.append(f"{label}: {k[key]}")
        prose = "\n".join(k.get("prose", [])).strip("\n")
        if prose:
            out.append(prose)
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def write_atomic(path: Path, text: str) -> None:
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False,
                                     prefix=path.name + ".", suffix=".tmp") as fh:
        fh.write(text)
        tmp = Path(fh.name)
    # 0600, deliberately and every time. This file restates the contents of
    # GARRETT-REQUESTS.md, which is 0600 and uncommitted; a derived file that relaxes the
    # permissions of its source is a leak with an extra step. `NamedTemporaryFile` happens to
    # create at 0600 already, so the first write was right by luck -- this makes it right on
    # purpose, and stops a later `copymode` from widening it back.
    tmp.chmod(0o600)
    tmp.replace(path)


#: `Folds #36 #41 #42 ...` on a task's detail line. The 2026-08-20 consolidation collapsed 58
#: numbered tasks into #73-#77 and recorded the mapping exactly here, in the surviving tasks'
#: own blocks -- which is the right place for it, since a fold is a fact about the task that
#: did the folding. Nothing read it, so 27 assignments pointed at numbers that had been folded
#: away and every one of them was counted as CARRIED. The page said 1 barrier and meant 28.
FOLDS_LINE = re.compile(r"^\s*Folds ((?:#\d+[\s,]*)+)")


def fold_map(root: Path) -> dict[str, str]:
    """old task number -> the number that folded it, from the `Folds` lines on disk.

    Read from `PROJECT-TASKS.md` and `review/CLOSED-TASKS.md` and nowhere else.
    `review/CONSOLIDATED-TASKS-2026-08-20.md` holds the pre-consolidation blocks and is
    deliberately NOT read: adding it to the resolver would make it a third document that
    describes current state, which is the one thing this repo has a standing rule against.
    The `Folds` line is the mapping; the archive is the detail those numbers used to carry.

    A fold is followed one hop only. `#36 -> #76` resolves; a chain would mean a task folded
    a task that had already folded others, and the honest response to that is the warning,
    not a graph walk that quietly papers over a renumbering nobody recorded.
    """
    out: dict[str, str] = {}
    for name in ("PROJECT-TASKS.md", "review/CLOSED-TASKS.md"):
        p = root / name
        if not p.exists():
            continue
        current = ""
        for line in p.read_text().splitlines():
            m = TASK_ROW.match(line)
            if m and m.group(2).startswith("#"):
                current = m.group(2)
                continue
            fm = FOLDS_LINE.match(line)
            if fm and current:
                for old in re.findall(r"#\d+", fm.group(1)):
                    # First writer wins, and a collision is left to the duplicate-number
                    # check above rather than resolved silently here.
                    out.setdefault(old, current)
    return out


def check_task_pointers(root: Path, kept: dict) -> list[str]:
    """Resolve every `task: #NN` against the task files. Returns human-readable problems.

    This exists because `TASK_REF` only ever asked whether a task reference was *present*, not
    whether it pointed at anything. That is the whole gap: `covered` in build_progress.py and
    the barrier count in `render` above both treat "has a `task:` line" as "is being carried",
    so a pointer at a task number that does not exist reads on the page as carried work. It is
    a barrier wearing a task's clothes, and it is invisible precisely where the count claims to
    be complete.

    It was not hypothetical. `7fcc96d` numbered 58 assignments and reused #60, #61, #62 and #63,
    which had already been spent on tasks archived in the same window -- so four numbers each
    named two different pieces of work, and `A-R99` pointed at a #62 that resolves two ways.
    Nothing reported it, because nothing looked.

    Both task files are read: a pointer at a CLOSED task is resolved, not dangling. An
    assignment whose task is finished is a normal state and must not be reported as a barrier.

    Called with `handled` (the archive merged under the live list), not with `kept`. Promotion
    moves an entry -- and therefore its `task:` line -- off INTAKE.md and into the archive, so
    checking the live list alone would mean every pointer became unverifiable at the exact
    moment it started being the only record of where the work went. The archive is where the
    pointers live now, so that is what has to be checked.

    WARN, not fail. `render_retired` and the INTAKE write are the load-bearing outputs and a
    stale pointer must not stop them landing -- and #62's surviving pair is inside
    `review/CLOSED-TASKS.md`, which is archived verbatim and is not ours to renumber. A check
    that made the documented build sequence exit non-zero over a historical record would be
    turned off, and then it would catch nothing at all.
    """
    folds = fold_map(root)
    seen: dict[str, list[str]] = {}
    for name in ("PROJECT-TASKS.md", "review/CLOSED-TASKS.md"):
        f = root / name
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            m = TASK_ROW.match(line)
            if m and m.group(2).startswith("#"):
                seen.setdefault(m.group(2), []).append(f"{name}: {m.group(3)}")

    problems = []
    for num, where in sorted(seen.items(), key=lambda kv: int(kv[0][1:])):
        if len(where) > 1:
            problems.append(f"task {num} is used by {len(where)} tasks: "
                            + " | ".join(where))

    for aid, k in sorted(kept.items()):
        ref = k.get("task")
        if not ref:
            continue
        m = TASK_REF.search(ref)
        if not m:
            continue
        num = m.group(0)
        if num not in seen and num in folds:
            # Folded, not dangling. The work was carried into the folding task, so the
            # assignment IS carried and reporting it as a barrier would be the opposite
            # error -- 27 false barriers instead of 27 hidden ones.
            continue
        if num not in seen:
            problems.append(
                f"{aid} points at {num}, which is in neither task file and is named by no "
                f"`Folds` line. It reads as carried on the page and is not: nothing on disk "
                f"says where that work went. Either give it a task number that exists, or "
                f"drop it with a reason.")
        elif len(seen[num]) > 1:
            problems.append(f"{aid} points at {num}, which resolves {len(seen[num])} ways")
    return problems


def main() -> int:
    # --root for the same reason build_progress.py has one: the test suite points both
    # generators at a temp tree, and without it the held-entry tests would either have to
    # rewrite the real INTAKE.md or stop exercising the ledger -> intake -> page path that is
    # the thing actually being asserted.
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    root = ap.parse_args().root
    target = root / "INTAKE.md"
    archive = root / "review" / "RETIRED-ASSIGNMENTS.md"
    kept = parse_existing(target)

    # The archive is an INPUT, not just an output. Two things depend on that.
    #
    # It stops the archive eating itself: `render_retired` builds the whole file from what it
    # is given, and what it was given was INTAKE.md alone -- which by then no longer contained
    # the retired entry, because that is what retiring it meant. So each run rewrote the
    # archive from a source one entry shorter than the run before.
    #
    # And it is what makes Drop permanent. Garrett, 2026-08-20: *"i click drop and it doesnt
    # remove from intake list"*. A dropped entry leaves the list below; the only record that it
    # was ever dropped is in the archive, so if the archive were not read back the source would
    # regenerate the entry on the next run as though it were brand new.
    archived = parse_existing(archive)
    handled = {**archived, **kept}          # INTAKE.md wins: it is the more recent edit

    assignments = gather(root)
    # Drop means gone. It used to mean struck through and still listed, on the reasoning that
    # removing a row hides the evidence -- but the evidence belongs in the archive, and leaving
    # thirty dropped rows on the list defeats the one thing the list is for. Nothing is lost:
    # every dropped entry is written to `review/RETIRED-ASSIGNMENTS.md` below, with whatever
    # Garrett typed on it.
    # Two exits, not one, and they leave by the same door. Dropped means Garrett said no;
    # PROMOTED means it is already a task, and both are finished with this file.
    #
    # Garrett, 2026-08-20: *"push intake.md to task"*, with the page in front of him reading
    # "28 assignments -- 0 barriers -- 28 promoted to tasks" and then listing all 28 anyway,
    # each with a Ready and a Drop button. This file calls itself "the queue in front of the
    # work"; a queue that everything passes through and nothing ever leaves is not a queue, it
    # is a second copy of the task list that asks him to tick boxes on work already under way.
    #
    # `handled`, not `kept`: a promoted entry has already left INTAKE.md, so its `task:` line
    # is in the archive now and reading only the list would promote it once and then hand it
    # straight back the next run.
    def _exited(a) -> bool:
        h = handled.get(a["id"], {})
        return bool(h.get("dropped") or h.get("task"))

    live = [a for a in assignments if not _exited(a)]
    text = render(live, kept)

    # The archive first, then the list. If the archive write fails, the entries are still in
    # INTAKE.md and the next run tries again; do it the other way round and a failure between
    # the two writes loses them, and they are the only copy of anything Garrett typed.
    seen = {a["id"] for a in live}
    for a in assignments:                   # keep a title on entries the sources still know
        if a["id"] in handled and not handled[a["id"]].get("title"):
            handled[a["id"]]["title"] = a["title"]
    retired = render_retired(handled, seen)
    if retired is not None:
        archive.parent.mkdir(exist_ok=True)
        if not archive.exists() or archive.read_text() != retired:
            write_atomic(archive, retired)
            print(f"wrote {archive}")

    # Pointer integrity, reported after the writes so a warning can never cost a write. See
    # check_task_pointers for why this warns rather than fails.
    for problem in check_task_pointers(root, handled):
        print(f"WARNING: {problem}", file=sys.stderr)

    # Idempotent: identical content is not rewritten, so this never fights an open editor over
    # mtime and never shows up in `git status` for having run.
    if target.exists() and target.read_text() == text:
        return 0
    write_atomic(target, text)
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
