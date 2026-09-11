# Archive — superseded, kept for history

Nothing in this directory is current. It is here because deleting it would lose real work,
and because more than one agent has previously rediscovered a stale file at the repo root and
treated it as authoritative. **If a file is in here, do not act on it.**

The live hierarchy is stated in `.claude/CLAUDE.md`; the short version is:

| Question | File |
|---|---|
| What are the rules? | `.claude/CLAUDE.md` |
| What is the current state, what is left to do? | `.claude/HANDOVER.md` |
| What does the hardware actually do? | `MIT_AI_Training.md`, and `docs/` |
| Why is the code like this? | `git log` — every commit states its reason |

## What is in here and why

### `00-MANUAL-INDEX.md` and `01-…` through `10-…`
The original ten playbooks. **Superseded by `MIT_AI_Training.md`**, which merged them into one
document and is the source every figure on the website is drawn from. The playbooks were left
at the repo root for months and are the single most likely thing for a fresh agent to mistake
for current material — which is exactly why they are now in here rather than there.

### `HANDOVER-2026-08-16-1910.md`
The previous session's handover, written at 19:10 on 2026-08-16. Superseded by `.claude/HANDOVER.md`
in the repo root. Still worth reading for the archaeology of the CSS bugs (`.bar` collapsing
the site header) and the reasoning behind the GPU governor's design, both of which remain
true. Everything it says about paths is **wrong**, because `demo/` was flattened into the repo
root afterwards.

### `PROJECT-STATE.md`
A third state document that competed with the two handovers. Having three files that all
claimed to describe "current state" caused real confusion; there is now exactly one.

### `.claude/START-PROMPT.txt`
The previous session's kickoff prompt. Replaced by `.claude/START-PROMPT.txt` in the repo root, which
reflects the flattened layout and the current queue.

### `checkcoderswork.txt`
A build/verification dump from the cuda-samples audit — sample name, status, runtime and which
virtualenv it needed. Raw output, superseded by `frontend/site/docs/05-verification.md`.
