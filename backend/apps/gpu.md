# `gpu.py` and `telemetry.py` — the lease's Python side, and the card reading

One document for both, per the one-`.md`-per-folder rule: they were extracted together, in one
commit, from `backend/api.py`.

## What is here

| module | subject | lines |
|---|---|---|
| `gpu.py` | the lease's Python side. Today: `record_engine`, which tells the governor which pid actually holds the card so eviction can signal it by identity rather than by `pkill -f` | 72 |
| `telemetry.py` | reading the card. One `nvidia-smi` exec per second at most, shared by every caller, plus the driver-fault classification that rides along in the same call | 182 |

Two modules rather than one because they answer different questions — the lease says *who may
touch the GPU*, this says *what the GPU currently reports* — and because the 500-line rule was
applied **before** writing rather than after: the lease plus the card reading plus the drain
arithmetic still in `scripts/gpu-governor.sh` does not fit one file.

## What did NOT come, and it is a sequencing finding

**`class GpuQueue` could not be extracted.** It calls `bus.announce()` (`api.py:996`),
`push_rack()` (`api.py:2804`) and `run()`, and `push_rack` calls `build_status()` — which is
the rack, and the rack is most of `api.py`.

Moving it means either dragging the rack out, which is `SPLIT-API` stage 1's job, or injecting
three callables into its constructor, which changes the call site this extraction was required
not to change. **So `GpuQueue` extraction is blocked behind the rack's extraction**, not behind
anything in these two modules.

## The trap this move walked into, recorded so the next extraction does not

`api.py` binds `gpu = GpuQueue(QUEUE_DEPTH)` at `:865`. Importing the new module as
`from apps import gpu` therefore **shadowed it**, and `gpu.record_engine(...)` resolved to the
queue instance — an `AttributeError` at the next engine spawn, on a code path that runs only
when an engine starts.

`import api` succeeded anyway, and so did the suite. It was caught by asking the imported
module for the attribute rather than treating a successful import as proof of correct wiring.
The fix is to import the function by name — `from apps.gpu import record_engine` — which also
leaves the call sites byte-identical to what they were before the move.

**A name that is already a module-level binding in the importing file is not available as a
module alias.** `SPLIT-API` will hit this again: `project`, `live`, `studio` and `voice` are
all both an app package and a plausible local variable.

## What stays in bash, and why it is not sentiment

`scripts/gpu-governor.sh` keeps the lock. `mkdir` is the atomic primitive, so there is no
correctness gain available in another language; it has no runtime dependency, on a box whose
serving path deliberately uses system dist-packages; it survives `api.py` being dead, which a
governor inside that process cannot; and it is **proven** — 46 samples, 0 two-holder, 0
two-resident, negative control red on 25 of 27. Re-proving that is the expensive part, not
rewriting the code.

## Still not recorded anywhere

`scripts/gpu-governor.sh` has **no row in `ops/RUNTIMES.tsv`** — the one runtime nothing
records while it arbitrates every other. That is why `backend/SMOKE-lease-503.md` could not
move to a folder of its own. Not resolved here, and not widened into this commit to reach it.
