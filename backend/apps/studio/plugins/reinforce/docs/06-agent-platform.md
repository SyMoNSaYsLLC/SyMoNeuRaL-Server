# 06 — The ten-agent platform

> Part of the [symoneural_reinforce documentation set](README.md).

The platform coordinates ten autonomous agents behind one orchestrator. This
document covers the roster, the routing policy, the generated system prompt, and
the checkpoint-custody hooks — and states plainly which parts are implemented
and which are stubs.

## What is built and what is not

Read this table before building on anything here.

| Component | Status |
|---|---|
| Agent registry, roles, tiers, dependency graph | **Implemented**, 45 tests |
| Residency planner (VRAM budgeting) | **Implemented**, derived from live free memory |
| Routing engine (workload → agent, with degradation) | **Implemented** |
| Orchestrator system prompt | **Implemented**, generated from live hardware |
| Checkpoint sealing (Fernet and AES-256-GCM) | **Implemented**, round-trip and tamper tests |
| Verify-before-decrypt ordering + audit trail | **Implemented** |
| HTTP endpoints for all of the above | **Implemented** |
| **TRON TVM licence client** | **STUB** — `DenyAllVerifier` denies everything. No chain RPC, no contract address, no keys. |
| **Akash GPU leasing client** | **STUB** — the agent is declared; no network client exists. |
| **QLoRA fine-tuning execution** | **STUB** — the orchestrator agent is declared and routable; no training loop is implemented. |
| **Actual 1.5B / 7B / 14B models** | **Not present.** Tiers are budgeting abstractions. The engine ships a synthetic micro-MLP, not a language model. |

The routing and budgeting logic is real and testable today. The external
integrations are interfaces waiting for clients.

## The ten agents

Grouped by plane. Order is stable in `symoneural/agents/registry.py`.

### Data plane

| Agent | Tier | Handles | Why this tier |
|---|---|---|---|
| `telemetry-ingest` | none | telemetry | Highest request rate (~5000/s nominal). Kept model-free so a busy GPU can never stall ingestion. |
| `telemetry-classify` | 1.5B | classify | The canonical specialist case — short in, short out, latency over depth. |
| `telemetry-summarise` | 7B | generate, extract | Batch-friendly and latency-tolerant, so it queues rather than triggering an eviction. Marked non-interactive. |

### Control plane

| Agent | Tier | Handles | Why this tier |
|---|---|---|---|
| `akash-lease` | none | control | Lease negotiation is IO, not inference. **Stub.** |
| `capacity-planner` | 1.5B | classify, control | Local-vs-leased placement. Consumes the hardware dossier; the 7 GB/s PCIe ceiling dominates every offload decision. |
| `tron-licence` | none | verify, control | Entitlement checks are cryptographic, not linguistic. **Stub, denies by default.** |

### Model plane

| Agent | Tier | Handles | Why this tier |
|---|---|---|---|
| `weight-custodian` | none | verify | Holds sealed checkpoints; unseals only after a positive verification. |
| `finetune-orchestrator` | 14B | train, reason | The only agent that legitimately wants the heavy tier and sustained exclusive VRAM. **Non-interactive** — scheduled, never served on demand. |

### Safety net

| Agent | Tier | Handles | Why this tier |
|---|---|---|---|
| `state-verifier` | none | verify, telemetry | Append-only audit records. Model-free so the audit trail survives GPU exhaustion — a log that fails under load is useless. |
| `fallback-router` | 1.5B | *all* | Absorbs work when a preferred agent is saturated, evicted or unhealthy. Always sorts last among candidates. |

## The constraint that shapes everything

Ten agents cannot all hold a model. The numbers, measured on this box:

| | |
|---|---|
| Total VRAM | 15.9 GiB |
| Typical free | ~14.2 GiB |
| KV/activation reserve | 35% of free |
| 1.5B @ Q4 | ~0.9 GB |
| 7B @ Q4 | ~3.9 GB |
| 14B @ Q4 | ~7.7 GB |

With ~10 GiB of weights budget, **1.5B + 7B** fits with ~4.5 GiB to spare;
1.5B + 7B + 14B does not.

### Why eviction is the enemy

Loading a model crosses PCIe, which this host caps at **Gen 3 x8, ~7 GB/s
measured**:

| Tier | Load time |
|---|---|
| 1.5B | ~138 ms |
| 7B | ~598 ms |
| 14B | ~1,181 ms |

A 7B load alone exceeds a 500 ms interactive budget. Once resident, the same
weights are read at ~752 GB/s — a **107× gap** between resident and
non-resident access.

That single ratio produces the entire routing policy.

### Residency planning is greedy by traffic share, not by size

An earlier version picked the largest model that fit and produced
**1.5B + 14B** — leaving the *default* 7B tier non-resident, so every ordinary
`generate` request degraded to the specialist. Technically no eviction; wrong
answer for the common case.

The planner now prefers, in order:

1. **1.5B always** — it is the fallback target. If it must be paged in *during*
   a fallback, the fallback itself stalls.
2. **7B next** — the documented default, serving the largest traffic share.
3. **14B only if all three fit.**

## Routing policy

`Router.route(workload, latency_budget_ms, allow_evict)` returns a `Decision`
carrying the chosen agent, the tier, whether it degraded, whether it would
evict, and **a reason string**. A router that cannot explain itself cannot be
debugged.

Order of consideration:

1. **Preferred agent, resident and available** → clean hit.
2. **Pay for the preferred agent** — only when `allow_evict=True`, the request
   is non-interactive, *and* the swap fits the budget.
3. **Any other resident, available agent** → reported as **degraded**.
4. **`fallback-router`** → degraded.

Two rules are absolute:

- **A budget at or below 500 ms marks the request interactive, and an
  interactive request never evicts** — regardless of `allow_evict`. The swap
  alone would blow the budget.
- **Settling for a less-specialised agent is a degradation and is reported as
  one.** An earlier version returned `degraded=False` when it quietly fell back
  to the 1.5B specialist. A silent downgrade is a correctness bug, not an
  optimisation — the orchestrator prompt says so, so the router must not commit
  one.

Observed behaviour with `1.5B + 7B` resident:

```
classify     200ms evict=False -> telemetry-classify     [1.5b ] clean
generate    2000ms evict=False -> telemetry-summarise    [7b   ] clean
generate     200ms evict=False -> fallback-router        [1.5b ] DEGRADED
reason     60000ms evict=False -> fallback-router        [1.5b ] DEGRADED
reason     60000ms evict=True  -> finetune-orchestrator  [14b  ] EVICT+1181ms
train        500ms evict=True  -> fallback-router        [1.5b ] DEGRADED
telemetry     50ms evict=False -> telemetry-ingest       [none ] clean
verify       100ms evict=False -> weight-custodian       [none ] clean
```

## The orchestrator system prompt

**Generated, not stored.** Every hardware figure is read from the device at call
time, so the prompt cannot drift from reality the way a pasted spec sheet does.
Move the code to another GPU and the prompt describes that GPU.

```python
from symoneural.agents import build_system_prompt
from symoneural.core.context import DeviceContext
print(build_system_prompt(DeviceContext(0)))
```

Or over HTTP: `GET /v1/prompt` (~6,300 characters).

Sections:

1. **Role** — you orchestrate, you do not perform work.
2. **The machine** — live VRAM, SM count, both bandwidths, and the resident-vs-PCIe ratio stated explicitly.
3. **Residency and switching cost** — current plan, per-tier swap costs, and four rules: prefer resident, never evict for latency-sensitive work, batch instead of switching, keep the specialist loaded.
4. **How to delegate** — the five-step rule, with an instruction to state the chosen agent and to declare any degradation.
5. **Protected checkpoints** — route through the licence agent, deny on failure, never route around the check.
6. **The roster** — all ten agents, one line each.
7. **Reporting** — name the constraint that stopped you.

The batching guidance in section 3 cites measured numbers: batch 1 → 3,200
rows/s, batch 64 → 151,000 rows/s. A **47× gain from batching alone**, because
the work is bandwidth-bound and one pass over the weights serves the whole
batch.

## Checkpoint custody

### Two accuracy corrections

**Fernet is not AES-256.** Fernet is AES-128-CBC with PKCS7 padding,
authenticated by HMAC-SHA256. Its 32-byte key is *split* into a 16-byte signing
key and a 16-byte encryption key. The "AES-256 Fernet" shorthand is common and
wrong. Both are provided:

| Class | Algorithm |
|---|---|
| `FernetSealer` | AES-128-CBC + HMAC-SHA256 |
| `Aes256GcmSealer` | AES-256-GCM (genuine 256-bit) |

Use `Aes256GcmSealer` if a compliance requirement names AES-256.

**This protects checkpoints at rest, not in use.** Once weights are unsealed
into VRAM, anyone who can attach a debugger to the process, read
`/proc/<pid>/mem`, or run code on the GPU can recover them. That is a property
of executing a model at all, not a gap in this implementation. What you get is
a meaningfully higher cost for casual copying, plus an audit trail. Do not
describe it to end users as preventing extraction.

### The control is the ordering

`WeightCustodian.unseal()` calls the verifier **before** touching ciphertext and
raises `LicenceError` on denial without decrypting anything. There is a test
that spies on the sealer to prove decryption never runs on a denied path.

```python
from symoneural.agents import Aes256GcmSealer, WeightCustodian, DenyAllVerifier

sealer = Aes256GcmSealer(Aes256GcmSealer.generate_key())
cust = WeightCustodian(sealer=sealer, verifier=DenyAllVerifier())
cust.unseal("model-1", "user-1", blob)      # raises LicenceError
```

`DenyAllVerifier` is the default deliberately. A stub returning `granted=True`
would silently disable the whole control the moment someone forgot to configure
a real verifier.

To make it live, implement the `LicenceVerifier` protocol:

```python
class TronTvmVerifier:
    def verify(self, checkpoint_id: str, subject: str) -> Entitlement:
        ...   # your chain client here
```

Denials are audited as carefully as grants — a log of successes alone tells you
nothing about attacks.

## HTTP API

| Endpoint | Purpose |
|---|---|
| `GET /v1/agents` | Roster plus the live residency plan |
| `GET /v1/prompt` | Orchestrator system prompt + hardware facts |
| `POST /v1/route` | Choose an agent for a workload |
| `GET /v1/route/residency` | Residency plan and per-tier swap costs |
| `GET /v1/route/stats` | Decisions, degradations, evictions avoided |
| `POST /v1/checkpoint/seal` | Encrypt a checkpoint |
| `POST /v1/checkpoint/unseal` | Verify then decrypt — **403** on denial |
| `GET /v1/checkpoint/audit` | Append-only unseal record |

```bash
curl -s -X POST localhost:8000/v1/route \
  -H 'content-type: application/json' \
  -d '{"workload":"generate","latency_budget_ms":2000}'
```

> The seal endpoint generates an **ephemeral** key it does not return, so blobs
> cannot be unsealed later. It demonstrates the envelope; it is not a
> key-management service.

## Related

- [01 — Hardware dossier](01-hardware-dossier.md) — where every figure here comes from
- [02 — Setup and environments](02-setup-environments.md)
- [05 — Verification record](05-verification.md)
