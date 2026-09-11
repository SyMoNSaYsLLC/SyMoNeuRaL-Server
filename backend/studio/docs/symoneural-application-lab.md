# SyMoNeuRaL Application Lab — the inventory, and what each reference actually is

**Scope captured 2026-08-22.** Direction only. **No implementation, no folder migration, no
deploy, and no archive imported** by this document or the commit that introduced it.

This file exists because the next thing that happens to this tree is a migration, and a
migration needs to know how many applications there are. `business/REPOSITORY-PURPOSE.md` §2
established *that* applications are incubated here; this file is the list. Garrett, 2026-08-22:
*"Do not migrate the repo as if it contains only `backend/apps/studio`."*

## The rule this file obeys

> **Docs may describe the future architecture. Implementation must match Garrett's actual box
> and currently authorized scope.**

`business/REPOSITORY-PURPOSE.md`, *The rule*. So every column below marked **measured** is a
reading of this disk on 2026-08-22, and every column marked **brief** is Garrett's stated
purpose for a thing that has not been inspected. The two are never merged.

## This file does not classify. It points at the file that does

`business/REPOSITORY-PURPOSE.md` §2 already names `ops/audits/BOX-REALITY-AUDIT.md` as the home
of the PROD / AUDIT / REMOVED verdict, and `.claude/CLAUDE.md`'s first *never* is *"never
create a second state document."* A verdict restated here would drift from the audit on the
first re-measurement, so the **Verdict** column below is a pointer, not a judgement. New
verdicts go **into** `BOX-REALITY-AUDIT.md` — the ones for these ten areas are its §10.

## 1. The lab rule — three states, and the archive is not one of them

Every application area is **PROD** (proven working on this box) · **AUDIT** (useful, needs
inspection, design or tests) · **REMOVED** (dead, wrong, unsafe, superseded, or not
applicable).

**An area can be PROD in-tree and AUDIT by archive at the same time, and two of them are.**
This is the distinction the inventory turns on, so it is stated before the table rather than
discovered in it: the code in `backend/apps/` has been measured, and the `.tar.gz` beside it
in `references/` has not been opened. Embedded and Miner are both in that position. Collapsing
them to a single verdict would either credit an uninspected archive with the in-tree code's
standing, or discard working code because an archive next to it is unreviewed.

## 2. Archive references — measured on disk, contents unopened

Every archive Garrett's brief names, located by exact filename on 2026-08-22. **Sizes, paths
and mtimes are measurements.** Four of the five have **not** been opened — nothing was
extracted, listed or read, and no purpose in §3 is inferred from them.

**The exception is `@symoneural code.tar.gz`, and only because Garrett authorized it by name**
later on 2026-08-22: *"list archive contents · identify Project/CLI/Coder-relevant files ·
compare against current `bin/symoneural-cli` · compare against `backend/apps/coder` · extract
requirements."* It was **listed, not extracted**, and the finding changed the premise of the
work it was reference for: it contains **no SyMoNeuRaL code at all** — 3,598 entries across
eleven third-party Anthropic projects, zero first-party files. Full reading:
`backend/coder/docs/symoneural-coder-project-cli-scope.md` §1. It remains **AUDIT**: listing is not a
per-file review, and nothing is imported.

| Brief calls it | Path on disk | Size | Tracked? |
|---|---|---|---|
| `@symoneural code.tar.gz` | `references/symoneural code.tar.gz` | 74,707,050 B (71 MiB) | no — `.gitignore:68` `/references` |
| ^ **listed 2026-08-22** | 3,598 entries · 11 third-party Anthropic projects · **0 first-party files** | see coder/project/cli scope §1 | not imported |
| `@simpy.tar.gz` | `references/simpy.tar.gz` | 4,002,603 B (3.8 MiB) | no — same rule |
| `@symoneural streamer.tar.gz` | `references/IPTV/symoneural streamer.tar.gz` | 284,011,213 B (271 MiB) | no — same rule |
| `@miner.tar.gz` | **ambiguous — see below** | — | no — same rule |
| `@oematch.tar(5).gz` | `references/oematch.tar.gz` | 16,617 B (16 KiB) | no — same rule |

`git ls-files | grep -E '\.(tar\.gz|tgz|zip)$'` returns **nothing**: no archive is tracked
anywhere in this repository, and `/references` is excluded wholesale. That is what makes *"do
not commit raw archives"* already true rather than a promise.

**`@miner.tar.gz` is ambiguous and is not being guessed.** Two files match:

| Candidate | Size | Why it might be the one |
|---|---|---|
| `references/Projects_Crypto/symoneural miner/miner.tar.gz` | 182,587,592 B (174 MiB) | **exact filename match** — this is the one this document assumes |
| `references/Projects_Crypto/symoneural miner.tar.gz` | 703,520,202 B (671 MiB) | a different, larger file whose name matches the *product* |

Neither has been opened. **Garrett confirms which, or both get inspected when Miner is
scoped.** Recording the ambiguity is the point; picking one silently is how a migration
imports the wrong 671 MB.

**`@oematch.tar(5).gz` — the `(5)` is a browser duplicate-download suffix, not part of the
name.** The file on disk is `references/oematch.tar.gz`, and at **16 KiB** it is the smallest
reference by four orders of magnitude. A second, differently-named copy exists at
`references/ENGINEERING/oematch-0.1.0-src.tar.gz`. Nobody should read "Embedded platform
reference" and picture a platform-sized payload.

**The DeepSeek harness is not in this table because it is not in this repository.** It is
`/home/google/Downloads/deepseek-harness-master.zip`, 19,613,102 B, outside the tree entirely —
and **task #89 already tracks it at 50%**. Exp cites it as reference (§3.3); that citation is
#89's business, not a new track.

## 3. The inventory — ten areas

**Purpose** is Garrett's brief, verbatim in intent. **On this box** is measured: tracked-file
counts from `git ls-files` on 2026-08-22. **Verdict** points into
`ops/audits/BOX-REALITY-AUDIT.md`.

| # | Area | Purpose (brief) | On this box (measured) | Reference archive | Verdict |
|---|---|---|---|---|---|
| 3.1 | **Website** | Public product surface: identity/branding, signup/login, credits/pricing, Studio entry, app discovery, demos, job/result gallery, cloud/local hardware options, docs/API access | `site/` — **111 tracked files** | — | audit §10.1 |
| 3.2 | **Studio** | ComfyUI-style visual graph surface, SyMoNeuRaL-owned node/graph/workflow architecture, model/runtime/hardware aware, node docs/API link contract | `backend/apps/studio/` — **145 tracked files** | — | audit §5, §7 |
| 3.3 | **Exp** | Experience-plugin surface, DeepSeek harness as reference/inspiration | `backend/apps/studio/plugins/exp/` — **28 tracked files** | (harness, outside repo) | audit §10.2 |
| 3.4 | **Reinforce** | Studio-family LoRA / adaptation / reinforcement / training area; reward and feedback loops, evals, merge/export, publish-to-registry | `backend/apps/studio/plugins/reinforce/` — **76 tracked files** | — | audit §10.2 |
| 3.5 | **Project** | Claude/Codex-like coworker workspace: repo/file/task context, code review, implementation planning | `backend/apps/project/` — **5 tracked files** | `@symoneural code.tar.gz` | audit §10.3 — **and see the conflict in §5** |
| 3.6 | **CLI** | Developer/operator entrypoint: app management, runtime/model registry inspection, model load/unload/switch, job submit/status, hardware probe, workflow validation, deploy/audit helpers | `bin/symoneural-cli` — **1 tracked file**; tests `backend/apps/test_symoneural_cli.py`, `test_cli_upgrade.py` | `@symoneural code.tar.gz` (shared with Project) | audit §10.3 |
| 3.7 | **RavenCalc** | Calculator / business application reference; an application-lab app, classified separately from Studio/Project/CLI | `backend/apps/ravencalc/` — **5 tracked files** | `@simpy.tar.gz` | audit §10.4 |
| 3.8 | **Streamer** | Streaming/video/media: stream management, playback, channel-style behaviour; likely related to the TV / restream / HLS rows | `backend/apps/streamer/` — **14 tracked**; `backend/apps/live/` — **9**; `backend/apps/capture/` — **3** | `@symoneural streamer.tar.gz` | audit §10.5 |
| 3.9 | **Miner** | Miner/ASIC/GPU mining reference: inventory, monitoring, firmware/reference audit, pool/job dashboards, diagnostics, owner-authorized device management | `backend/apps/cryptominer/` — **21 tracked**; `backend/apps/asicminer/` — **7** | `@miner.tar.gz` (ambiguous, §2) | audit §10.6 |
| 3.10 | **Embedded** | Embedded/OEM/Yocto platform reference: hardware integration, OEM matching, board/device targets, edge runtime packaging | `yocto/oematch/` — **21 tracked files, in-tree and load-bearing** | `references/oematch.tar.gz` (16 KiB) | audit §10.7 |

Two further areas the brief names are already specified elsewhere and are **not** duplicated
here: **Runtime/ModelOps** is `backend/registry/docs/symoneural-runtime-registry.md` and
`models/docs/MODEL-REGISTRY.md`; **Local Agent**, **Worker services** and **Platform targets** are
`backend/studio/docs/symoneural-studio-upgrade-scope.md` §5.2 and
`ops/backend/authority/docs/symoneural-platform-targets.md`.

### What the measurements corrected in the brief

Three of these are not what the brief's framing implies, and each is a reading rather than an
opinion:

- **Reinforce and Exp are already inside Studio on disk.** The brief asks that *"Reinforce
  should not remain a disconnected side plugin."* It is not one: both are
  `backend/apps/studio/plugins/*`, 76 and 28 tracked files. What is separate is the **Live
  Stack row**, not the code's location. See §4.
- **Embedded is not wholly "AUDIT until the archive is inspected."** `yocto/oematch/` is
  **tracked, in-tree, and depended on**: it is the licence-detection tool that #97's
  spec-mediated pipeline calls, and `.gitignore` carries three `yocto/oematch_*.deb` rules for
  its Debian build products. Its in-tree half has standing the 16 KiB archive does not.
- **Miner is in-tree twice.** `cryptominer` (GPU) and `asicminer` (ASIC) are separate apps with
  separate tests, and #85 is an open task about the miner *page*. The archive is a third thing.

## 4. Studio family — Reinforce and Exp are Studio surfaces, not standalone products

**Target architecture.** Reinforce is the Studio-family **LoRA / adaptation / reinforcement /
training** area. Exp is the Studio-family **experience-plugin** surface, using the DeepSeek
harness as **reference and inspiration only**.

The full statement of what Studio exposes — model selection, LoRA/adapter control through
Reinforce, and the owner/admin gate on base-weight mutation — is
`backend/studio/docs/symoneural-studio-upgrade-scope.md`, *Studio family and what Studio exposes*. It is
Studio architecture and lives with Studio; this section records only the consequence for the
inventory.

**The current observable state, and why it is not a contradiction.** The Live Stack may show
Reinforce and Exp as **separate units**, because that is what they are today: each is a
distinct running or queued unit that can be tested on its own. That is allowed and stays
allowed during audit and transition.

**What the migration must not do:** it must not use the separate Live Stack rows as licence to
separate Reinforce or Exp permanently into unrelated applications. Studio being offline does
not make them unrelated to Studio. They are Studio-family surfaces throughout migration
planning.

**No files move on account of this section.** The code is already in the right place (§3.3,
§3.4); the grouping being written down is the deliverable.

## 5. §19 of the brief and open task #83 — the conflict, and his answer

**Flagged, then resolved the same day. Both halves are kept: the resolution is only legible
next to what it resolved.**

| Source | Says |
|---|---|
| Garrett's pre-migration scope, §19 | the future structure must preserve *"Project as Claude/Codex-like coworker app"* — and §3.5 maps it to `@symoneural code.tar.gz` |
| **open task `◻ #83`** | *"Remove SyMoNeuRaL Project completely; put a cowork inside SyMoNeuRaL Chat"*, with machine checks `absent site/project.html`, `absent backend/apps/project`, `absent tests/project.mjs` |

#83 records his reason as the specification — R-161, *"to keep it from being confusing remove
symoneural project completely and just integrate a 'cowork' into the symoneural chat"* — and it
is an open coder-owned task whose checks would **delete** `backend/apps/project`. §19 asks the
migration to preserve it.

Both are Garrett's words, eight rows apart on the same list. Three readings are defensible and
they lead to different work:

- **(a) #83 stands.** The *app package* goes; "Project" survives as the cowork surface inside
  Chat, and §19's "Project" means the capability, not `backend/apps/project`.
- **(b) §19 supersedes #83.** The archive reference changes what Project should be, so #83 is
  dropped or rewritten before anything is deleted.
- **(c) Both, sequenced.** #83 removes the current confusing surface; Project is later
  re-incubated from `@symoneural code.tar.gz` as a new application, sharing code with CLI.

This was recorded rather than decided because a spec and a task quietly disagreeing is
precisely how a migration deletes an application and nobody notices which sentence authorised
it.

### Answered — (a), in his words, later the same day

Garrett's Chat scope, **2026-08-22**:

> *"SyMoNeuRaL Project / cowork / copilot belongs inside Chat"* … *"SyMoNeuRaL Project should
> become a capability inside Chat, not an unrelated standalone app, unless current migration
> scope explicitly chooses otherwise."*

That is reading **(a)**, and it agrees with #83's own stated reason. So:

- **#83 stands as written** and is not blocked by §19. Its `absent backend/apps/project` check
  is consistent with this answer rather than in conflict with it.
- **§19's "Project" means the capability, not the package.** A migration preserves
  project-aware conversation, repo/file/task context, code review and planning **inside Chat**;
  it does not preserve `backend/apps/project/`.
- **`@symoneural code.tar.gz` stays AUDIT until inspected.** It is the reference for what that
  capability should do — not an app to be imported, and not a replacement for Chat's cowork.

The capability's own scope, including the privileged filesystem gate a browser-based coder
requires, is `backend/chat/docs/symoneural-chat-scope.md`. **#83 is still not worked by this document**
— it is an open task and gets worked as a task.

## 6. Promotion, and where the gate is

An application that proves useful here can later be promoted to a platform-specific target —
**Linux · Apple · Android · Windows**.

**The gate is not in this file and is not restated in it.** `GUARDRAILS.md`, *The platform build
order*, owns it: the browser API is the only cleared build surface, the four native platforms
are each individually held, and no platform build starts on inference or on "obvious next
step" — only on Garrett naming that platform. `ops/backend/authority/docs/symoneural-platform-targets.md` is
the direction document and it points at the same gate rather than copying it, for the reason
`REPOSITORY-PURPOSE.md` already gives: *"a second copy of a gate is how a gate gets opened by
accident."*

## 7. Future workspace and catalog shape

Both are **future direction only** and both are already specified:
`backend/studio/docs/symoneural-studio-upgrade-scope.md` §11 (Backstage-style catalog) and §12
(Nx-style workspace boundaries). They are not restated here.

What this file adds to them is the count: an `apps/` boundary set that does not have a home for
all ten areas in §3 is incomplete, and the ten are the test.

## 8. What is not authorized by this document

No archive is imported, extracted, or committed · no folder is migrated · no implementation is
started · no model is downloaded · no weights or `.venv` are committed · no deploy · raw
ComfyUI is not exposed as product · no platform or toolchain build work begins · **and no
verdict in `BOX-REALITY-AUDIT.md` is changed by writing this file.**

The referenced archives stay **AUDIT until inspected**, and inspection is its own scoped task.
