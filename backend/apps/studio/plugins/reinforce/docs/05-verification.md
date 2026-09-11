# 05 - Verification record

What was proven by execution, what was carried over untested, and the environment provenance.

> Part of the [symoneural_reinforce documentation set](README.md). Sliced from the consolidated manual at `../../../../docs/symoneural-manual.md`, which remains the canonical single file.

# Appendix B — What was and was not verified

## Verified by execution

- **All 33 CUDA Python samples were run on this machine.** 32 completed
  successfully; `simpleP2P` waived because the box has one GPU, which is the
  sample's designed behaviour on such a system.
- Every number in the Part II matrix, in every *On this box* block, and in Part I
  traces to a captured log. The raw logs are in the session scratchpad under
  `runlogs/` and `captures/`.
- Repository-layout claims (`Samples/` → `cpp/`, `bandwidthTest` absent, CMake
  build, prebuilt binaries) were confirmed by listing the filesystem.
- Dependency conflicts were confirmed by building the four isolated environments
  and running the affected samples in them.
- The numpy 2.5.2 → 2.4.6 downgrade was confirmed by diffing `pip freeze` before
  and after.

## NOT verified — carried over from the original playbooks

These claims were in the source documents and are reproduced unchanged. **No
attempt was made to test them in this pass**, and they should be treated as the
original author's assertions:

| Playbook | Unverified content |
|---|---|
| 01 | The hardware comparison table (4090 / 3060 / M4 Max / DDR5 / Pi 5 figures); the quantization bytes-per-param constants; the `llama-bench` workflow |
| 03 | **The entire engine comparison.** No engine was installed. llama.cpp, vLLM, Ollama and TensorRT-LLM numbers and claims are all untested here |
| 04 | LoRA/QLoRA/DPO procedures and any implied throughput |
| 05 | The distillation pipeline and filtering yields |
| 06 | KV-quantization quality claims; prompt-caching behaviour |
| 07 | Speculative-decoding speedup figures (2–4x) |
| 08 | Embedding-model recommendations; chunking defaults |
| 09 | Agent-loop and routing claims |
| 10 | All edge-hardware claims (Pi, Jetson, phones, BitNet) — no edge device involved |

## Inferred, not directly measured

- **The predicted decode-speed table in Part I** applies the bandwidth formula to
  the measured 752 GB/s. The bandwidth is measured; the tok/s figures are arithmetic
  from it, not observed inference runs.
- **"Model does not fit" thresholds** come from parameter-count arithmetic against
  15.9 GiB, not from attempting to load those models.
- **The suggestion that the card might be in a chipset rather than CPU-direct slot**
  is a hypothesis. What is measured is `Host Max: 3` and a link that trains to Gen 3
  x8 under load. The cause was not investigated.

## Environment provenance

**The base venv `$CUDA_SAMPLES/python/.venv` is pristine and contains exactly the
original 7 packages.** Verified by `pip freeze` diff against the pre-work snapshot:

```
cuda-bindings==13.3.1   cuda-core==1.0.1      cuda-pathfinder==1.6.0
cuda-python==13.3.1     cupy-cuda13x==14.1.1  numpy==2.5.2
pillow==12.3.0
```

Full disclosure of how that came to be, since it affects how much you should trust
the run results:

- During the first pass, the extras (`cuda-cccl`, `nvtx`, `numba-cuda`, `torch`,
  `mpi4py`) **were** installed into the base venv, which downgraded numpy
  2.5.2 → 2.4.6 via `numba-cuda`'s `numpy<2.5` pin.
- The venv was subsequently **wiped and rebuilt** from the pre-work `pip freeze`
  snapshot. It now matches the original byte-for-byte in package terms, and
  `vectorAdd` was re-run against it to confirm it still works.
- The 9 affected samples were then **re-run from `$VENVS/venv-extras`**, an
  isolated environment outside the project tree. All 9 passed again. The results
  quoted in this document for those samples come from those isolated re-runs, so
  every documented recipe is one that was actually executed as written.

Isolated environments used, all outside the repository:
`venv-extras`, `venv-nvmath`, `venv-rapids`, `venv-ckpt`, `venv-tf`.

To check the base venv has not drifted:

```bash
$CUDA_SAMPLES/python/.venv/bin/pip freeze | wc -l    # expect 7
```

---

*Generated 2026-08-16. Sources: the eleven playbooks in this directory and the 34
READMEs under `cuda-samples/python/`, merged in full.*
