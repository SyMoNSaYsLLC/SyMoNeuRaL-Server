# SyMoNeuRaL Runtime Profiles — the contract

**Status: stub. A contract for something not yet built.**

**Authority boundary.** `docs/ops/HARDWARE-PROFILES.md` says what the *machine* is;
this file says what can *serve* on it. `docs/ops/BOX-REALITY-AUDIT.md` §8 is the authority on
which of these runtimes actually exists on this box today — and the answer for most of them is
"not yet". Nothing in this file may be read as a claim that a service is running.

Consumers: `docs/specs/symoneural-runtime-registry.md`,
`docs/specs/symoneural-model-hot-swap.md`, and the planned `GET /api/runtimes`.

> **Portable-repo boundary, audited 2026-08-26.** The uploaded HEAD archive contains none
> of the four `engines/symoneural-*` homes and no `references/` build inputs. “Built” rows
> below are dated readings from the original host, not claims about a clone or `.deb`.
> `python3 tools/audit/audit_runtime_dependencies.py` reports the portable state; full findings
> are in `docs/ops/AUDIT-DEPENDENCY-RUNTIME-2026-08-26.md`.

---

## The maturity ladder — used everywhere in these docs

The ladder, in one line: **`absent` / `source-only` / `built` / `running` / `measured`.**

A runtime is at exactly one level. **Naming the level is mandatory**; "supported" is not a
level and never appears alone.

| Level | Means |
|---|---|
| `absent` | Not on disk |
| `source-only` | Source tree present, not built |
| `built` | Binary exists; not running |
| `running` | A process is serving right now |
| `measured` | A stamped figure from a real run exists, with the SHA it was read on |

**Nothing is called green above the level the disk supports.** This ladder exists because the
one thing this project has published untruthfully before is a figure that outran its evidence.

## Runtime families

Roles are Garrett's, 2026-08-22. Current levels are measured — see the audit for evidence.

| Family | Role | Level today |
|---|---|---|
| **llama.cpp** → `symoneural-llm` | primary GGUF/local LLM runtime candidate — local/customer/owner, quantized, smaller edge models, OpenAI-compatible local service where applicable | **built** |
| **stable-diffusion.cpp** → `symoneural-diffuse` | local/customer/owner image runtime candidate — lower-level image generation, GGUF/quantized workflows, a simpler runtime beside Comfy | **built** |
| **ComfyUI** → `symoneural-ui` | **private** workflow/image runner: complex image/audio/video graph execution, the current FLUX/Schnell bridge. **Not a public raw product surface.** | **source-only** |
| **whisper.cpp** | primary ASR runtime candidate — local/customer/owner speech-to-text | **absent** |
| **vLLM** | primary **cloud** LLM runtime candidate — high-throughput serving, OpenAI-compatible API, future dynamic adapter/LoRA serving where supported | **`installed-not-serving`** — see the correction below |
| **NVIDIA samples/tools** (`nvidia-diagnostics`) | diagnostic and benchmark **reference only** — GPU diagnostics, CUDA benchmarking, memory/concurrency experiments. **Not blindly copied into app logic.** | **absent** on disk |
| **TensorRT-LLM, Triton, CUDA graphs / MPS** | future NVIDIA-optimized path, **after proof** | **absent** — future/AUDIT only |

> **Correction, 2026-08-23 at `507e09ee`.** The vLLM row read **`absent`** — *"Not on disk"* —
> and that was **false when it was written**, on 2026-08-22 at `7a4e5c98`. **vLLM 0.25.1** lives in
> **`/home/google/.venvs/vllm`**, created **2026-07-20** (three weeks earlier) by `uv 0.11.27`. It
> imports, `torch 2.11.0+cu130`, `torch.cuda.is_available()` **True**, device **RTX 5070 Ti**.
> **No service, no port, no unit.**
>
> **`installed-not-serving` is deliberately not a ladder level.** The ladder above has five rungs
> and none of them fits: `absent` is false, `built` is misleading (we compiled nothing; a
> third-party venv is not our artefact), `running` is false. **Naming the level is mandatory here,
> so the honest move is to say the ladder is short a rung rather than round to the nearest one.**
> Two options — add the rung, or rule the ladder repo-scoped so an external venv is out of scope.
> **Garrett's ruling; the argument is in `docs/ops/VLLM-BENCH-PARITY.md` §1.**
>
> **`whisper.cpp` above stays `absent`, and it is correct.** The weight
> (`symoneural-listen-base-en.bin`, 147,964,211 B) is present and manifested, but `contrib/` does
> not exist — so **two apps** (`voice`, `sigils`) name a runtime that cannot load it. Two
> `whisper-cli` binaries exist under `references/`, and both are **quarantined** by
> `backend/apps/test_references_boundary.py:70`, which bans `references/<tree>/` **and** the
> `contrib/whisper.cpp/` spelling — so `absent` is right for the ladder even though a binary
> exists on the disk. **The sanctioned home is `engines/symoneural-listen/`**, the id
> `docs/specs/symoneural-runtime-registry.md:88` already reserves, following `d6b7838a`, which
> forked the other two runtimes under our own names. This ladder was right; a depth chart claiming
> ASR was *serving* was wrong, and is corrected in `docs/specs/symoneural-bootcamp.md` §5.

**On NVIDIA sample code specifically:** do not import sample source into product logic without
a license and security review. That is not only a rule here — `backend/apps/test_references_boundary.py:70`
already enforces the `references/` boundary in a test, and a rule with a test behind it is
stronger than a rule in a document.

## Profile fields

Each runtime profile entry:

| Field | Notes |
|---|---|
| `runtime_id` | stable, ours — e.g. `symoneural-llm`, `comfy-private` |
| `family` | one of the families above |
| `maturity` | the ladder value, mandatory |
| `model_formats` | `gguf` \| `safetensors` \| `diffusers` \| `onnx` \| `bin` |
| `api_styles` | `openai-compatible` \| `comfy-prompt` \| `native-cli` \| `http-json` |
| `targets` | `cloud` \| `local_customer` \| `local_owner_nvidia` \| `auto` |
| `health_endpoint` | how "is it up" is answered |
| `model_list_endpoint` | how "what can it serve" is answered |
| `load_strategy` | how a model becomes resident |
| `unload_strategy` | how it stops being resident |
| `hot_swap_support` | `native` \| `restart` \| `none` \| `unknown` |
| `multi_model_support` | `concurrent` \| `one-at-a-time` \| `unknown` |
| `gpu_memory_requirements` | derived, labelled measured / vendor / projected |
| `concurrency_class` | `llm` \| `image` \| `asr` \| `embedding` \| `utility` |
| `docs_href`, `api_href`, `openapi_operation_id` | where applicable |

## Rules

- **`maturity` is not optional and not inferred.** A profile with no maturity is invalid.
- **`hot_swap_support: unknown` is a legitimate value.** Guessing `native` because a runtime
  *looks* like it should support it is how a swap becomes a crash.
- **No CPU fallback for GPU workloads on the owner profile unless explicitly authorized.**
- **`multi_model_support: concurrent` must be measured before it is claimed.** On one 16 GB
  card, a large image model and a large LLM co-resident is not an assumption anyone gets for
  free — see `docs/ENGINEERING.md`: chat ~5 GB, image ~7 GB, a QLoRA run ~12 GB, and they
  "cannot coexist".
- **Every runtime goes through the governor.** A runtime that takes the card without a lease is
  the failure `scripts/gpu-governor.sh` exists to prevent, whatever its family.

---

## Candidate runtime compatibility — ANSWERED 2026-08-22

**Verdict for `symon-openai-20b` (`openai/gpt-oss-20b`): NEEDS CONVERSION.** Everything needed is
in this tree; a conversion step stands between upstream's format and the engine's.

| Question | Answer, measured |
|---|---|
| format the active engine requires | **GGUF** |
| format `gpt-oss-20b` ships | **safetensors only** — `original/model.safetensors` 12.81 GiB, or three shards of the same total. **No GGUF upstream** |
| conversion needed? | **Yes, and it is supported in-tree** — `engines/symoneural-llm/conversion/gpt_oss.py`, `@ModelBase.register("GptOssForCausalLM")`, with `repack_mxfp4()` |
| **MXFP4 supported?** | **Yes.** `GGML_TYPE_MXFP4 = 39` in `ggml.h:429`, **and the CUDA path** — `convert.cu`, `getrows.cu`, MMQ configs |
| architecture registered? | **Yes.** `LLM_ARCH_OPENAI_MOE` → `"gpt-oss"` (`llama-arch.cpp:121`) |
| chat template? | **Yes.** `LLM_CHAT_TEMPLATE_OPENAI_MOE` — Harmony (`llama-chat.cpp:75`) |
| VRAM on the 15.92 GiB card | **will not fit at the production context.** 12.81 GiB weights + ~3.9 GiB KV at `-c 65536 -np 2` ≈ 16.7 GiB on a 16,303 MiB card. The smoke uses `-c 8192 -np 1` |
| engine build | `build 296, commit 2246ab7` |

**`repack_mxfp4` is why this is viable.** It repacks the 4-bit blocks instead of dequantising
them — `dequant_model()` returns early when `_is_mxfp4` — so the GGUF keeps the 4-bit weights
rather than inflating to bf16, which would not fit this card at all.

**Conversion requires PyTorch and the interpreter matters:** `/usr/bin/python3` has none;
**`training/.venv/bin/python3` has torch 2.11.0+cu128 with CUDA available and sm_120 recognised.**
**The isolated smoke path needs no PyTorch** — it is the C++ engine binary.

**No runtime family moved on the maturity ladder**, and no document here claims a runtime is
running that was not already claimed. What changed is that a candidate's compatibility is now
**recorded** rather than unrecorded. Full detail: `docs/ops/OPENAI-GPT-OSS-MIGRATION.md` §2.
