# Scope of work — 2026-08-22

**This is a dated proposal, not a state document.** `PROJECT-TASKS.md` is the canonical list
and stays it; `run/progress.html` is the reading. New items here enter through the ledger
(R-175..R-178, captured tonight) and become numbered tasks the way everything does. If this
file and the task list ever disagree, the task list is right and this file is stale — that is
the rule that killed the last three documents which claimed to describe current state, and it
applies to this one on purpose.

Everything below is grounded in what is on disk tonight: the open tasks (#75–#102), the
uncommitted working tree, `docs/studio-harness-gap.md`, `symoneural-diffuse/SMOKE-livestack-image.md`,
and the miner audit under R-176. Where a figure appears it names where it was read.

---

## Phase 0 — clear the tree (hours, blocking everything)

The working tree currently carries four unrelated changes. Nothing new starts until they are
verified and committed separately — this phase is the commit-hygiene plan already agreed, plus
the repo's own standing re-measure instruction.

| Step | What | Gate |
|---|---|---|
| 0.1 | **Gateway fold verification** (R-175). The block is written; the two readings that decide it: `rows: 13` with no top-level `gateway`, and `miner subs` ending `('gateway','net','offline')`; then `frontend.mjs`'s *"gateway page prints the API's own state verbatim"* — the assertion that catches a bad `sub` lookup rendering "not present" to every visitor. | all suites green + that line |
| 0.2 | **Commit A** — fold: `backend/server.py`, `backend/apps/ROSTER.md`, `test_status_rack.py`, `test_roster.py`, `tools/build_pages.py`, `tests/frontend.mjs`, `site/gateway.html` (generated output ships with its generator — #81's lesson) | `git diff --cached --check` |
| 0.3 | **Commit B** — `docs/studio-harness-gap.md` (#89 → 50%, does not archive) | — |
| 0.4 | **Commit C** — closure evidence: `PROJECT-TASKS.md`, `review/CLOSED-TASKS.md` | — |
| 0.5 | **Full-suite re-measure.** CLAUDE.md's own instruction: the 1758 reading has no SHA because the ravencalc repair was uncommitted; `ce4fb27c` landed it. Run both invocations from `backend/`, plus `apps/remix`, stamp the counts with the SHA, extend the ladder. | counts + SHA in CLAUDE.md |
| 0.6 | **Tree hygiene.** `symoneural.zip` (40 MB export) out of the repo root; decide `.claude/settings.local.json`. | `git status` = clean |
| 0.6b | **CLAUDE.md migration** (R-180). Migrate, never delete: durable rules → `docs/ENGINEERING.md`, the ladder (with 0.5's fresh entry) → `docs/ops/MEASUREMENTS.md`, export policy → `docs/ops/EXPORTS.md`; `CLAUDE.md` survives as a short pointer so the say-hi onboarding keeps working; stale Claude-only files → `garbo/` (precedent `2d2af124`). KEEP list is explicit: `.claude/settings.local.json` (interpreter deny rules), `.claude/HANDOVER.md` (canonical state), `.claude/worktrees/`. Own hygiene/docs commit. | inventory classified; grep for active `CLAUDE.md` deps returns pointers and history only |

### Phase 0.1–0.4 — CLOSED 2026-08-22 09:36 EDT

The gate and its hold are history. Verification classified green on all six keys at
`e71b51f7` (97 pytest · 63/63 frontend · rows:13 · no top-level gateway ·
`('gateway','net','offline')` in miner subs · `site/index.html` regenerated), and the
commits landed in order and were then message-repaired at 09:47 — Commit A's history-expansion
clip amended with `-F` and B/C rebased on top. **Final chain: A `c779e2cb` (fold, 8 files),
B `294564e9` (gap doc), C `242a688d` (`PROJECT-TASKS.md` only — `/review/` is gitignored
on-disk evidence, never force-added).** The pre-repair set (b5731054/5a29352f/f29a1f68) lives
on branch `phase0-before-message-repair` until 0.6 hygiene deletes it. Verified directly:
`git log -1 --format=%B c779e2cb` carries the full lookbehind paragraph — the `-1` matters,
since bare `git log --format=%B <ref> | tail` prints the OLDEST message, which is how the
repair block's own verification step misreported the initial commit as Commit A.

The capture pattern survives by reference for every later gate: tee the run to a log,
grep a decision tail, hand over thirty lines. One lesson from this pass joins it:
**interactive bash history-expansion ate a commit-message line containing `!` —
write multi-line messages to a file and commit with `-F`, or `set +H` first.**
Commit A's last paragraph lost its lookbehind sentence to exactly that; the full
lesson survives in `test_status_rack.py`'s own comment.

Next: **0.5 full-suite re-measure**, then **0.6 tree hygiene**.

### Phase 0.5 — CLOSED GREEN 2026-08-22, measured at `ca0571b7`

First run: 3 fail at `242a688d` (the SHELL-placeholder pair and the SERVER-READY gateway
row), fixed as Commit D `ca0571b7`. Rerun on D's own tree, post-run status untracked-only:
**1818 pass, 0 fail, 14 skip in 143.73 s; collect-only 1832 = 1818 + 14; remix 28/28 in
0.44 s.** Ladder written into `.claude/CLAUDE.md` (headline + rung) in house style — one
home for counts, not two. Next: Commit E (the ladder entry), then 0.6 hygiene and 0.6b.

Deploy discipline for every phase after this one, learned the hard way tonight: verify →
commit → capture `SHIP_SHA` → `deploy.sh` → `install-caddy.sh` if the Caddyfile moved →
**restart the API** → public smoke with GET (not `curl -I`) → evidence file naming the SHA.

## Phase 1 — repairs already found, small and compounding

These are findings with evidence attached, not ideas. Each is one sitting; together they make
every later phase cheaper to ship safely.

1. **The deploy/restart guard.** Nothing in `deploy.sh` or `install-caddy.sh` restarts the
   API, so the public origin serves a process older than the commit — `/livestack/coder` was
   publicly 404 from #87 landing until tonight, with a green suite throughout. Extend #86's
   `check_deployed.py` scope: compare the *running service* against the tree (a `/api/status`
   build stamp, or route-probe), and put the restart into the deploy sequence or
   `ops/symoneural-deploy.service`. This is the highest-leverage single item in this file.
2. **#102 — rotate the spent Studio token** (R-174). Garrett's half is the root-owned edit;
   the coder half is the probe-not-environ lesson already written into the ledger.
3. **#75 — secrets.** Rotate → untrack `remix/.env` and `cryptominer/miner.env` → archive-path
   leak guard. **Hard prerequisite for Phase 4**, which wants HF sources and download tooling;
   a model catalog must never be the reason a token lands in a tracked file.
   **New sub-item, found 2026-08-22: whole-repo zip exports carry the trade secret.** Every
   export shared tonight — `symoneural.zip`, the structure/livestack passes, and
   `symoneuralv2_scope_applied.zip` — contains `training/corpus.jsonl` (320 KB, the 327
   hand-authored examples) and `training/build_dataset.py`, because both are tracked and the
   exports were built from tracked files. Trade secret exists only while reasonable measures
   keep it in; zips into third-party sandboxes are the erosion CLAUDE.md warns cannot be
   pulled back. Fix: an export script (`tools/export_snapshot.sh`) that excludes the two
   protected artefacts, the mode-600 ledgers, and adapter weights — and make it the only
   sanctioned way a snapshot leaves this box.
4. **#92 — `check_figures.py`.** Every published figure carries the SHA it was read on. The
   miner audit alone produced three new figures tonight; the tool pays for itself immediately.
5. **HEAD/404 uniformity** (recorded on closed #81). Every extensionless route answers
   GET=200 HEAD=404, StaticFiles swallows the miss, `curl -I` reports working pages dead.
   Either add HEAD everywhere — including `/`, where the mount serves `index.html` on HEAD
   while the API redirects GET — or write the probe discipline into CLAUDE.md and close it as
   documented behaviour. A decision, not a mystery.

## Phase 2 — Miner to 100% (R-176; folds #85, tasks #6/#7 pending numbers)

Order matters here: cull before build, build before page, page shows real readings.

| Step | What | The check that cannot lie |
|---|---|---|
| 2.1 | **Cull.** Legacy `SyMon_MinerGPUWorker_PROD_20260102-1818/` → `garbo/` with a README line; `asicminer/.venv` off the app tree (per-app venvs live by the env rules, not in-package); `miner.env` handled under #75; `miner.env.example` repointed off the dead `contrib/` path. | `ngrep contrib/kawpowminer -- backend/apps/cryptominer/miner.env.example` |
| 2.2 | **Build `engines/symoneural-miner`** from kawpowminer — R-150's unfinished quarter, the pattern proven twice (`symoneural-llm`, `symoneural-diffuse`): our name, upstream copyright carried, sm_120, built in `engines/`, never from `references/`. | `exists engines/symoneural-miner/build/bin/symoneural-miner` + a SMOKE with a measured Mh/s and SHA, superseding the vendor 52.6 log |
| 2.3 | **Governor integration.** The miner takes the lock through `gpu-governor.sh with gpuminer --`, never evicts `train`, never runs while a P0 surface holds the card. A real short run writes `SMOKE-miner.md`. | the smoke file — only a run writes it honestly |
| 2.4 | **ASIC vendors** (#7): resolve "bf" (Bitfury vs Braiins — different companies, different firmware), extend `scan.py`/`probe.py`/`fwcheck.py`; emulator only where firmware is obtainable and decryptable, and a documented refusal where it is not — the Whatsminer-encrypted precedent, kept. | vendor detection asserted in `test_asic.py` against fixtures |
| 2.5 | **#85 — the page**, embedded the way RavenCalc is, instrument first, folding not trimming. Done last so it renders the new engine's real readings instead of a nicer arrangement of "offline". | `MinerEmbeddedTests` + `miner-instrument-first` in frontend.mjs — written against the working surface, never as stubs |

Exit state: the tile's *"KawPow on the RTX 5070 Ti"* is true, or the tile says what is true.

## Phase 3 — Studio to 100% (R-177; #89 + #88, order from the gap doc §7)

1. **Permissions card in the browser.** The one safety inversion: four `dangerous=True` tools
   and the only surface that can refuse them is the CLI. Protocol exists (`agent.py:242-307`);
   the page needs the card and the resume wire. Red-first: a test drives `ask` mode and
   watches the browser refuse.
2. **Wire the workflow converter.** `graph.py` + `GET /api/studio/workflow/{name}` exist and
   nothing calls them; the editor's Workflows panel reads "No workflows found" — the first
   difference anyone meets coming from Comfy Desktop. Convert `flux-schnell` to graph format
   into the editor's workflows dir, save-back next.
3. **Sessions on the page.** The CLI already threads (`run/agent-<session>.json`); the page
   lists, resumes, and stops being a single-turn amnesiac.
4. **Tool cards, diffs first.** `write_file`/`generate_native_code` already return structure;
   render it instead of raw JSON where raw JSON hides what changed on disk.
5. **The plugin surface** — Exp's runtime (manifest, fibers, `ctx.effect`, hot reload, the
   mount/patch/enable UI) migrated onto Studio, per #89's stated dependency; the rack's Exp
   row folds per R-163. `StudioPluginSurfaceTests` exists because the surface exists.
6. **#88 — token posture**, Garrett's call from R-162's three options (recommended: nothing on
   read paths, token only where the card or disk is at stake). Landed whenever decided; the
   proof is `studio.mjs` passing with nothing set.

Exit state: #89's both checks green honestly, `tests/studio.mjs` grown to cover each step,
and a person opening `/studio` after Comfy Desktop finds their workflows where they expect.

## Phase 4 — the dual-model / function-block epic (R-178)

Adopted with three corrections where the pasted scope collides with standing decisions:

**Host it on Studio's plugin surface, not beside it.** The addendum proposes
`backend/apps/{models,pipelines,agents}` — three new registries in a repo that already has
Studio's tool registry, Exp's plugin registry, and `ROSTER.md`. The gap analysis's central
finding is that we already built the lifecycle machinery once on the wrong page; the answer
is not a third copy. Function blocks are plugins on the Phase-3 surface; pipelines are
manifests in the format Exp already parses (its presets are YAML pipelines today); agents are
presets. **Phase 4 therefore starts after Phase 3 lands** — that is a dependency, not a
preference.

**GPU profiles are policy on the governor, not a second arbitrator.** `gpu-governor.sh`
already owns surfaces, leases, the compute-scoped drain floor (R-171), and the
never-evict-train rule. `dual_resident_quantized` / `single_resident_swap` / `staged_gpu`
become planner logic that *asks* the governor, with the priority ladder P0 interactive → P1
training → P2 batch → P3 miner. No `pkill -STOP` arbitration — killing or freezing a process
does not return CUDA memory, and the next tenant OOMs at step 0; that is measured behaviour
here, not opinion. **Feasibility stated with tonight's numbers, then re-measured:** 15.92 GiB
card, 1.3–1.4 GiB KDE, warm `symoneural-llm` ~8.1 GiB resident → the honest first "dual" is
the 7B-Q4 plus one small tenant (whisper / CLIP / rembg / a classifier). Two 7Bs is a
measurement to take, not a claim to make; `single_resident_swap` is the fallback the design
must be comfortable in. No silent CPU fallback — RavenCalc is CPU *by design and says so*,
which is the standard.

**Routes: `/api/*` is public; the developer surface is `/local/*`.** Every new
`/api/models|pipelines|agents` route goes out through Caddy to the internet on the day it
exists, so the #88 token decision precedes them, writes stay behind the gateway's validation,
and nothing takes the card without a lease. The route-index / code-jump system (`file:` /
`vscode://` links to `routes.py:144`) is genuinely good and goes under `/local/` behind the
existing peer-address check — the proven trust path — not a new `/dev/` convention. Build it
as a generator (`tools/build_route_index.py`) reusing the AST scanners that
`test_caddy_delegation.py` and `test_deploy_routes.py` already maintain, so there is one
route-parsing truth, not a third parser to teach. No `/v1` migration; the gateway owns `/v1`.

**Kept from the addendum as written:** the catalog schema (id, family, type, path, source,
license, VRAM estimate, precision, loader, allowed blocks, routes, owner, status); the
function-block vocabulary with typo aliases normalised in code; provenance-before-ready —
already this repo's law (`backend/models/PROVENANCE.json`, LICENSES.md, the honesty rules),
now enforced by a check; no auto-download of unlicensed weights; real tests over grep stubs;
and the pipeline shapes — discussion, coding (planner → coder → test runner → reviewer),
training (QLoRA path exists in `training/`), image (encoder → diffusion → controlnet/lora →
VAE), voice (whisper → agent → TTS, which also finally builds `symoneural-listen`, R-150's
other missing quarter).

**Decomposition when its turn comes** (each with checks only a run turns green):

1. Catalog schema + `backend/models/catalog.yaml` starter set, reconciled with the existing
   `NAMES.md`/`PROVENANCE.json` and the Comfy-Desktop model dirs — one models story, not two.
2. Registry parser + validation tests (parse, license coverage, block→implementation, stage
   references resolve).
3. `tools/build_route_index.py` + `/local/routes` + the panel links.
4. Governor profile planner, red-first: an unsafe pair is **refused** and a test watches the
   refusal happen.
5. Discussion pipeline MVP — the milestone that proves the epic: **two models resident under
   an approved profile, one conversation between them over the API, the VRAM curve recorded
   in a SMOKE.**
6. Coding pipeline; image chain (wiring what Studio/ComfyUI already do into declared blocks);
   voice.
7. The model-graph panel on Studio, with a browser gate proving it executes — loaded/available
   models, blocks, pipelines, leases, licenses, and the code-jump links (local origin only).

### Phase 4 standing non-claims — adopted into scope 2026-08-22

Written first by the parallel prototype's own PATCH-SUMMARY and adopted here as **gates on
every Phase-4 increment**, not just that patch. Each is a sentence a SMOKE or a reviewer must
be able to repeat truthfully of the increment in front of them:

1. **No claim that two full 7B models fit simultaneously on the RTX 5070 Ti** until a run on
   this box records the VRAM curve. Until then the planner's `max_large_models: 1` stands and
   the honest dual is 7B-Q4 + one small tenant.
2. **Catalog/registry/planner changes load no GPU weights.** Planning is paper; a dry-run
   route answers without touching the card. The first increment that loads weights is the
   discussion-pipeline MVP, and it arrives with its SMOKE.
3. **`scripts/gpu-governor.sh` is neither modified nor replaced** by planner work. Profiles
   ask the governor; any change to the governor itself is its own task with its own measured
   eviction/drain evidence.
4. **Local editor/code links never reach the public origin.** `/local/*` behind
   `_require_local`, absent from the public OpenAPI, and no `/api/*` response ever carries a
   `file://`/`vscode://`/`pycharm://` link.
5. **No increment is a deploy smoke of itself.** Everything re-runs the discipline on this
   box: verify → commit → `SHIP_SHA` → deploy → restart the API → public GET smoke →
   evidence naming the SHA. A green run in any other sandbox is a claim about that sandbox.

### The parallel prototype (`incoming/symv2-parallel/`), assessed 2026-08-22

A second implementation pass, built outside this repo on a ~00:56 snapshot and returned as
`symoneuralv2_scope_applied.zip`. Read, not merged. What it got right is worth keeping:
`modelgraph` under `backend/apps/studio/` rather than a third registry; `/local/routes` +
`/local/model-graph` behind `_require_local`; literal route decorators both guard parsers can
see; a **JSON-compatible catalog so the serving path stays stdlib-only** (no yaml import —
repo-literate); `budget_mib: 13620` with `max_large_models: 1`; and an honest non-claims
section this scope now inherits.

**Why it must be re-applied as a patch and never adopted as a tree:** its base predates the
gateway fold — `api.py` there still builds gateway as a top-level Unit and says FOURTEEN — so
taking the tree reverts R-175. It has no `.git`, and `git log` is load-bearing here. Its
claimed test result (44 passed, 191 subtests) was run in its own sandbox and is a claim about
that sandbox; the numbers that count are read on this box when the patch lands at its place
in the phase order. Two review items for that landing: the public `/api/studio/model-graph*`
reads ride the tokenless-read precedent and must wait on the #88 posture decision; and the
per-model license/provenance enforcement is proven for exactly one model (rembg) — the check
must fail on an *uncovered* model, red-first, before "provenance-before-ready" is claimed.

### Phase 4.8 — SyMoNeuRaL Sentinel (R-179, spec at docs/specs/symoneural-sentinel-spec.md)

A model-facing supervisor between a client and a target model: shadow the context, score the
draft before it becomes durable history (drift, contradiction, unsupported claims, entropy),
intervene on a ladder — observe · nudge · prune · restrain · escalate to the Phase-3
permissions card — with an **append-only audit for every intervention**, because a supervisor
that silently rewrites history is the one dishonest pixel this product cannot carry. Not
healthcare, and the production wording says so.

Arrived pre-adapted to the house rules and adopted with two corrections, both in the spec:
the proposed `/v1/chat/completions` shim collides with the `/v1` surface **symon-gateway
already owns**, so any shim is a gateway adapter and never a second claimant; and the
streaming question is decided up front — per-surface `buffered` (full interception, costs
the measured 0.2 s warm first-frame) or `post-hoc` (the stream passes; symptoms produce a
*visible* correction event), declared in the manifest, because a token shown cannot be
unshown. Evaluators are catalog models behind the provenance gate — rules + small
classifier first, never a second 7B by default; rules-only mode takes no lease. Depends on
Phase 3 (surface + permissions card), #88, and Phase 4's catalog and planner; proposed as
task #104 at promotion.

### A runnable example of these rules

`incoming/scope-example/` — stdlib-only, no pip, 16 unittest tests green and a demo that
writes its own SMOKE. Each Phase-4 rule appears as working code: the plugin surface with
inject/effects/failed-fibers, the JSON catalog, provenance-before-ready going red on a
deliberately uncovered model, the planner refusing by closed vocabulary (and the ordering
pinned: `provenance-missing` outranks `two-large-models`), the governor contract whose
`hold()` releases even on a crashing tenant, a dual-resident discussion run whose lease
events show both tenants genuinely holding together, and the one-AST-truth route index with
`local_only` editor links. Reference like its neighbours: read it, run it, import nothing.

## Phase 5 — cutover to a v2 runtime (advisory adopted 2026-08-22, premise corrected)

A decommission/commission addendum was proposed and its *procedure* is adopted: preflight
inventory, maintenance page, freeze-don't-delete, rollback written before the old service
stops, evidence binding the public smoke to the shipped SHA, and the abort conditions. That
is this repo's own deploy discipline extended to a whole-runtime swap, and it is right.

**The premise is corrected, and the correction is the phase:** there is no v2 repo today.
`symoneuralv2_scope_applied.zip` is a snapshot fork with **no `.git`**, whose base predates
the gateway fold — and this repo's history never leaves this box, which is doing much of the
protecting. What the zip also lacks tells you what a cutover to it would silently lose: the
mode-600 ledgers (`GARRETT-REQUESTS.md`, `INTAKE.md` are not in it), `run/` state including
the GPU lock, adapter weights, model weights, the built engines, and every commit's reason.

So Phase 5's first step is not a service swap, it is **how v2 comes to exist**: born from
live HEAD with history carried (`git clone`/worktree from `/home/google/Symoneural`, never
from a sandbox zip), patches re-applied on top, verified by the same suites. Only then does
the cutover procedure run — old repo frozen with its SHA recorded, renamed not deleted,
`ops/ROLLBACK-v2-cutover.md` written before the stop, `backend/SMOKE-v2-cutover.md` written
from the run. Proposed as task **#103** through intake, with the addendum's checks plus one
it was missing: `check: exists <v2>/.git` — a cutover target without history is refused at
the first gate, the way the planner refuses an unprovenanced model.

Sequencing: Phase 5 runs **last**, after Phases 0–4 have landed on the live repo — cutting
over mid-phase would strand verified work on the decommissioned side. And whether to cut over
at all, versus the live repo simply *becoming* v2 as the phases land, is Garrett's call at
the Phase-4 boundary; both paths keep every gate above.

## Dependencies, one look

```
Phase 0 ──► everything
#75 secrets ─────────────► Phase 4.1 (HF sources, download tooling)
#88 token posture ───────► Phase 4.3+ (every new /api route)
Phase 3.5 plugin surface ► Phase 4 host
Phase 2.2 engine ────────► Phase 2.5 page shows real readings
Phase 1.1 restart guard ─► every deploy after it exists
```

## Out of scope / standing rejections

The `/mnt/data` ZIP lineage and `livestack-scripts/`; Caddy rewrites or aliases of any kind;
meta-refresh redirects; moving pages out of `site/`; `git add .`; empty test classes that
satisfy grep checks; rewriting `api.py` into a stub gateway; `pkill -STOP` GPU arbitration;
`/v1` migration of existing routes; cloud serving, multi-GPU, Kubernetes; editor deep-links on
the public origin; auto-downloading unlicensed models; a second state document — including
letting this file become one.

## Acceptance discipline, all phases

Every phase ends the same way or it is not ended: measured figures with the SHA they were read
on; deltas attributed per file, never inferred from totals; a SMOKE record for anything that
runs, written from the run; generated output committed with its generator; deploy → restart →
public GET smoke; and the task's checks chosen so that 100% means done — the check that can
pass without the work is the one failure this repo has proven it cannot afford.
