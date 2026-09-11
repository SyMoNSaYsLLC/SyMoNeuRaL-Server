# Design specs and audits — proposals, not state

**None of these is authoritative for what the project currently is.** `.claude/HANDOVER.md`
is the one state document and `.claude/CLAUDE.md` is the one rulebook; that separation exists
because three files once all claimed to describe current state and agents kept acting on the
stale one. Most of these are *inputs* — findings and recommendations produced on 2026-08-17 by
agents working in parallel. Read them as arguments to evaluate, not as decisions taken.
`miner-preemption.md` is the exception in kind: it is not a proposal awaiting a decision, it
records a decision already taken — the yield protocol is specified so that the three files
citing it resolve, and its §7 argues for leaving it unbuilt.

They live here rather than in a scratch directory because each represents real measurement
work that would be expensive to redo, and scratch directories do not survive the session.
`docs/` is not deployed — `scripts/deploy.sh` publishes `site/` only — so nothing here
reaches a visitor.

**This table lists fewer files than the directory now holds.** Later sessions added specs without
indexing them here; treat an unlisted file as unreviewed by this README rather than as absent.

| File | What it is | Status |
|---|---|---|
| `image-spec.md` | Restyle brief for `/image.html` (HANDOVER §5 item 1) | proposed, not implemented |
| `chat-spec.md` | Restyle brief for `/chat.html` (§5 item 2), modelled on the llama.cpp web UI | proposed, not implemented |
| `css-audit.md` | Collision audit of `site/symoneural.css`, plus a reserved-name list | findings; **the `.card` bug it reported is fixed** — see below |
| `cuda-audit.md` | Audit of the CUDA engine (§5 item 8) | findings; nothing fixed |
| `online-apps-audit.md` | Test pass over all twelve rack units, 2026-08-17 | findings; **one defect found and fixed** |
| `symon-ml-review.md` | Review of the SyMoN_ML blueprint and the TRON licensing PoC | review; nothing implemented |
| `miner-preemption.md` | The GPU miner yield protocol — why a live miner is never evicted, and the mechanism that would change it | **specified, deliberately not implemented — read its §7 first** |
| `voice-spec.md` | SyMoNeuRaL Voice (§5 item 12) — the ASR half **measured** on the CPU build already on disk, which settles the governor question; TTS unmeasured and says why | proposed, nothing built |
| `symoneural-studio-upgrade-scope.md` | Studio as a ComfyUI-shaped surface that SyMoNeuRaL owns: product modes, the four execution targets, the four compile targets, badges, security boundaries. Task #103. Its §2 answers the recorded reason the first canvas was deleted; §3.2 records that `/studio/editor/*` publicly proxies ComfyUI's own frontend **today**; §3.4-3.5 correct the packet's SDXL examples against the FLUX baseline actually on this disk | proposed direction-lock, nothing implemented |
| `symoneural-studio-node-system.md` | The data half of #103 — node registry fields, the canonical graph schema, validator, target resolver, compiler, and the five-node MVP | implementation plan; **not** authorization to implement |
| `symoneural-runtime-registry.md` | Task #104, the RuntimeOps half: the runtime registry (distinct from the model registry) and the runtime router that joins them. Carries the maturity ladder — of seven runtime families, two are built, one is source-only, four are absent | proposed, nothing implemented |
| `symoneural-model-hot-swap.md` | Task #104 — hot swap as a controlled operation rather than manual process killing, and the six multi-model-serving mechanisms kept deliberately distinct | proposed, nothing implemented |
| `symoneural-application-lab.md` | The pre-migration inventory: ten application areas, the five reference archives located and sized on disk with their contents deliberately unopened, and the resolved §19-vs-#83 conflict over SyMoNeuRaL Project. Verdicts are **not** here — they point into `BOX-REALITY-AUDIT.md` §10 | inventory + direction; nothing implemented, no archive imported |
| `symoneural-platform-targets.md` | What a platform target *is* in SyMoNeuRaL terms — the ten-row platform contract, and Linux/Apple/Android/Windows as direction only. Deliberately contains neither the gate (`GUARDRAILS.md`) nor the measured per-platform state (`REPOSITORY-PURPOSE.md`) | direction only; **no platform or toolchain build authorized** |
| `symoneural-miner-scope.md` | R-176's Miner overhaul scope, and the rule for what the public page may claim. Records why the GPU half cannot run as shipped: `contrib/` is absent, `SYMONEURAL_MINER_CMD` points at a dead path, and `build-kawpowminer.sh` is not tracked, so the 52-53 MH/s benchmark is provenance rather than current telemetry | AUDIT / overhaul; page copy corrected, no engine work |
| `symoneural-coder-project-cli-scope.md` | Coder, Project/Cowork and CLI. Mostly a set of corrections: `@symoneural code.tar.gz` holds **no first-party code** (3,598 entries of third-party Anthropic projects), the CLI's "missing" interactive UX is all implemented, and Coder's local-only/token/root/denylist posture already exists and is tested | scope + audit; nothing implemented |
| `symoneural-live-stack.md` | The observable rack: identity in `ROSTER.md`, state from `/api/status`, the thirteen units, and the two `bus` cells that look like mistakes and are not (`live`=net because OBS's NVENC is outside the governor; `streamer`=net overriding the module's `cpu`). Records one defect: `coder`'s href is `/documentation.html` | scope; no rack change |
| `symoneural-control-board.md` | The operator half. `RackPowerGate` (raw ASGI, `api.py:1415`) already refuses HTTP work for a powered-off unit, so "controls must be real" is satisfied and preserved rather than queued. Records why the rackpower/Live Stack/Control Board move is bigger than a rename: the rack tripwires must move with the inline assembly | scope; **no move authorized** |
| `symoneural-api-surface.md` | `/api/*` is public through Caddy and `/local/*` is not — the rule behind there being no `/api/coder`. Rate buckets: configured is not wired, and `check_rate` returns True for any surface it cannot find, so an absent name is *unmeterable* rather than unlimited | scope; no route change |
| `symoneural-website-look-feel.md` | Instrument-first layout, the no-data-dropped rule (fold, never trim), honesty rules for anything numeric, and the build order — `build_cachebust.py` runs last, because `build_pages.py` alone strips every `?v=` hash | scope; no page change |
| `symoneural-parameters.md` | The control contract: every visible control must reach the engine. Names the three honest states for a control that does not do what it looks like (locked / inert / unsupported) and identifies the fourth — shown, active-looking, ignored — as the defect. FLUX/Schnell is the worked example | AUDIT until scoped |
| `symoneural-moe.md` | Mixture-of-experts direction, opening with the measurement: **there is no MoE model on this box** — every occurrence of "MoE" is educational text or a news keyword. Separates a true MoE architecture (a property of a model file) from SyMoNeuRaL-level composition (a property of the router) | AUDIT until scoped |
| `symoneural-cloud-local-targets.md` | The two execution targets and their resolver states. Cloud is where a job runs relative to the customer, **not a fleet** — one card, so no capacity or SLA claim. Local's honest default is `NEEDS_LOCAL_AGENT`, because no local agent exists | AUDIT until scoped |
| `symoneural-generic-contracts.md` | The shared shape of model/runtime/job/node/parameter/target, and the two hard rules: not a third registry, and not a product page. Records why a Pydantic `BaseModel` cannot be the wire — #97 found it renders untyped through `registry._json_type` | AUDIT until scoped |
| `symoneural-chat-scope.md` | Chat as the primary conversational surface, the residency-vs-work-lock distinction, RavenCalc as verified math co-processor, and why hosting Project/cowork makes Chat privileged — `/api*` is public, so filesystem tools reuse Coder's already-built gate | PROD direction; nothing implemented |
| `symoneural-image-scope.md` | The four FLUX/Schnell files measured on disk, the four Schnell rules (cfg 1.0, negative prompt inert, raising cfg is not quality, guidance is embedded conditioning), and image-to-image captured as requested upgrade | PROD direction; upgrades AUDIT |
| `symoneural-remix-scope.md` | The two things called Remix — the live `/api/remix` chat-surface client, and the older `symoneural_dj` Spotify app — which fail independently. Corrects `DJ_TOKEN_PATH`: it is the Spotify OAuth cache, not a token file | PROD live surface; DJ naming AUDIT (Q12) |
| `symoneural-ravencalc-scope.md` | CPU by design, not fallback — with the carve-out that stops a future audit reading "no CPU fallback" as a violation. The five load-bearing claims a layout change must not delete | PROD direction; page layout is #84 |
| `symoneural-sigils-scope.md` | Sticker/sigil generation, separate from Image. The rate-limit requirement is already satisfied *and tested* — `test_sigils.py` asserts the router throttles, and against the right surface. Exact output vocabulary: a PNG is not an SVG | PROD direction; nothing implemented |
| `symoneural-streamer-scope.md` | The Tuner+Guide fold, already done: guide nested at `/api/streamer/guide` precisely so its readiness probe cannot resolve against Streamer's `/state` — the decorative-indicator failure, prevented by mount order | PROD direction; archive AUDIT |
| `symoneural-live-scope.md` | Live, not Live Stack. "Absent OBS must not break boot" is enforced by the import graph — `hls.py` never imports `obs.py`, so a wrong password costs the telemetry line, not the video. Records why Live has no power switch | PROD where proven |
| `symoneural-commercial-mode.md` | One switch (`SYMONEURAL_MODE`), default `free_offline`, **off**. Opens with the correction that **the meter already exists** — `accounts/meter.py` has balances, holds, a ledger and reserve-then-resolve, so the commercial work is connection and decision, not construction | mode DISABLED; Meter BUILT/AUDIT |
| `symoneural-revenue-edge.md` | The five bets and which hooks already exist. Notes that `_RATE_SUGGESTED` is already a cost model in rate-limit clothing — and is not a price list | hooks disabled by default |
| `symoneural-entitlements.md` | *May this identity run this?* — asked **before** the meter's *can they afford it?*, because a permission check after a debit is a refund waiting to happen. Flags an existing `gateway/entitlement.py` that must be read before a second one is written | AUDIT |
| `symoneural-marketplace.md` | Sellable workflows/adapters/packs. FUTURE, and gated on Studio having a plugin contract at all — a marketplace for an extension point with no contract is a shop with no shelves | FUTURE |
| `symoneural-appliance.md` | The signed offline local-AI box. Blocked on a build that has never run, so its licence manifest is **not yet producible** rather than missing — plus three weights that cannot legally travel | FUTURE/AUDIT |
| `symoneural-trust-report.md` | The customer-facing compliance render. FUTURE because it renders rather than generates, and its governing rule is that it must never render a field it does not have | FUTURE/AUDIT |
| `symoneural-sentinel-spec.md` | R-179's model-supervision surface — interceptor, evaluator, intervention ladder, session audit. **Renamed from `therapist-spec.md` 2026-08-22**: the old name needed a production disclaimer denying healthcare, and a name that needs a denial attached is the wrong name, so the disclaimer and the clinic aliases are deleted rather than reworded | FUTURE/AUDIT |

## What is worth acting on, and what was verified independently

Three claims from these reports were checked directly rather than taken on trust, because a
report is not evidence:

- **`.card` was defined twice** — `site/symoneural.css:118` and `:955`. The later rule was
  written for the homepage receipts grid and should have been `.cards .card`; it was winning
  on eleven unrelated `.card` elements in `documentation.html`. A fourth instance of the
  collision class documented in CLAUDE.md. **Fixed, and no longer a live bug** — re-verified
  2026-08-17: the file now carries exactly one definition, `.cards .card` at `:1027`, in both
  `HEAD` and the working tree, and the browser suite asserts it against production
  (`a .card outside the receipts grid keeps its own styling — 11 general cards, display:block
  padding:22px`). This line said "live bug" for a day after it stopped being one, which is the
  drift this directory's own preamble warns about.
- **The CUDA engine is not where the brief said it was.** There is no `symoneural_reinforce/`;
  it is `backend/apps/studio/plugins/reinforce/`, moved in `9b5da84`, and it is 35 Python files with no
  `.cu` and no CMake — it compiles through NVRTC at runtime. HANDOVER §10's layout block
  still showed the old path and has been corrected.
- **`context.py:149`** is the only `_attr` call in that file without an explicit default,
  and `_attr` defaults to `0`, so a name mismatch yields zero SMs silently while every
  neighbouring call guards itself. Confirmed by reading the file.

The rest of each report is unverified beyond the agent's own working. Where a report claims a
measurement, it generally records how it was taken; where it claims a bug, treat it as a lead
until you have reproduced it. The `cuda-audit.md` honest-labelling findings in particular
touch the argument the whole site rests on and deserve a careful second look before anything
is changed on their say-so.

## One thing these reports cannot tell you

They were written against the tree as it stood on 2026-08-17 and they quote line numbers.
`build_pages.py` has already changed since (the miner surface was added at the end of
`main()`). Re-grep before trusting any `file:line` in here.
