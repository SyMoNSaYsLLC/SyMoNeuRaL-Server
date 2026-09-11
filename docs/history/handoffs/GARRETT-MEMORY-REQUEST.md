---
schema: garrett-memory-request/v1
document_status: READY
created_at: 2026-09-08T05:20:00-04:00
updated_at: 2026-09-08T06:00:00-04:00
current_fact_cutoff: 2026-09-08T06:00:00-04:00
source_agent: claude-code
source_agent_running_at_capture: true
repository_path: /home/google/Symoneural
repository_branch: main
repository_head: 5b14957ef6a17eacd722394252a01095a416316a
repository_clean: true
history_root_commit: bf7c8fb0cc54f18168b3c1391ad31ef0bac44f7c
history_reachable_commit_count: 618
canonical_status_path: /home/google/Symoneural/ProjectStatus.md
canonical_handoff_path: /home/google/Symoneural/docs/HANDOFF.md
migration_manifest_path: /home/google/.claude/scratch/session-0d019856/MIGRATION-MANIFEST-APPLIED.tsv
pre_migration_backup_path: /home/google/claude-backup-20260908-035459.zip
pre_migration_backup_sha256: 060b5de9cfbacb289feabb579cfd75dd33168e5a0c8f3a6df49abe48f70e2443
finalizer_path: /home/google/claude-retirement-finalize-20260908-050000.sh
finalizer_sha256: ac6a91999237be4ab0a208c7bcd149bcfb7f0b85998b724e657a6a8b09c0dd29
handoff_ready_for_transfer: true
claude_session_may_exit: true
final_backup_ready: false
purge_ready: false
contains_secret_values: false
canonical_project_authority: false
---

NEXT CODER: Read this file completely before acting. Re-measure every claimed current fact.
This is a derived transfer snapshot and evidence index—not permission to purge, uninstall,
kill, restart, deploy, overwrite state, run destructive Git operations, expose secrets, or
mine on a public network.

# READ THIS FIRST

This document is a **map, not an authority**. The authorities are:

| Authority | Path |
|---|---|
| Rules | `/home/google/Symoneural/docs/authority/PROJECT-AUTHORITY.md` |
| Current verified state | `/home/google/Symoneural/ProjectStatus.md` |
| Current handoff | `/home/google/Symoneural/docs/HANDOFF.md` |
| Source of truth for code | `/home/google/Symoneural` and its 618-commit Git history |
| Disposition ledger | the migration manifest named in the front matter |
| Private recovery archive | the pre-migration backup ZIP named in the front matter |

**Three things to do before anything else**, in this order:

```bash
cd /home/google/Symoneural && git status && git log --oneline -12
cat ProjectStatus.md | head -40          # the checkpoint block
cat docs/HANDOFF.md                      # 64 lines; what will bite you
```

**Two facts you must not act on without re-measuring:** the test count and the service
states. Both were true at capture and both go stale the moment anything runs.

**`PURGE_READY=NO`.** A Claude Code process was alive when this was written, so no backup
taken so far can be the authoritative quiescent one. Section 15 has the exact sequence.

# OWNER GOAL

`OWNER_REQUIREMENT` — One repository, `/home/google/Symoneural`, that runs the whole local
web/UI/server stack, with genuinely **first-party** SyMoNeuRaL runtime code: honest
licensing, honest identity, no renamed wrappers and no licence laundering.

`OWNER_REQUIREMENT` — Retire Claude Code. Migrate the owner's own portable work into the
first-party CLI, remove the repository's dependency on `.claude`, take one authoritative
backup after Claude has exited, then purge — preserving that backup.

`OWNER_REQUIREMENT` — Working behaviour beats plans and branding. Verify source, tracked
state, installed artefact, live process and smoke behaviour **separately**. A version string
is not evidence that something runs.

`OWNER_REQUIREMENT` — The miner is fail-closed until explicit configuration exists.

# AUTHORITY AND SAFETY BOUNDARIES

`DECISION` — These held throughout and must keep holding:

- Nothing Claude-owned was deleted, purged, moved, uninstalled or stopped. The running
  Claude process was never touched.
- No `git reset --hard`, no `git clean`, no wildcard deletion, no `find … -delete` sweep.
- No secret value appears in any commit, test, manifest, report or in this file.
- The proprietary Claude executable was never copied, translated, patched, relabelled or
  relicensed. Vendored third-party trees under `external/`, `vendor/` and `archive/` were
  never modified or executed as first-party runtime code.
- No real mining: no public pool, no real wallet, no submitted share. The test fixture binds
  `127.0.0.1` as a class constant with no code path that changes it.
- No production service was restarted or reconfigured beyond one owner-authorised change
  (Caddy config path, applied by the owner in their own shell).
- One writer only. No concurrent agent or worktree edited the repository.

`BLOCKED` — One thing needed privileges this session did not have and was **not** worked
around: **Caddy derename step 2**. Restarting `symoneural-api` was also listed here in v1 and
turned out to be unnecessary — the process had already restarted on its own and was running
the fixed paths. See §22.

# CURRENT MEASURED CONTROL POINT

`MEASURED_CURRENT` at 2026-09-08 06:00 EDT:

```
repository   /home/google/Symoneural      branch main
HEAD         5b14957ef6a17eacd722394252a01095a416316a
             (v2 — see §22)
root commit  bf7c8fb0cc54f18168b3c1391ad31ef0bac44f7c   (first commit 2026-08-16)
commits      618 reachable   40 made today   6 tags   20 branch refs
tree         0 tracked modifications, 0 staged, 0 stashed
worktrees    4   (main, .claude/worktrees/authority-plane-plan, and two detached
                  build-evidence trees under archive/build-20260902-src{,-b})
engines/     GONE — the five compatibility symlinks were deleted after the live
             API was PROVED to be running the fixed paths
git fsck     0 non-dangling problems
full suite   2360 passed, 0 failed, 59 skipped — measured AT THIS HEAD
services     symoneural-api active/enabled · symoneural-web active/enabled · site 302
             symoneural-gateway inactive/disabled, 64 source files intact
runtimes     11 top-level symoneural-* directories, addressed directly
```

`MEASURED_CURRENT` — The 59 skips are all environmental prerequisites, not failures: yocto
`openembedded-core` absent (5), not the serving box (2), no staged modelops candidate (3),
`SYMONEURAL_SERVER_READY_BASE` unset (2), and **4 intentional** — the desktop-window test is
opt-in behind `SYMONEURAL_TEST_WINDOW=1`.

# HISTORICAL CLAIMS AND SUPERSEDED STATE

Every row's left column is a `HISTORICAL_CLAIM`: something asserted earlier in this work, by
the prior Codex note, or by me. The right column is the verdict now. The two are kept apart
because a claim and its disposition are different things, and collapsing them is how a
corrected statement gets read as one that was never wrong.

| `HISTORICAL_CLAIM` | Status now |
|---|---|
| "the final continuation prompt has not been delivered" — Codex note, 04:22 | `SUPERSEDED`. It was delivered and executed. |
| suite `2340 passed` | `SUPERSEDED`. That was `e6000070`. At this HEAD it is **2360**. |
| HEAD `544168a1` | `SUPERSEDED` by seven further commits. |
| `symoneural-cli` not discoverable on PATH | `SUPERSEDED`. `scripts/install-cli.sh` links five entry points into `~/.local/bin`; verified from `env -i` login shell. |
| no Claude-import command exists | `SUPERSEDED`. `symoneural-cli import-claude` exists, 41 tests. |
| repository authority lives in `.claude/` | `SUPERSEDED`. Migrated to `docs/authority/` and `docs/HANDOFF.md`; `.claude` untracked. |
| `symoneural-diffuse` has a blocking absolute RUNPATH | `SUPERSEDED` 2026-09-04. Never real; `symoneural-llm` was the leak, fixed at `b4d701cc`. |
| the two `symoneural-build-20260902` trees are a dangerous second source of truth | `SUPERSEDED`. Documented never-deployed build evidence; recommend leaving. |
| `symoneural-web` running is an anomaly | `SUPERSEDED`. It **is** the public web server; active/enabled is correct. |
| `symoneural-image-engine` is a fictional runtime | `SUPERSEDED`. It is a recorded **alias** of `symoneural-diffuse`, not fiction. |
| vLLM is not installed | `SUPERSEDED`. Present in its venv; nothing in the product imports it. |
| "symoneural-api not restarted, shims load-bearing" — **my own v1 claim** | `SUPERSEDED`. The API is pid 143775, started 03:51:08, running the fix from `6dd06d43` (02:46). Proved by moving `engines/` aside: API 200, chat `ready`. **Shims deleted.** |
| "two root-owned directories" | `SUPERSEDED` in part. `AI_PURGE_PSEUDOFS` is root-owned; `symoneural-cutover-rollback-…` is **google**-owned and read-only by mode, holding 6 root-owned files. |

`PRIOR_MEMORY_NOTE` — `/home/google/.codex/memories/extensions/ad_hoc/notes/20260908T042250-0400-claude-to-codex-transfer.md`
(13,932 bytes). Read in full and folded in here. **Not modified.** Its mutable facts were
revalidated; the rows above are the ones that moved.

`HISTORICAL_CLAIM` — that note states the final continuation prompt had not been delivered.
`SUPERSEDED`: it was delivered, and this document is part of the result.

`HISTORICAL_CLAIM` — earlier reports in this work quoted a suite of 2,281, then 2,293, then
2,328, then 2,340 passing. Each was true at its own commit and none is true now.
`MEASURED_CURRENT` at `5b14957e`: **2360 passed, 0 failed, 59 skipped**. The repository's own
rule is that a figure without a commit beside it is not evidence.

# COMPLETE HISTORY COVERAGE LEDGER

Dispositions are exactly: `SUMMARIZED_AND_INDEXED`, `AUTHORITATIVE_IN_GIT`,
`AUTHORITATIVE_IN_MIGRATION_MANIFEST`, `PRIVATE_BACKUP_ONLY`, `SUPERSEDED`, `DUPLICATE`,
`MISSING_BEFORE_TRANSFER`, `CORRUPT_OR_UNREADABLE`, `UNKNOWN`.

| SOURCE_ID | SOURCE_PATH | CONTENT_CLASS | TIME_RANGE | ITEM_COUNT | STATE | DISPOSITION | INDEXED_IN_HANDOFF | PRESERVED_IN_GIT | PRESERVED_IN_PRIVATE_BACKUP | SHA256_OR_MANIFEST_REFERENCE | SECRET_OR_LICENSE_RESTRICTION | NOTES |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S01 | `/home/google/Symoneural` (.git) | source history | 2026-08-16 → 2026-09-08 | 618 commits, 6 tags, 20 refs | healthy, fsck 0 | `AUTHORITATIVE_IN_GIT` | yes | yes | git-state record | none | root `bf7c8fb0`, HEAD `5b14957e`; branches and tags enumerated in §8 |
| S02 | tracked working tree | current source | now | HEAD tree | clean | `AUTHORITATIVE_IN_GIT` | yes | yes | HEAD | none | 0 modifications |
| S03 | `external/` | third-party reference | — | 149 GB, 82 entries | ignored | `PRIVATE_BACKUP_ONLY` | yes | no | not archived — see notes | third-party licences | read-only by owner rule; **not** in any backup; recoverable from upstreams |
| S04 | `archive/` | bulk, evidence, transcripts | — | 285 GB | ignored | `PRIVATE_BACKUP_ONLY` | yes | no | not archived | mixed | too large; contents indexed in `docs/ops/CONSOLIDATION-20260908.md` |
| S05 | the five derived engine trees | derived binaries | — | 11 GB | ignored | `AUTHORITATIVE_IN_GIT` (recipe) | yes | recipe only | no | GPL-3.0 for 2 of 5 | rebuilt by `tools/fork_engines.sh` |
| S06 | worktrees + stash | uncommitted work | — | 4 worktrees, 0 stashes | 7 carried uncommitted state | `PRIVATE_BACKUP_ONLY` | yes | no | `metadata/git/worktree-*` | none | status + diff + diff-binary + untracked captured |
| S07 | `/home/google/.claude` | Claude Code state | 2026-07 → now | 18,204 files | live | `PRIVATE_BACKUP_ONLY` | yes | no | in pre-migration ZIP | **credentials** | 194 transcripts, 3 memory files |
| S08 | `/home/google/.config/Claude` | Claude Desktop state | — | 14 GB (≈120 MB unique) | live | `PRIVATE_BACKUP_ONLY` | yes | no | in pre-migration ZIP | **credentials** | 12 GB `vm_bundles` + caches excluded by name |
| S09 | `/home/google/claudelastrun.md` | saved transcript | this work | 964 KB | present, mode 664 | `SUMMARIZED_AND_INDEXED` | yes | no | on disk | prompts are historical | digest in §7; **mode 664 — see §16** |
| S10 | Codex transfer note | prior memory | 04:22 today | 13,932 B | present | `SUMMARIZED_AND_INDEXED` | yes | no | on disk | none | folded in; unmodified |
| S11 | `ProjectStatus.md` | canonical state | 2026-08 → now | 1 file | current | `AUTHORITATIVE_IN_GIT` | yes | yes | HEAD | none | re-pinned this session |
| S12 | `docs/HANDOFF.md` | canonical handoff | current | 64 lines | current | `AUTHORITATIVE_IN_GIT` | yes | yes | HEAD | none | split from a 4,876-line archive |
| S13 | `docs/history/handoffs/` | dated handoffs | 2026-09-01 → now | 41 files | current | `AUTHORITATIVE_IN_GIT` | yes | yes | HEAD | redacted | includes the pre-2026-09-08 HANDOVER archive |
| S14 | `symoneural-miner-core/` | first-party miner | today | 51 tests, 13-check smoke | current | `AUTHORITATIVE_IN_GIT` | yes | yes | `5c0ad43f` | none | `docs/ALGORITHM-GAP.md` states the gap |
| S15 | `symoneural-code/` | CLI + importer | today | 41 importer tests | current | `AUTHORITATIVE_IN_GIT` | yes | yes | `98180797`… | none | source == launcher, hash `b79a6f5e` |
| S16 | migration manifest | disposition ledger | today | 18,434 rows | present, mode 600 | `AUTHORITATIVE_IN_MIGRATION_MANIFEST` | yes | no | on disk | no secrets | every source row classified |
| S17 | pre-migration backup | private archive | 03:54 today | 83,628 entries, 11 GB | verified | `PRIVATE_BACKUP_ONLY` | yes | no | `060b5de9…` | **credentials** | `unzip -t` clean, manifest verified |
| S18 | `claudebackup.zip` | earlier ad-hoc archive | 03:45 today | 36,984 entries, 4.8 GB | superseded | `SUPERSEDED` | yes | no | on disk, mode 600 | **credentials** | superseded by S17; retained |
| S19 | `claude-system-inventory-…txt` | discovery record | 03:46 today | 11,249 lines | present, mode 600 | `SUMMARIZED_AND_INDEXED` | yes | no | on disk | paths only | 21 sections |
| S20 | the finalizer | retirement tool | today | 1 script | present, mode 700 | `SUMMARIZED_AND_INDEXED` | yes | no | `ac6a9199…` | none | preflight tested; backup never run |
| S21 | 4 files deleted before proof | lost config | — | 4 | gone | `MISSING_BEFORE_TRANSFER` | yes | no | no | — | §16; searched both ZIPs, git, file-history |
| S22 | Codex attachments | supplied evidence | today | 3 files | referenced by S10 | `UNKNOWN` | yes | no | not verified here | unknown | paths in S10; **not opened by this session** |
| S23 | nested third-party `.claude` | vendor config | — | 4 dirs, 222 files | present | `PRIVATE_BACKUP_ONLY` | yes | partly | in pre-migration ZIP | third-party | inside `external/`; removal is a separate owner decision |

**Reconciliation.** 23 source classes. Every one carries a disposition. Two are honestly
short of "covered": **S03/S04** (434 GB of third-party and bulk material) are indexed by
path and classification but are **not inside any backup** — too large, and recoverable from
upstreams or already evidence-only. **S22** is `UNKNOWN` because this session never opened
those attachment files. Nothing else is unindexed, unpreserved or unclassified.

# CHRONOLOGICAL WORK AND DECISION HISTORY

Safe digest. No secret values, no raw tool traces, no proprietary internal instructions.

**2026-09-04/05 — concurrent sessions, and three errors of the same shape.**
A second session opened on a repository another was writing. It wrote nothing and measured
everything. `DECISION`: no concurrent writes. Three errors surfaced, all *acting on a row
rather than on the thing*: a peer reported "no worktree" without running `git worktree list`
(there were four); this session called two build trees a dangerous second source of truth
from a listing row (opening the directory showed `"Deployment performed: NO"`); and it
reported `symoneural-web` running as an anomaly off a service-map row — nearly getting the
**public web server** disabled. `DECISION` (owner): leave it alone. Also corrected: the
diffuse RUNPATH "blocker" was never real; `symoneural-llm` was the leak, fixed at
`b4d701cc`. `ProjectStatus.md` had been *half*-corrected, which is worse than uncorrected.

**2026-09-05 — powerdown.** Two files found uncommitted, one an 80-line HANDOVER entry that
had sat three days through 21 commits. Committed. No git remote by policy, so an uncommitted
state document has one copy and no history.

**2026-09-08 — consolidation.** 26 loose home directories brought under the repository:
`docs/` (tracked), `external/` (149 GB, was `references/`), `archive/` (285 GB).
`archives/` → `releases/`. Zero disk cost — all same-filesystem renames, 618 GB before and
after. A **101 MB filesystem listing** naming `training/corpus.jsonl` was caught before it
reached Git.

**Restructure.** Five runtimes promoted to top level; four first-party runtimes created.
Licence position enforced in code: `fork_engines.sh` stamps permissive upstreams and
**refuses** copyleft ones. Moving the client **broke** it — `ROOT = HERE.parent`, whose own
comment already read *"wrong four times in this repo"*. That produced `symoneural-audit`,
which found **81 more files** with the same silent bug. The ratchet then caught its own
author, twice.

**Application verification.** All 22 declared surfaces read against the running box. Six
declared-versus-enforced defects, **all fixed**: `project`'s docs said public and enforced
401; published rate limits were not enforced *and* three of four figures disagreed with the
table beside them; `_require_local` missed three proxy headers; the rack said `train` ready
while it answered 503; `POST /api/rack/power/{unit_id}` leaked a 422 before its gate; nine
`/local/*` routes had no owner because the totality test looked only at `/api/*`.

**Backup.** First attempt archived **212 files instead of 68,278** — `rsync
--no-dereference` does not exist in rsync 3.4.1 and `2>/dev/null` hid it. One root-owned
file was omitted from *both* inventory and exclusions. `BACKUP.json` contained the hash of
the ZIP containing it. All three fixed; S17 verified.

**This session.** Miner core (§10), importer (§11), neutralisation (§13), installer (§12).
Idempotence took three attempts and is the subject of two corrective commits.

`OWNER_REQUIREMENT`, refused three times and still refused: **GPL-3.0 code cannot be
relicensed MIT by editing a file.** See §10.

# SYMoNeuRaL REPOSITORY AND CODE HISTORY

```
root commit      bf7c8fb0cc54f18168b3c1391ad31ef0bac44f7c   2026-08-16
final HEAD       5b14957ef6a17eacd722394252a01095a416316a   2026-09-08
reachable        618 commits · 22 merge commits · 0 stashes · 4 worktrees
integrity        git fsck --no-progress: 0 non-dangling problems
self-contained   YES — no remote by policy; history is complete locally
```

**Branches (20), enumerated rather than counted.** `main` is the only one this session
touched. The `worktree-*` names are the per-task branches this project's workflow creates;
two pairs share a tip, which is why a count alone is misleading.

| Branch | Tip | Branch | Tip |
|---|---|---|---|
| `main` | `5b14957e` | `worktree-gateway-online` | `94159c3e` |
| `experiment/native-hybrid-gpu-player` | `44863110` | `worktree-matrix-count-fix` | `3e4a4353` |
| `research/custom-runtime-freeze-20260824` | `44863110` | `worktree-miner-online` | `a20a7469` |
| `merge-clean-four` | `38d66e2f` | `worktree-online-apps-audit` | `39d5386a` |
| `merge-coder` | `8951715a` | `worktree-project-page` | `0ea9cb82` |
| `tuner-transcode` | `8fae5ca8` | `worktree-ravencalc-mobile` | `b1d85777` |
| `worktree-application-run-batch-a` | `7c03346c` | `worktree-reinforce-rl` | `4820d621` |
| `worktree-authority-plane-plan` | `596c1a0a` | `worktree-site-typography-tlc` | `1f98ff50` |
| `worktree-coder-online` | `fbd9675f` | `worktree-stickers` | `fc8a49ef` |
| `worktree-control-plane-matrix` | `acc95e00` | `worktree-docs-accuracy` | `cb50fd18` |

**Tags (6).** All release or research checkpoints; none created by this session.

| Tag | Commit |
|---|---|
| `pre-dispatchos-preview` | `51bf4b5e` |
| `dispatchos-preview-boundaries` | `796a8b23` |
| `dispatchos-preview-tested` | `2c95202c` |
| `dispatchos-preview-live-protected` | `8cb6f1f6` |
| `research/native-runtime-freeze-20260824` | `a8ce8b7f` |
| `research/trusted-firmware-scaffold-20260824` | `38f90370` |
```

**No Git bundle was created.** The receiving coder is on this machine and can read the
repository directly; a bundle would be a redundant second copy of a healthy 618-commit
history. `INFERENCE`: create one only if the work moves to another machine.

This session's focused commits, oldest first:

| Commit | Area |
|---|---|
| `5c0ad43f` | miner — first-party Keccak/Stratum/config, 51 tests, 13-check smoke |
| `98180797` | migration — `import-claude`, importer module, 32 tests |
| `51e546f2` | migration — idempotence, correcting an overclaim in the previous message |
| `9b945d41` | tests — a rerun test that asserted the defect it was named against |
| `7f1a6d2a` | neutralisation — `docs/authority/`, `docs/HANDOFF.md`, tool policy, untracking |
| `ca513dad` | docs — split the canonical handoff from its 4,876-line archive |
| `78e675c2` | CLI — `scripts/install-cli.sh` |
| `5b14957e` | reconcile the open items; close the API/shim blocker; delete `engines/` |

Inspect without altering anything:

```bash
git -C /home/google/Symoneural log --oneline --graph --decorate -40
git -C /home/google/Symoneural show 5c0ad43f --stat
git -C /home/google/Symoneural log --since='2026-09-08' --format='%h %s'
git -C /home/google/Symoneural worktree list --porcelain
git -C /home/google/Symoneural fsck --no-progress
```

# RUNTIME AND APPLICATION MAP

**11 top-level runtime directories.** Tracked (ours) versus derived (gitignored, rebuilt):

| Directory | Kind | State |
|---|---|---|
| `symoneural-api/` | tracked | entry point; application stays in `backend/` |
| `symoneural-code/` | tracked | CLI, session front door, discovery, importer |
| `symoneural-audit/` | tracked | finds move-fragile path resolution |
| `symoneural-miner-core/` | tracked | first-party miner layers — **not a miner** |
| `symoneural-adaptive-fabric/` | tracked | **PLANNED / NOT_IMPLEMENTED** |
| `symoneural-llm/` | derived | MIT upstream, SyMoNeuRaL licence applied |
| `symoneural-diffuse/` | derived | MIT upstream, SyMoNeuRaL licence applied |
| `symoneural-listen/` | derived | MIT upstream, SyMoNeuRaL licence applied |
| `symoneural-miner/` | derived | **GPL-3.0** — licence refused, reference-only |
| `symoneural-ui/` | derived | **GPL-3.0** — licence refused, reference-only |

`COMPONENT-MAP.tsv` has 18 rows and a test asserts every runtime directory has one and every
`SOURCE_ROOT` exists.

**22 declared application surfaces.** 19 wired and answering; 3 offline by configuration,
each naming its own remedy (`miner`, `gpuminer`, `asicminer`, `gateway` need config;
`studio` needs ComfyUI on `:8188`, which nothing starts at boot).

`MEASURED_CURRENT` — **`engines/` no longer exists.** Nine Python files including the live
`api.py` were repointed at `6dd06d43`; the API restarted at 03:51:08 and has run the fixed
paths since. Proved before deleting anything by moving `engines/` aside entirely — the live
API answered 200 and the rack reported chat `ready` — then the five symlinks were removed.
All four engine binaries resolve at their canonical top-level paths.

The **`bin/` symlinks are kept**: they are the documented install path used by
`scripts/install-cli.sh` and 39 tracked files, not transitional shims. Same shape,
different purpose — do not delete them too.

# MINER IMPLEMENTATION AND LICENSING STATE

`MEASURED_CURRENT` — **Two things, and only one of them is a miner.**

**`symoneural-miner/` — a working miner, not first-party.** Class 3: a derivative of GPL-3.0
`kawpowminer`. Evidence: its `LICENSE` is the GNU GPL v3 text, and
`external/contrib/build-kawpowminer.sh` clones `RavenCommunity/kawpowminer` at 1.2.4 and
compiles from that tree. `tools/fork_engines.sh` **refuses** to stamp the SyMoNeuRaL licence
on it, and that refusal is tested.

**`symoneural-miner-core/` — first-party, and not a miner.** Written from published
specifications:

| Layer | Specification | Evidence |
|---|---|---|
| Keccak-f[800] / f[1600] | FIPS PUB 202 | round constants **computed** from the standard's LFSR and asserted against published values; SHA3-256 vectors; cross-checked against `hashlib` across the rate boundary |
| Stratum client | public protocol | 22 tests against a loopback fixture that also misbehaves |
| Fail-closed config | project rule | 18 tests; `SYMONEURAL_MINER_ENABLED` must be the literal `1` |

51 tests. Smoke `bin/symoneural-miner-smoke`: **13/13** — handshake, real work, deterministic
candidate from our own Keccak, share formatted and **accepted**, socket released.

**`BLOCKED` — the gap, precisely.** KawPoW is Keccak-f[800] **plus** a pseudo-random program
over a multi-gigabyte DAG. Steps 2–4 and the CUDA kernel are **not implemented**.
`symoneural-miner-core/docs/ALGORITHM-GAP.md` breaks it into four steps and marks which are
done. **No hashrate figure appears anywhere, because none was measured.** The four states are
named separately: builds / executes a test vector / talks to a local fixture / measured real
hashrate. Only the first three are claimed.

**The route through it.** `cpp-kawpow` 1.1.0 is **Apache-2.0** — measured at
`external/referencestochatgpt/kawpow-src/cpp-kawpow-1.1.0/LICENSE`. Apache-2.0 permits
linking into a proprietary product with a NOTICE; GPL-3.0 does not. So the algorithm layer
need not be GPL: a first-party shell over `cpp-kawpow`, or a clean-room ProgPoW
implementation. `/yocto` does **not** help — its mining material is `cgminer`, also GPL-3.0.

`DECISION` — The repository's own prior position is quoted rather than overruled silently:
`backend/apps/cryptominer/__init__.py` says *"Writing a competitive KawPow kernel is a
project in its own right and a bad one to attempt here."* Override it deliberately if at all.

**External runtime dependencies of `symoneural-miner-core`:** none. Zero references to
`symoneural-miner/` in its code. Platform dependencies — Linux kernel, glibc, CPython and
its `socket`/`json`/`threading` — are listed and explicitly **not** claimed as first-party.
`hashlib` is used in tests only.

# CLAUDE-TO-SYMoNeuRaL MIGRATION

**Command:** `symoneural-cli import-claude [--source DIR] [--apply] [--manifest FILE]`.
Dry run unless `--apply`. Manifest: front matter path, mode 600, 18,434 rows.

`MEASURED_CURRENT` — dispositions over the live state:

| Disposition | Count |
|---|---|
| `SKIPPED_CACHE_OR_TELEMETRY` | 17,626 |
| `BACKUP_ONLY` | 695 |
| `ALREADY_NATIVE` | 113 |
| `MIGRATED` | 114 first apply, then 0 (idempotent) |
| `SKIPPED_VENDOR_SPECIFIC` | 6 |
| `MISSING_BEFORE_MIGRATION` | 4 — §16 |

**Zero rows reached the tracked destination**, because this installation has no
user-authored commands, skills, agents or hooks. Everything went to a gitignored private
tree at `0700` with `0600` files. `REAUTH_REQUIRED`: none — no MCP server definitions were
found in the settings.

Refused **in code**: credentials at any depth (record dropped whole, never redacted-and-kept);
anything not a plain `role`/`content` turn; absolute paths, `..` traversal and symlink
escapes; silent overwrites; an allow-everything permission mode; unbounded input.
`~/.config/symoneural/keys.json` and `accounts.json` were never opened.

41 tests. Two defects found by **running** it, not by the tests: containment refused every
legitimate first import when the destination root did not exist, and the private root stayed
at the umask's 775 while its leaves were 0700. Idempotence took three attempts —
`51e546f2` and `9b945d41` are the corrective commits.

# SYMoNeuRaL CLI SOURCE, INSTALLATION, AND SMOKES

```
source     /home/google/Symoneural/symoneural-code/bin/symoneural-cli
launcher   /home/google/Symoneural/bin/symoneural-cli -> the source (symlink)
identical  YES — both sha256 b79a6f5e23ccbc48bb6c7e4b70d3c24bfa23af08dbcc1c115b6bde8e0b5baa97
installed  ~/.local/bin/{symoneural-cli,symoneural-code,symoneural-discovery,
                          symoneural-audit,symoneural-api}  — symlinks
stale copy /home/google/.symoneural-full/bin/symoneural-cli  sha256 dd9b67b7…
           DIVERGENT. Not overwritten, not blessed. Left exactly as found.
```

`MEASURED_CURRENT` — verified from a shell with nothing inherited (`env -i HOME=… bash -lc`):
all five resolve; `status` returns real device readings; `import-claude` reports 113
`ALREADY_NATIVE`; `mcp --help` works; `symoneural-audit` returns findings;
`symoneural-api --check` resolves the root and target.

`DECISION` — symlinks, not copies. The divergent stale copy above is the argument: it drifted
and nothing noticed until hashes were compared.

# NEUTRAL PROJECT AUTHORITY

| Was | Now |
|---|---|
| `.claude/CLAUDE.md` | `docs/authority/PROJECT-AUTHORITY.md` |
| `.claude/HANDOVER.md` | `docs/HANDOFF.md` (64 lines) + `docs/history/handoffs/HANDOVER-ARCHIVE-pre-20260908.md` (4,876) |
| `.claude/START-PROMPT.txt` | `docs/authority/START-HERE.txt` |
| `permissions.deny` | `docs/authority/TOOL-POLICY.json`, **enforced** by `backend/apps/test_tool_policy.py` |
| root `CLAUDE.md` importing `.claude/CLAUDE.md` | a pointer with no rules in it |

Seven `.claude` paths **untracked, not deleted** — physical copies retained for the final
backup, `/.claude/` ignored so the later purge cannot dirty the repository.

**The policy is enforced, not copied.** Its protected-class test failed on first run, and
that failure was the finding: the retired settings denied destructive shell patterns and
said nothing about `training/corpus.jsonl`, `build_dataset.py`, the adapter weights, or the
mode-600 ledgers that `docs/ops/EXPORTS.md` names. **8 refusals were added** and are listed
under `deny_added_by_migration`, separate from the 13 `deny_migrated`, so nobody reads the
old posture as stronger than it was. No `allow` list was migrated.

`ACTIVE_DOT_CLAUDE_DEPENDENCIES` — `MEASURED_CURRENT`: **none functional.** Of 14 files with
a path-shaped `.claude` reference, 13 are inside
`backend/vendor/anthropics/claude-agent-sdk-python` — third-party code that legitimately
addresses the product it wraps — and the 14th is the archive guard's *protection* rule, which
must keep refusing `.claude/` while that directory physically exists. **~128 prose citations
in docstrings remain**, inert, and are recorded as work rather than swept: the last blanket
sweep of that kind silently edited an assertion.

# TEST AND VERIFICATION LEDGER

| Check | Result | At |
|---|---|---|
| full suite | **2360 passed, 0 failed, 59 skipped** | `5b14957e` (re-measured after the shim deletion) |
| miner core | 51 passed | `5b14957e` |
| miner smoke | 13/13, `SMOKE-miner-core.md` written | `5c0ad43f` |
| importer | **41** passed | `5b14957e` — was 42 at `78e675c2`; the rerun test was rewritten and merged two assertions |
| tool policy | 10 passed | `5b14957e` |
| archive guard | 28 passed | `5b14957e` |
| `import-claude` dry run | 18,434 rows classified | now |
| idempotence | 115 files stable across 3 applies | now |
| fresh-shell `command -v` | 5 of 5 resolve | now |
| CLI smoke | status / import / mcp / audit / api all answer | now |
| `.claude` functional deps | 0 outside the vendored SDK | now |
| external miner load-bearing | no — 0 references | now |
| status sequence twice | `INTAKE.md` and `progress.html` stable; `test_build_progress.py` 28 passed | `5b14957e` |
| `git fsck` | 0 non-dangling problems | now |
| pre-migration ZIP | `unzip -t` clean, sidecar verifies | now |
| finalizer preflight | correctly BLOCKED, wrote nothing | now |

# BACKUP, FINALIZER, PRESERVE, AND PURGE STATE

| Artefact | Path | Size | Mode | Verified |
|---|---|---|---|---|
| pre-migration staging | `/home/google/claude-backup-20260908-035459/` | 15 GB | 700 | yes |
| pre-migration ZIP | `…035459.zip` | 11 GB | 600 | `unzip -t` clean; 83,628 = 83,628 |
| its sidecar | `…035459.zip.sha256` | — | 600 | `sha256sum -c` OK |
| superseded archive | `/home/google/claudebackup.zip` | 4.8 GB | 600 | retained |
| inventory | `claude-system-inventory-20260908-034644.txt` | 1.5 MB | 600 | 21 sections |
| **finalizer** | `claude-retirement-finalize-20260908-050000.sh` | 20 KB | **700** | syntax OK; preflight BLOCKED |

`finalizer_sha256`: `ac6a91999237be4ab0a208c7bcd149bcfb7f0b85998b724e657a6a8b09c0dd29`

`EXPECTED_FINAL_BACKUP_PATTERN`: `/home/google/claude-final-backup-<YYYYmmdd-HHMMSS>.zip`
plus `.sha256`, staging `…/`. The purge allowlist and preserve list are written **by the
finalizer** into `<staging>/metadata/PURGE-ALLOWLIST.txt` and `PRESERVE-LIST.txt`. They do
not exist yet, because the finalizer has not run.

The finalizer refuses while any Claude process, background agent, archive job, other
finalizer, or live session socket exists; never reuses a staging name; preserves the
pre-migration checkpoint untouched; inventories `~/.local/bin/claude` and versions
**2.1.228, 2.1.231, 2.1.236**; treats Desktop separately; preserves symlinks as symlinks;
requires a non-empty reason on every row; treats copy errors, duplicates and count
mismatches as failures; compares ZIP against staging **path-and-type, not by count**; and
**never purges**.

`PURGE_READY=NO`. A Claude process was alive at capture.

# MISSING, UNRECOVERED, AND UNMEASURED ITEMS

`MISSING_BEFORE_TRANSFER` — four files removed by an earlier command in this session
**before** preservation was proven. Searched: both ZIPs, `git log`,
`~/.claude/file-history`, and the session transcripts. **Not present in any of them** — both
backups were taken after the deletion. Contents are **not** reconstructed and **not**
fabricated.

| Path | Searched | Result |
|---|---|---|
| `/home/google/.symoneural-full/.claude/START-PROMPT.txt` | both ZIPs, git, file-history | `MISSING_BEFORE_TRANSFER` |
| `/home/google/.symoneural-full/.claude/CLAUDE.md` | as above | `MISSING_BEFORE_TRANSFER`. **Candidate, unproven:** `/home/google/.symoneural-full/CLAUDE.md` (570 B) still exists — a sibling, not demonstrably the same file |
| `/home/google/.symoneural-full/.claude/HANDOVER.md` | as above | `MISSING_BEFORE_TRANSFER` |
| `/home/google/Downloads/.claude/settings.local.json` | as above | `MISSING_BEFORE_TRANSFER` |

`UNKNOWN` / not measured by this session:

- **S22 Codex attachments** — three paths named in the Codex note. Never opened.
- **`claudelastrun.md` is mode 664**, world-readable, and holds a 964 KB transcript. Not
  changed, because the task forbade touching Claude material — but flag it.
- **`external/` and `archive/`** (434 GB) are in **no** backup.
- **Real hashrate** — never measured, deliberately.
- **Authenticated surfaces** — `dispatchos` (15 routes), `accounts` (8) and `project`'s write
  side were probed unauthenticated only.
- **`voice` end-to-end** — no audio submitted.
- **81 path-fragility findings** — counted and ratcheted, not repaired.
- **~128 `.claude` prose citations** — inert, unswept.
- **`Downloads/`** — 34 GB, 408 entries, holds personal material, unclassified.
- **Two root-owned directories** could not be moved: the cutover-rollback set (holds a live
  credential file) and `AI_PURGE_PSEUDOFS` (byte-identical duplicate).

# OPEN BLOCKERS AND OWNER DECISIONS

| # | Blocker | Class | Needs |
|---|---|---|---|
| 1 | Caddy derename step 2 — `User=caddy`, `/var/lib/caddy` | privilege | root. **`/var/lib/caddy/.local/share/caddy/certificates` is live Let's Encrypt production, cert valid to 2026-11-15 — COPY and chown, never move** |
| 2 | KawPoW algorithm + CUDA kernel | project | owner decision: clean-room, or build on Apache-2.0 `cpp-kawpow` |
| 3 | `symoneural-ui` is GPL-3.0 | licence | replace with a render surface over MIT `symoneural-diffuse`, or keep vendored and labelled |
| 4 | 81 files compute a root by counting parents | source | ratcheted; repair lowers the baseline |
| 5 | `Downloads/` unswept | owner decision | holds personal material |
| 6 | ~128 `.claude` prose citations | source | mechanical; do it deliberately |
| 7 | The two detached build trees | owner decision | recommend leaving; retention unruled |
| 8 | `AI_PURGE_PSEUDOFS` is root-owned; the cutover directory is google-owned but read-only by mode with 6 root-owned files inside | privilege | root |
| 9 | `claudelastrun.md` mode 664 | owner decision | `chmod 600` if that transcript should not be world-readable |

# ARTIFACT INDEX

**Must travel together** if this leaves the machine: this file, a Git bundle of
`/home/google/Symoneural` (not yet created — see §8), the migration manifest, and the
pre-migration ZIP **plus** its sidecar. Everything else is machine-local.

| Path | What | Mode |
|---|---|---|
| `/home/google/Desktop/garrettmemoryrequest.md` | this file | 600 |
| `/home/google/Symoneural` | the project and its 618-commit history | — |
| `…/ProjectStatus.md` · `…/docs/HANDOFF.md` | canonical state · canonical handoff | tracked |
| `…/docs/authority/{PROJECT-AUTHORITY.md,TOOL-POLICY.json,START-HERE.txt}` | rules, policy, start-here | tracked |
| `…/docs/ops/CONSOLIDATION-20260908.md` | where every home directory went | tracked |
| `…/docs/ops/APPLICATION-VERIFICATION-20260908.md` | the 22-surface sweep | tracked |
| `…/symoneural-miner-core/docs/ALGORITHM-GAP.md` | the miner gap, precisely | tracked |
| `…/run/private/` | imported sessions and memories | 700/600, gitignored |
| the six `/home/google` artefacts in §15 | backups, inventory, finalizer | 600/700 |
| `/home/google/claudelastrun.md` | saved transcript, 964 KB | **664** |
| the Codex note (§5) | prior memory, unmodified | 664 |

# ORDERED NEXT SAFE ACTIONS

1. `cd /home/google/Symoneural && git status && git log --oneline -12`
2. Read `ProjectStatus.md` checkpoint and `docs/HANDOFF.md`.
3. Re-run the suite. **Do not reuse 2360.**
4. `/exit` Claude. Confirm with `pgrep -af claude`.
5. Run the finalizer (command at the end of this document). Require
   `CLAUDE_FINAL_BACKUP_READY=YES`.
6. Read the generated purge allowlist and preserve list. **Then and only then** decide.
7. Caddy step 2 — **copy** the TLS state, never move it.
8. Pick up the remaining blockers in the owner's order.

*(The former step 7 — restart the API and delete the shims — is done. See §22.)*

# MACHINE-READABLE RESUME STATE

```json
{
  "schema": "garrett-memory-request/v1",
  "captured_at": "2026-09-08T06:00:00-04:00",
  "source_agent": "claude-code",
  "source_agent_running_at_capture": true,
  "repository": {
    "path": "/home/google/Symoneural",
    "branch": "main",
    "head": "5b14957ef6a17eacd722394252a01095a416316a",
    "root_commit": "bf7c8fb0cc54f18168b3c1391ad31ef0bac44f7c",
    "reachable_commits": 618,
    "tags": 6,
    "branch_refs": 20,
    "worktrees": 4,
    "stashes": 0,
    "clean": true,
    "fsck_problems": 0,
    "self_contained": true,
    "engines_shim_directory": "deleted"
  },
  "tests": {
    "full_suite_at_head": {
      "passed": 2360,
      "failed": 0,
      "skipped": 59
    },
    "miner_core": 51,
    "miner_smoke_checks": "13/13",
    "importer": 41,
    "tool_policy": 10,
    "measured_at": "5b14957e"
  },
  "authority": {
    "rules": "/home/google/Symoneural/docs/authority/PROJECT-AUTHORITY.md",
    "current_state": "/home/google/Symoneural/ProjectStatus.md",
    "current_handoff": "/home/google/Symoneural/docs/HANDOFF.md",
    "history_archive": "/home/google/Symoneural/docs/history/handoffs/HANDOVER-ARCHIVE-pre-20260908.md",
    "tool_policy": "/home/google/Symoneural/docs/authority/TOOL-POLICY.json",
    "active_dot_claude_functional_dependencies": 0,
    "dot_claude_prose_citations_remaining": 128
  },
  "miner": {
    "first_party_tree": "/home/google/Symoneural/symoneural-miner-core",
    "implementation_class": "clean-room-partial",
    "complete_miner": false,
    "gap": "kawpow-progpow-loop-and-cuda-kernel-not-implemented",
    "hashrate_measured": false,
    "derived_gpl_runtime": "/home/google/Symoneural/symoneural-miner",
    "derived_gpl_licence": "GPL-3.0",
    "permissive_algorithm_layer": {
      "path": "external/referencestochatgpt/kawpow-src/cpp-kawpow-1.1.0",
      "licence": "Apache-2.0"
    },
    "external_runtime_dependencies": []
  },
  "migration": {
    "command": "symoneural-cli import-claude",
    "manifest": "/home/google/.claude/scratch/session-0d019856/MIGRATION-MANIFEST-APPLIED.tsv",
    "manifest_rows": 18434,
    "counts": {
      "MIGRATED_first_apply": 114,
      "ALREADY_NATIVE": 113,
      "BACKUP_ONLY": 695,
      "SKIPPED_CACHE_OR_TELEMETRY": 17626,
      "SKIPPED_VENDOR_SPECIFIC": 6,
      "MISSING_BEFORE_MIGRATION": 4
    },
    "rows_to_tracked_destination": 0,
    "reauth_required": [],
    "idempotent": true
  },
  "backups": {
    "pre_migration_zip": "/home/google/claude-backup-20260908-035459.zip",
    "pre_migration_sha256": "060b5de9cfbacb289feabb579cfd75dd33168e5a0c8f3a6df49abe48f70e2443",
    "pre_migration_verified": true,
    "superseded_zip": "/home/google/claudebackup.zip",
    "finalizer": "/home/google/claude-retirement-finalize-20260908-050000.sh",
    "finalizer_sha256": "ac6a91999237be4ab0a208c7bcd149bcfb7f0b85998b724e657a6a8b09c0dd29",
    "finalizer_mode": "700",
    "final_backup_ready": false,
    "expected_final_pattern": "/home/google/claude-final-backup-<timestamp>.zip",
    "purge_allowlist": null,
    "preserve_list": null
  },
  "missing_before_transfer": [
    "/home/google/.symoneural-full/.claude/START-PROMPT.txt",
    "/home/google/.symoneural-full/.claude/CLAUDE.md",
    "/home/google/.symoneural-full/.claude/HANDOVER.md",
    "/home/google/Downloads/.claude/settings.local.json"
  ],
  "open_blockers": [
    "caddy derename step 2 - copy the live TLS state, never move it (privilege)",
    "kawpow algorithm and cuda kernel (project)",
    "symoneural-ui is GPL-3.0 (licence decision)",
    "81 path-fragility findings (ratcheted, unrepaired)",
    "Downloads/ unswept - 411 entries, holds personal material",
    "~128 .claude prose citations",
    "two detached build trees - retention unruled",
    "AI_PURGE_PSEUDOFS root-owned; cutover dir google-owned but read-only by mode (privilege)",
    "claudelastrun.md is mode 664"
  ],
  "claude_session_may_exit": true,
  "purge_ready": false,
  "contains_secret_values": false,
  "canonical_project_authority": false,
  "document_version": 4,
  "closed_since_v1": [
    "symoneural-api restart and engines/ shim removal - the API was ALREADY running the fixed paths; proved, then the shims were deleted"
  ]
}
```

# NEXT CODER BOOTSTRAP REQUEST

Please pick this up in this order:

1. **Re-measure first.** `git status`, HEAD, worktrees, stashes, service states, and re-run
   the suite. Treat every number in this file as evidence of what was true at 05:20 on
   2026-09-08, not as current truth.
2. **Take the final backup.** The owner must `/exit` Claude first. Then the finalizer, then
   `CLAUDE_FINAL_BACKUP_READY=YES`, then read the two generated lists. **Do not purge
   without them.**
3. **Close blockers 1 and 2** — both need root, both are small, both unblock the shim
   deletion and finish the Caddy derename. **Copy the TLS state; never move it.**
4. **Decide the miner.** §10 has the licence facts. `cpp-kawpow` being Apache-2.0 is the
   fact that makes a first-party miner possible; the ProgPoW loop and kernel are the work.
5. **Do not** claim first-party for anything whose upstream is copyleft, however the files
   are named. `fork_engines.sh` refuses it in code and there are tests.
6. **When you stop**, write a dated handoff into `docs/history/handoffs/` and update
   `docs/HANDOFF.md` and `ProjectStatus.md`. One canonical state source and one canonical
   handoff. Do not create a third.

# PROVENANCE, REDACTION, AND CHANGE HISTORY

**Written by** Claude Code (Opus 5, 1M context) on 2026-09-08 at approximately 05:20 EDT,
while that session was still running — which is why `final_backup_ready` is `false` and
`purge_ready` is `false`.

**Sources.** Direct measurement of the repository, filesystem, processes and services; the
618-commit Git history; `ProjectStatus.md` and the handoff chain; the migration manifest;
the pre-migration backup's inventory and checksums; the 11,249-line system inventory; and
the Codex transfer note of 04:22 today, read in full, folded in, marked where superseded,
and **not modified**.

**Redaction.** `contains_secret_values: false`. No password, token, OAuth state, cookie,
API key, private key, credential blob, session-authentication datum or environment **value**
appears here. Environment variables are named, never valued. Wallet addresses are absent —
the miner smoke uses a shape-valid placeholder. File paths, hashes, sizes, modes and counts
are present by design.

**Known limits of this document.** It is derived, so it can be wrong where the machine has
moved on. §16 lists what was never measured. Two source classes totalling 434 GB are indexed
but in no backup. Three Codex attachment files are `UNKNOWN` because this session never
opened them. Four files are `MISSING_BEFORE_TRANSFER` and their contents are not
reconstructed — a session command deleted them before proving they were copied, and that is
recorded rather than smoothed over.

**Change history.**

- **v1**, 2026-09-08 05:20. First capture.
- **v2**, 2026-09-08 05:45. Corrects v1's largest error. v1 listed "`symoneural-api` not
  restarted; shims load-bearing" as open blocker 1. It was already closed: the path fix
  landed at `6dd06d43` (02:46) and the API restarted at **03:51:08**, so it had been running
  the fixed code for over an hour. v1 said this because it recorded the API's pid as 1507,
  the process restarted, and the fact was never re-measured — the same
  reading-a-stale-record failure this document describes elsewhere. Proved by moving
  `engines/` aside (API 200, chat `ready`), then the five symlinks and the directory were
  deleted. Blockers renumbered; the root-ownership row corrected; `docs/ops/RECONCILIATION-20260908.md`
  added as the Phase 2 ledger. Suite re-measured at the new HEAD: still 2360 passed, 0 failed.
- **v3**, 2026-09-08 05:55. Audited against the addendum's exact wording rather than my
  memory of it, which found two deviations in v1/v2: five history-ledger columns had been
  abbreviated (`INDEXED`, `IN_GIT`, `IN_BACKUP`, `SHA256_OR_REF`, `RESTRICTION`) and now
  carry the specified names; and `HISTORICAL_CLAIM`, one of the seven required labels, was
  used **zero** times — §5's rows now carry it explicitly, separating each claim from its
  verdict. A third: §8 counted branches and tags without listing them, so all 20 branch tips
  and all 6 tags are now enumerated — a count cannot be checked, and two branch pairs here
  share a tip, which a count hides. Also corrected a stale `HEAD 78e675c2` left in the S01
  ledger row. None of these changed a fact; all of them changed whether this document can be
  checked against its own specification.
- **v4**, 2026-09-08 06:00. Re-measured every focused test count at the current HEAD instead
  of carrying the `78e675c2` figures forward, which is this repository's own rule. Four held.
  One did not: the importer is **41** tests, not 42 — the count dropped when
  `test_apply_then_rerun_adds_nothing_new` was rewritten and two of its assertions merged.
  v1–v3 said 42 in five places. A number carried across a commit without being re-run is
  exactly the failure `ProjectStatus.md` has recorded three times.
