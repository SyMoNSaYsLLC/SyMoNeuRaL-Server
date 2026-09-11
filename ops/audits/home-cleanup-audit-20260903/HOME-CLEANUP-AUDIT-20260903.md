# HOME WORKSPACE CLEANUP AUDIT — /home/google

**Date:** 2026-09-03
**Auditor:** Claude — READ-ONLY WORKSPACE AUDITOR
**Mutation authority:** NONE, except the single authorized evidence root
**Authoriser:** Garrett (sole task authoriser)
**Concurrent:** Codex held sole repository mutation authority for a separate documentation task

**VERDICT: HOME CLEANUP PLAN READY FOR OWNER AUTHORIZATION**

Coverage is complete: **291 of 291** top-level entries inventoried, zero gaps. Nothing was
deleted, moved, renamed, compressed, extracted or altered.

---

## 1. Audit coverage

| Measure | Value |
|---|---|
| Top-level entries under `/home/google` | **291** (169 visible + 122 hidden) |
| Entries inventoried | **291** — verified by `comm` against a live `ls -A`, no gaps |
| `/home` filesystem | `/dev/nvme0n1p5`, 885 GB, **359 GB used**, 522 GB available |
| Total accounted by classification | **356.8 GB** (99.4 % of used space) |
| Project-related clutter (excludes ACTIVE + PERSONAL) | **154 entries, 68.823 GB** |

Every top-level entry received exactly one primary class. Hidden entries were enumerated
with a second `du -sb` pass over `.[!.]*` after the first pass covered only `*` — the initial
glob silently skipped all 122 dotfiles, and that gap was closed before classification.

### Concurrent event — recorded, not treated as this audit's mutation

Repository HEAD moved during the audit, exactly as the gate anticipated:

```
e517a343  Record coder rotation, shared sessions, and verified Symon restoration   (at audit start)
1d72cc6e  models: harden image payload provenance                                  (during audit)
```

`1d72cc6e` is Codex's separately authorized documentation commit. It wrote
`upstream_revision` and `sha256` fields into `backend/models/PROVENANCE.json` for the four
Image/Sigils payloads — the values this session measured and recommended in the preceding
task's response. **This audit performed no repository mutation of any kind.**

---

## 2. Classification totals

| Primary class | Entries | Bytes | GB |
|---|---:|---:|---:|
| ACTIVE | 15 | 257,962,002,672 | **240.246** |
| PERSONAL | 122 | 51,472,419,841 | **47.937** |
| THIRD_PARTY_LAB | 7 | 36,024,334,597 | **33.550** |
| BACKUP | 3 | 16,528,127,375 | **15.393** |
| ARCHIVE | 34 | 11,703,333,880 | **10.900** |
| BUILD | 3 | 7,648,272,425 | **7.123** |
| DURABLE_EVIDENCE | 97 | 1,247,459,899 | **1.162** |
| UNKNOWN_STOP | 7 | 507,651,874 | **0.473** |
| DUPLICATE | 1 | 239,392,891 | **0.223** |
| STAGING | 2 | 8,304 | **0.000** |

ACTIVE is dominated by the canonical repository itself (156.86 GB) plus live tool state
(`.config` 25.9 GB, `.venvs` 25.1 GB, `.local` 19.0 GB, `.cache` 10.1 GB, `.claude` 5.2 GB).
None of it is cleanup material.

**Class and action are different axes, and the counts above are per top-level entry.** The
table says `DUPLICATE: 1` while §6 reports nine proven duplicates — both are correct and they
measure different things. Primary class is assigned once per *top-level* entry, so only
`HashingManifestSignsChecksums` carries the DUPLICATE class; the other eight duplicates are
individual files nested inside `Downloads` or are second copies whose retained twin sets the
parent's class. Likewise `Downloads` keeps its PERSONAL class while its proposed *action* is
REVIEW and several of its children carry their own DELETE rows. Read `HOME-INVENTORY.tsv` for
class-per-entry and `HOME-CLEANUP-MANIFEST.tsv` for action-per-path; where they overlap they
have been reconciled to agree.

---

## 3. Largest offenders

The 25 largest cleanup candidates are in `HOME-LARGEST.tsv`. The head of that list:

| Path | GB | Class | Proposed |
|---|---:|---|---|
| `/home/google/src` | 24.90 | THIRD_PARTY_LAB | REVIEW |
| `/home/google/ServerTransfer` | 12.06 | BACKUP | MOVE |
| `/home/google/ComfyUI-Installs` | 7.17 | THIRD_PARTY_LAB | REVIEW |
| `/home/google/training.tar.gz` | 4.25 | ARCHIVE | MOVE → archives/ |
| `/home/google/symoneural-build-20260902` | 4.15 | BUILD | **UNKNOWN_STOP** (worktrees) |
| `/home/google/SyMoNeuRaL-Backups` | 3.61 | BACKUP | MOVE → backups/ |
| `/home/google/SyMoNeuRaL-Projects` | 2.56 | ARCHIVE | REVIEW (holds repo symlink) |
| `/home/google/experiments` | 2.41 | ARCHIVE | REVIEW |
| `/home/google/TensorRT-LLM` | 2.10 | THIRD_PARTY_LAB | REVIEW |
| `/home/google/SyMoNeuRaL-Builds` | 1.82 | BUILD | MOVE → builds/ |
| `/home/google/ComfyUI-Shared` | 1.63 | **ACTIVE** | **KEEP — repo symlink target** |
| `/home/google/symoneural-engine-repro-…` | 1.15 | BUILD | MOVE → builds/ |

`/home/google/Downloads` (33.7 GB) is larger than any of these. Its primary class stays
PERSONAL, but it was **scanned rather than waved through** (§7.1) and its proposed action is
REVIEW. That scan produced the single most important finding in this audit — the vault
archive holding the only located copy of the LoRA weights (§5) — plus seven of the nine
proven duplicates (§6). No blanket action is proposed for it.

---

## 4. Active and protected paths

These were established from **actual consumers**, not documentation.

### Live consumers — systemd

Four units reference `/home/google`, and every one resolves to the **canonical repository
only**:

| Unit | Reference |
|---|---|
| `symoneural-api.service` | `WorkingDirectory=/home/google/Symoneural`, `ExecStart=…/backend/server.py`, governor calls in `ExecStartPre`/`ExecStopPost` |
| `symoneural-gateway.service` | `ExecStart=…/backend/apps/gateway/target/release/symoneural-gateway` |
| `symoneural-web.service` | `ExecStart=…/web/symoneural-web/build/symoneural-web` |
| `symoneural-progress.service` (user) | `ExecStart` of `tools/build/build_intake.py`, `archive_tasks.py`, `build_progress.py`; `ReadWritePaths` |
| `rclone-gdrive.service` | `RequiresMountsFor` + `RCLONE_CONFIG=/home/google/.config/rclone/rclone.conf`; backs the `/mnt/gdrive` rclone mount |

**No systemd unit references any clutter directory.**

### Live consumers — processes

A sweep of every `/proc/*/cwd` and `/proc/*/exe` found **no process rooted in any cleanup
candidate**. The only home-rooted processes have `cwd=/home/google` itself and are desktop
session components (konsole, kate, gvfs, pipewire, ChatGPT/Codex desktop, ulaa). `pid 1505`
(the API) runs with the canonical repo as its working directory.

### Symlinks — two, and they point in opposite directions

| Symlink | Target | Consequence |
|---|---|---|
| `/home/google/Symoneural/references/ComfyUI-Shared` | `/home/google/ComfyUI-Shared` | **The canonical repo depends on a path outside itself.** `ComfyUI-Shared` is therefore ACTIVE/KEEP, and is *not* interchangeable with `ComfyUI-Installs`. |
| `/home/google/SyMoNeuRaL-Projects/Symoneural` | `/home/google/Symoneural` | **A symlink into the canonical repo.** Any future `rm -rf` of `SyMoNeuRaL-Projects` must not follow it. Recorded as a hard precondition on manifest row 37. |

### Git worktrees — the finding that most changes the plan

```
/home/google/Symoneural                       1d72cc6e [main]
/home/google/symoneural-build-20260902/src    98326529 (detached HEAD)
/home/google/symoneural-build-20260902/src-b  98326529 (detached HEAD)
```

`symoneural-build-20260902/src` and `src-b` are **registered git worktrees** with
administrative state in `/home/google/Symoneural/.git/worktrees/`. They look like ordinary
build clutter and are not: a plain `rm -rf` leaves stale administrative files inside the
canonical repository, and removing them properly needs `git worktree remove` — a repository
mutation, prohibited under this gate and requiring its own.

They are therefore **UNKNOWN_STOP** (rows 39–40). Their siblings `gocache-b` and `gocache-c`
are genuinely disposable Go build caches and are split into separate MOVE rows (21–22) so an
executor can take the safe part without touching git.

### Other protected paths

- **`/yocto`** — a separate filesystem (`/dev/nvme0n1p2`), not under `/home/google` and out
  of scope. Note that the 39 repo references to `/home/google/yocto` are **dangling**: that
  path does not exist; the real mount is `/yocto`.
- **`/mnt/gdrive`** — external `fuse.rclone` mount, backed by `.config/rclone/rclone.conf`.
- **Credentials** — `providerapikeys.txt`, `.ssh`, `.gnupg`, `.git-credentials`,
  `.smbcredentials`, `.passwd-s3fs`, `.claude.json`. All KEEP, rows 5–10. `providerapikeys.txt`
  is called out explicitly because silence in a manifest is how a credential file gets swept.
  **No credential content was read into or copied into any evidence file.**
- **Current model paths** — `backend/models/` inside the canonical repo, including the four
  Image/Sigils payloads restored earlier today.

---

## 5. Reference checking — why grep alone is not evidence

The gate forbids basing safety on mutable documentation. Every reference verdict in
`HOME-REFERENCES.tsv` therefore carries a `reference_kind` column:
**`EXEC` / `COMMENT` / `DOC` / `SYMLINK` / `WORKTREE` / `DANGLING`**.

The case that proves the column is necessary: **`/home/google/MIT_AI_Training` is the most
heavily referenced non-canonical path in the repository — 176 hits — and not one of them is
a consumer.** The `scripts/deploy.sh:31` hit, which looks decisive because it is in a live
script, is a comment describing a historical path bug. The rest are archived documentation
and prose inside `.claude/settings.local.json`. The entry is a 300 KB text file that nothing
resolves. Without the `reference_kind` column, a future executor would keep it forever for
the wrong reason.

Nine documented paths are **DANGLING** — referenced by repo documentation but absent from
disk: `/home/google/yocto`, `Symoneural_backups`, `symoneural-apt`, `models`,
`AI_Local_NVIDIA`, `symoneural-merge4`, `retraining-notes`, and the `.zshrc` alias target
`/home/google/huggingface/start_server.sh` (a pre-existing broken alias, at `.zshrc:44-45`).
These are documentation debt, not cleanup targets.

### The doc-versus-disk divergence — and where the missing weights actually are

`.claude/HANDOVER.md:2237` describes `/home/google/.symoneural-full` as an IP vault of
**"mode 700, 499 M, 1051 files"** holding, among other things, `training/adapter/` and
`adapter-qwen36/` `adapter_model.safetensors` at **454 M**, "*untracked, so the tarball has
the configs and not the weights*."

Measured on disk today, the live vault is **22.17 MB**. The following files, named by that
documentation, **do not exist anywhere on the live filesystem**:

| File | Live status |
|---|---|
| `training/adapter/adapter_model.safetensors` | absent |
| `training/adapter-qwen36/adapter_model.safetensors` | absent |
| `training/adapter/symoneural-lora.gguf` | absent — **and this is `CHAT_ADAPTER` at `backend/server.py:237`** |
| `run/reinforce/adapters/*/adapter_model.safetensors` | absent |

Verified properly rather than by a single suppressed `find`: `training/adapter/` and
`training/adapter-qwen36/` **do exist** in the canonical repo and contain only
`adapter_config.json`, `chat_template.jinja`, `README.md` and `tokenizer_config.json` — the
configs, no weights. A `find` for `*.gguf` across `training/` and the vault returns nothing,
and a `find` for `*.safetensors` outside `backend/models/image/` returns only the
`huggingface_hub` cache snapshots, no adapter.

**The weights are not lost.** They are inside
**`/home/google/Downloads/symoneural-vault-2026-08-19-v2.tar.gz`** (398,369,206 bytes,
sha256 `86aa9d85f7894640ace5e21b59aff2549b10bab72482dd41d8a6bbdab117644f`, mode 600). Its
`tar -tzf` listing contains all four items above, including
`.symoneural-full/training/adapter/symoneural-lora.gguf`.

Two consequences, both load-bearing:

1. **That archive is the only located copy of the persona LoRA weights and of the live
   `CHAT_ADAPTER` target.** It is promoted to **manifest row 0 — the highest-priority KEEP
   in the plan** — precisely because it sits in `Downloads`, the directory most likely to be
   bulk-deleted in a cleanup. Losing it would destroy the one artefact `NAMES.md` calls "the
   one artefact that *is* ours".
2. The API degrades safely in the meantime: `_adapter_matches()` returns `False` when
   `CHAT_ADAPTER` is absent, so chat serves without the persona rather than failing. That is
   why this has gone unnoticed.

This audit does not restore the weights — that is a mutation, outside this gate. It records
where they are so a future authorized task can, and it flags that a cleanup plan built on
the documentation would have treated the live vault as a 499 MB asset while the real asset
sat unprotected in `Downloads`.

---

## 6. Exact duplicates

Nine duplicates are **proven**, every one by byte comparison or SHA-256 rather than by name
or size.

| Retained | Duplicate proposed for deletion | Bytes | Proof |
|---|---|---:|---|
| `/home/google/Symoneural-yocto-compiled-code-scan-20260828T200848Z` | `HashingManifestSignsChecksums/Symoneural-yocto-compiled-code-scan-20260828T200848Z` | 239,392,891 | `diff -rq` exit 0, no differences, 19 files each side |
| `symoneural-repo-2026-08-19.tar.gz` | `Downloads/symoneural-repo-2026-08-19.tar.gz` | 89,472,788 | identical SHA-256 `d7159542…` |
| `Symoneural-yocto-…-20260828T200848Z.tar.gz` | `Downloads/Symoneural-yocto-…-20260828T200848Z.tar.gz` | 20,745,642 | identical SHA-256 `6f22173f…` |
| `Downloads/symoneural.zip.part00` | `Downloads/symoneural.zip.part-00` | 19,922,944 | identical SHA-256 `f98d11fb…` |
| `Downloads/symoneural.zip.part01` | `Downloads/symoneural.zip.part-01` | 19,922,944 | identical SHA-256 `bf273983…` (3-way set) |
| `Downloads/symoneural.zip.part01` | `Downloads/symoneural.zip (1).part01` | 19,922,944 | identical SHA-256 `bf273983…` (3-way set) |
| `Downloads/symoneural.zip.part02` | `Downloads/symoneural.zip.part-02` | 14,790,007 | identical SHA-256 `0214a8bd…` (3-way set) |
| `Downloads/symoneural.zip.part02` | `Downloads/symoneural.zip (1).part02` | 14,790,007 | identical SHA-256 `0214a8bd…` (3-way set) |
| `SYMONEURAL-GATEWAY-DEPLOY-REFACTOR-CODER-PROMPT.txt` | `SYMONEURAL-GATEWAY-DEPLOY-REFACTOR-CODER-PROMPT (1).txt` | 35,688 | identical SHA-256 `a1cb56de…` plus `cmp` byte-identical |

Seven of these nine were only found because `Downloads` was actually scanned rather than
waved through as personal data — see §7.1. The `symoneural.zip` split archive exists in
three parallel naming variants (`.partNN`, `.part-NN`, and a browser-suffixed
`(1).partNN`), each set byte-identical, so two of every three copies are redundant.

**Thirty-four archives were hashed and all 34 SHA-256 values are distinct** — there is no
redundant archive among them. Three near-miss cases show why filename and size are not proof:

- **`ServerTransfer/SyMoNeuRaL-Builds` vs `SyMoNeuRaL-Builds.zip`** — *identical* size
  (1,029,202,197 bytes) and the same payload listing, but **different SHA-256**. They were
  zipped three minutes apart (09:21 vs 09:24) and the container timestamps differ. Same
  payload, not the same bytes → **REVIEW, not delete** (row 33).
- **`DonaldNorris.zip` vs `Donnie.zip`** — similar names, different sizes and hashes. Not
  duplicates.
- **`MIT_AI_Training` vs `MIT_AI_Training.zip`** — one is UTF-8 text, the other a zip.

### An archive that is the primary copy, not a redundant one

**`Platforms.tar.gz` (223.91 MB) is roughly 90× larger than `Platforms/` (2.44 MB).** The
directory is a near-empty stub of `.platform` shells; the tarball holds the real Apple SDK
payload. Treating the archive as redundant because an extracted directory exists — the exact
inference the gate prohibits — would destroy the only copy. It is **KEEP** (row 12).

Where only containment could be established (`Symoneural-yocto-…tar.gz` holding the retained
tree; the `SyMoNeuRaL-Backups`/`Builds` archive pairs; `Symoneuraltree.md`/`.zip`), the
verdict is **REVIEW**. `DELETE_EXACT_DUPLICATE` is used only where both sides were hashed or
byte-compared.

---

## 7. Disposable staging candidates

Only one entry qualifies as provably disposable staging:

**`/home/google/staging-image-2026-09-03`** — 7,670 bytes of file content (88 KB with
directory overhead). This is **this session's own** external staging area from the preceding
Image/Sigils payload task. The four model payloads were moved out of it on adoption; what
remains is `hf` download metadata and two download logs.

Full disclosure on its evidence status: §3 of
`review/RESPONSE-2026-09-03-claude-image-sigils-payload-restoration.md` cited those
`.metadata` files as corroborating provenance for the pinned revisions and digests. **That
evidence is now superseded** — Codex committed the same `upstream_revision` and `sha256`
values into `backend/models/PROVENANCE.json` at `1d72cc6e`, which is durable, tracked and
independent of this directory. The precondition on row 15 states that dependency explicitly.

`/home/google/symoneural-model-downloads-20260902` (634 bytes) is **REVIEW** rather than
delete: it is a model staging root from the previous day and this audit did not establish
that every payload it staged was adopted.

### 7.1 Downloads — scanned, not assumed

`Downloads` is 33.7 GB, the second-largest tree on the box, and the gate names
"Downloads/Pictures project artifacts where relevant". Relevance cannot be judged without
looking, so it was scanned rather than classified by its name. The result changed the plan
twice over:

- It holds the **critical vault archive** that is the only located copy of the LoRA weights
  (§5) — now manifest row 0.
- It holds **seven of the nine proven duplicates** (§6), worth 199,567,276 bytes — 45 % of
  all provable reclaim in this plan.
- The bulk is genuinely personal and is **not** cleanup material: `Win11_25H2` ISO
  (8.08 GB), `Projects_Crypto-*` bundles (~7.2 GB), `Imagesandvideos-*` bundles (~7.3 GB),
  `pngarchive.zip` (1.13 GB).

`Downloads`, `Desktop`, `Documents`, `Pictures` and `Music` are therefore all recorded as
**REVIEW** in both the inventory and the manifest — meaning "scan before acting", the same
treatment `Downloads` just received — rather than the blanket `KEEP` an earlier pass of this
audit had assigned them. No blanket action is proposed for any user tree.

---

## 8. Relocation candidates

**128 entries, 26,971,520,146 bytes (25.119 GB)** are proposed for MOVE — relocation, not
deletion. These are entries with real retention value that are merely in the wrong place:
97 dated DURABLE_EVIDENCE roots, the a-series and session handoff records, 34 archive
bundles, and the BACKUP/BUILD trees.

Nothing in this group is proposed for deletion, and no MOVE crosses a filesystem boundary —
every source and destination is on `/dev/nvme0n1p5`, so each is an atomic same-filesystem
rename with a trivial `mv`-back rollback.

---

## 9. UNKNOWN_STOP items

Eight entries totalling **4.628 GB** are declared rather than guessed.

| Path | Why stopped |
|---|---|
| `symoneural-build-20260902/src` | registered git worktree — needs `git worktree remove` under a repository gate |
| `symoneural-build-20260902/src-b` | same |
| `/home/google/review` | shadows the repo's own `review/`; contents and purpose not established |
| `/home/google/ClaudeAlienware` | 165.80 MB separate agent workspace; purpose not established |
| `/home/google/FakeDesktop` | 275.37 MB mirroring `Documents`/`SyMoNeuRaL` trees; relationship to the real Desktop not established |
| `/home/google/symoneural_tbd` | 42.03 MB "tbd" recovery tree; purpose not established |
| `/home/google/DifficultCode` | purpose not established |
| `/home/google/hiranktesting` | purpose not established |
| `/home/google/AI_PURGE_PSEUDOFS` | root-owned; not this user's to alter |
| `lockdown-20260831T15*.log` (8 files) | root-owned logs; not this user's to remove |

Per the gate's "if uncertain: UNKNOWN_STOP", these are surfaced for Garrett rather than
assigned an action. Declaring them is compatible with a READY verdict; silently guessing
would not be.

---

## 10. Recommended workspace structure

The proposed consolidation target evaluates well, with one addition:

```
/home/google/SyMoNeuRaL-Workspace/
├── evidence/     97 dated evidence roots            ~1.16 GB
├── handoffs/     a-series + session records          ~0.5 MB
├── staging/      transient model/build staging       ~0 GB
├── builds/       SyMoNeuRaL-Builds, engine-repro,
│                 gocache-b, gocache-c               ~7.1 GB
├── archives/     34 archive bundles                ~10.9 GB
├── backups/      ServerTransfer, SyMoNeuRaL-Backups,
│                 gate1-unit-backup                 ~15.4 GB
└── imports/      operator scripts and scan tools    ~0.1 MB
```

`/home/google/Symoneural` remains the canonical repository and receives **nothing** from this
plan. The three distinctions the gate names are held: no build or staging output is proposed
for the repository, no historical evidence is proposed for the repository, and third-party
trees (`src/oss`, `TensorRT-LLM`, `bentoml`, `ComfyUI-Installs`, `Platforms`, `Toolchains`)
are kept out of the workspace entirely — they are upstream material, not SyMoNeuRaL work
product, and consolidating them would misrepresent what the workspace holds.

`/home/google/ComfyUI-Shared` must **stay where it is**, because the canonical repo symlinks
to that exact absolute path. Moving it into the workspace breaks the repo.

This is a **proposal**. Nothing was created; the directory does not exist.

---

## 11. Exact proposed cleanup order

The ordered manifest is `HOME-CLEANUP-MANIFEST.tsv` — 56 rows:

| Action | Rows | Meaning |
|---|---:|---|
| KEEP | 13 | protect first, before anything moves; **row 0 is the critical vault archive** |
| DELETE_EXACT_DUPLICATE | 9 | every one proven by SHA-256 or byte comparison |
| DELETE_DISPOSABLE_STAGING | 1 | this session's own staging remnant |
| MOVE | 10 | relocation groups covering 128 inventory entries |
| REVIEW | 13 | needs an owner decision |
| UNKNOWN_STOP | 10 | stop and report |

Ordering rationale: **rows 0–12 assert protection before any mutation is attempted**, so a
partially executed run cannot damage a protected path. Rows 13–15g are the only deletions.
Rows 16–25 relocate. Rows 26–48 require a human.

Every deletion names an **exact absolute path**. There are **no wildcard deletion
proposals** — the two grouped rows that mention many files (23–25, MOVE) require one `mv`
per entry with paths taken from `HOME-INVENTORY.tsv`, and row 48 lists root-owned logs as
UNKNOWN_STOP rather than as a deletion.

Every MOVE row carries source, destination, precondition, expected identity and rollback.
Every DELETE row carries the objective evidence supporting it.

---

## 12. Estimated disk space reclaimed

| Category | Bytes | GB |
|---|---:|---:|
| **Reclaimed by proven deletion** (rows 13–15g) | **439,003,525** | **0.409** |
| Relocated, not reclaimed (rows 16–25) | 26,971,520,146 | 25.119 |
| Potential further reclaim, owner decision (REVIEW) | 78,380,742,262 | 72.998 |
| Held pending clarification (UNKNOWN_STOP) | 4,968,936,938 | 4.628 |
| Protected (KEEP) | 272,772,403,851 | 254.039 |

Breakdown of the proven reclaim — every line an exact path with a byte-level proof:

```
239,392,891   HashingManifestSignsChecksums/…yocto-compiled-code-scan…   diff -rq
 89,472,788   Downloads/symoneural-repo-2026-08-19.tar.gz                sha256
 20,745,642   Downloads/Symoneural-yocto-…-20260828T200848Z.tar.gz       sha256
 19,922,944   Downloads/symoneural.zip.part-00                           sha256
 19,922,944   Downloads/symoneural.zip.part-01                           sha256
 19,922,944   Downloads/symoneural.zip (1).part01                        sha256
 14,790,007   Downloads/symoneural.zip.part-02                           sha256
 14,790,007   Downloads/symoneural.zip (1).part02                        sha256
     35,688   SYMONEURAL-GATEWAY-…-PROMPT (1).txt                        sha256 + cmp
      7,670   staging-image-2026-09-03                                   disposable staging
-----------
439,003,525   = 0.409 GB
```

**The honest headline is that provable cleanup reclaims 0.41 GB, not tens of gigabytes.**
The 68.8 GB of project clutter is overwhelmingly material with genuine retention value that
is merely misplaced — it needs organising, not deleting. Scanning `Downloads` nearly doubled
the provable reclaim (0.22 → 0.41 GB), which is worth noting mainly because it shows how
small the deletable fraction really is even after a deliberate hunt for duplicates.

The large reclaims Garrett may be hoping for all sit behind REVIEW decisions only he can
make: `/home/google/src` (24.90 GB of re-clonable upstream OSS), the personal media in
`Downloads` (~24 GB of ISO and photo bundles), and `ComfyUI-Installs` (7.17 GB). Approving
the REVIEW tier is where the space actually is, and this audit deliberately does not
pre-approve it.

---

## 13. Mutations performed

Inside the single authorized evidence root
`/home/google/symoneural-home-cleanup-audit-20260903/`:

1. Created the directory itself.
2. `HOME-INVENTORY.tsv` — 291 rows, one per top-level entry.
3. `HOME-CLEANUP-MANIFEST.tsv` — 56 ordered rows.
4. `HOME-REFERENCES.tsv` — 36 rows with the `reference_kind` column.
5. `HOME-DUPLICATES.tsv` — 21 candidate pairs/sets with proof method and verdict.
6. `HOME-LARGEST.tsv` — the 25 largest cleanup candidates.
7. `HOME-CLEANUP-AUDIT-20260903.md` — this report.
8. `SHA256SUMS` — digests of the above.
9. `HOME-TOTALS.tsv` — per-class totals. **This is a tenth file beyond the seven the gate
   names**; it is declared here rather than left unmentioned. It contains only aggregate
   sums already reproduced in §2.
10. Three dot-prefixed working files retained as raw measurement evidence:
    `.sizes-visible.tsv`, `.sizes-hidden.tsv`, `.hashes.txt`. Also declared rather than
    hidden — they are the primary readings the TSVs are derived from.

Outside that root: **nothing.** One scratchpad generator script
(`gen_audit.py`) was written to the session scratchpad, which is outside `/home/google`.

No credential content was read into, or copied into, any evidence file.

---

## 14. Prohibited actions not performed

Confirmed not done:

- **Nothing deleted, moved, renamed, compressed, extracted, or deduplicated by deletion.**
- **No symlink changed.** Both discovered symlinks were read with `readlink` only.
- **No service edited, started, stopped, reloaded, or restarted.** Unit files were read only.
- **No shell configuration edited.** `.bashrc`, `.profile`, `.zshrc` read only.
- **No repository file edited.** `/home/google/Symoneural` was read only — `git grep`,
  `git worktree list`, `git rev-parse`, `git log`, file reads. Codex held sole repository
  mutation authority throughout and this audit did not contend for it.
- **No process killed.** `/proc` was read only.
- **No cache cleaned.**
- **No Git state altered** — no stage, commit, worktree add/remove, prune, or gc. The HEAD
  move to `1d72cc6e` was Codex's authorized commit, not this audit's.
- **No evidence modified.** Existing evidence roots were listed and read, never written.
- **No mount modified.** `/yocto` and `/mnt/gdrive` were observed via `mount` only.
- **No cleanup executed.** No agent dispatched. No next task selected.
- The proposed `SyMoNeuRaL-Workspace/` tree was **not created**.

---

## 15. Final verdict

**HOME CLEANUP PLAN READY FOR OWNER AUTHORIZATION**

Coverage is complete — 291 of 291 top-level entries classified, verified against a live
listing with no gaps — and every entry carries exactly one primary class and a reference
state derived from actual consumers rather than from documentation. The plan is executable:
48 ordered rows, every deletion naming an exact path backed by byte-level proof, every move
carrying a precondition and a rollback, and no wildcards anywhere.

Four findings materially changed the plan and would each have caused damage if missed:

1. **`Downloads/symoneural-vault-2026-08-19-v2.tar.gz` is the only located copy of the
   persona LoRA weights and of `CHAT_ADAPTER`** (`backend/server.py:237`). Those files exist
   nowhere on the live filesystem. It sits in the directory most likely to be bulk-deleted,
   and it is now manifest row 0.
2. Two **registered git worktrees** masquerading as build clutter — a plain `rm -rf` would
   corrupt administrative state inside the canonical repository.
3. The canonical repository's outbound **symlink dependency** on `ComfyUI-Shared`, which
   means that directory cannot be moved into the proposed workspace.
4. **`Platforms.tar.gz` is 90× larger than its extracted directory** — an archive a
   filename-based duplicate rule would have destroyed as the redundant copy when it is in
   fact the primary one.

Ten items are declared UNKNOWN_STOP rather than guessed, which is what makes the remainder
safe to execute.

No cleanup was executed. The next authorized mutation gate can run rows 1–25 from this
manifest without re-deriving any of it.

---

## Control state at stop

```
Claude:  STOPPED — MUTATION AUTHORITY: NONE
Codex:   repository task authority independent of this audit
Garrett: SOLE TASK AUTHORIZER
```

Cleanup not executed. No agent dispatched. Repository not modified.
