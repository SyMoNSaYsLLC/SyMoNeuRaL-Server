# SyMoNeuRaL — project authority and working agreements

**This is the canonical, provider-neutral operating contract for this repository.**
Migrated from `.claude/CLAUDE.md` on 2026-09-08 as part of retiring the provider-specific
authority path. The rules are unchanged; what changed is that they no longer live in a
directory named after one vendor's tool, and no longer read as instructions to that tool.

Any coding agent or person working in this repository follows this file. Where the text
below still says "the agent", read it as whoever is doing the work.

| Question | File |
|---|---|
| What are the rules? | **this file** |
| What do the words mean? | `ops/authority/GLOSSARY.md` |
| What is the current verified state? | `ProjectStatus.md` |
| What is the state, what is left, what will bite me? | `HANDOFF.md` |
| Every folder and what it is for | `README.md` |
| What may leave this box? | `ops/registry/EXPORTS.md` |
| How do I install, start, verify or roll back the API? | `RUNBOOK.md` |
| Where does each surface listen? | `ops/PORTS.tsv` — rendered as `ops/registry/PORTS.md` |
| What runs behind a surface, what invokes it, what does it load, does it take the GPU lease? | `ops/RUNTIMES.tsv` — rendered as `ops/registry/RUNTIMES.md` |
| How does any of this come back after a reinstall? | `restore/` — and `THIRD-PARTY-REBUILD-MANIFEST.tsv` for pinned upstreams |
| Why is the code like this? | `git log` |

There is one canonical current-state source (`ProjectStatus.md`) and one canonical handoff
source (`HANDOFF.md`). Do not create a third.

The two registries are indexed here for the reason `restore/` had to be: an authority nobody
is pointed at gets rediscovered as a gap. Both follow the same pattern — **a TSV that is the
record, a reader in `backend/apps/`, a generator that renders the Markdown, and a test
asserting the registries agree with each other.** The Markdown is a rendering, never the
record; hand-editing it is a change that the next generator run silently discards.

`ops/registry/RUNTIMES.md` is **not** `backend/hardware/docs/RUNTIME-PROFILES.md`, which is one word away and
opens *"Status: stub. A contract for something not yet built."* The first is a reading of
this disk; the second is a maturity ladder for runtimes that mostly are not here, written
against the retired `engines/symoneural-*` layout. Neither supersedes the other.

`RUNBOOK.md` (added 2026-09-09 by the commissioning pass) is **operational procedure, not
state and not rules** — the commands in order, and what their output looks like. It is
indexed here rather than left unlisted so it cannot quietly become a third authority: if you
find yourself putting a rule or a current-state figure in it, that belongs in this file or
`ProjectStatus.md` instead.

---

## Original working agreements, migrated verbatim below


Repo for symoneural.com: the public site, the live API behind it, the CUDA engine, and
the engineering manual the site's numbers come from.

## Coder rotation — owner instruction, 2026-09-02 (R-182 / R-183)

The current order is **Codex → Claude → Codex**, repeating. Codex writes the initial
execution plan. Each receiving coder reviews the prior evidence, executes a bounded task
batch, verifies the results, and writes the next execution plan for the next coder.
Complete useful work within the agreed batch; do not hand off routine unfinished fixes.

Once **SyMoNeuRaL Coder** proves this complete cycle using the local Symon model, expand
to **Codex → Claude → SyMoNeuRaL Coder → Codex**. Its admission requires a real bounded
workspace task: read the plan and files, use the model and authorized tools, apply a change,
run meaningful verification, save the response, resume the session, and produce a usable
next-coder plan. A terminal page or READY badge is insufficient.

The continuing objective is a trained, evaluated Symon model and working integration across
Chat/cowork, Coder, Image, Remix, Studio, LoRA/training, Sigils, Miner, and the remaining
requested channels. Identify training data/configuration, model/adapter artifacts and
held-out evaluation evidence before claiming the training milestone. Restoring base weights
alone does not complete it. Each channel uses the appropriate runtime: diffusion, language
inference, training, mining, and CPU orchestration remain distinct workloads governed by
the existing resource controls.

Use the existing **request → intake → numbered task → execution response → next task**
records. PROJECT-TASKS.md is the sole work list; HANDOFF.md records the next
executor and handoff links. Keep owner: coder and name the particular executor in task
notes and the handoff. The later owner rule still applies: unblocked authorized work
promotes without an additional Ready click.

Every execution batch saves two linked Markdown artifacts in the appropriate review/ops
evidence location: its measured response and the next coder's plan. Use unique dated names;
preserve earlier versions. The response records request/task IDs, incoming plan, baseline
and result revision/artifact identity, actual changes, tests and real application evidence,
remaining defects, and deployment/rollback. The next plan names its recipient, source
response, task IDs, objective, scope, prerequisites, files/services, acceptance checks,
constraints, rollback, and completion evidence. It must stand alone without chat history.

The receiving coder checks the handoff against current source/runtime state before
executing. Generated plans and old reports cannot override newer owner instructions.
Preserve failed evidence, user data, private training assets, and credentials. Record
genuine blockers and continue unaffected work.

R-183 adds a control-board launcher with all single-coder selections, all three pairs,
and the three-coder batch selection. Its specification is
backend/coders/docs/coder-rotation-launcher-spec.md and implementation is carried under #109,
with #77/#90/#104 dependencies. Until that launcher is implemented and explicitly started
for an authorized batch, handoffs are file-based; this standing rule alone neither dispatches
another agent nor creates a scheduler. No additional reboot is authorized by this workflow.

## Shared coder sessions and cooperation — R-184/R-185/R-187

The control board has separate Rotation, Multi-response, and Training modes. One prompt
in Multi-response produces separately attributed answers from all selected coders. The user
chooses among conflicting proposals and may request a bounded discussion. Training delivery
requires every selected trainer's explicit approval of the identical final prompt; changes
invalidate approval. Never mistake consensus or an in-context lesson for trained weights.
Follow backend/coders/docs/coder-rotation-launcher-spec.md and its real acceptance requirements.

Claude, Codex, and Symon are collaborators. Preserve each other's changes and evidence,
re-read shared files before editing, identify the active executor and scope, and explain
disagreements with measurements and concrete options. Do not duplicate a completed task,
overwrite a colleague's work, or dispatch the next coder without the authorized handoff.

## START HERE — you have just been opened in this repo and Garrett said "hi"

Do not ask him what to work on. He has already answered, standing, 2026-08-20: *"i want to
be able to cd /Symoneural lauch claude and say hi and the agent already know what we need to
do"*. Everything you need is on disk. Read it, then say what you are picking up and why.

**Three commands, in this order.** They take about a minute and they answer "what is the
state of this project" without a single question.

```bash
python3 tools/build/build_progress.py     # rebuild the page from the disk -- never trust a stale one
xdg-open run/progress.html          # or open file:///home/google/Symoneural/run/progress.html
sed -n '1,80p' PROJECT-TASKS.md     # the standing rules for the task list itself
```

`run/progress.html` is the handover artefact and it is deliberately complete. Garrett:
*"with our progress.html even if my computer blows up the next agent will have exactly what
it needs to pick up the project and not miss a beat"*. It renders every open task with a
**measured** percentage, every assignment waiting on him, the request ledger's depth, the
four test suites with the commit each count was read on, and the comments people have left
on individual tasks. It is generated from the files below, so it cannot drift from them; if
it looks wrong, the file it reads is wrong and that is the bug.

**Then pick up work like this:**

1. Open **`PROJECT-TASKS.md`**. That is the only place work comes from. Take the lowest-
   numbered open task whose blockers are clear, or the one Garrett just named.
2. Anything not on that list is **not yours to start**, however obviously useful. The way in
   is `INTAKE.md`, and the gate is Garrett ticking a box — not your judgement that it is
   worth doing. This is the one rule that keeps the list meaning what it says.
3. Work the task. When behaviour changes, prove it changed: break it on purpose and watch a
   test fail, then fix it. A test that passes before and after your change tested nothing.
4. Regenerate and commit — see *Completing a task*, below.

**The one thing to be suspicious of on arrival:** a figure with no commit SHA beside it. This
project has published a test count that was never true of the commit it sat next to, because
somebody carried it forward and re-dated it. Re-measure anything you are about to rely on.

## The two surfaces, and how to complete a task

There are exactly two lists, they have different owners, and conflating them is the failure
this structure exists to prevent.

```
INTAKE.md         assignments: requests, questions, audit findings.   GARRETT ticks.
PROJECT-TASKS.md  numbered tasks.                                     THE AGENT works.

assignment  ->  (answer, if it is a question)  ->  [x] Ready  ->  task #NN  ->  done
```

**Every entry is in exactly one of three states: `done`, `task`, or `intake`.** There is no
fourth. "Pending" is a marker on a task, not a place to put something. An assignment that is
neither carried by a task nor dropped is a **barrier** — recorded and uncarried — and the
page counts them in red at the top, because an uncounted barrier is how work goes missing.
The count was 58 on 2026-08-20, and it said **0** in this file for a day and a half while it was
not 0 — the same unSHA'd carried-forward figure the rest of this file warns about. The fix is
not to re-stamp it. **Read it off `run/progress.html`, which computes it, and do not write a
number here at all**: unlike the test counts, this one is a reading of two mode-600 untracked
files, so a SHA beside it proves nothing and nobody can check it — and it expires the moment
Garrett clicks a button. It went from 3 to 4 inside the session that first stamped it, which is
as short a shelf life as a figure can have.

**But `run/progress.html` is only as fresh as the last manual run, and nothing on the page
says so.** `symoneural-progress.timer` is a `--user` unit and is **`disabled`** — measured
2026-09-09, and `disabled` against a preset of `enabled`, so it was turned off rather than
never turned on. Whether that was deliberate is with the owner (QUESTIONS-FOR-OWNER.md row
17). Until it is answered, **regenerate before you read the number**:

```bash
python3 tools/build/build_intake.py && python3 tools/lib/archive_tasks.py && python3 tools/build/build_progress.py
```

The instruction above is still right — do not write a barrier count into this file. It just
is not enough on its own: reading a stale page is how you get a confidently wrong figure from
the one source that was supposed to prevent exactly that. If the timer is later enabled, this
caveat becomes redundant rather than wrong.

What is durable is the two ways back to 0, and there are only two: **he ticks `[x]` and you give
it a task number, or he clicks Drop and the reason goes in the file.** Anything else you invent
to make the number smaller is the third state this file already rejects.

### Working a task

Tasks live in `PROJECT-TASKS.md` as `◻ #41 — Title` with an **indented** detail block. The
indentation is structural, not cosmetic: `tools/lib/archive_tasks.py` ends a task's block at the
first non-blank column-zero line, so an unindented line silently truncates its own task and
takes every line under it out of the task.

Declare machine checks so the percentage is measured rather than asserted:

```
◻ #62 — Per-app artefacts
        owner: coder                        coder | garrett; unlabelled means coder
        check: exists backend/apps          also: absent <path>
        check: grep <pat> -- <path>         also: ngrep (true when NOT found)
        check: maxcount <n> <pat> -- <path>
        resolve: OLD -> NEW                 state read from disk: NEW present, OLD gone
        note: 2026-08-20 garrett — comment  append-only; see the comments box below
```

The percentage is passing checks over declared checks, recomputed from the disk every two
minutes. A task with no checks reads `—`, never `0%`, because an unmeasured task is not an
unstarted one. **Choose checks where 100% genuinely means done** — a check that can pass
without the work being finished is worse than no check, since it will archive the task.

**If the deliverable is a program that runs, one check must be something only a real run can
turn green.** `exists`, `grep` and `ngrep` ask what is written on disk; none of them can ask
whether the thing works. #94 shipped a desktop client whose eighteen checks all went green and
whose chat surface was dead on arrival — a missing Tauri capability meant the page was never
permitted to hear the stream it had asked for, so it rendered a turn and then nothing, with no
error to read. The timer archived it two minutes later. #74 did the same at `87c4042` with two
of seven items not started. The cheap fix is a stamped smoke record committed beside the code —
`check: exists <dir>/SMOKE.md` — because that file cannot be written honestly without running
the thing. Note that a `note:` explaining the checks are insufficient does **not** help:
`archive_tasks.py` reads checks, not notes, and #94's note said exactly that and was ignored.

At 100% `archive_tasks.py` moves the block to `review/CLOSED-TASKS.md` verbatim with a line
saying what judged it finished. Nothing is deleted; the list stays a reading of what is left.

### Completing a task — the sequence, every time

```bash
python3 tools/build/build_intake.py        # assignments  -> INTAKE.md (+ review/RETIRED-*.md)
python3 tools/build/build_progress.py      # everything   -> run/progress.html
# run BOTH twice and diff: these generators re-read their own output, and one that does
# not recognise something it emits will accumulate it, one copy per run. That bug has
# now happened three times in this repo. Two runs with no diff is the check that catches it.
cd backend && python3 -m pytest apps/test_build_progress.py -q
```

Then commit, with the reason in the message — `git log` is the answer to "why is the code
like this" and is load-bearing here. Commit **between** items, not in one batch at the end.

### Ready and Drop — the two controls on the page, and nothing else

`run/progress.html` renders each assignment with two buttons, which POST to
`/local/intake` and write `INTAKE.md` directly.

- **Ready** (`[x]`) — Garrett judges it ready to become work. You then give it a task number.
- **Drop** (`[-]`) — not needed. The entry is **removed** from the list and written to
  `review/RETIRED-ASSIGNMENTS.md` with everything typed on it. Removed, not struck through:
  *"i click drop and it doesnt remove from intake list"* was reported as a bug and fixed.

**Do not invent a third state.** A "frozen"/"deferred"/"parked" bucket was proposed and
rejected outright, and the reason generalises: a third state takes the decision away from
Garrett while looking like it recorded one. If something cannot be carried, it is dropped
with a reason, and the reason goes in the file.

His standing test for whether an assignment should exist at all: *"if it isnt going to break
our project and its something that will resolve itself naturally DROP IT"*. A rule already
written down is not outstanding work. A request already satisfied is not outstanding work.

### Assigning work to another agent

Tasks are labelled `owner: coder` or `owner: garrett`, and **a coder-owned task can be handed
to any coding agent** — that is what the label is for. Unlabelled means coder: the default
claims work rather than parking it on Garrett.

`owner: garrett` is reserved for exactly five things, and nothing else qualifies: physical
hardware access, credentials only he holds, third-party dashboards with no API, money, and
legal or business decisions. The standing rule is **FIX, not FILE** — filing a task back to
him because it is awkward is the failure mode this list is guarding against.

An agent picking up a `garrett` task should read its `[ ]` checkbox as a handoff: he ticks it
when he has done his half, which sets the state to `ready for review` — deliberately **not**
`done`, so the task cannot archive itself before anyone reads his answer.

### The comments box

Every task on the page has one. A comment is stored as an indented, append-only `note:` line
in that task's own detail block, so it lives beside the thing it is about and travels with it
in `git log`. Append-only means two people cannot overwrite each other and no generator run
can eat a comment. Keep the `note:` prefix on **every** line of a multi-line comment: an
unindented continuation would truncate the task, and a continuation reading `owner: garrett`
would be parsed as a directive instead of as somebody's words.

### Never do these to the task surface

- **Never create a second state document.** Three files once claimed to describe current
  state and agents kept acting on the stale one. If a harness offers you its own task list,
  it is a second state document; `PROJECT-TASKS.md` is the canonical one.
- **Never carry a figure forward and re-date it.** Re-run it or drop it.
- **Never hand-edit `INTAKE.md`'s skeleton** — it is generated. Ticks, answers, task numbers,
  briefs and prose are merged back over the top and preserved; everything else is rewritten.
- `INTAKE.md` and `GARRETT-REQUESTS.md` are **mode 600** and stay that way. `/api*` is proxied
  to the public internet by `ops/Caddyfile`, which is why the write endpoints are `/local/*`
  behind a peer-address check that also refuses proxy headers.

## Where to look — there is exactly one of each

Three files once all claimed to describe "current state" and agents kept acting on the stale
one. There is now one of each, and everything superseded lives in `ops/history/archive/` behind a
README that says so.

| Question | File |
|---|---|
| What are the rules? | **this file** |
| What is the state, what is left to do, what will bite me? | **`HANDOFF.md`** |
| Build, deploy, GPU, environments, honesty, trade secret, serving, branding? | **`ENGINEERING.md`** |
| Suite counts, the ladder, how to run the tests? | **`ops/registry/MEASUREMENTS.md`** |
| What may leave this box? | **`ops/registry/EXPORTS.md`** |
| What does the hardware actually do? | `frontend/site/docs/symoneural-manual.md`, and `docs/` |
| Why is the code like this? | **`git log`** — every commit states its reason |

Do not create a second state document. Update `HANDOFF.md`.

**`demo/` no longer exists.** It was flattened into the repo root: `demo/api.py` is `api.py`,
`demo/playground.sh` is `scripts/symoneural.sh`. Any path with `demo/` in it is from before that and
is wrong.


## The engineering rules moved — R-180, 2026-08-22

Everything that used to follow this section — parallelising builds, the GPU governor, the
Python environments, the honesty rules, the trade-secret boundary, build and deploy, the
whole test-and-ladder section, `run/`, serving architecture, branding — was migrated
VERBATIM to the three files in the table above. Same words, project-owned homes. Garrett:
*"can we clean project of claude.md"*. This file keeps the agent's operating process (how
work enters, how a task is worked and completed, what never to do) and points at the rest.

**Read `ENGINEERING.md` before touching the build, the card, or an environment.
Read `ops/registry/MEASUREMENTS.md` before running or quoting a test count. Read
`ops/registry/EXPORTS.md` before any byte leaves this box.** A rule you did not read still
applies; the pointer being short is a convenience, not a shrinking of the rules.
