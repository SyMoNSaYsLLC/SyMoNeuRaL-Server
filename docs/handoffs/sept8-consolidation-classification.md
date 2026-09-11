# Sept 8 — Home-directory consolidation: classification and gate

> **REDACTED COPY.** Credential filenames and infrastructure posture masked as `*****`. Concepts kept, identifiers blurred.
>
> **Read-only pass. Nothing was moved, merged, renamed, deleted or committed.** Every row below was read off the disk this session, not off a prior document.

## Continues from

`sept4-concurrent-session-decision-gate.md` (2026-09-05, HEAD `30add06b`). Tree was clean at powerdown; it still is.

## The request

Review ~26 directories in `/home/google`, merge/migrate/rename them into the repo, update the documentation, test, and commit — with the end goal that **all engines are first-party code in `backend/apps`**.

Three facts change the shape of that job, and one changes its scope. All four are measured.

---

## 1. Facts, not decisions

| Stated | Measured |
|---|---|
| repo at `/home/google/SyMoNeuRaL` | **Does not exist.** The repo is `/home/google/Symoneural`. Proceeding against the real path. |
| `symoneural-workspace`, `symoneural-projects` | **Do not exist.** The 277 GB `SyMoNeuRaL-Workspace` is probably what was meant by the first. |
| `review` | **Empty** — 0 files. |
| `RAVENCALC.md` | **A directory, not a file** — an unzipped `.docx` (`[Content_Types].xml`, `_rels/`, `word/`) with a `.md` name. |

## 2. Git-tracking the bulk is infeasible, and the repo already forbids it

Not a disk-space argument — `mv` inside `/home` is free. The problem is that committing this material **doubles it into `.git` objects** and contradicts the repo's own rules.

```
/home/google/Symoneural           159 G   (repo as it stands)
SyMoNeuRaL-Workspace              277 G   of which archives 253 G, backups 16 G
src/oss                            30 G   46 upstream OSS trees
ComfyUI-Installs                  7.2 G
symoneural-build-20260902         3.2 G   already ruled: leave (never-deployed evidence)
TensorRT-LLM                      2.2 G
ComfyUI-Shared                    1.7 G   model weights
                                  -----
free on /home                     263 G
```

`docs/ops/EXPORTS.md` already excludes weights, `run/`, `review/`, `.env` files and session transcripts; `.gitignore` already excludes `review/` and `run/`. Bulk archives, backups and third-party source trees are the same class. **They get a recorded home and a manifest, not a commit.**

## 3. The licence wall — this is a scope change, not a note

The four first-party engines worked because their upstreams are permissive. The fifth is not.

| Engine | Upstream licence | First-party fork available? |
|---|---|---|
| `symoneural-llm` | **MIT** | yes — done |
| `symoneural-diffuse` | **MIT** | yes — done |
| `symoneural-listen` | **MIT** | yes — done |
| `symoneural-miner` | (no root LICENSE; vendored kawpowminer) | yes — done |
| **`symoneural-ui` (ComfyUI)** | **GNU GPL v3** | **NO** |

Verified twice on disk: `engines/symoneural-ui/LICENSE` and `ComfyUI-Installs/TestingforChatGPT/ComfyUI/LICENSE` are both GPL-3.0.

**MIT permits relicensing the combined work as proprietary provided the notice is retained — GPL-3.0 does not.** The Caddy pattern that `symoneural-web` uses (import Apache-2.0 upstream as a library, proprietary licence on the wrapper only, `THIRD_PARTY_NOTICES.md` for the 157 linked modules) is available for Apache/MIT and **unavailable for GPL-3.0**.

The codebase already knows this. `tools/fork_engines.sh` defines `fork_llm`, `fork_diffuse`, `fork_listen`, `fork_miner` — **there is no `fork_ui`.** The pattern was never extended to it, and it cannot be.

What *is* available: ComfyUI runs as **its own Python process** (proxied at `127.0.0.1:8188` in `ops/Caddyfile`; no systemd unit yet). Separate-process invocation is aggregation, not linking, so the project can ship and drive it under GPL-3.0 terms — first-party code calling it across a process boundary, GPL notice intact, no proprietary claim over ComfyUI itself.

**So "all five engines as first-party proprietary code in `backend/apps`" is not achievable for the fifth.** Three honest options in §6.

---

## 4. Classification — all 26 targets

### A. Merge into the repo, git-tracked (small, first-party, documentation)

| Target | What it actually is | Proposed home |
|---|---|---|
| `SymonSaysLLC` (1.1 M, 26 files) | A-4 / D-11 decision records — same family as the `handoffs/` rulings | `docs/decisions/` |
| `symoneural-docs-reconciliation-20260903` (36 K) | one reconciliation document | `docs/decisions/` |
| `symoneural-lora-restoration-20260903` (48 K) | `LORA-PAYLOADS.tsv`, `SHA256SUMS`, restoration write-up — **metadata only, no weights** | `docs/ops/` |
| `DifficultCode` (940 K) | `coder/`, `dispathosbuild/`, `gssymondevalien-ui/` — **looks first-party; needs a read before it moves** | TBD — see gate |
| `RAVENCALC.md` (544 K) | exploded `.docx` | `docs/` as a real document, re-zipped or converted |
| `hiranktesting`, `AI_PURGE_PSEUDOFS` (56 K each) | identical-looking host diagnostic dumps (`CGROUPS/KERNEL/EFIVARS/ERRORS`) | `docs/ops/diagnostics/`, deduplicated |

### B. Record a home + manifest, do NOT git-track (bulk, third-party, weights, evidence)

| Target | Size | What it is |
|---|---|---|
| `SyMoNeuRaL-Workspace/archives`, `/backups` | 253 G + 16 G | archive + backup corpus |
| `SyMoNeuRaL-Workspace/handoffs`, `/evidence` | 98 M + 1021 M | **the live handoff chain — already the canonical home. Leave exactly as is.** |
| `src/oss` | 30 G | 46 upstream OSS trees (linux, llvm, chromium, openssl, nginx, mongo…) — reference corpus |
| `ComfyUI-Installs` | 7.2 G | third-party GPL-3.0 installs |
| `ComfyUI-Shared` | 1.7 G | **model weights** (`models/`, `input/`, `output/`) |
| `TensorRT-LLM` | 2.2 G | NVIDIA, Apache-2.0, its own git repo |
| `symoneural-model-downloads-20260902` | 60 K | Qwen2.5 GGUF pointers |
| `symoneural-lora-restore-staging-20260903` | 40 M | LoRA staging payloads |
| `ninjatraining` | 381 M | `Symoneural-OE` — Yocto/OpenEmbedded build |
| `Toolchains`, `Platforms` | 116 M + 2.6 M | Xcode / JDT toolchains, Apple SDK platforms |
| `bentoml` | 636 K | BentoML runtime state (`bentos/`, `models/`, `envs/`) |
| `symoneural-build-20260902` | 3.2 G | **already ruled — leave.** Never-deployed build evidence |
| `symoneural_tbd` | 43 M | single `recovery/` tree |

### C. Never commit — contains credential material

| Target | Why |
|---|---|
| `symoneural-cutover-rollback-20260826-154113` (65 M) | holds a live `*****` environment file and a vendor binary, alongside the rollback manifest and unit files. `docs/ops/EXPORTS.md` rule 3 excludes this class outright. Manifest and unit files can be extracted; **the credential file stays put and untracked.** |

### D. Third-party agent installs — out of scope, already declined once

| Target | Why |
|---|---|
| `Claude` (172 K), `ClaudeAlienware` (171 M) | vendor agent state and artifacts. Rebranding the vendor install was declined on 2026-09-04 — compiled ELF, no source, third-party proprietary, and it is the running install. Same answer here. |

---

## 5. Runtime ↔ application map — measured

```
engines/            symoneural-llm      MIT      first-party fork   built
                    symoneural-diffuse  MIT      first-party fork   built
                    symoneural-listen   MIT      first-party fork   built
                    symoneural-miner    vendored first-party fork   built
                    symoneural-ui       GPL-3.0  NOT forkable       vendored, no unit

services            symoneural-api      :8000    active/enabled
                    symoneural-web      :80/:443 active/enabled  (Caddy as library, Apache-2.0)
                    symoneural-gateway  ---      inactive/disabled, 64 source files intact
                    ComfyUI render      :8188    proxied in ops/Caddyfile; HANDOVER records
                                                 "Studio inference answers; render service 8188 does not"

build path          tools/fork_engines.sh   references/contrib -> engines/
                    fork_llm | fork_diffuse | fork_listen | fork_miner    (no fork_ui)
```

The user's target is `backend/apps`. The engines currently live in `engines/`, built by `fork_engines.sh` out of `references/contrib`. Moving them is a `git mv` plus a path update in that script and the units — cheap and safe — **but it is a different question from making them first-party**, which four of five already are.

---

## 6. GATE — two decisions, and I am not proceeding past them

**Q1 — what does "merge into the repo" mean for the bulk?**
Group A (a few MB of first-party source and documents) is unambiguous and I will do it. Group B is ~320 GB of archives, weights and third-party source. Options: a recorded home plus a tracked manifest in the repo; or move it under the repo path but gitignored; or leave it where it is and only document it.

**Q2 — the GPL-3.0 engine.** `symoneural-ui` cannot become proprietary first-party. Options: ship alongside it under GPL-3.0 with first-party code driving it across the process boundary; replace it with a first-party render surface over the already-MIT `symoneural-diffuse`; or keep it vendored as-is and drop the first-party goal for that one engine.

Everything else I can decide as a careful colleague and will state as an assumption rather than ask.

## Errors and judgment calls

- I did **not** treat any directory as understood from its name. `RAVENCALC.md` looked like a file and is a directory; `review` looked like the repo's gitignored `review/` and is an empty unrelated directory; `symoneural-cutover-rollback-*` looked like an artefact set and holds credential material. Each was opened.
- I have **not** read inside `DifficultCode` beyond its three top-level names. It is the one Group A row I am not yet confident about, and it is marked TBD rather than assigned a home.

## To resume

```
repo    /home/google/Symoneural   branch main   HEAD 30add06b   tree CLEAN
state   nothing moved, nothing merged, nothing committed
next    Q1 + Q2 answered -> Group A merges first, one commit per target
        so that any error is attributable to a single item
```
