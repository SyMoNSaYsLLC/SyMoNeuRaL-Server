# scripts/docs/ — how the operational scripts work

Documents that belong to `scripts/`, not to a surface. Right now that is one:

- [`GPU-GOVERNOR.md`](GPU-GOVERNOR.md) — the lease protocol: acquire, evict, drain, release,
  and what each refusal means.

## Why the governor has a document and the other scripts do not

Every other script here does one thing and says so in its header. The governor is a
**protocol** between four processes that never talk to each other — the API, the diffuse
engine, the miner and the training bay — and a protocol cannot be explained in the file that
implements one side of it.

Read it before changing anything that takes the card. The two facts that catch people:

- **release drains.** It waits for VRAM to fall below `DRAIN_FLOOR_MIB` before unlocking,
  because a CUDA context that has not finished tearing down still holds memory the next
  surface would allocate into.
- **a training run is never evicted.** Everything queues behind it. That is architectural.

Anything about a *surface* goes in that component's `docs/`, not here.
