# SyMoNeuRaL Coder · Project · CLI — scope, and what is already built

**Scope captured 2026-08-22.** Docs and scope only. **No implementation, no folder migration, no
public filesystem route, no archive imported, no deploy.**

Three related surfaces that are not the same object: **Project/Cowork**, **Coder**, and
**CLI**. This document's main job turned out not to be recording a wish-list. It is recording
what the disk already contains, because most of what the brief asks to be built **is built**,
and filing it as new scope would have queued work that already exists.

## 0. The headline, first

Two findings, both measured on 2026-08-22, both changing what should happen next:

1. **`@symoneural code.tar.gz` contains no SyMoNeuRaL code at all.** It is 3,598 entries across
   eleven **third-party Anthropic projects**. Zero first-party files. §1.
2. **The CLI's "missing interactive UX" is not missing.** Every item on the brief's list —
   interactive session, `/help`, `/clear`, `/status`, `/tools`, `/model`, `/resume`, permission
   prompts, `@file`, multiline, Ctrl-C, markdown, streaming, resume-by-id — is implemented in
   `bin/symoneural-cli`. §3.

## 1. The archive — inspected, as authorized

Garrett authorized inspection explicitly on 2026-08-22: *"list archive contents · identify
Project/CLI/Coder-relevant files · compare against current `bin/symoneural-cli` · compare
against `backend/apps/coder` · extract requirements."* **Listed, not extracted. Nothing was
written into the tree.**

`references/symoneural code.tar.gz` — 74,707,050 B, `tar -tzf` gives **3,598 entries** under a
single top directory `symoneural code/`:

| Project | Entries | Licence, read from inside the archive |
|---|---|---|
| `anthropic-sdk-python` | 1,639 | **MIT** — "Copyright 2023 Anthropic, PBC … free of charge … to deal in the Software without restriction" |
| `claude-agent-sdk-demos` | 385 | per-demo `LICENSE` files |
| `claude-code` | 379 | **© Anthropic PBC. All rights reserved.** Use subject to Anthropic's Commercial Terms of Service |
| `claude-code-action` | 300 | `LICENSE` present |
| `claude-agent-sdk-python` | 214 | `LICENSE` present |
| `anthropic-cli` | 208 | `LICENSE` present |
| `code-migration-kit-with-claude-code` | 118 | `LICENSE` present |
| `claude-code-security-review` | 97 | `LICENSE` present |
| `claude-code-base-action` | 97 | `LICENSE` present |
| `claude-agent-sdk-typescript` | 96 | `LICENSE.md` present |
| `claude-code-monitoring-guide` | 64 | `LICENSE` present |

**Zero paths below the top directory mention `symoneural` or `symon`.** The only occurrence of
the name is the tarball's own wrapper directory. The name on the outside describes what it was
collected *for*, not what is inside it.

### What that means, and what it does not

**It does not mean the archive is rejected.** It is exactly the thing Garrett's own clean-room
rule already contemplates — *"Claude desktop / Claude terminal / DeepSeek Harness references may
be used only for behavior and UX comparison … The experience is reimplementable. The source is
not."*

But it **changes the operation**. "Extract requirements first" reads very differently once the
contents are known:

- **There is no old SyMoNeuRaL Project or CLI code in here to recover.** Any plan shaped as
  "restore our previous implementation from the archive" has nothing to restore.
- **`claude-code` is all-rights-reserved.** Its licence is one line and it is not permissive.
  It may be read for behaviour. Copying from it is prohibited by its own terms, independent of
  any repo rule.
- **`anthropic-sdk-python` is MIT**, so it is *legally* copyable with attribution. It still must
  not be vendored here: `LICENSES.md` governs what ships, `references/` is untracked on purpose,
  and pulling in 1,639 files of somebody else's SDK to obtain behaviour we already have is not a
  requirement, it is a dependency.
- **The comparison the brief asked for has an answer**, and it is §3 and §4: our CLI and Coder
  already implement the behaviour these projects would have been consulted for.

**Classification is unchanged: AUDIT.** Inspected at the listing level; per-file review of 3,598
third-party entries is not done and is not proposed. Nothing is imported, nothing is committed,
and `references/` stays untracked (`.gitignore:68`).

## 2. Project / Cowork — a Chat capability, and #83 stands

Garrett, 2026-08-22: *"SyMoNeuRaL Project should become a capability inside Chat, not an
unrelated standalone app"*, and *"Project/cowork/copilot belongs inside Chat."*

> **SyMoNeuRaL Project is the cowork mode inside Chat: a project-aware conversation that can
> reason over repo state, tasks, files, and implementation plans. It is not a raw shell and it
> is not a public filesystem endpoint.**

This resolves the conflict written up in `symoneural-application-lab.md` §5. **Open task #83
stands as written** — *"Remove SyMoNeuRaL Project completely; put a cowork inside SyMoNeuRaL
Chat"* — and its `absent backend/apps/project` check is consistent with this direction rather
than in conflict with it.

**Measured:** `backend/apps/project/` is 5 tracked files, and the rack carries a
`SyMoNeuRaL Project` row. Both remain during transition. **#83 is a task and gets worked as a
task** — not by this document, and not as a side effect of a migration.

Capability scope: project-aware conversation · repo/file/task context · code review ·
implementation planning · planning before edits · task-state awareness · resumeable sessions ·
Coder/CLI tools through the gates in §4. **No raw shell. No public filesystem endpoint.**

## 3. CLI — the interactive client already exists

`bin/symoneural-cli` is **1,809 lines**. Line 1349 states it plainly: *"The interactive client.
`symoneural-cli` with no arguments, or `repl`."*

**Subcommands, all thirteen:** `agent · chat · image · mcp · ravencalc · repl · residency ·
state · status · tool · tools · upgrade · _stop-chat`.

*(A first pass of this audit reported `agent`, `tools`, `tool` and `state` as absent. That was
wrong — they register through a local `studio()` helper rather than `add_parser` directly, and
grepping for the wrong call shape produced four false absences. Recorded because the correction
is the useful part: a grep that does not know how the code registers things reports missing
features that are there.)*

### The brief's "missing interactive UX", measured against the file

| Brief says missing | Actually |
|---|---|
| bare invocation opens an interactive session | **present** — `:1349`, `repl`, `:1492` prints `SyMoNeuRaL Code  interactive session` |
| `/help` `/clear` `/status` `/tools` `/model` `/resume` | **all present** in the `SLASH` table `:1363-1371` — plus `/session`, `/permissions`, `/exit` |
| permission prompt before side-effect tools | **present** — `--permissions ask\|deny\|allow`, gating `delete_path`, `env_set`, `run_command`, `write_file`; `auto` asks with a terminal and denies without one |
| explicit mode that skips prompts | **present** — `--dangerously-allow-all`, and `--allow-tool NAME` to exempt one |
| resume by session id | **present** — `/resume [ID]`, `--session NAME` |
| picker over existing transcripts | **present** — `/resume` with no argument lists recorded sessions; `:1388` globs `run/agent-*.json` by mtime |
| `@file` references | **present** — `expand_at()` `:1394`, with a cap that **says when it clips**: *"silently sending half a file is the same class of bug as silently dropping a rack row"* |
| multiline paste | **present** — `:1432-1443` |
| Ctrl-C interrupt | **present** — *"Ctrl-D does the same; Ctrl-C only cancels the line"* |
| markdown rendered in terminal | **present** — `render_markdown()` `:850`, used at `:1262`. `:803` records why: *"The loop answers in markdown and this client printed the source"* |
| streaming as it arrives | **present** — `agent` is *"one agent turn, streamed — thinking, tool calls, results, answer"* |
| visible status line | **present** — elapsed stamps `:422-426`; `:1078` notes they are elapsed-since-asked on purpose |

**So the CLI's classification is PROD direction with the interactive UX already built**, not
"engine exists, interactive UX incomplete". `-c` continuation and `run/agent-<session>.json`
threading are real (`:578-586`, `:1714-1717`), and the reason the thread lives client-side is
recorded: the server keeps no session state to resume.

**What is genuinely open** is the brief's *operator* command list — registry inspection, model
load/unload/switch, job submit/status, hardware probe, workflow validation. Those are
**ModelOps/RuntimeOps surfaces the CLI would query**, and §6 is the rule about that.

## 4. Coder — the security posture the brief asks for is already implemented and tested

> **SyMoNeuRaL Coder is the privileged browser terminal / developer coding surface.** Local-only,
> token-gated, rooted, shut by default. Not public `/api`. Not a documentation page. Not a raw
> shell.

**`backend/apps/coder/` is not thin.** Measured: `__init__.py` **1,029 lines**, `test_coder.py`
790, `tests/test_coder_surface.py` 338, `README.md` 386, `SMOKE-surface.md` 205 — **2,748 lines**,
including the stamped smoke record `.claude/CLAUDE.md` prescribes for a surface that has to run.
The brief's *"backend/apps/coder appears thin and needs location audit"* was based on a file
count of five; the audit is done and the answer is that it is not thin.

### Route posture — measured

| Requirement | Reading |
|---|---|
| `/api/coder/*` must not exist | **it does not exist.** `tests/test_coder_surface.py:18` asserts it: *"there is no `/api/coder/...` route at all"*, and `:172` gives the reason — *"an `/api/coder/...` endpoint is remote file read on a public host"* |
| developer routes under `/local/*` | **yes** — `/local/coder`, `/local/coder/status`, `/local/coder/ls`, `/local/coder/file`, `/local/coder/history`, `/local/coder/journal` |
| `/local/*` refused off-box | **yes** — loopback only unless `SYMONEURAL_CODER_ALLOW_REMOTE=1` |
| published route `/livestack/coder` | both `/livestack/coder` and `/live-stack/coder` answer (`backend/server.py:2080`, `:3168-3169`, `:3214-3215`). The hyphenated form is compatibility; **the published link must use `/livestack/coder`** |

The reason is recorded in the code at `backend/server.py:2075`: *"`ops/Caddyfile` delegates the
whole `/api/*` subtree"* — so every `/api` route is internet-facing unless separately blocked.
That is why `/local/*` exists and why it is the right home.

### The gates — measured

| Control | Implementation |
|---|---|
| disabled unless enabled | `SYMONEURAL_CODER_ENABLED == "1"` **and** a non-empty token, both required (`:159-160`) |
| token | `SYMONEURAL_CODER_TOKEN`, **constant-time compared** (`:22-24`, `:170`) |
| off-box | `SYMONEURAL_CODER_ALLOW_REMOTE == "1"`, otherwise loopback only |
| workspace root | `SYMONEURAL_CODER_WORKSPACE`, defaults to the repo root; narrowing it is documented (`:127-131`) |
| no path escape | every path `resolve()`d — **which follows symlinks** — and must land inside the resolved root (`:49-50`) |
| protected paths | a **denylist applied to the resolved absolute path** (`:249-271`) |

**The denylist covers exactly the artefacts the brief names**, and it carries a recorded defect
and fix worth preserving: it was `adapter` alone, matching a path *segment*, so `training/adapter`
was denied while **`training/adapter-qwen36` — a second real LoRA, 200 MB of weights — was
reachable**, and `/local/coder/file` returned `adapter_config.json` and `README.md` with 200s.
The entry is now a glob. That is the difference between a denylist and a tested denylist.

Protected: `training/corpus.jsonl` · `training/build_dataset.py` · `training/adapter*` — and by
the root rule, everything outside the workspace. `pip install` is blocked by the deny rules.

## 5. Clean-room posture

**The experience is reimplementable. The source is not.** Allowed: observe the interaction
model, describe expected UX, recreate from scratch, implement SyMoNeuRaL-owned code, use generic
concepts — REPL, slash commands, session resume, permission prompt, browser terminal.

Not allowed: copy proprietary source · rebrand proprietary binaries · decompile · vendor
proprietary assets · **serve files from `references/`** · link against reference code.

§1 sharpens this from a rule into a live constraint: the archive on this box *is* proprietary
Anthropic source in part, `claude-code`'s licence is one line of all-rights-reserved, and
`references/` is untracked precisely so none of it can ship. `backend/apps/test_references_boundary.py`
exists to keep that true.

## 6. Relationship to Studio and to ModelOps/RuntimeOps

**Do not fold Coder into Studio.** Studio is the visual graph/workflow surface; Coder, Project
and CLI are developer/operator/cowork surfaces. Project belongs in **Chat** (§2). Coder and CLI
may integrate with Studio for workflow validation and model/runtime inspection.

**They may query. They must not own.** Model registry · runtime registry · hardware profile ·
queue/job status · route index · task board — all read, none reimplemented.

**Do not create a third registry beside Studio/Runtime/ModelOps**, and do not create a separate
agent stack that bypasses the model, runtime, GPU-governor or task rules. `.claude/CLAUDE.md`'s
first *never* is the same rule one level up: *"If a harness offers you its own task list, it is
a second state document."*

## 7. Repo operating rules these surfaces must respect

`PROJECT-TASKS.md` is canonical task state · `run/progress.html` is the live reading · **never
`git add .`** · never commit `review/`, raw archives, model weights or `.venv` · never deploy
without explicit authorization · report `git status` / `log` after changes · preserve repo-local
author identity.

The `git add .` rule is not stylistic. `.gitignore` records four separate incidents where a bulk
add staged secrets, 7,620 cargo files, and an 11.6 MB `.mhtml`.

## 8. What is actually open — the short list

Everything else in the brief is built. These are not:

| Open | Notes |
|---|---|
| CLI operator commands | registry inspection, load/unload/switch, job submit/status, hardware probe, workflow validation. Depend on #103/#104 landing the registries — the CLI queries, it does not own |
| published Coder link | must be `/livestack/coder`; the hyphenated route stays as compatibility only |
| Project → Chat cowork | **open task #83.** Not started here |
| how much of the CLI needs tests | already an audit question — `AUDIT.md` Q8 |
| per-file review of the archive | 3,598 third-party entries; listing done, contents not reviewed, and no import proposed |

## 9. Not authorized by this document

No implementation · no folder migration · no filesystem route under `/api` · no archive import
or commit · no proprietary source or binary copied · no decompilation · no token or gate change ·
no route or page deleted without a scoped redirect/deprecation plan · no deploy.
