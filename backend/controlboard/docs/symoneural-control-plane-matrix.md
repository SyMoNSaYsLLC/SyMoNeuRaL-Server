# SyMoNeuRaL Control Plane Matrix — the normalized record for every app instance

**Opened 2026-08-23, read at `507e09ee`.** Nothing here activates anything.

> **This file owns one thing: the 16-dimension record shape, and the measured rows that fill it.**
> It is **not** a second depth chart. `backend/studio/docs/symoneural-bootcamp.md` owns the roster
> vocabulary, the starter gate, the coin-flip rules, the Referee, the First-Time Evolution Shadow
> Rule and the per-position depth charts. Where a cell here would restate Bootcamp prose, it
> cites the section instead. Where the two ever disagree, **Bootcamp wins on competition rules
> and this file wins on the record shape** — and the disagreement is a bug in whichever file was
> not re-measured.

## 0. Ownership, so no fact has two homes

| Question | Home |
|---|---|
| Who is starter, who may race, who is cheating, what the six first-time modes are | **`backend/studio/docs/symoneural-bootcamp.md`** |
| **The 16-dimension record shape, and the measured row per app instance** | **this file** |
| Which app can actually load which weight | **`ops/docs/APPLICATION-MODEL-CAPABILITY-MATRIX.md`** |
| Benchmark figures and the SHA each was read on | **`ops/docs/MODEL-BENCHMARKS.md`** |
| vLLM parity, and why it is unmeasured | **`ops/docs/VLLM-BENCH-PARITY.md`** |
| Runtime ladder level per family | **`ops/docs/RUNTIME-PROFILES.md`** |

## 1. The 16 dimensions, defined once

`App × Instance × Team × Starter × Candidate × Captain × Model × Tool × Agent × Data × Runtime ×
Gate × Meter × State × Risk × Runbook`

| # | Dimension | Definition | Measured from |
|---|---|---|---|
| 1 | **App** | the product surface a person names | `backend/apps/<name>`, `site/<name>.html` |
| 2 | **Instance** | one app can have several; an instance is *one exposure of one app* (web UI vs public API vs CLI) | Caddy path set + route module |
| 3 | **Team** | the group of components competing for that instance's positions | Bootcamp §5 |
| 4 | **Starter** | the proven current best **for this instance** | `api.py` AST, read not remembered |
| 5 | **Candidate** | smoke-passed or partly proven competitor | Bootcamp §5, `staging/` |
| 6 | **Captain** | which evaluator policy arbitrates | Bootcamp §1 *Captain types* |
| 7 | **Model** | the weight actually reachable | `models`, GGUF headers |
| 8 | **Tool** | non-model executables the instance calls | binaries on disk |
| 9 | **Agent** | anything that acts without a per-action human | route + loop inspection |
| 10 | **Data** | most sensitive class the instance can reach | denylists, DB paths, env |
| 11 | **Runtime** | the engine family and its ladder level | `RUNTIME-PROFILES.md`, disk |
| 12 | **Gate** | what stops an unauthorised caller | `*_TOKEN` / `*_ENABLED` flags, Caddy |
| 13 | **Meter** | whether usage is counted | `backend/apps/accounts/meter.py` call sites |
| 14 | **State** | the live reading, now | `GET /api/status` |
| 15 | **Risk** | the three derived ratings in §2 | derived, rule stated |
| 16 | **Runbook** | how a human tests, benches, promotes, rolls back | `scripts/` |

**`—` means nothing has been run.** It never means "probably fine". That convention is inherited
from Bootcamp §5 deliberately.

## 2. The three ratings, and the rule that derives them

**A rating without a derivation is an opinion wearing a number.** So each is a function of
measured inputs, and the inputs are printed beside the result in §4.

### Safety rating

Inputs, and each is a reading of source rather than a judgement:

- **exposure** — `public` = a path in `ops/Caddyfile` reaches it, **including everything under
  `handle /api/*`**, which covers every router mounted with an `/api/…` prefix in `backend/server.py`
  · `loopback` = reachable only from this box · `none` = **no route exists at all**
- **gate** — `token` · `flag-only` · `none`
- **blast** — `read` · `write-local` · `device-or-money`

**The rule is a total lookup over (exposure × blast).** It has to be: the first version of this
section was a list of four conditions that **did not cover `public · none · read`**, so six rows
had no derived answer and were hand-typed — and two of them were typed differently from the other
four. A derivation with a hole in it is not a derivation, and the hole is where the drift got in.

| exposure ↓ · blast → | `read` | `write-local` | `device-or-money` |
|---|---|---|---|
| **`none`** | `S-low` | `S-low` | `S-high` |
| **`loopback`** | `S-low` | **`S-med`** | `S-high` |
| **`public`** | **`S-med`** | **`S-high`** | `S-high` |

**`S-blocked` overrides any cell** when an open `HIGH-n` in `ops/docs/SECURITY-AUDIT.md` names the
instance. It is not a worse number; it is a named open finding.

**Gate is recorded and does **not** change the rating**, which is deliberate and worth defending: a
token gate reduces the *likelihood* of a bad caller, not the *blast radius* if one gets through,
and this column rates exposure of consequence. Putting `gate` in the formula is also what let the
first version claim `S-med` required `gate = token` while rating six ungated public surfaces
`S-med` anyway.

**`backend/apps/test_control_plane_matrix.py` recomputes every row from this table** and fails on
any disagreement, so a hand-typed rating cannot survive again.

### Data rating

The **most sensitive class reachable**, not the typical one: `D-none` → `D-public` →
`D-project` (repo/private project text) → `D-credential` (tokens, secrets, account rows) →
`D-device` (rack, miner, OBS, power).

### Performance rating

**This rates the evidence, not the speed** — deliberately, because a speed rating with no run
behind it is the exact failure this repo has published before.

| Rating | Means |
|---|---|
| `P-measured` | a stamped figure exists **with the SHA it was read on** |
| `P-partial` | something was measured; the measurement does not cover the production path |
| `P-none` | nothing has been run |

## 3. Modes — and the one that is forbidden

Requested as a set; **`off-the-record` is not an available mode.** Bootcamp §4a forbids
"first-time *off the record* bypass of audit, security or provenance", and it is listed here so
nobody reads its absence as an oversight.

| Mode | Means | Status on this box |
|---|---|---|
| **batch** | many inputs, one queued submission | **available** — `-np 2` on chat; Studio job queue |
| **bucket** | grouped storage/retention for outputs | **partial** — renders land in `backend/output`; no retention policy |
| **SDK** | a contract a third party builds against | **draft only** — `backend/vendor/anthropics/*` is vendored SDKs, not ours |
| **OpenEmbedded / Yocto** | customer image build | **local/dev only** — `ops/docs/YOCTO-LAYER-LICENSES.md`; no customer artefact |
| **wizard** | guided setup that asks rather than assumes | **available** — streamer guide setup asks, does not geolocate |
| **tuner** | supervised adapter/LoRA training | **built** — `backend/apps/studio/plugins/reinforce`; `train` reads `ready` |
| **tester** | blinded probe harness | **built** — `tools/lib/bootcamp_referee.py` |
| **by-the-book** | refuses undocumented shortcuts and unreviewed promotion | **enforced** — six activation gates, exit 3 |
| **off-the-record** | bypass audit / security / provenance | **FORBIDDEN.** Bootcamp §4a. No implementation, and none is wanted |

## 4. The matrix — one row per instance, measured 2026-08-23 at `507e09ee`

Dimensions that are constant across every row are stated once rather than repeated: **Captain**
policy defaults to `Team-Priority arbitrating` (Bootcamp §1), and **Runbook** is
`scripts/modelops/symoneural-modelops-stage.sh` for every model position.

Exposure/gate/blast are the §2 inputs, and **every Safety cell is recomputed from the §2 lookup
table by `test_control_plane_matrix.py`** — so "derived, not typed by hand" is now enforced rather
than asserted. Four cells were wrong in the first version of this table and are corrected below
with their source cited in the footnotes: **Voice**, **RavenCalc**, **Coder** and **Miner**.

| Instance | Team | Starter | Runtime (level) | Exposure · Gate · Blast | Safety | Data | Perf | State (live) | Meter |
|---|---|---|---|---|---|---|---|---|---|
| **Chat — web UI** | Chat | Qwen 7B q4_k_m + 0.5b draft + qwen2 LoRA | `symoneural-llm` **built** | public · none · read | `S-med`¹ | `D-public` | **`P-measured`** | `ready` | no |
| **Chat — public API** | Chat | same weights | `symoneural-llm` **built** | public · none · read | `S-med`¹ | `D-public` | **`P-measured`** | `ready` | no |
| **Chat — project / cowork** | Project | deterministic SQLite store, **no model** | n/a | public · token · write-local | **`S-high`** | `D-project` | `P-none` | `ready` | no |
| **Image** | Image | FLUX/Schnell, 4 components | `symoneural-diffuse` **built** | public · none · read | `S-med`¹ | `D-public` | `P-partial`² | `ready` | no |
| **Sigils** | Image (shared) | FLUX/Schnell, **same 4 weights** | `symoneural-diffuse` **built** | public · none · read | `S-med`¹ | `D-public` | `P-none` | `ready` | no |
| **Voice — ASR** | Voice | weight present, **runtime unusable** | `whisper.cpp` **absent** | public · token · read | `S-med`¹⁰ | `D-public` | `P-none` | **no unit on rack** | no |
| **RavenCalc** | RavenCalc | CPU deterministic, **no model** | n/a | public · none · read | `S-med`¹¹ | `D-none` | `P-none` | `ready` | no |
| **Studio — editor** | Studio | **undetermined** (`SYMONEURAL_STUDIO_LLM`) | `symoneural-ui` **see §5** | public · token · write-local | **`S-blocked`**³ | `D-credential` | `P-none` | **`offline`** | no |
| **Studio — API** | Studio | 46 routes | `symoneural-ui` **see §5** | public · token · write-local | **`S-blocked`**³ | `D-credential` | `P-none` | **`offline`** | no |
| **Streamer** | Streamer | deterministic guide/EPG/HLS, **no model** | ffmpeg **built** | public⁴ · none · read | `S-med` | `D-public` | `P-none` | `ready` | no |
| **Coder** | Coder | token gate + resolved-path denylist | n/a | loopback · token · write-local | `S-med`¹² | `D-project` | `P-none` | `ready` | no |
| **Project store** | Project | SQLite + FTS5, **no weights** | n/a | public · token · write-local | **`S-high`** | `D-project` | `P-none` | `ready` | no |
| **Miner — status** | Miner | read-only status | kawpowminer **unreproducible**⁵ | none · flag-only · device-or-money | **`S-high`**¹³ | `D-device` | `P-partial`⁵ | `offline` | no |
| **Gateway** | Gateway | `symon-gateway` (Rust) | own binary **running** | public (all `/api/*`) · none · read | `S-med` | `D-public` | `P-none` | `running` | no |
| **Live** | Live | OBS scenes | OBS **external** | public · flag-only · device-or-money | **`S-high`** | `D-credential`⁶ | `P-none` | `ready` | no |
| **Remix** | Remix | client of chat | `symoneural-llm` **built** | public · flag-only · read⁷ | `S-med` | `D-credential`⁷ | `P-none` | `ready` | no |
| **Reinforce / tuner** | Tuner | qwen2 LoRA training | `symoneural-llm` **built** | public · token · write-local | **`S-high`** | `D-project` | `P-partial`⁸ | `ready` | no |
| **ModelOps** | ModelOps | by-the-book scripts | n/a | none · none · write-local | `S-low`⁹ | `D-project` | **`P-measured`** | n/a (CLI) | no |
| **NeuroScope / Model Atlas** | Inspection | metadata-only GGUF reader | pure Python **built** | none · none · read | `S-low` | `D-public` | `P-none` | n/a | no |
| **Exp / plugin runtime** | Studio | plugin host | `symoneural-ui` **see §5** | public · token · write-local | **`S-blocked`**³ | `D-credential` | `P-none` | **`queued`** | no |

**20 instances across 20 app modules.** Both numbers are asserted by
`backend/apps/test_control_plane_matrix.py` against the table and the tree, because a count in
prose that has stopped matching the table under it is this repo's signature drift.

Two reconciliations, so neither number reads as contradicting a neighbour:

- **20 instances here vs 19 positions in Bootcamp §5.** Different questions, both right. Bootcamp
  charts *positions* including future ones (CLI, Sentinel, OpenEmbedded/SDK); this table rows
  *exposures that exist now* and adds Gateway, the Project store, Reinforce/tuner and Exp.
- **20 app modules, of which only 18 are importable packages.** `ravencalc` and `remix` are
  directories with **no `__init__.py`**. The Scout counts directories, so 20 is the number every
  document quotes — and the two-module gap is recorded here rather than left to be rediscovered.

  17 → 19 on 2026-09-03, and neither new module adds an instance row above, which is why the
  instance count stays at 20 while the module count moves by two. `capture` is a helper package
  with no exposure of its own. `coders` is the R-184 multi-coder surface, and it is deliberately
  absent from a table of *exposures*: it mounts under `/local`, not `/api`, so it is not an
  exposure in the sense the rows above measure — `ops/Caddyfile` proxies `/api/*` to the internet
  and has no matcher for `/local/*`, and `_require_local` refuses anything carrying an
  `x-forwarded-*` header. A row here would assert a public surface that does not exist.

  19 → 20 on 2026-09-04 for `authority`, which likewise adds no instance row -- the instance
  count stays at 20 while the module count moves again. It is not an exposure at all: no
  route, no page, no surface. It is the mutation-authority plane every host effect is gated
  by, so it sits UNDER the rows above rather than beside them. A table of exposures is the
  wrong place to list the thing that governs them.

Footnotes are the derivation, not decoration:

1. `public · read` → `S-med` straight off the §2 table. **This footnote used to do the work the
   rule could not** — it argued "`S-med` and not `S-low` because the path is public and the role is
   anonymous", which was reasoning applied to six rows and, by oversight, not to RavenCalc or
   Voice. The rule is now total, so the footnote explains nothing and the table decides. Gate is
   `none` by design on the public product surfaces; the rating records that, it does not object.
2. `P-partial` — the FLUX bundle serves, but no stamped throughput figure exists for the image
   path. Its VRAM footprint (~11.8 GiB resident) is recorded in Bootcamp §5, and it is a capacity
   reading rather than a benchmark.
3. **`S-blocked` is not my judgement.** `ops/docs/SECURITY-AUDIT.md` **HIGH-1** (editor as a
   product surface) and **HIGH-2** (WebSocket origin posture) are open against Studio, and
   `/studio` + `/studio/*` are public paths in `ops/Caddyfile:150`. Live state is `offline`, so
   the exposure is currently latent rather than active — **both facts belong in the row.**
4. `/tuner.html` and `/tuner-watch.html` are public and **302 to the streamer pages** — the
   rename is live. `site/streamer.html` is deployed.
5. The 52–53 MH/s figure exists and **its binary cannot be rebuilt from this tree**
   (`contrib/build-kawpowminer.sh` untracked). `P-partial` with the caveat attached, per
   Bootcamp §5. See §5 for why this is now the *second* instance of that failure mode.
6. `SYMONEURAL_OBS_PASSWORD` is in the instance's environment surface.
7. Remix still carries `DJ_TOKEN` / `DJ_ACCOUNTS_DB` / `DJ_PLAYLIST_COST` naming after the
   DJ→Remix rename — recorded as debt in Bootcamp §5, not renamed opportunistically here.
8. `backend/studio/docs/qlora-27b-measured.md` holds a measured training run; it does not cover the
   currently-wired adapter path.
9. `S-low` for a script with `write-local` blast is the `none · write-local` cell, and it is the
   right cell: no route reaches it, and its writes are refused by construction — **no mode deletes
   a weight**, and `--activate-candidate` will not rewrite `CHAT_MODEL` even with six green gates.

**The four corrections, each with the source that settles it:**

10. **Voice exposure was `none`. It is `public`.** `backend/server.py:2932` mounts
    `voice.router` at **`prefix="/api/voice"`**, and `ops/Caddyfile:50` delegates the whole
    `handle /api/*` subtree — so the routes are internet-reachable. `public · read` → **`S-med`**.
    **The ASR runtime status is unchanged and still dead:** the surface answers off because
    `SYMONEURAL_VOICE_ENABLED` is unset, and `whisper-cli` is absent regardless. **A reachable
    route in front of an unusable runtime is exactly the pair worth rating** — the old `none`
    hid the reachable half.
11. **RavenCalc was `S-low` on the same `public · none · read` triple that five other rows read
    `S-med`.** Straight contradiction, now `S-med` off the table. The instinct behind the wrong
    value was "a deterministic calculator is harmless" — true about *blast*, which is already
    `read`, and not a licence to also discount the public path.
12. **Coder exposure was `public`, which inverted its safety case.** The page is public at
    `/live-stack/coder` (`ops/Caddyfile:226`), but **every read and write goes to `/local/coder/*`,
    which Caddy never proxies** — `api.py:3545-3559` states it outright: *"`/local/*` matches no
    `handle` block in `ops/Caddyfile`, so it falls through to `handle { file_server }`, is looked
    up in `/var/www/symoneural`, and 404s from disk without this process ever being asked."* The
    consequence lives on the loopback path, so `loopback · write-local` → **`S-med`**. This is a
    *downgrade from `S-high`*, and the reason it is not a softening: `S-high` was reached by
    calling the data path public, which is the one thing this design deliberately is not.
    `SYMONEURAL_CODER_ALLOW_REMOTE` relaxes the peer check on that mount and **still cannot make
    it internet-reachable**, because Caddy proxies no `/local` path at all.
13. **Miner exposure was `loopback`, naming a service that does not exist.** `cryptominer` and
    `asicminer` declare **0 routes each** and appear in **no `include_router` call** in `api.py` —
    so exposure is `none`. **The rack status a visitor sees is `/api/status`, a different
    instance** (the Gateway/Chat row family), and conflating the two is what produced the wrong
    input. Rating stays **`S-high`**: `device-or-money` is `S-high` at *any* exposure, which is
    the one cell where the blast column alone decides.

**Meter is `no` in every row.** That is the honest reading: `backend/apps/accounts/meter.py` is
built, but its only caller is `symoneural_dj.pipeline.run_job`. **A ledger one caller uses is a
ledger, not a metering system** — `ops/backend/authority/docs/symoneural-commercial-mode.md` §1 states it, and
this column agrees with it rather than restating it. Commercial mode is **off**.

## 5. What the Runtime column caught that the Model column could not

Two findings, both from filling in dimension 11 against the disk instead of against a document.

### 5a. ASR: the weight is present and its runtime is gone

| Reading | Value |
|---|---|
| weight | `models/whisper/symoneural-listen-base-en.bin`, **147,964,211 B**, present, **1/1 manifested** |
| runtime | `whisper-cli` — **absent.** `asr.py:53-54` resolves it to `contrib/whisper.cpp/build/bin/whisper-cli` |
| `contrib/` | **the directory does not exist**, and `.gitignore:63` ignores `/contrib` |
| box-wide search | **two `whisper-cli` binaries exist**, both **973,872 B**, at `references/ENGINEERING/questions/contrib/whisper.cpp/build/bin/` (Aug 21) and `references/referencestochatgpt/whisper.cpp/build/bin/` (**Aug 17 14:04**) — **and neither may be used** (see below) |
| enablement | `SYMONEURAL_VOICE_ENABLED` is **not set** in `symoneural-api.service` |
| live rack | **no `voice` unit appears in `GET /api/status`** |

**Nothing above is a new discovery, and that is the actual finding.** Three places already had it
right: `RUNTIME-PROFILES.md:42` (`absent`), `symoneural-runtime-registry.md:90` (`absent`, naming
`contrib/` explicitly), and **task #104 in `PROJECT-TASKS.md`**, which states *"`contrib/` **does
not exist**, and two live things cite it… `apps/voice`'s whisper binary lives there"* — measured
at **`41524770`, 2026-08-22 13:12**.

**Bootcamp's depth chart then said `proof: serving` at `507e09ee`, 2026-08-22 22:21 — nine hours
later.** So this is not a stale document that nobody re-measured. It is a **newer** document
asserting something an **older** measurement had already disproved, in the same repo, on the same
day. A fact can be known and lost inside nine hours, and the mechanism was that the depth chart
filled its **Model** row from `PROVENANCE.json` ("1/1 manifested") and never filled its
**Runtime** row at all.

**That is the argument for this matrix having a Runtime column**, and it is the only argument this
file needs.

#### Correction to my own first draft, same day

This section first said *"a filesystem sweep found no `whisper-cli` anywhere."* **That was wrong,
and I wrote it before the sweep finished.** Two binaries exist, both under `references/`, and one
is dated **Aug 17 14:04** — the same hour `backend/voice/docs/voice-spec.md:28` recorded the build. **The
conclusion does not change and the reason gets sharper:** they are quarantined, not missing.
`references/` is INSPIRE_ONLY and `backend/apps/test_references_boundary.py:70` enforces it in a
test, banning `references/<tree>/` **and** the pre-restructure `contrib/whisper.cpp/` spelling.

**So the fix is not "rebuild `contrib/whisper.cpp`" — that rebuilds into a banned path.** The
boundary's own failure message says it: *"Put what you need in our own tree."* Both other GPU
runtimes were already forked under our own names into `engines/` (`symoneural-llm`,
`symoneural-diffuse`, commit `d6b7838a`); whisper never was. And
`backend/registry/docs/symoneural-runtime-registry.md:88` **already reserves `runtime_id:
symoneural-listen`** for it. **The sanctioned home is `engines/symoneural-listen/`**, which is
what task #105's check now targets.

Worth recording, because it explains why no test caught this: the boundary check skips prose and
requires a quote character, so `asr.py:4`'s backticked mention is correctly ignored — and
`asr.py:54` and `sigils/listen.py:44` assemble the path from **segments**
(`ROOT / "contrib" / "whisper.cpp" / …`), so the banned literal never appears on a line. **The
rule and the code disagree, and the grep cannot see it.**

**Still open, and not mine to close here:** `voice/routes.py:107,116` emit
`"engine": "whisper.cpp, CPU build (GGML_CUDA=OFF)"` and `"measured_ms_short_utterance": 650`
**unconditionally** — a measured figure, with no SHA, about a binary that is absent. The route is
otherwise honest (`available: false`, `problem: "whisper-cli missing at <path>"`), and the surface
is disabled, so nobody is being told this today. **Filed under #104 already; recorded here so the
matrix does not imply it was fixed.**

**This is not a never-built runtime. It is a disappeared one.** `backend/voice/docs/voice-spec.md:28`
records `contrib/whisper.cpp @ 1fe009c` as *"cloned **and built** — `build/bin/whisper-cli`,
`whisper-server`, `whisper-bench` all present. Gitignored."* That was true on 2026-08-17. The
directory is gone, nothing tracked it, and **the same sentence that recorded the build recorded
the reason it could not survive.**

**So this is the miner's failure mode a second time** — a real capability whose artefact lives
outside version control, and the honest state is `absent` until something rebuilds it. Note the
code is blameless: `asr.py:106-109` returns `"whisper-cli missing at <path>"` rather than
pretending. The dishonesty was only ever in the depth chart.

### 5b. vLLM is installed, and four documents say it is absent

| Reading | Value |
|---|---|
| location | `/home/google/.venvs/vllm` — **outside the repo**, untracked by construction |
| version | **vLLM 0.25.1**, imports cleanly |
| stack | `torch 2.11.0+cu130`, `torch.cuda.is_available()` **True**, device **NVIDIA GeForce RTX 5070 Ti** |
| created | **2026-07-20**, by `uv 0.11.27`, Python 3.12.13 |
| service | **none.** No process, no port, no unit |

The venv predates by **three weeks** the commit (`7a4e5c98`, 2026-08-22) that wrote
*"vLLM … **absent**"* into `RUNTIME-PROFILES.md:43`.

**The ladder has no word for what this is.** `absent` is false — it is on disk and it imports.
`built` is misleading — nothing here was compiled by us, and a venv is not our artefact.
`running` is false — no service. Rather than pick the nearest word, this file records the
measurement and **asks for a ruling**: either add a level meaning *"installed, importable, no
service"*, or rule that a third-party venv outside the repo is out of ladder scope and say so in
`RUNTIME-PROFILES.md`.

**What does not change:** `MODEL-REGISTRY.md:108` and `BOX-REALITY-AUDIT.md:507` say vLLM is a
**cloud candidate only, no service running**. Both are **still true** and are not touched. Only
the flat *"absent / not installed"* claims are wrong, and only those are corrected.

### 5c. `symoneural-ui` (Comfy) — needs a ruling, not a reclassification

`RUNTIME-PROFILES.md:41` says `source-only`. Measured: source present **and** a working
`.venv` with `torch 2.13.0+cu130`, `cuda True`. A Python application has no compile step, so
`built` may be the wrong word for it too. **Left as `source-only` with the measurement recorded;
this is Garrett's ruling, not mine to take.** No process is running either way.

## 6. The 3D / spatial pipeline — a position, not a capability

The weights are physically here and **none of it may be described as a capability of this box**:

| Stack | Files | Size | Route | Provenance |
|---|---|---|---|---|
| **3D** `triposplat_fp16` + VAE decoder | 2 | 1.23 GiB | none | **none** |
| **video** `minimax_h3_*` + video VAE + turbo LoRA | 3 | 26.20 GiB | none | **none** |
| **audio gen** `stable_audio_3_medium` + audio VAE | 2 | 9.15 GiB | none | **none** |
| **second image** `z_image_turbo_bf16` | 1 | 11.46 GiB | none | **none** |

Gate for any of them, and the order is not negotiable: **provenance → licence → runtime → smoke
→ bench → route.** First 3D generation or export is a **first-time evolution** under Bootcamp
§4a — `simulation_available: REQUIRED`, `solo_allowed: NO`. The smallest honest next step is
**one manifest entry with a read licence for one file**, then re-scout. Inference is not the next
step; paperwork is.

## 7. NeuroScope / Model Atlas — the one FUTURE item that is already half-real

Bootcamp §5 rates Option 1 (metadata-only inspection) a **STARTER**, and this matrix agrees for a
reason worth stating: the reader is **already built and already total**. `api.py:197 _gguf_arch`
and `tools/lib/bootcamp_scout.py:46 gguf_arch` both parse GGUF headers and return `None` rather than
raising on a truncated file, a non-GGUF file or an unknown value type. Measured today: it reads
`clip`, `gpt-oss`, `qwen2`, `qwen3`, `qwen35` across 54 files.

**Option 2 needs no new capability — only a surface.** That makes it the highest value-per-risk
item on this whole matrix. **Option 3 (activation/projection capture) stays BLOCKED**: activations
reveal properties of inputs, and storage plus retention is undesigned.

## 8. Anti-cheat, restated only as it binds this file

Full rules: Bootcamp §3. The two that constrain **these** tables:

- **No row may cite a benchmark the Referee scored as `fallback_trap` FAIL.** Provenance is
  checked before content: a reply from the wrong engine invalidates whatever else it shows.
- **A `negative_control` PASS is a generic or absent answer.** So the two "both models got
  SyMoNeuRaL wrong" readings are **two PASSES** and appear as such in `MODEL-BENCHMARKS.md`. A
  model that named this box's card or ports would have been the alarm.

**Blind by construction, not by careful wording:** `build_request()` reads `probe.prompt` and
nothing else, and a test asserts that two probes identical in prompt but differing in every
evaluator field produce **byte-identical payloads**.

## 8a. Tunnel health — **NEEDS CHECK**, and every "public" cell above depends on it

The `Exposure` inputs in §4 say `public` because a path in `ops/Caddyfile` reaches the instance and
`symoneural.com` answered **200** when measured. **The ingress path itself is classified
`NEEDS CHECK` and is not treated as proven here:**

| Reading | Value |
|---|---|
| `cloudflared` unit | **`activating` / restarting**, `NRestarts` climbing (**6932** at 02:59:12 on 2026-08-23, ~5/min) |
| cause | `ExecStart=/usr/local/bin/cloudflared`; the binary is at `/usr/bin/cloudflared` |
| observed ingress | `symoneural.com` → **96.37.45.61**, this box's own IP; response headers `server: Caddy`, **no `cf-ray`** |
| conclusion | Caddy appears to serve **directly**, so the flapping tunnel is **not** the live path |

**"Appears to" is doing real work in that sentence.** Whether the tunnel is redundant, mid-migration
or supposed to be the only ingress is **not established by these readings**, and the answer changes
what a `public` cell means. **So: `NEEDS CHECK` until verified separately.** No cell in §4 should be
read as a statement about the tunnel, and nothing here recommends changing it — the unit fix is a
`systemd` edit outside this batch's scope.

## 9. What this file deliberately does not claim

- **No starter changed.** Qwen is the Chat starter, FLUX the Image starter, the deterministic
  engines hold RavenCalc / Streamer / Project.
- **ASR has no starter today.** The weight is manifested and the runtime is absent; that is a
  position with a blocker, not a serving surface.
- **Every rating is derived by §2 from measured inputs.** Where an input was not measured, the
  rating is `P-none` / `—`, never a guess.
- **Phase 1 not started · nothing deployed · commercial mode off · auth unchanged · gpt-oss not
  activated · no weight moved, deleted or committed.**
- **404 commits between 2026-08-17 and `7a4e5c98` are not audited.** Every runtime, route and
  state reading here is **measured at `507e09ee` on 2026-08-23** and is not historical proof.

**Related** `backend/studio/docs/symoneural-bootcamp.md` · `ops/docs/APPLICATION-MODEL-CAPABILITY-MATRIX.md` ·
`ops/docs/MODEL-BENCHMARKS.md` · `ops/docs/VLLM-BENCH-PARITY.md` · `ops/docs/RUNTIME-PROFILES.md` ·
`ops/docs/SECURITY-AUDIT.md` · `backend/apps/test_control_plane_matrix.py`
