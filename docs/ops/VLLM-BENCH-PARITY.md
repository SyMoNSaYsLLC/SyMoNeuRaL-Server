# vLLM ↔ SyMoNeuRaL benchmark parity — the contract, and why it is unmeasured

**Opened 2026-08-23, read at `507e09ee`.** **No parity figure exists.** This file defines what
parity would have to mean before anyone measures it, and records a finding about vLLM's presence
on this box that four other documents get wrong.

> **This file owns the parity contract and its unmeasured status.**
> `docs/ops/RUNTIME-PROFILES.md` owns the runtime ladder. `docs/ops/MODEL-BENCHMARKS.md` owns the
> figures that *do* exist. Nothing here activates, installs, serves or benchmarks anything.

## 0. Classification, in the project's own vocabulary

Stated as labels and not only as prose, so the status is greppable and cannot be softened by a
sentence somewhere else:

| Thing | Classification |
|---|---|
| **vLLM 0.25.1 on this box** | **PRESENT** — installed, imports, CUDA-visible. A measured fact |
| **A running vLLM service** | **ABSENT** — no process, no port, no unit |
| **SyMoNeuRaL ↔ vLLM integration** | **AUDIT** — nothing wired, nothing proven |
| **vLLM ↔ SyMoNeuRaL benchmark parity** | **AUDIT** — no parity figure exists at any value |
| **Production readiness** | **NOT PRODUCTION-READY.** Not a candidate for serving, not a fallback, not a claim to make about this box |

**PRESENT is not READY, and this table exists to keep those two words apart** — because the
opposite conflation (*not installed* vs *not serving*) is precisely the error §1 corrects. Getting
the correction right and then over-reading it in the other direction would be the same mistake
with the sign flipped.

**`AUDIT` stays `AUDIT` until every row of the §2 contract is satisfied and recorded.** Installing
a package proves the package installs. It proves nothing about this project.

## 1. The finding: vLLM is installed, and four documents say it is absent

| Reading | Value | How |
|---|---|---|
| location | **`/home/google/.venvs/vllm`** — outside the repo, untracked by construction | `git check-ignore` refuses it: outside repository |
| version | **vLLM 0.25.1** | `import vllm; vllm.__version__` |
| stack | **`torch 2.11.0+cu130`**, `torch.cuda.is_available()` → **True** | same interpreter |
| device visible | **NVIDIA GeForce RTX 5070 Ti** | `torch.cuda.get_device_name(0)` |
| created | **2026-07-20 16:04**, `uv 0.11.27`, CPython 3.12.13 | `pyvenv.cfg`, dir mtime |
| **service** | **none.** No process, no listening port, no unit | `pgrep`, `ss -ltn` |

**The venv predates by three weeks** the commit that wrote *"vLLM … **absent**"* into
`RUNTIME-PROFILES.md:43` (`7a4e5c98`, 2026-08-22).

### What is corrected, and what is left alone

**Corrected** — the flat *absent / not installed* claims, which are false:

| File | Was |
|---|---|
| `docs/ops/RUNTIME-PROFILES.md:43` | `absent` |
| `docs/ops/BOX-REALITY-AUDIT.md:454` | "**absent** — Not installed" |
| `docs/specs/symoneural-runtime-registry.md:97` | `maturity: absent` |
| `docs/specs/symoneural-studio-node-system.md:221` | "`vllm-cloud` is `absent` on this box" |

**Left alone, because they are still true** — and this distinction is the whole point:

| File | Says | Status |
|---|---|---|
| `docs/ops/MODEL-REGISTRY.md:108` | "vLLM is a cloud candidate only — no service is running" | **TRUE** |
| `docs/ops/BOX-REALITY-AUDIT.md:507` | "vLLM: candidate only. No running service, and this report does not claim one." | **TRUE** |

**"No service is running" was never wrong. "Not installed" always was.** The two got conflated,
and conflating them is what let a false sentence sit beside a true one for three weeks.

### The ladder has no word for this, so this file does not invent one

`absent` is false — it is on disk and it imports. `built` is misleading — nothing here was
compiled by us and a third-party venv is not our artefact. `running` is false — no service.

**This needs Garrett's ruling, and it is deliberately not taken here.** Two defensible options:

1. **Add a level** meaning *installed, importable, no service* — the ladder gains a rung and every
   third-party runtime can be classified honestly.
2. **Rule the ladder repo-scoped** — a venv outside the repo is out of scope, and
   `RUNTIME-PROFILES.md` says so explicitly rather than by omission.

Until then, the entries above read **`installed-not-serving (see VLLM-BENCH-PARITY.md)`**, which
is a measurement rather than a ladder claim.

## 2. What parity would have to mean

**"vLLM is faster" is not a finding.** Two runtimes serving different quantisations of different
models at different contexts produce two unrelated numbers. Parity requires the comparison be
*constrained*, and here is the contract:

| Axis | Parity requirement | Why |
|---|---|---|
| **model identity** | the **same weights**, or a documented conversion with the conversion recorded | `symoneural-llm` serves **GGUF**; vLLM serves **safetensors**. The 20B candidate has both (`original/model.safetensors` 12.81 GiB; `symon-openai-20b.gguf` 12.85 GiB MXFP4) |
| **quantisation** | stated on both sides, never assumed equal | MXFP4 GGUF vs bf16/fp16 safetensors is **not** the same arithmetic |
| **context** | identical, and stated | production argv is `-c 65536 -cb -np 2` |
| **concurrency** | identical request pattern | vLLM's continuous batching is its main claim; a single-stream test measures the wrong thing |
| **card state** | same idle baseline, sole tenant | **239 MiB idle** measured; the governor must hold the lease |
| **tokens counted** | the **same** definition on both sides | gpt-oss charges 259 tokens for a one-sentence answer; a runtime comparison that counts differently is meaningless |
| **prompt set** | identical, and Referee-blind | Bootcamp §3: the model may not learn it is being benchmarked |
| **failure counted** | a refusal or OOM is a **result**, not an excluded run | excluding failures is how a parity table lies |

**A parity number missing any row above is not a parity number.** It is two benchmarks printed
side by side.

## 3. Why no parity figure exists today, in order

1. **No service runs.** Installed and importable is not serving.
2. **Standing instruction.** vLLM is the **cloud** runtime candidate
   (`RUNTIME-PROFILES.md:43` role). Standing locks: **do not deploy, do not start Phase 1, do not
   enable commercial mode.** A cloud-runtime parity run is adjacent to all three and is not
   authorised by the request that produced this document.
3. **It is a first-time evolution.** First vLLM service start on this box is *first route
   exposure* + *first GPU-heavy batch* under Bootcamp §4a: `solo_allowed: NO`,
   `shadow_required: YES`, `simulation_available: REQUIRED`.
4. **The card is the constraint, and the arithmetic is already known.** The GGUF candidate peaked
   at **14,297 MiB** of **16,303 MiB** at production context. vLLM pre-allocates a KV pool
   (`gpu_memory_utilization`) and would want a large fraction of the same card. **A parity run is
   a co-residency event on a 16 GB card**, and one probe already came within **894 MiB** of the
   governor's 1.5 GB drain floor.
5. **No safetensors runtime path is wired.** vLLM would read
   `staging/openai-gpt-oss-20b/original/model.safetensors` or the `hf/` shards — **weights with no
   route, in a staging tree wired to nothing.**

## 4. The smallest safe first step, if parity is ever wanted

Not a benchmark. In this order, and each step stops if the previous one fails:

1. **Rule the ladder question** (§1) so the runtime can be classified honestly first.
2. **Dry-run only**: `vllm --help` and a model-load *plan*, recording the pre-allocation it
   intends. No serve.
3. **Simulation**: load on an **isolated port**, sole GPU tenant, governor lease held, production
   module never imported — the exact shape the gpt-oss smoke used (port 8099, `dbb2adc5`).
4. **Record the co-residency ceiling before any throughput number**, because that is the reading
   that decides whether this box can host the runtime at all.
5. **Only then** the §2 contract, with a Referee-blind prompt set.
6. **Shadow, then partner, then review.** No promotion, no default change, no deploy.

**Anything that produces a tok/s figure before step 4 has measured the wrong thing.**

## 5. Caveats carried forward

- **No parity figure is claimed, projected or estimated in this file.** There is no number to
  quote, and that is the finding, not a gap in the writing.
- **Nothing was installed, started, served or benchmarked** to produce this document. The vLLM
  readings are an `import` and a `pyvenv.cfg`, taken read-only.
- **Measured at `507e09ee`, 2026-08-23.** Runtime presence is a reading of this disk now, **not
  historical proof** — which is exactly how the `absent` claim survived three weeks.
- **404 commits between 2026-08-17 and `7a4e5c98` are not audited.**

**Related** `docs/ops/RUNTIME-PROFILES.md` · `docs/ops/MODEL-BENCHMARKS.md` ·
`docs/ops/BOX-REALITY-AUDIT.md` · `docs/ops/MODEL-REGISTRY.md` ·
`docs/specs/symoneural-control-plane-matrix.md` §5b · `docs/specs/symoneural-bootcamp.md` §4a ·
`backend/apps/test_control_plane_matrix.py`
