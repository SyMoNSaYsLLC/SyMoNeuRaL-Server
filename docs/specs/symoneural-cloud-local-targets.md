# SyMoNeuRaL Cloud and SyMoNeuRaL Local — the two execution targets, and their resolver states

**Scope captured 2026-08-22.** Docs only. **AUDIT until scoped. No implementation, no capacity
claim, no pricing.**

Execution and deployment targets, named explicitly so a migration cannot erase them.
`symoneural-studio-upgrade-scope.md` §5 holds the four-target model (`CLOUD`, `LOCAL_CUSTOMER`,
`LOCAL_OWNER_NVIDIA`, `AUTO`); this file is the Cloud and Local halves in their own right, with
the resolver vocabulary.

## 1. SyMoNeuRaL Cloud

> **The hosted execution target: the customer uses symoneural.com and a SyMoNeuRaL server GPU
> runs the job.**

The customer **never sees** raw GPU, raw CUDA, a filesystem, ComfyUI, or model weights.
Execution goes through accounts, credits, queue and rate limits.

### What must be true, and what must never be said

**It uses the existing machinery, not a parallel one:** queue · credits · account gates · rate
limits · model registry · runtime registry · GPU governor. Plus **job and result isolation
between users**, and **only safe product/API surfaces exposed**.

**Forbidden claims, all of them, until proven:** production cloud capacity · an SLA · pricing ·
unlimited or multi-user hosting.

**The reason is measured, not cautious.** `api.py:1391-1396` states the box: one RTX 5070 Ti,
15.92 GiB, chat and image weight sets do not both fit, so exactly one holds the card and the
others queue. **This is demonstration hardware.** "Cloud" today describes *where the job runs
relative to the customer* — not a fleet. A capacity claim would be a claim about hardware that
does not exist.

### Resolver states

`CLOUD_ALLOWED` · `CLOUD_RECOMMENDED` · `CLOUD_REQUIRED` · `CLOUD_UNAVAILABLE` · `QUEUED` ·
`REJECTED_WITH_REASON`

`CLOUD_UNAVAILABLE` and `REJECTED_WITH_REASON` are the load-bearing two: **a target resolver that
cannot say no, with a reason, is a resolver that says yes to things that will fail.** Every
rejection carries a reason string and, per the node contract, the docs/API links for the
decision.

## 2. SyMoNeuRaL Local

> **The customer's own machine runs the model — and the browser cannot reliably know whether it
> can.**

### The honest problem, stated first

**Browser-only hardware detection is approximate.** A page cannot see VRAM, driver version, CUDA
availability or disk headroom with any reliability. **Real detection requires a local helper —
agent, CLI, or desktop companion.**

That helper does not exist. Measured 2026-08-22: **there is no local-agent directory in this
repo.** So *"SyMoNeuRaL Local works"* is not a claim that can be made today, and the resolver
must be able to say exactly that instead of guessing.

**`bin/symoneural-cli` is the nearest thing that exists** — 1,809 lines, with a `status`
subcommand reporting device and lock state (`symoneural-coder-project-cli-scope.md` §3). Whether
the local agent *is* the CLI, wraps it, or is separate is an open design question and is not
decided here.

### What a local report must carry

OS · CPU · RAM · GPU vendor and name · VRAM · CUDA / ROCm / Metal · driver versions · Python and
runtime versions · model paths · disk headroom · permissions.

### Rules

- **Do not claim local execution works without local-agent proof.**
- **Unsupported local workflows recommend Cloud — they do not silently fall back to CPU.** This
  is the no-silent-CPU-fallback rule at the routing layer (`BOX-REALITY-AUDIT.md` §2.2, and it is
  PROD: the code already has none). A silent CPU fallback for a GPU workload turns a clear
  "your machine cannot do this" into a render that takes forty minutes.
- **RavenCalc is not an exception to that rule, because it was never in scope for it.** Its CPU
  use is by design, not a downgrade (`BOX-REALITY-AUDIT.md` §10.4).
- **Local still enforces provenance, both registries, and the safety gates.** Running on the
  customer's hardware does not relax licence or provenance obligations.
- **Local filesystem access is gated and rooted** if any local-agent or developer tool is exposed
  — same posture as Coder: enable flag, token, workspace root, `resolve()`-based containment,
  denylist on the resolved path (`symoneural-coder-project-cli-scope.md` §4).

### Resolver states

`RUNS_LOCAL` · `NEEDS_LOCAL_AGENT` · `NEEDS_MODEL_DOWNLOAD` · `NEEDS_DRIVER_RUNTIME` ·
`CLOUD_RECOMMENDED` · `UNSUPPORTED`

**`NEEDS_LOCAL_AGENT` is the current default answer for any browser-only visitor**, and saying so
is more useful than an approximate guess dressed as a capability check.

## 3. The two together

`AUTO` resolves between them using hardware profile, model and runtime metadata, current GPU
state, queue state, and account/credit/permission state — `symoneural-studio-upgrade-scope.md`
§6, and the hardware badges in its §8 (`RUNS_LOCAL`, `CLOUD_RECOMMENDED`, `UNSUPPORTED`,
`OWNER_GPU_ONLY`, `NEEDS_LOCAL_AGENT`, `NEEDS_MODEL_DOWNLOAD`, `NEEDS_DRIVER_RUNTIME`).

**`LOCAL_OWNER_NVIDIA` is a third case and is not the same as either.** It is Garrett's own box —
a *known* hardware profile rather than one detected per visit, named `rtx5070ti-16gb` unless the
audit dictates otherwise, on the same queue contract as cloud but marked owner/local. It is the
only one of the three whose hardware is measured rather than reported.

## 4. What would promote these from AUDIT

| To claim | Proof required |
|---|---|
| Cloud is a real target | queue + credits + account gate + isolation, each tested, and a job that runs end to end without the customer seeing a path |
| Cloud has capacity | measured concurrency on real hardware. Not available on one card |
| Local is a real target | a local agent that exists and returns a real hardware report, plus a job that runs from it |
| `RUNS_LOCAL` is trustworthy | agreement between the agent's report and what the job actually did |

## 5. Not authorized

No cloud or local implementation · no local agent built · no queue, credit or account change · no
pricing or SLA statement anywhere · no capacity claim · no resolver code · no folder migration ·
no deploy.
