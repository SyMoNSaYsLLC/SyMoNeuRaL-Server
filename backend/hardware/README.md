# backend/hardware/

What the card and the host are actually doing. Readings, not control — the **lease** lives in
`scripts/gpu-governor.sh` and this component never takes it.

`/api/metrics/*` serves them: the live numbers, the static parts that never change, the model
parameters, and the overclock envelopes with a plan.

**No arithmetic on `nvidia-smi` CSV happens in shell.** It moved to Python after R-171 was
diagnosed out of exactly that. `lib/gpu.py` parses; the governor calls it and acts on the
answer.

Measured facts this surface reports, and what they mean: the card is **memory-bandwidth
bound**. Memory clock pins at 14,001/14,001 MHz (100%) while power sits at 227/300 W (76%).
Time per token is proportional to bytes read per token, so raising the power limit cannot
help this workload — a smaller quantisation can. `apps/overclock.py` reports the envelope
honestly rather than promising a gain it cannot deliver.

<!-- generated: do not edit below -->

## Operations — 6

|  | path | what it does |
|---|---|---|
| GET | `/api/metrics` | Everything in one object, for a cold page load or a `curl` on the box. |
| GET | `/api/metrics/live` | The fast-moving half: card, context, last request, CPU/RAM. Poll this on |
| GET | `/api/metrics/overclock` | SyMoNeuRaL Local Model Overclocking: the bounds, and the presets. Applie |
| GET | `/api/metrics/overclock/plan` | Three percentages in; the real limits and the exact commands out. **Runs |
| GET | `/api/metrics/params` | The model's generation parameters, and which of them this box will actua |
| GET | `/api/metrics/static` | The slow-moving half: fabric status, test inventory, benchmarks. Fetch o |

## Library — no routes, no side effects on import

| file |  |
|---|---|
| `gpu.py` | The lease's Python side. Currently one thing: telling the governor what it evicts. |
| `hostmetrics.py` | CPU, RAM and disk, read from this host. Same contract as `modelmetrics`: readings only. |
| `layer_probe.py` | Probe every reported endpoint at all four layers and print the route matrix. |
| `modelmetrics.py` | Real numbers about the model's work, read from the hardware and the engine. Never asserted. |
| `telemetry.py` | Reading the card. One nvidia-smi exec per second at most, shared by every caller. |

## Programs — runnable, or driven by a route

| file |  |
|---|---|
| `overclock.py` | SyMoNeuRaL Local Model Overclocking — GPU / CPU / RAM budgets for this box. |

## Documents

- [`HARDWARE-PROFILES.md`](docs/HARDWARE-PROFILES.md)
- [`RUNTIME-PROFILES.md`](docs/RUNTIME-PROFILES.md)
- [`cuda-audit.md`](docs/cuda-audit.md)
- [`nim-on-one-card.md`](docs/nim-on-one-card.md)
- [`symoneural-model-hot-swap.md`](docs/symoneural-model-hot-swap.md)

<!-- end generated -->
