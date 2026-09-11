# SyMoNeuRaL application × model capability matrix — what each app can actually load

**Read at `507e09ee`, 2026-08-23.** Measured by grepping the app tree for weight names and
resolving each against the disk. **Nothing here activates anything.**

> **This file owns one question: which app can actually load which weight.** Not who is starter
> (`docs/specs/symoneural-bootcamp.md`), not how fast (`docs/ops/MODEL-BENCHMARKS.md`), not the
> record shape (`docs/specs/symoneural-control-plane-matrix.md`).

## 0. The distinction this file exists to make

**"The weight is on disk" and "this app can use it" are different sentences**, and the gap
between them is where two findings were hiding:

- a weight can be **present and manifested** while the **runtime that reads it is absent** — the
  ASR case below, which affects **two** apps, not one;
- a weight can be **physically present and legally unusable** — the 38 unmanifested files.

So a cell in this matrix is `reachable` only when **the app names it, the weight is on disk, and
the runtime that loads it exists.** All three, measured.

## 1. Reachability — app × weight, measured

Legend: **`R`** reachable (app names it · weight present · runtime present) · **`W`** weight
present but **runtime absent** · **`X`** named but weight absent · **`—`** not named by this app.

| App / module | chat 7B | draft 0.5B | persona LoRA | 14B | FLUX unet | FLUX t5 | FLUX clip | FLUX vae | whisper base.en | u2net |
|---|---|---|---|---|---|---|---|---|---|---|
| **`api.py`** (chat, image) | **R** | **R** | **R** | — | **R** | **R** | **R** | **R** | — | — |
| **`sigils`** | — | — | — | — | **R** | **R** | **R** | **R** | **R** | **X** |
| **`studio`** (workflows) | — | — | — | — | **R** | **R** | **R** | **R** | — | — |
| **`studio`** (`symoneural_gguf` node) | — | — | — | — | — | **R** | — | — | — | — |
| **`studio/plugins/reinforce`** | — | **R** | **R** | **X** | — | — | — | — | — | — |
| **`voice`** | — | — | — | — | — | — | — | — | **R** | — |
| all other 11 app modules | — | — | — | — | — | — | — | — | — | — |

### The ten weights those columns name, by exact filename

Spelled out in full because `backend/apps/test_control_plane_matrix.py` resolves **every one of
them against the disk**, and a column header cannot be resolved. The adapter is the one that does
**not** live under `backend/models`.

**Eight of the ten are present as of 2026-09-04; two are not.** All ten were present when this
was written, which is why the `ABSENT` markers below are dated corrections rather than an
original state -- and why the reachability table above reads **X** where it read **R** or
**W** for them. `W` means *weight present, runtime absent*; once the weight goes too, the honest
cell is `X`, and leaving a `W` would understate the gap by naming the smaller of two absences.

**CORRECTED 2026-09-04: whisper `base.en` is back, and so is its runtime, so the two ASR cells
now read `R`.** This is the one movement on this table that went the good way. Both halves were
missing and both are now present: `engines/symoneural-listen` is built from source under our own
names by `tools/fork_engines.sh listen`, and the weight is on disk at 147,964,211 bytes. Neither
is asserted -- `symoneural-listen/SMOKE-listen-asr.md` records a real transcription of real speech, which
is the only evidence that distinguishes `R` from a hopeful `W`.

| Column | Filename | Location |
|---|---|---|
| chat 7B | `symon-1.0-7b-q4_k_m.gguf` | `backend/models/llm/` |
| draft 0.5B | `symon-1.0-draft-0.5b-q4_k_m.gguf` | `backend/models/llm/` |
| persona LoRA | `symoneural-lora.gguf` | **`training/adapter/`** — protected, reported separately |
| 14B | `symon-1.0-14b-q4_k_m.gguf` | **PRESENT** since 2026-09-08 — fetched through `scripts/fetch-models.sh` at the owner's instruction; 8,988,110,976 bytes, exactly the count `PROVENANCE.json` records, sha256 `e47ad95d…`. Still **not a serving default**: it is named by the tuner registry and by tests, and `RESTORE_REQUIREMENT=OPTIONAL` in `restore/manifests/MODELS.tsv` because nothing in `api.py` loads it. |
| FLUX unet | `symoneural-image-unet-q4_k.gguf` | `backend/models/image/` |
| FLUX t5 | `symoneural-image-t5-q8_0.gguf` | `backend/models/image/` |
| FLUX clip | `symoneural-image-clip.safetensors` | `backend/models/image/` |
| FLUX vae | `symoneural-image-vae.safetensors` | `backend/models/image/` |
| whisper base.en | `symoneural-listen-base-en.bin` | `backend/models/whisper/` — present 2026-09-04, with its runtime; ASR serves |
| u2net | `u2net.onnx` | **ABSENT** — rembg background removal does not serve |

**Source lines, so every cell is checkable:** `api.py:187,266,188,277-280` ·
`sigils/render.py:86-89` · `sigils/listen.py:44,49` · `sigils/segment.py:53-54` ·
`sigils/cutout_worker.py` · `studio/workflows.py:48-51` ·
`studio/custom_nodes/symoneural_gguf/__init__.py:5` ·
`studio/plugins/reinforce/registry.py:588-589`, `jobs.py:852` · `voice/asr.py:53-54,56`.

### Three readings worth pulling out of that table

**1. The FLUX bundle is shared by three consumers, not one.** `api.py:277-280`,
`sigils/render.py:86-89` and `studio/workflows.py:48-51` name **the same four components**. That
is a capacity fact before it is a capability fact: ~11.8 GiB resident on a **16,303 MiB** card,
so Image, Sigils and Studio cannot all hold it independently, and none of them can co-reside with
the 20B chat candidate. Bootcamp §5 records the same finding from the depth-chart side.

**2. The ASR runtime was unusable and took two apps down with it — RESOLVED 2026-09-04.**
Both `voice/asr.py` and `sigils/listen.py` resolved `whisper-cli` to a path under `contrib/`,
which **did not exist** and which `.gitignore` ignores. Two `whisper-cli` binaries did exist
under `references/` — both **973,872 B** — but `references/` is INSPIRE_ONLY and
`backend/apps/test_references_boundary.py` bans that spelling from product code, so they were
**quarantined, not available**.

**What fixed it was building the engine we were entitled to build, not finding the binary.**
`tools/fork_engines.sh listen` now forks the vendored upstream into
`engines/symoneural-listen` under our own names — the same treatment the other two engines got
— and both call sites resolve there. CPU-only by decision, not default: `ldd` reports zero CUDA
libraries linked, so it cannot take the card, which is what lets a spoken sticker transcribe
*while* another surface holds the GPU instead of queueing behind it.

The lesson this row exists to carry is not "the binary was missing". It is that **the binary
lived in a gitignored directory**, so it could vanish leaving nothing in `git log` to say it
ever had — the same way the miner's benchmark binary went. Two instances made it a pattern;
building into `engines/` from a tracked script is the fix for the pattern.

Both call sites were honest throughout — `voice/asr.py` returned `"whisper-cli missing at
<path>"` and `sigils/listen.py` gated on the file existing. **The code never claimed
otherwise; a depth chart did**, nine hours after task #104 had already recorded `contrib/` as
missing. See `docs/specs/symoneural-control-plane-matrix.md` §5a for that timeline.

**3. The tuner names a model no serving path uses.**
`studio/plugins/reinforce/registry.py:588-589` names
`symon-1.0-14b-q4_k_m` and the 0.5b draft, and **no serving default points at it** — `CHAT_MODEL`
is the 7B. That is Bootcamp's "redshirt" for the Chat position, seen from the app side: reachable
by the trainer, not by the product.

**CORRECTED 2026-09-03: the 14B is no longer on disk.** This paragraph said "on disk (8.99 GB) and
manifested", and `docs/specs/coder-spec.md` still says "present, not wired to any surface". A
filesystem-wide search of `/`, `/home` and `/yocto` for `symon-1.0-14b*` and for any
`Qwen2.5-14B-*Q4_K_M*` returns nothing — the restoration that brought back the 7B, the 0.5b draft
and the four FLUX payloads did not bring back the 14B. `backend/models/PROVENANCE.json` still holds
its record, which is correct and is precisely the distinction that file exists to make: **a
provenance record describes an artefact's origin and is not evidence the artefact is on disk now.**

Nothing serves it, so this is not a production blocker — it is an absence that had been documented
as a presence for long enough that a reader would have believed it. Restoring it means re-fetching
~8.4 GiB from `bartowski/Qwen2.5-14B-Instruct-GGUF` (see `backend/models/NAMES.md`), which is an
owner call about disk and bandwidth rather than an engineering one, and it blocks no surface.

## 2. Weights on disk that **no app names at all**

54 weight files, 231.52 GiB total. The apps above name **10 distinct weights**. The remainder:

| Group | Files | Size | Named by any app? | Provenance | Status |
|---|---|---|---|---|---|
| `llm/` 27B, 32B, 27B-vision | 3 | 24.58 GiB | **no** | manifested | rollback / redshirt |
| `staging/openai-gpt-oss-20b/` | 5 | 38.49 GiB | **no** — staging is wired to no route | candidate tree | **candidate**, not activated |
| `hf/hub/` Qwen2.5-7B, Qwen3.6-27B | 21 | 65.94 GiB | **no** | none | walk-on — raw HF, not serving format |
| `diffusion_models/`, `text_encoders/`, `vae/`, `checkpoints/`, `loras/`, `clip_vision/`, `background_removal/` | 20 | ~99 GiB | **no** | **none** | **injured reserve** |

**Every unnamed, unmanifested file is injured reserve by rule.** The blocker is one sentence and
it is the same for all of them: **no recorded provenance, therefore no recorded licence,
therefore no lawful basis to serve or redistribute output.**

**This is the honest shape of this box:** ~99 GiB of video, 3D, audio and second-image weights
that are the most impressive things physically present here, that no line of application code
names, and that may not be described as capabilities. See
`docs/specs/symoneural-control-plane-matrix.md` §6 for the gate order.

## 3. What would make a `W` become an `R`

For ASR, in order, and none of it is inference work:

1. **Build it into `engines/symoneural-listen/`, not `contrib/`.** `contrib/whisper.cpp/` is a
   path the references boundary explicitly bans, so rebuilding there recreates a rule violation
   the grep happens not to see. The precedent is already set: both other GPU runtimes were forked
   under our own names into `engines/` (`symoneural-llm`, `symoneural-diffuse`, `d6b7838a`), and
   `docs/specs/symoneural-runtime-registry.md:88` **already reserves `runtime_id:
   symoneural-listen`**.
2. **Repoint `voice/asr.py:53-54` and `sigils/listen.py:44`** at the new home — two call sites,
   and they are the only two.
3. **Track the build script.** `/contrib` being gitignored is exactly how this capability
   disappeared once, and how the miner's benchmark binary disappeared too.
4. **Set `SYMONEURAL_VOICE_ENABLED=1`** — the literal string `1`; `true` leaves it off, silently
   (`voice/__init__.py:53`).
5. **Re-read `GET /api/status`** and confirm a `voice` unit appears. It does not today.
6. **Then** the depth chart may say `serving`, and not before.

**This is the miner's failure mode a second time.** The 52–53 MH/s figure has the same shape: a
real measurement whose binary lives outside version control
(`contrib/build-kawpowminer.sh`, untracked). Two instances make it a pattern, and the pattern is
**artefacts that matter living in a gitignored directory.**

## 4. Caveats carried forward, deliberately

- **Measured at `507e09ee` on 2026-08-23.** A reachability cell is a reading of this disk at this
  commit, **not historical proof**.
- **404 commits between 2026-08-17 and `7a4e5c98` are not audited**, and they touched
  `backend/server.py` (53 commits) and Studio (16). A cell here could have been different last week
  without any commit in the audited range saying so.
- **Nothing was activated, moved, deleted or committed** to produce this file. `backend/models`
  holds exactly two tracked files, `NAMES.md` and `PROVENANCE.json`; `.gitignore:5` ignores the
  rest.

**Related** `docs/specs/symoneural-control-plane-matrix.md` · `docs/specs/symoneural-bootcamp.md` ·
`docs/ops/MODEL-BENCHMARKS.md` · `docs/ops/PROVENANCE.md` · `docs/ops/SYMONEURAL-MODEL-BUNDLES.md` ·
`backend/apps/test_control_plane_matrix.py`
