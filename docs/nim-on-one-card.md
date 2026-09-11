# NVIDIA NIM on a single 15.92 GiB card

Measured on this box, 2026-08-20. Every figure here is either measured locally and labelled
so, or read off NVIDIA's own catalogue page and labelled so. There are no estimates.

## The question

Whether `nvcr.io/nim/qwen/qwen3-32b:1.0.0` — NVIDIA's Qwen3-32B NIM — can serve the chat
surface on this machine, under the house name Symon 1.0.

## The card

    NVIDIA GeForce RTX 5070 Ti    16303 MiB total    14910 MiB free    300 W limit

`nvidia-smi --query-gpu=name,memory.total,memory.free,power.limit`, 2026-08-20. The ~1.4 GiB
gap between total and free is the desktop session, and it is not recoverable while anyone is
logged in graphically.

## The answer: no, for three independent reasons

Any one of these is sufficient. They are listed in the order they were found, not by weight.

### 1. It does not fit

    $ NIM_MODEL=qwen3-32b ./scripts/nim-qwen36.sh preflight
      warn  this card has 16303 MiB against the 19000 MiB this profile is reported
      warn  to need; NIM selects a profile at startup and refuses when none fits

19000 MiB is the floor carried for the **27B**, whose NVFP4 profile is reported at ~18.6 GB.
Qwen3-32B has 19% more parameters, so its real requirement is higher and the comparison only
becomes more certain. The floor was deliberately not raised for the 32B, so that the check
cannot be accused of having been tuned to produce this refusal.

NIM selects an optimised profile at startup against the GPU it finds, and refuses when none
of them fits. That is the mechanism; it is not a soft warning that can be overridden with a
flag. Note also that the RTX 5070 Ti is **not** on NIM's GeForce support list, which names
the 5090, 5080, 4090 and 4080.

**20.74 GB is not a VRAM figure.** It is the compressed registry size of the image, which is
what the pull costs. Quantised weights are close to incompressible, so the uncompressed
layers are larger, and what the engine then allocates on the card is larger again once the
KV cache is reserved. The same trap applies to the 27B's 11.87 GB.

### 2. NVIDIA has stopped supporting it

The NGC page carries, verbatim:

> This artifact is no longer supported. NVIDIA strongly recommends artifacts that are up to
> date and supported.

The reason is architectural, and it is in NVIDIA's own migration notes. **NIM LLM 2.0 is one
container, one backend** — a dedicated vLLM container — replacing the 1.x design that bundled
vLLM, TensorRT-LLM and others behind a single image. `qwen3-32b:1.0.0` is a 1.x-generation
artifact, published 2025-08-20, digest `sha256:b1e15025885a…`, last refreshed 2026-02-16.

Its own Anchore scan, at that refresh: **493 findings — 0 critical, 21 high, 323 medium, 149
low.** The highs are the Ubuntu 24.04 / python3.12 userland rather than NVIDIA's inference
code: `CVE-2025-68973` across eight gnupg dpkg names, plus urllib3, starlette, aiohttp,
protobuf, sentencepiece, xgrammar, pillow, and setuptools' vendored wheel. A NIM is somebody
else's userland running on our card. On an unsupported artifact those numbers only grow.

### 3. It is not ours to redistribute

NIM is part of NVIDIA AI Enterprise. The container is governed by the NVIDIA Software License
Agreement plus the Product Specific Terms for AI Products; the weights by the NVIDIA AI
Foundation Models Community License Agreement.

This is the same class of constraint as Apple's Xcode SDK in `references/`: **licensed to use,
not to bundle.** No `.deb`, no `meta-symoneural-*` recipe, and no `Symoneural_backups` archive
may carry this image. Pulling it also requires an NGC API key, which is Garrett's credential
and is not held here — `podman login --get-login nvcr.io` reports not logged in, which is why
nothing has been pulled and nothing here has been scanned by us.

## What is actually installed

    backend/models/llm/symon-1.0-27b-q2_k_xl.gguf      11 849 779 424 B   opt-in
    backend/models/llm/symon-1.0-14b-q4_k_m.gguf  8 988 110 976 B   heavy tier
    backend/models/llm/symon-1.0-7b-q4_k_m.gguf   4 683 074 240 B   chat (api.py:142)
    backend/models/llm/symon-1.0-draft-0.5b-q4_k_m.gguf   397 808 192 B   draft
    backend/models/llm/symon-1.0-27b-vision-f16.gguf                     927 607 360 B   vision tower
    training/adapter-qwen36/adapter_model.safetensors       200 384 784 B   persona, 27B
    training/adapter/adapter_model.safetensors             161 533 192 B   persona, 7B

`du`, 2026-08-20. There is no 32B of any kind on this box, and `api.py:142` still names the
7B as `CHAT_MODEL`.

## The path that could work

The 27B's, which is the GGUF path: a Q2-class quantisation served by `contrib/llama.cpp`,
which already carries `LLM_ARCH_QWEN35` and can serve a LoRA adapter. That is how an 11.85 GB
27B came to run on a 15.92 GiB card at all.

Whether a **32B** GGUF clears this card with usable KV headroom is a measurement nobody here
has taken. Until it is taken, no figure for it appears on any page. The control board's
`32B @ IQ2 · ~78 tok/s · 9.6 GB` cell is marked `data-src="projected"`
(`tools/build_console.py:122`) and must stay marked that way.

## Two NIM features worth remembering, even though this one is refused

Both are from NVIDIA's NIM LLM 2.0 documentation, and both bear on us later:

- **Model-free NIMs** serve a model configured at runtime from NGC, Hugging Face, S3, GCS or
  a local directory, rather than a baked-in manifest. NVIDIA names our exact case — "custom
  trained or heavily fine-tuned models stored in your own infrastructure."
- **LoRA injection.** The `nim-llm` orchestration layer injects LoRA adapters. We have two
  trained adapters sitting on disk.

Neither changes the arithmetic. NIM LLM 2.0's engine is vLLM, and vLLM's memory model wants
to reserve a fraction of the card up front, which is the opposite of what
`scripts/gpu-governor.sh` exists to enforce here — hold the lock for a job, never for a
process lifetime. On one 15.92 GiB card shared by chat, image, train and ComfyUI, a resident
vLLM locks out everything else. That is the same reasoning that kept vLLM out before.

If the card changes, this changes. That decision belongs to `symoneural-invest`.

## Reproducing this

    ./scripts/nim-qwen36.sh preflight                    # the 27B, default
    NIM_MODEL=qwen3-32b ./scripts/nim-qwen36.sh preflight # the 32B

Neither pulls anything. Both fail on the missing NGC login before reaching the network, and
report the VRAM comparison anyway, which is the part that does not need an account.

The model table is pinned by `backend/apps/test_nim_models.py`.
