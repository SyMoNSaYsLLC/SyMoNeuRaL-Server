# SyMoNeuRaL Model Hot Swap and Multi-Model Serving

**Status: proposed. Nothing here is implemented and this commit implements nothing.** Task #104
carries it.

**The thesis: a hot swap is a controlled SyMoNeuRaL operation, not manual process killing.**
Today "swap the model" means a person stops a surface and starts another. That works and it is
honest, but it cannot be queued, cannot be refused with arithmetic, cannot be attributed to an
account, and cannot be explained to a user. This document specifies the operation that
replaces it.

Companions: `backend/registry/docs/symoneural-runtime-registry.md` (who can serve),
`ops/docs/GPU-GOVERNOR.md` (who holds the card), `ops/docs/MODEL-REGISTRY.md` (what may be
loaded), `ops/docs/RUNTIME-PROFILES.md` (the maturity ladder).

---

## 1. Why this is not just "restart the service"

`ENGINEERING.md` fixes the constraint this whole document lives inside:

> One RTX 5070 Ti, 15.92 GiB. Chat (~5 GB), image (~7 GB) and a QLoRA run (~12 GB) cannot
> coexist.

So residency is a scarce, exclusive resource, and the interesting operations are all about
*taking it away from something*. The governor already owns the **process** lease and does it
crash-safely. What does not exist is a **model**-level layer above it: the governor knows about
surfaces, not about which weights are in VRAM.

**Both layers are required.** A model-accounting layer that bypasses the lease loses the
crash-safety; a lease without model accounting cannot answer "can I load this too?".

## 2. Required operations

| Operation | Contract |
|---|---|
| **load model** | Admission-checked *first* (§4). Returns the lease it took. |
| **unload model** | Explicit. Frees residency without killing the runtime where the runtime supports it. |
| **switch active model** | Unload + load as **one** operation, so there is no window where the surface is neither. |
| **pin resident model** | Exempt from eviction. A pin is a promise and therefore a cost. |
| **evict idle model** | By eviction priority (`MODEL-REGISTRY.md`), never a pinned one, and **never `train`** — `ENGINEERING.md` is explicit that training is not evicted to serve a page view. |
| **reject unsafe load** | With the arithmetic. A refusal that does not show its working is indistinguishable from a bug. |
| **queue when GPU is busy** | `queued` ≠ `rejected`. The card being busy is not the job being impossible. |
| **report status** | What is resident, what is pinned, what is queued. |
| **report memory pressure** | Compute memory, not whole-card — the whole-card figure includes this box's desktop session (R-171). |
| **report runtime health** | Per `RUNTIME-PROFILES.md`'s `health_endpoint`. |

**Every one of these is refusable.** An operation that cannot say no is not a manager, it is a
trigger.

## 3. Six mechanisms, deliberately distinguished

Collapsing these is how "hot swap" becomes a word that means nothing. They are not
alternatives to pick between once; a given runtime supports some and not others, which is what
`hot_swap_support` and `multi_model_support` record.

| Mechanism | Means | Where it fits |
|---|---|---|
| **Multiple models resident at once** | Two sets of weights in VRAM simultaneously | Needs measurement on a 16 GB card. **Not assumed.** |
| **Multiple runtime processes** | Two servers alive, each with its own model | Cheap to reason about, expensive in VRAM |
| **Runtime-native dynamic loading** | The runtime loads/unloads without restarting | `hot_swap_support: native` |
| **Service-restart-based swapping** | Stop, start with different weights | `hot_swap_support: restart`. What effectively happens today. |
| **Queue-controlled on-demand loading** | Load when a job arrives, unload when idle | The default for `on_demand` models |
| **Pinned resident models** | Never evicted while pinned | The exception, priced accordingly |

Eviction of idle models is the policy that makes on-demand loading survivable; without it the
first model to load holds the card forever.

## 4. The owner profile — `rtx5070ti-16gb`

Named per Garrett unless the audit dictates otherwise; the audit confirms the hardware matches
(RTX 5070 Ti, 16303 MiB, driver 610.57.04, CUDA 13.3), so **the name stands.**

Non-negotiable on this profile:

- **No CPU fallback for GPU workloads unless explicitly authorized.** The audit confirms the
  code has none today: all eight CPU-device sites are in `training/` and are deliberate shard
  offload, not fallback.
- **VRAM admission is mandatory**, not advisory. Refused before admitting, with the sum.
- **Large image + large LLM concurrency is not assumed.**
- **Multi-model residency must be measured before it is called green.** Until a stamped record
  exists, `multi_model_support` is `unknown` — which is a legitimate value and the honest one.

### The stale-marker precedent, which this design must not regress

`run/resident` currently reads `image` while **no image process exists**, and
`gpu-governor.sh status` says so in the same breath: `image (not running -- stale marker)`.
That is R-172's fix working, and `scripts/SMOKE-governor-evict.md` records what it was like
before — evictions that reported success having freed nothing.

**The lesson for the hot-swap manager: a residency record is a claim about the world and must
be reconciled against the process table, not trusted.** `report status` reads the card; it does
not read its own bookkeeping and call that a reading.

## 5. Planned API shape

**Planned. None of these exists.** See `symoneural-runtime-registry.md` §4 for the full list
and for the prefix collision that must be resolved first.

```
GET  /api/runtimes/status     resident, pinned, queued, memory pressure, health
POST /api/runtimes/load       {runtime_id, model_id, pin?}   -> allowed | queued | rejected
POST /api/runtimes/unload     {runtime_id, model_id}
POST /api/runtimes/switch     {runtime_id, from_model_id, to_model_id}   -- one operation
```

`POST /api/models/resolve` answers "what *would* happen" without doing it — the router decision
as a dry run, which is what a Studio node needs to render a badge before the user commits.

## 6. What a green implementation must prove

Tests, or a stamped smoke record beside the code. **None of these can pass on a surface that
was never run** — which is the point, per `.claude/CLAUDE.md` on #94 and #74.

- a load that does not fit is **rejected with its arithmetic**, before admission
- a load while the card is busy comes back `queued`, not `rejected`
- `switch` leaves no window in which neither model is serving
- a pinned model is not evicted, and `train` is not evicted at all
- `report status` disagrees with a deliberately falsified residency record, and reports the
  **card**, not the record
- unloading frees compute memory below the drain floor before the next tenant is admitted
- no path reaches a CPU device for a GPU job on the owner profile
- a runtime whose `maturity` is below `built` is refused **by level**, naming it
