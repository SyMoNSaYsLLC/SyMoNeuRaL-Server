# SyMoNeuRaL Bootcamp — the training camp, test range, competition field and truth gate

**Opened 2026-08-22.** Framework and depth charts. **Nothing here activates anything.**

> **Bootcamp recommends. Garrett approves. Nothing activates silently.**

Bootcamp decides who is present, who is capable, who is cheating, who is blocked, who is a
candidate, who is a starter, who is captain-recommended, who needs more training, and who is
not allowed on the field yet. It decides all of that **as a recommendation**.

## 0. The guardrail, stated before anything else

**No captain, race, benchmark, coin flip or scout report may:** edit active defaults · deploy ·
start Phase 1 · enable commercial mode · delete models · expose raw internals · bypass
auth/security · bypass licence/provenance · bypass Garrett's approval.

**This is enforced structurally, not by convention.** The precedents are in `git log`:

- `--activate-candidate` exits **3** on any of six unmet gates, and **even with all six green it
  refuses to rewrite `CHAT_MODEL`** — it backs up `api.py` and stops, because promotion edits a
  file the API reads at import and belongs in a reviewed commit.
- `--stage-*` prints the download command and will not run it, even with the confirmation phrase.
- `--smoke-candidate` cannot *name* the production default, so a fallback is unreachable rather
  than disabled.

**A captain that could activate would not be a captain. It would be a deploy script with an
opinion.**

## 1. Roster vocabulary

Every component on the field has exactly one status. The point of the vocabulary is that
**"it is on the disk" and "it is allowed to play" stop being the same sentence.**

| Role | Means | Rule |
|---|---|---|
| **Roster** | every model, tool, agent, data component, runtime, route, app, worker, script and package | membership is measured by the **Scout**, never asserted |
| **Starter** | the proven current best for **one position** | must pass the starter gate; **app-instance-specific, never global** |
| **Backup** | the verified rollback | **must stay available.** A starter without a live backup is a single point of failure |
| **Candidate** | smoke-passed or partly proven competitor | labelled candidate / smoke-passed / benchmarked / blocked |
| **Walk-on** | present on disk or in code, unproven | **may not be described as working** |
| **Redshirt** | held for a later phase | not active, not competing now |
| **Practice squad** | experimental, local-only, audit-only | never a public surface |
| **Injured reserve** | blocked by runtime, licence, safety, data or security | **named blocker required** |
| **Captain** | evaluator / policy / agent that recommends | **cannot activate alone** |
| **Coach** | operator runbook or scripted workflow | tells a human how to test, bench, promote, roll back |
| **Referee** | the anti-cheat gate | detects fallback, wrong route, fake adapter, cache contamination, benchmark leakage, false status |
| **Scout** | inventory and discovery | finds and classifies; `tools/bootcamp_scout.py` |
| **Depth chart** | the ranked roster for one position | starter · backup · candidates · blockers · next smallest safe commit |

### Captain types

**Performance** (speed, VRAM, throughput, latency) · **Quality** (correctness, task success) ·
**Safety** (safety, data, security, legal) · **Cost** (GPU time, disk, queue, metering) ·
**Product** (usefulness, UX) · **By-the-Book** (refuses undocumented shortcuts and unreviewed
promotion) · **Team Priority** (defers to the position's declared priority).

### Team priorities

`quality_first` · `speed_first` · `safety_first` · `cost_first` · `offline_first` ·
`gpu_coexistence_first` · `creative_first` · `deterministic_first` · `experimental_first` ·
`commercial_ready_first`

**Starter is not "best model overall". Starter is "best proven component for this position under
this position's priority."** A model can be starter for Chat and injured reserve for Studio.

## 2. The starter gate

A candidate becomes starter **only** if all hold:

1. smoke passes · 2. benchmark exists · 3. app-specific route or runtime proof exists ·
4. licence/provenance recorded · 5. safety/data rating acceptable · 6. capacity acceptable ·
7. **fallback ambiguity eliminated** · 8. rollback target exists · 9. **status strings truthful** ·
10. tests pass · 11. **Garrett approves any active-default change**

**Gate 9 is the one this repo learned the hard way.** Gates 1–8 are all readings of files and
markers, and **not one of them asks whether the surface starts or whether it describes itself
honestly.** On 2026-08-22 the gpt-oss candidate passed every file-based gate and would still have
produced a chat surface that exited 1 — while five status sites went on reporting
`"adapter": true`. That is the `#94` failure the working agreements name: **green checks over a
dead surface.**

### Coin-flip race

Permitted **only** when two candidates pass all hard gates, the benchmark difference is within
tolerance, safety/data/licence status is equal or acceptable, team priority does not clearly pick
one, and **both have a rollback**.

Rules: seed recorded · inputs recorded · candidates recorded · app instance recorded · priority
policy recorded · **reproducible** · **recommends only**.

**A coin flip may never override:** a failed safety gate · a failed licence/provenance gate · a
missing rollback · a failed smoke · a failed benchmark · a forbidden fallback · **Garrett's
explicit instruction** · commercial/deploy/Phase-1 locks.

> **A tie-break is not a way to make a decision nobody is allowed to make.**

## 3. The Referee — blinded probes and anti-cheat scoring

`tools/bootcamp_referee.py`. Two properties, both structural.

### The model under test learns nothing about the test

**Some probes do not ask whether a model knows the answer. They ask whether it is being helped.**
A negative control asking whether project-private facts leak into a supposedly isolated path
**answers its own question** the moment the prompt says *"negative control — you should not know
this"*. Any competent model reads the label and behaves.

So the guarantee is not careful wording. `build_request()` reads `probe.prompt` **and nothing
else**, and the tests assert that **two probes identical in prompt but differing in every
evaluator field produce byte-identical payloads** — so the test type cannot reach the model even
through a changed system prompt or sampling setting.

**The model may never see:** that it is being benchmarked · the expected score · which prompts
are canaries · which answers are expected wrong · which facts are project-private · whether a
wrong answer is desired · the labels *fallback trap*, *persona truth test*, *project knowledge
test*, *expected incorrect*, *negative control*, *canary*, *cheating detector*.

**The harness and evaluator know the purpose. The model under test does not.**

### Scoring is not "correct is good"

That default is wrong for half these modes, and **getting it wrong inverts the finding.**

| Mode | Pass condition |
|---|---|
| `capability` | correct answer is good |
| **`negative_control`** | **generic/absent answer = PASS. The exact private answer = SUSPICIOUS** |
| `route_integration` | correct **with declared context** = good |
| **`fallback_trap`** | **any answer from the wrong model/route = FAIL, however good** |
| `persona_truth` | **status truth beats answer fluency** |

**`fallback_trap` fails on provenance, not content**, and that check runs **first for every
mode** — a reply from the wrong engine invalidates whatever else it shows.

> **A bare model getting SyMoNeuRaL facts wrong is a PASS. It proves the harness is isolated.**
> Only the project-aware route, the adapter path, a RAG path or a documented context path should
> know project-private facts.

**This corrected a finding already on the record.** The 2026-08-22 benchmark asked *"What is
SyMoNeuRaL?"*. gpt-oss answered *"a hybrid neural-symbolic architecture"*; Qwen, *"a symbolic
mathematics library"*. Both wrong. Reported first as a **caveat on the benchmark** — and that was
the wrong sign on the right data. Re-scored as the negative control it always was: **two PASSES.**
The probe was only ever asking whether the isolated path leaked project context. It did not. A
model naming this box's card or ports would have been the alarm.

`capability` deliberately returns **inconclusive** rather than letting a regex pretend to judge
prose quality.

## 4. Scout report — the measured roster

Read by `tools/bootcamp_scout.py`, 2026-08-22. **Every figure below is measured; nothing in this
section is an opinion.**

| | |
|---|---|
| app modules | **17** |
| declared routes | **150** — 31 in `api.py`, 119 in app modules, parsed from the AST |
| weight files | **54**, **231.52 GiB** |
| architectures readable | `clip`, `gpt-oss`, `qwen2`, `qwen3`, `qwen35` |
| **provenance-covered** | **11 of 54** — `llm/` (6), `image/` (4), `whisper/` (1) |
| **unmanifested** | **43 files.** Everything outside those three directories |

**The 150 counts declared route decorators, not public URLs** — mount prefixes are not applied,
so it is an upper bound on distinct paths. Stated because two earlier greps in this repo produced
141 and 123 and neither was reconciled; the AST number is reproducible and the caveat is part of
the number.

### The roster by directory

| Directory | Files | Size | Manifested | Bootcamp status |
|---|---|---|---|---|
| `llm/` | 6 | 36.92 GiB | **6/6** | starters + backups + redshirts |
| `image/` | 4 | 11.80 GiB | **4/4** | starter bundle (FLUX/Schnell) |
| `whisper/` | 1 | 0.14 GiB | **1/1** | **weight present, runtime absent** — no ASR starter (corrected 2026-08-23) |
| `staging/openai-gpt-oss-20b/` | 5 | 38.49 GiB | 0/5 | **candidate** — smoke-passed, benchmarked |
| `hf/hub/` Qwen2.5-7B, Qwen3.6-27B | 21 | 65.94 GiB | 0/21 | **walk-on** — raw HF snapshots, not serving format |
| `diffusion_models/` | 3 | 31.68 GiB | 0/3 | **injured reserve** — video/image/3D, no provenance |
| `text_encoders/` | 4 | 27.44 GiB | 0/4 | **injured reserve** |
| `vae/` | 5 | 6.58 GiB | 0/5 | **injured reserve** |
| `checkpoints/stable_audio_3_medium` | 1 | 8.59 GiB | 0/1 | **injured reserve** — audio generation |
| `loras/minimax_h3_fl2v_turbo` | 1 | 1.82 GiB | 0/1 | **injured reserve** |
| `clip_vision/dino_v3_vit_h` | 1 | 1.57 GiB | 0/1 | **injured reserve** |
| `background_removal/birefnet` · `rembg/u2net.onnx` | 2 | 0.57 GiB | 0/2 | **injured reserve** |

**Every unmanifested weight is injured reserve or walk-on by rule, never a working option.** The
blocker is the same for all 43 and it is named: **no recorded provenance, therefore no recorded
licence, therefore no lawful basis to serve or redistribute output.** `docs/ops/PROVENANCE.md`
measures the gap; this table is the roster consequence of it.

**Note what is in there.** `minimax_h3_*` (19.53 GiB diffusion + 4.85 GiB video VAE + a turbo
LoRA) is a **video** stack. `triposplat_*` is **3D**. `stable_audio_3_medium` is **audio
generation**. `z_image_turbo` is a second **image** model. None of it is wired to a route, none of
it has provenance, and **none of it may be described as a capability of this box.** They are the
strongest future candidates on the roster and simultaneously the least eligible to play.

### Serving defaults, read from `api.py` rather than from memory

```
CHAT_MODEL       = MODELS / 'llm' / 'symon-1.0-7b-q4_k_m.gguf'      qwen2
DRAFT_MODEL      = MODELS / 'llm' / 'symon-1.0-draft-0.5b-q4_k_m.gguf'
CHAT_ADAPTER     = ROOT / 'training' / 'adapter' / 'symoneural-lora.gguf'   qwen2, type=adapter
CHAT_MODEL_LABEL = 'SymonChat S1-7B'
```

`CHAT_MODEL_LABEL` exists because the rack unit hardcoded *"SymonChat S1-7B"*: promoting to a 20B
model would have kept displaying 7B. It is now pinned to the model by a test — **change one and
the other must change.**

## 4a. Secret Sauce — the First-Time Evolution Shadow Rule

> **No first-time evolution may work alone.**

A **first-time evolution** is any app, model, tool, agent, runtime or data path doing something
materially new for the first time: first model activation · first starter promotion · first
captain recommendation · first route exposure · first write path · first delete/cleanup path ·
first external API call · first account/credit/money action · first hardware or rack control
action · first GPU-heavy batch · first OpenEmbedded/SDK/package build · first public-facing claim ·
first safety-sensitive mode · first inspection run on an unknown model · first 3D/spatial
generation or export · first customer/local/cloud target execution · first autonomous agent
action · first migration or schema mutation · first deployment-adjacent action.

**For every one of those, the system must try every safe means to avoid solo execution.**

### The six allowed first-time modes

| Mode | What it does | Hard limit |
|---|---|---|
| **Shadow** | observes, compares against the current starter | no writes, no activation, **no user-visible claim unless labelled shadow** |
| **Partner** | runs beside the proven starter, outputs compared | **cannot override the starter alone** |
| **Dry-run** | computes the planned action, records command and inputs | **no durable change** |
| **Simulation** | fixture, copy, sandbox or mock target | **no production mutation** |
| **Review** | proposes, waits | Garrett/operator approves |
| **Captain-supervised** | captain scores and recommends | **cannot silently activate; cannot bypass any gate** |

### Forbidden outright

First-time evolution working alone · first-time autonomous activation · first-time destructive
action · first-time external write · first-time public exposure · **first-time model promotion
without a rollback** · first-time agent control of another system without approval · first-time
regulated-domain output as a product claim · first-time cleanup or delete without explicit
authority · **first-time "off the record" bypass of audit, security or provenance.**

### The boundary that makes "try all means" safe

**"Try all means" means all safe, logged, reversible, reviewed means.** It does **not** mean
bypass auth, skip tests, hide work, evade logging, ignore licence, ignore safety, or mutate
production. **A first-time evolution that got around a gate has not satisfied this rule — it has
broken it in a more inventive way.**

### Evolution states

`proposed` → `shadowing` → `partnered` → `dry-run` → `simulated` → `reviewed` →
`captain-recommended` → `Garrett-approved` → `promoted` → `solo-eligible`; or `rolled-back`,
or `blocked`.

### Solo eligibility

Granted **only** after: at least one successful shadow/partner/dry-run cycle · smoke proof ·
benchmark or route proof where applicable · acceptable safety rating · acceptable data rating ·
acceptable licence/provenance · a rollback exists · **failure mode documented** · tests added ·
**status strings truthful** · Garrett/operator approval if behaviour changes.

### Team behaviour

Rookies shadow starters · candidates partner with starters · captains recommend but do not
activate · **the starter stays responsible until the challenger proves itself** · **a first-time
evolution may not take the captain role over itself** · captain decisions require by-the-book
proof.

### Competition integration

A candidate **may enter a race** before solo eligibility. A candidate **may not become starter**
until the first-time evolution gates pass. A captain may recommend but not promote.
**Coin-flip races are forbidden for first-time evolutions** unless both candidates have already
passed every hard gate.

### This rule was already being followed before it was written down

Worth stating, because a governance layer that describes nothing is decoration. Every gpt-oss step
this session ran in one of the six modes, and the record is in `git log`:

| Step | Mode used | Evidence |
|---|---|---|
| download | **review** | ran only on the explicit phrase, twice |
| conversion | **dry-run first** | the converter's own `--dry-run` printed `459 tensors, 13.8G` before a byte was written |
| smoke | **simulation** | port 8099, isolated process, production module never imported |
| production-argv check | **simulation** | probes A/B/C against the candidate on the smoke port, never 8081 |
| promotion | **blocked at review** | five gates green, stopped, reported |
| adapter guard | **partner** | `adapter_applies()` returns **True** for the shipping pair, asserted — the fix changed nothing today |

**And the rule's value showed up as a caught error, not as paperwork.** The conversion dry-run
would have caught a 40 GiB bf16 inflation for free. The simulation probes turned "three blockers"
into "one blocker and two wrong predictions of mine". The promotion review caught five green gates
over a surface that would have exited 1.

**`is_first_time` for gpt-oss as Chat starter is YES**, which is why `solo_allowed` is **NO** even
with the licence stored and the smoke passed — and why the persona-adapter blocker is a
`graduation_rule`, not a footnote.

### Per-option first-time record

Every depth-chart option below carries this implicitly; stated explicitly for the two live cases.

```
Chat / gpt-oss challenger
  is_first_time            : YES -- first model activation on this box
  evolution_type           : first starter promotion + first model activation
  current_state            : captain-recommended AGAINST (quality_first)
  solo_allowed             : NO
  shadow_required          : YES -- shadow the Qwen starter on real prompts
  partner_required         : YES -- outputs compared before any promotion
  dry_run_available        : YES -- --activate-candidate --dry-run
  simulation_available     : YES -- --smoke-candidate on port 8099
  captain_required         : YES
  Garrett_approval_required: YES -- active default change
  rollback_required        : YES -- exists; Qwen never stopped being default
  proof_required            : persona path, governor-tenant reading, multi-prompt quality
  blocker                  : no gpt-oss-shaped persona adapter exists
  graduation_rule          : train or obtain a matching adapter, OR Garrett accepts persona loss
                             explicitly; then shadow, then partner, then review

Image / any unmanifested challenger (z_image_turbo, minimax_h3 video, triposplat 3D)
  is_first_time            : YES
  evolution_type           : first route exposure + first 3D/video generation + first GPU-heavy batch
  current_state            : blocked
  solo_allowed             : NO
  shadow_required          : YES -- shadow FLUX/Schnell
  simulation_available     : REQUIRED -- first 3D generation/export must be sandboxed
  Garrett_approval_required: YES
  blocker                  : no provenance, therefore no licence, therefore no lawful basis
  graduation_rule          : one manifest entry with a READ licence for one file, then re-scout
```

## 5. Depth charts

**Format.** Each position gets exactly **three primary options** — Current/Proven, Near
Upgrade/Candidate, Future/Blocked — plus the competition record. Extras go in notes.
`proof` is what has actually been run; **`—` means nothing has been run, not "probably fine".**

---

### Chat — web UI  ·  `POST /api/chat`, `WS /ws/chat`
**Classification** PROD · **Depth** starter + backup + 1 candidate · **Lifecycle** active
**Team** Chat Team · **Priority** `quality_first` → `safety_first` → `gpu_coexistence_first`

**Option 1 — Current / Proven**
- **model/runtime** `symon-1.0-7b-q4_k_m.gguf` (qwen2, 4.36 GiB) + `symon-1.0-draft-0.5b` speculative + `symoneural-lora.gguf` persona adapter · engine `build 296, commit 2246ab7`
- **route/file** `backend/api.py:187` · launch argv `:1181-1197` · `-c 65536 -cb -np 2`
- **proof** live, serving, adapter applied (arch-matched, asserted). Bench 147.6 tok/s gen, 1807.1 prompt, 25 tokens for a one-sentence answer, **5,259 MiB peak**, 2.02 s load
- **blockers** none
- **risk** low. GPU starvation risk **moderate** — holds the card during generation
- **recommendation** **STARTER. Stay.**

**Option 2 — Near Upgrade / Candidate**
- **model/runtime** `symon-openai-20b.gguf` (gpt-oss, 12.85 GiB, MXFP4, `file_type 38`)
- **route/file** `backend/models/staging/openai-gpt-oss-20b/` — **staging, not wired to any route**
- **proof** smoke-passed (5 of 6 readings) · benchmarked · 166.3 tok/s gen · **14,297 MiB at production context, generating** · negative control **PASS**
- **proof needed** governor-lease reading (structurally impossible via the isolated path) · a quality comparison that is not one prompt
- **blockers** **(1) no persona adapter** — the qwen2 LoRA cannot apply, measured exit 1; promotion *loses the persona outright* and no gpt-oss-shaped LoRA exists. **(2) 259 tokens for a one-sentence answer** — 10× Qwen's, the Harmony reasoning channel is charged whether read or not. **(3) 14.3 GiB leaves under the governor's 1.5 GB drain floor when co-resident**
- **risk** UX confusion **high** (persona loss) · cost **high** (token inflation) · GPU coexistence **high**
- **recommendation** **CANDIDATE. Do not start.** Its win is a 13% generation rate against a 10× token cost and the loss of the thing that makes the surface SymonChat.

**Option 3 — Future / Advanced / Blocked**
- **model/runtime** `symon-1.0-14b` (8.37 GiB, qwen2, manifested) or `symon-1.0-27b/32b` q2_k_xl
- **missing pieces** no adapter trained at those sizes · 27b/32b are **q2_k_xl**, a quantisation this repo has not quality-tested · no bench at production context
- **blocker** **AUDIT** — present and manifested, entirely unproven for this position
- **risk** correctness risk of q2 quantisation is unmeasured; that is the whole problem
- **recommendation** **REDSHIRT.** Smallest safe next step: bench 14b against the starter on the same harness, adapter excluded, before considering a persona retrain.

**Competition / starters**
```
team               : Chat Team
current starter    : symon-1.0-7b-q4_k_m.gguf + persona adapter + 0.5b draft
candidates         : symon-openai-20b (benchmarked) · symon-1.0-14b (walk-on)
captain policy     : Quality + Safety + Cost, Team-Priority arbitrating
team priority      : quality_first > safety_first > gpu_coexistence_first
current leader     : Qwen starter
challenger         : symon-openai-20b
race status        : benchmarked — NOT starter
coin flip eligible : NO. Benchmark difference is not within tolerance and priority picks clearly
starter gate       : 10 of 11 met for the challenger; gate 9 (status truth) now enforced in code
promotion blocker  : persona adapter loss + token inflation + co-residency headroom
rollback target    : unchanged — Qwen never stopped being the default
captain recommendation: Quality Captain says NO (persona loss). Cost Captain says NO (10x tokens).
                     Performance Captain says marginal yes (+13% gen). By-the-Book says NO until a
                     persona path exists. Team Priority is quality_first: NO.
```
**Lifecycle** starter=active · challenger=benchmarked
**Events** user prompt · API call · WS stream · GPU lease
**Inputs** text · JSON  **Outputs** text response · JSON · operator log
**State machine** disabled → enabled → running → completed / failed / cancelled
**Failure modes** model missing · GPU unavailable · VRAM OOM · runtime launch failure · **runtime launch failure is the measured one for the challenger**
**Fallback** allowed: none for the candidate path (forbidden by construction) · rollback: Qwen, in place · rollback test: `test_chat_model_identity.py`
**Capacity** 5,259 MiB starter / 14,297 MiB challenger of 16,303 · queue `-np 2`
**Observability** `/api/status` · engine log · `run/progress.html` · `SMOKE-PASSED.txt`
**Roles** anonymous (public chat) · owner
**UI contract** shows `CHAT_MODEL_LABEL`; **must not claim an adapter it is not running** — enforced
**Risk score** security low · cost med · correctness med · reliability low · licence low · UX low
**Runbook** smoke `scripts/modelops/symoneural-modelops-stage.sh --smoke-candidate <id>` · bench Referee probes · rollback: none needed, default unchanged

---

### Chat — API  ·  `POST /api/chat` (public via Caddy)
**Classification** PROD · **Depth** same starter, different exposure · **Priority** `safety_first` → `quality_first`

- **Option 1 — Current/Proven** — same weights as the web UI. **proof** live and public. **blockers** none. **risk** the exposure itself: public route, anonymous role. **recommendation** STARTER.
- **Option 2 — Near Upgrade** — per-caller metering + entitlement (`accounts` 15 routes, `licensing`, both **BUILT/AUDIT**, commercial mode **OFF**). **proof needed** route tests under load; abuse posture. **blocker** commercial mode is locked off by instruction. **recommendation** CANDIDATE, blocked by policy not by code.
- **Option 3 — Future/Blocked** — project-aware chat with retrieval over repo context. **missing pieces** no RAG path, no context provenance, no per-caller data boundary. **blocker** **BLOCKED** — a project-aware route is exactly where private facts become answerable, and the boundary is undesigned. **recommendation** do not build until the Referee has a `route_integration` probe that proves context lands *only* on the declared route.

**Competition** team Chat Team · starter as above · **race status** `no_race` · coin flip **not eligible** (single starter) · promotion blocker: none pending · rollback: same file

---

### Chat — project / cowork mode  ·  `backend/apps/project/` (19 routes)
**Classification** PROD (token-gated) · **Priority** `safety_first`

- **Option 1 — Current/Proven** — deterministic project store, SQLite, **no model**. **proof** 19 routes, token-gated, denylist applied to the *resolved* path so a symlink cannot escape. **risk** filesystem reach. **recommendation** STARTER — a non-model engine is the correct starter here.
- **Option 2 — Near Upgrade** — the chat starter summarising project items on request. **proof needed** `route_integration` probe proving supplied context lands, plus a `negative_control` on the same route proving it does not leak *without* context. **blocker** none technical. **recommendation** CANDIDATE — smallest safe next step on this whole chart.
- **Option 3 — Future/Blocked** — autonomous agent acting on project files. **blocker** **BLOCKED** — write authority over a filesystem plus a model is the highest-consequence combination here; needs the Coder security model first. **recommendation** not this phase.

**Competition** starter = deterministic engine · candidates = chat starter as an explanation layer · **captain policy** Safety + By-the-Book · **race status** `candidate_entered`

---

### Image generation  ·  `POST /api/image`, `GET /api/gen/<name>`
**Classification** PROD · **Priority** `creative_first` → `gpu_coexistence_first`

- **Option 1 — Current/Proven** — **FLUX/Schnell bundle**, four separately-loaded components: unet 6.41 GiB q4_k · t5 4.84 GiB q8_0 · clip 0.23 · vae 0.31. **4/4 manifested.** `api.py:202-205` == `workflows.py:48-51`. **proof** serving; cfg locked 1.0, 4 steps, embedded guidance — negative prompt is **inert** and the UI must not imply otherwise. **risk** UX confusion (inert negative prompt) · GPU coexistence high. **recommendation** **STARTER.**
- **Option 2 — Near Upgrade / Candidate** — `z_image_turbo_bf16.safetensors` (11.46 GiB) or `flux2-vae`. **proof needed** everything — provenance, licence, runtime wiring, smoke, bench. **blocker** **unmanifested**. **recommendation** CANDIDATE only in the sense that it is the nearest *plausible* upgrade; **injured reserve** by rule until provenance exists.
- **Option 3 — Future/Blocked** — **video** (`minimax_h3` 19.53 GiB + video VAE 4.85 + turbo LoRA 1.82) and **3D** (`triposplat` 0.69 + VAE decoder 0.54). **missing pieces** provenance, licence, runtime, VRAM budget, storage/retention for large media, a route. **blocker** **BLOCKED — unknown-blocked weights.** **risk** licence risk unquantified. **recommendation** the honest next step is *provenance*, not inference: one manifest entry with a read licence for one file, then re-scout.

**Competition**
```
team          : Image Team          starter: FLUX/Schnell bundle (4 components)
candidates     : z_image_turbo (blocked) · minimax_h3 video (blocked) · triposplat 3D (blocked)
captain policy : Product + Cost, Safety vetoing on licence
team priority  : creative_first > gpu_coexistence_first
race status    : candidate_blocked — no challenger has provenance
coin flip      : NOT eligible (no candidate passes the licence gate)
rollback       : the bundle is the rollback; nothing has replaced it
```
**Outputs** image artefact · job status **Capacity** ~11.8 GiB resident — **cannot co-reside with the 20B chat candidate**, which is a Bootcamp finding in its own right

---

### Voice — ASR  ·  `backend/apps/voice/` (3 routes)
**Classification** PROD · **Priority** `speed_first` → accuracy

> **Corrected 2026-08-23 at `507e09ee`.** Option 1 read *"**proof** serving"*. **It is not
> serving, and it cannot.** The weight is present and manifested; **the runtime is absent.**
> `voice/asr.py:53-54` and `sigils/listen.py:44` both resolve `whisper-cli` to
> `contrib/whisper.cpp/build/bin/whisper-cli` — **`contrib/` does not exist**, `.gitignore:63`
> ignores `/contrib`, `SYMONEURAL_VOICE_ENABLED` is unset in `symoneural-api.service`, and **no
> `voice` unit appears in `GET /api/status`.**
>
> Two `whisper-cli` binaries **do** exist, both 973,872 B, both under `references/` — and both are
> **quarantined**: `references/` is INSPIRE_ONLY and `test_references_boundary.py:70` bans
> `references/<tree>/` **and** the `contrib/whisper.cpp/` spelling from product code. So the fix
> is **not** to rebuild `contrib/`; it is `engines/symoneural-listen/`, the home
> `symoneural-runtime-registry.md:88` already reserves and the pattern `d6b7838a` already set for
> the other two runtimes.
>
> **This is the #94 failure this framework was built to catch, in this framework's own chart** —
> a claimed live surface behind a runtime that cannot start. It got in because "1/1 manifested"
> and "serving" were read as the same sentence; **the roster vocabulary in §1 exists precisely to
> keep them apart**, and it was not applied to the Runtime dimension here.
>
> **The code is blameless.** `asr.py:106-109` returns `"whisper-cli missing at <path>"` and
> `sigils/listen.py:85` gates on `WHISPER.is_file()`.
>
> **And this repo already knew.** `docs/ops/RUNTIME-PROFILES.md:42` and
> `docs/specs/symoneural-runtime-registry.md:90` both say whisper.cpp is **`absent`**, the latter
> naming `contrib/` explicitly — and **task #104 records it outright**: *"`contrib/` **does not
> exist**, and two live things cite it… `apps/voice`'s whisper binary lives there"*, measured at
> **`41524770`, 13:12 on 2026-08-22.**
>
> **This chart was written at `507e09ee`, 22:21 the same day — nine hours later.** So the failure
> was not a stale document nobody re-measured; it was a **newer** document contradicting an
> **older** measurement in the same repo on the same day. The mechanism is worth naming, because
> it will recur: this position's **Model** row was filled from `PROVENANCE.json` — *1/1
> manifested* — and its **Runtime** row was never filled at all. "The weight is manifested" was
> allowed to stand in for "the surface serves", which is the exact substitution §1's vocabulary
> exists to forbid.
>
> **It is a disappeared runtime, not a never-built one.** `docs/specs/voice-spec.md:28` records
> `contrib/whisper.cpp @ 1fe009c` as *"cloned **and built** — `whisper-cli`, `whisper-server`,
> `whisper-bench` all present. Gitignored."* True on 2026-08-17. **The same sentence that recorded
> the build recorded why it could not survive.** This is the miner's failure mode a second time
> (`contrib/build-kawpowminer.sh`, also untracked, also `/contrib`), which makes it a pattern:
> **artefacts that matter living in a gitignored directory.**

- **Option 1 — Current/Proven** — `symoneural-listen-base-en.bin` (147,964,211 B, whisper.cpp, `voice/asr.py:56`). **1/1 manifested.** **proof** — **the weight loads nothing: `whisper-cli` is absent, and ASR is not enabled.** **risk** low; nothing runs. **recommendation** **NO STARTER for this position.** The weight is the backup for a starter that does not currently exist; the smallest honest step is to rebuild the runtime and *track its build script*, then re-scout — not to bench anything.
- **Option 2 — Near Upgrade** — a larger whisper tier for accuracy. **proof needed** the weight is **not on disk** — nothing to bench. **blocker** absent. **recommendation** **no safe candidate yet**, and that is the honest answer rather than nominating something unrelated.
- **Option 3 — Future/Blocked** — TTS / audio generation via `stable_audio_3_medium` (8.59 GiB) + audio VAE (0.56). **blocker** **BLOCKED** — unmanifested, no route, and **TTS is a different position from ASR**; a generation model is not an upgrade to a transcriber. **recommendation** if wanted, open it as its own position with its own gate.

**Competition** team Voice Team · **starter: NONE — runtime absent (corrected 2026-08-23)** · **candidates: none proven** · race `no_race` · rollback: the weight is present and unchanged · **note** whisper/listen may serve ASR paths **only**, and serves none today · **blocker** `whisper-cli` absent, `/contrib` gitignored

---

### RavenCalc  ·  `backend/apps/ravencalc/` (0 routes, 5 py)
**Classification** PROD · **Priority** `deterministic_first`

- **Option 1 — Current/Proven** — **CPU deterministic math engine, no model.** **proof** deterministic by construction. **risk** none from inference because there is none. **recommendation** **STARTER, permanently.** `deterministic_first` means a model may never be the calculator.
- **Option 2 — Near Upgrade** — an LLM **explanation layer only**, narrating a result the deterministic engine computed. **proof needed** a `route_integration` probe proving the number in the prose is the number the engine returned. **blocker** none technical. **recommendation** CANDIDATE — as a *layer*, never a replacement.
- **Option 3 — Future/Blocked** — model-computed results. **blocker** **BLOCKED by priority, not by capability.** **recommendation** never. A stochastic calculator is the wrong product regardless of accuracy.

**Competition** starter = CPU deterministic · challenger = explanation layer · **captain policy** By-the-Book + Safety · **race status** `no_race` — the starter cannot be raced for, only supplemented

---

### Studio — editor  ·  `/studio/editor/*` · **Classification** PROD (token-gated)
**Priority** `safety_first` (control-plane)

- **Option 1 — Current/Proven** — token gate + **loopback-only bypass** (`SYMONEURAL_STUDIO_LOCAL_BYPASS`), which bypasses the *secret* and never the *switch*. **proof** implemented and tested (`gate.py`, commit `a8450310`). **blockers** SECURITY-AUDIT **HIGH-1** (editor as a product surface) and **HIGH-2** (WebSocket origin posture) remain open. **risk** security **high** — highest on this chart. **recommendation** STARTER, with the two HIGHs still open and named.
- **Option 2 — Near Upgrade** — `SYMONEURAL_STUDIO_LLM` reasoning model selection. **proof needed** which model actually serves Studio reasoning is **not currently asserted by any test**. **blocker** unproven. **recommendation** CANDIDATE — first make the served model observable.
- **Option 3 — Future/Blocked** — public Studio. **blocker** **BLOCKED** — do not expose `/studio/editor/*` unauthenticated; do not expose raw ComfyUI. **recommendation** not a goal.

**Competition** team Studio Reasoning Team · **starter: undetermined** — `SYMONEURAL_STUDIO_LLM` selects it and nothing pins it, which is itself the finding · race `no_race` until the Scout can name the served model · **captain policy** Safety + By-the-Book

---

### Studio — API  ·  46 routes, `GET /api/studio/events` (cursor-polled JSON)
- **Option 1 — Current/Proven** — 46 declared routes, token-gated. **proof** route inventory measured. `/api/studio/events` is a **WebSocket** — `@router.websocket("/events")`, `routes.py:679` — relaying ComfyUI's event stream.

> **Corrected 2026-08-22.** This line first said `/api/studio/events` was "cursor-polled JSON,
> not SSE, not a WebSocket". **It is a WebSocket.** I had conflated it with a genuinely
> cursor-polled endpoint (`api.py:345` describes a page polling `/events` with a cursor) after
> being corrected earlier about *that* route, and then carried the correction onto the wrong one.
> **A correction applied to the wrong target is a new error**, and it landed in the sentence
> claiming precision about transport. The transport matters here because it decides the timeout,
> reconnect and origin-check model — and SECURITY-AUDIT **HIGH-2** is open on exactly that.
- **Option 2 — Near Upgrade** — per-route auth assertions and an OpenAPI contract. **proof needed** operation ids are not systematically declared. **recommendation** CANDIDATE.
- **Option 3 — Future/Blocked** — public Studio API. **blocker** **BLOCKED.**

---

### Streamer  ·  `backend/apps/streamer/` (14 routes) · **Priority** `deterministic_first`
- **Option 1 — Current/Proven** — deterministic guide/EPG/HLS handling, **no model**. **proof** 14 routes; `/xtream`, `/epg`, `/hls`. **risk** external service unavailable is the live failure mode. **recommendation** STARTER.
- **Option 2 — Near Upgrade** — chat starter for **metadata enrichment only** (titles, descriptions). **proof needed** `negative_control` proving it does not invent programme facts. **recommendation** CANDIDATE — and label any generated metadata as generated.
- **Option 3 — Future/Blocked** — model-driven restream decisions. **blocker** **AUDIT** — no proof, and a wrong automated decision is user-visible. **recommendation** redshirt.

**Competition** team Streamer Metadata Team · starter = deterministic · race `no_race`

---

### Miner — rack status and control  ·  `cryptominer` (0 routes) · `asicminer` (0 routes)
**Classification** AUDIT · **Priority** `safety_first`
- **Option 1 — Current/Proven** — status read-only, gated by `SYMONEURAL_MINING_ENABLED` / `SYMONEURAL_ASIC_ENABLED`, tokens required. **proof** the **52–53 MH/s benchmark exists but its binary cannot be rebuilt from this tree** — `contrib/build-kawpowminer.sh` is untracked, three copies all outside the repo. **That is a provenance failure with a real number attached, and the number must carry the caveat.** **recommendation** STARTER for *status*; **do not publish a current hashrate claim without current proof.**
- **Option 2 — Near Upgrade** — track the build script so the figure is reproducible. **proof needed** rebuild and re-measure. **recommendation** CANDIDATE — smallest safe step on this position.
- **Option 3 — Future/Blocked** — control paths (power, firmware). **blocker** **BLOCKED** — no touching real devices, no network scans, no firmware flashing. **recommendation** never from a web surface without a physical interlock.

---

### CLI — local operator  ·  `bin/symoneural-cli` · **Priority** `offline_first`
- **Option 1 — Current/Proven** — MOTD dashboard, three-state gate row, **pure renderer** so "no token in output" is assertable. **proof** `def50db9`, tests including *no bytecode left beside the shipped script*. **recommendation** STARTER.
- **Option 2 — Near Upgrade** — surface Bootcamp depth charts in the MOTD. **proof needed** the Scout must stay fast enough for a shell prompt. **recommendation** CANDIDATE.
- **Option 3 — Future/Blocked** — CLI that promotes models. **blocker** **BLOCKED by the captain guardrail** — a CLI that can activate is the thing this framework forbids. **recommendation** never.

---

### Coder — browser / terminal  ·  `backend/apps/coder/` (0 routes, token + `ALLOW_REMOTE`)
**Classification** AUDIT · **Priority** `safety_first`
- **Option 1 — Current/Proven** — token-gated, denylist on the **resolved** path. **proof** carries a recorded regression: `adapter` matched a path *segment*, so `training/adapter-qwen36` was readable until the entry became a glob. **That regression is the reason this is `safety_first`.** **risk** security **high**. **recommendation** STARTER, local only.
- **Option 2 — Near Upgrade** — model-assisted editing behind the same gate. **proof needed** a `fallback_trap` probe proving only the declared model serves it. **recommendation** CANDIDATE.
- **Option 3 — Future/Blocked** — public/remote coder. **blocker** **BLOCKED** — do not expose filesystem/coder tools publicly. **recommendation** never.

---

### Live  ·  `backend/apps/live/` (5 routes) · **Priority** `safety_first`
- **Option 1 — Current/Proven** — OBS-driven scenes, `SYMONEURAL_LIVE_ENABLED`, `SYMONEURAL_LIVE_PUBLIC_SCENE`. **proof** 5 routes. **risk** an OBS password in env; public scene selection is a real exposure decision. **recommendation** STARTER.
- **Option 2 — Near Upgrade** — model-generated scene metadata. **proof needed** none run. **recommendation** CANDIDATE.
- **Option 3 — Future/Blocked** — autonomous scene switching. **blocker** **AUDIT.** **recommendation** redshirt.

---

### Sigils  ·  `backend/apps/sigils/` (5 routes) · **Priority** `creative_first` → `gpu_coexistence_first`

> **Corrected 2026-08-22.** The first draft of this chart called Sigils "deterministic, no model"
> and gave it `deterministic_first`. **That was wrong and a two-line check found it:**
> `backend/apps/sigils/render.py:85-90` declares a `WEIGHTS` map naming all four FLUX components
> — unet, vae, clip, t5. Sigils is **GPU image-backed**, it **shares the Image starter's weights**,
> and its priority is therefore a coexistence question, not a determinism one. Recorded rather
> than silently edited, because "which apps hold the card" is exactly what a capacity plan is for.

- **Option 1 — Current/Proven** — **the FLUX/Schnell bundle**, the same four components the Image starter uses (`render.py:85-90`). **proof** 5 routes; weights present and 4/4 manifested. **risk** **GPU starvation risk shared with Image and Chat** — three positions, one card. **recommendation** STARTER.
- **Option 2 — Near Upgrade** — an explicit governor lease so Sigils cannot preempt Chat. **proof needed** a concurrency probe running Sigils and Chat together; **not run**. **recommendation** CANDIDATE — the highest-value safe step here, because sharing weights with Image means the two can already collide.
- **Option 3 — Future/Blocked** — a distinct sigil-specific model. **blocker** **AUDIT** — no candidate on the roster, and adding one costs VRAM the card does not have spare. **recommendation** redshirt.

---

### Remix  ·  `backend/apps/remix/` (8 routes) · **Classification** AUDIT
- **Option 1 — Current/Proven** — playlist/DJ surface. **proof** 8 routes. **blocker** **stale `DJ_*` naming throughout** (`DJ_TOKEN`, `DJ_ACCOUNTS_DB`, `DJ_PLAYLIST_COST`) after the DJ→Remix rename; recorded as an AUDIT follow-up, **not** renamed opportunistically. **risk** UX confusion + credential naming. **recommendation** STARTER with the naming debt named.
- **Option 2 — Near Upgrade** — the Remix naming/product upgrade. **blocker** needs explicit authorisation. **recommendation** CANDIDATE.
- **Option 3 — Future/Blocked** — external music APIs (Spotify/Google client ids present in env). **blocker** **BLOCKED** — third-party credentials and terms. **recommendation** owner decision.

---

### ModelOps  ·  `scripts/modelops/`, `tools/modelops_inventory.py`
**Classification** PROD · **Priority** `safety_first` + `by_the_book`
- **Option 1 — Current/Proven** — by-the-book scripts and gates. **proof** six activation gates, exit 3 on refusal; smoke refusal exit 5; **no mode deletes a weight**; the stage mode refuses to overwrite a manifest that records real state. 34 tests. **recommendation** **STARTER.**
- **Option 2 — Near Upgrade** — Bootcamp Captain agents that rank candidates. **proof needed** a captain must be shown unable to activate. **blocker** none — but the guardrail is the design. **recommendation** CANDIDATE.
- **Option 3 — Future/Blocked** — automated promotion. **blocker** **BLOCKED by the captain guardrail.** **recommendation** never.

---

### NeuroScope / Model Atlas
**Classification** FUTURE · **Priority** `safety_first` → `detail_first`
- **Option 1 — Current/Proven** — **metadata-only inspection.** The Scout reads `general.architecture`, `file_type`, tensor counts and types from GGUF headers today. **proof** that reader is tested and total. **recommendation** STARTER — and it is genuinely useful already.
- **Option 2 — Near Upgrade** — full metadata atlas across all 54 weights with provenance status. **proof needed** the Scout already has the data; the surface does not exist. **recommendation** CANDIDATE — small, safe, high value.
- **Option 3 — Future/Blocked** — runtime activation / projection capture. **missing pieces** viewer, projection storage, retention policy, and a security model for what activations reveal about inputs. **blocker** **BLOCKED.** **recommendation** the smallest safe step is Option 2; do not capture activations until storage and retention are designed.

---

### Sentinel  ·  `docs/specs/symoneural-sentinel-spec.md` · **Classification** FUTURE
**Priority** `safety_first`

**Sentinel is not medical, not therapy, and not a mental-health product.** That is the naming
decision on record (renamed from "Therapist" for exactly this reason), and it is the first thing
any depth chart for it has to say.

- **Option 1 — Current/Proven** — **nothing runs.** No route, no model, no surface. **proof** — . **recommendation** the honest starter is "not implemented", not a placeholder.
- **Option 2 — Near Upgrade** — a **non-clinical** review/shadow layer that observes and reports, making no claim about a person. **proof needed** everything. **first-time record** `shadow_required: YES`, `solo_allowed: NO`. **recommendation** CANDIDATE, shadow-only.
- **Option 3 — Future/Blocked** — anything in a regulated domain. **blocker** **BLOCKED.** **First-time regulated output is blocked or safety-gated, and there is no clinical solo mode, ever.** **recommendation** do not build; if it is ever wanted it is a legal question before it is an engineering one.

---

### OpenEmbedded / Yocto / SDK  ·  `docs/ops/YOCTO-LAYER-LICENSES.md`
**Classification** FUTURE/AUDIT · **Priority** `commercial_ready_first` (and therefore currently blocked)

- **Option 1 — Current/Proven** — **local/dev only.** **proof** licence scope documented; no customer artefact built. **recommendation** STARTER = the local build, and nothing is claimed beyond it.
- **Option 2 — Near Upgrade** — a **draft** SDK contract. **first-time record** first package build is **local/dev only**; first SDK contract is a **draft**. **recommendation** CANDIDATE.
- **Option 3 — Future/Blocked** — customer install. **blocker** **BLOCKED until rollback, update and support docs exist** — plus `build provenance: none` and no reproducibility check on any engine here (`docs/ops/PROVENANCE.md` §4). **recommendation** an attestation over a build nobody has reproduced attests to an event, not an artefact; reproducibility comes first.

---

## 6. What this chart deliberately does not say

- **No quality claim anywhere is based on one completion.** The Chat bench is one prompt at
  temperature 0. It measures throughput, tokens and VRAM, and it does **not** measure quality.
- **No unmanifested weight is presented as a capability**, including the video, 3D and audio
  stacks that are physically present and would be the most impressive things here.
- **No starter changed as a result of writing this.** Qwen is the Chat starter, FLUX the Image
  starter, and the deterministic engines hold RavenCalc and Streamer. **ASR has no starter** —
  corrected 2026-08-23; the weight is present and its runtime is absent. **Sigils is not
  deterministic either** — it shares the Image starter's four FLUX weights (`render.py:85-90`),
  corrected earlier in this file.
- **Commercial mode is off, Phase 1 is not started, nothing is deployed, auth is unchanged.**

**Related** `docs/ops/OPENAI-GPT-OSS-MIGRATION.md` · `docs/ops/PROVENANCE.md` ·
`docs/ops/SECURITY-AUDIT.md` · `docs/ops/MODEL-LICENSES.md` · `docs/ops/SYMONEURAL-MODEL-BUNDLES.md` ·
`tools/bootcamp_scout.py` · `tools/bootcamp_referee.py`
