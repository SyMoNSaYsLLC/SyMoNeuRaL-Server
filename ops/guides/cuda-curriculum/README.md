# `ops/guides/cuda-curriculum/` — CUDA, in order

```
1_GettingStarted.md  2_CoreConcepts.md  3_FrameworkInterop.md
4_DistributedComputing.md  Utilities.md
```

Reference for the kernel work under
`backend/studio/plugins/reinforce/symoneural/compute/`, which is **hand-written CUDA C++
compiled at runtime by NVRTC** — not a wrapper over a third-party runtime. Every arithmetic
operation there executes in a kernel written as a C++ source string.

Target hardware is one card: RTX 5070 Ti, Blackwell `sm_120`, 15.92 GiB. `4_Distributed` is
read for the concepts; there is no second GPU here and the P2P tests are waived for that
reason rather than skipped quietly.
