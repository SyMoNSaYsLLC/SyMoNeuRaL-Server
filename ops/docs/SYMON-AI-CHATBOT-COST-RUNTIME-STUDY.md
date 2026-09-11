# SyMon AI chatbot — cost and runtime study

**Read at `03eba142`, 2026-08-24. Study only — nothing here activates, changes or enables
anything.** The default model is unchanged and remains the Qwen-lineage local weight. gpt-oss
is candidate-only and is not activated by this document.

> **Labels.** Every figure below is marked **measured** (read off this box, with the date),
> **projected** (arithmetic done here from a measured input), or **placeholder** (a value that
> does not exist yet and must not be invented). The repo rule is that a projection is never
> presented as a result.

> **Naming.** Customer-facing copy says **SyMon AI**. Model lineage names appear in this file
> because it is an internal ops document; they do not belong on a public page.

---

## 1. Current repo runtime inventory

### Chat entrypoints

| Path | Where | Notes |
|---|---|---|
| `POST /api/chat` | `backend/server.py:2479` | The chat surface. Streams SSE deltas; final event carries `tokens`, `seconds`, `tok_per_s`, `model`, `adapter` |
| `GET /api/status` | `backend/server.py:2291` | Live rack state, including whether the chat surface is up |
| `GET /api/ws` | `backend/server.py:2319` | WebSocket status feed |
| `POST /v1/chat/completions` | gateway, `src/router.rs:54` | OpenAI-**compatible** surface we *serve*. Not an outbound call |

### Model paths and config names

| Constant | Value | Source |
|---|---|---|
| `CHAT_MODEL` | `backend/models/llm/symon-1.0-7b-q4_k_m.gguf` | `api.py:187` |
| `DRAFT_MODEL` | `backend/models/llm/symon-1.0-draft-0.5b-q4_k_m.gguf` | `api.py:266` |
| `CHAT_ADAPTER` | `training/adapter/symoneural-lora.gguf` | `api.py:188` |
| `CHAT_MODEL_LABEL` | `SymonChat S1-7B` | `api.py:194` — the product label, pinned to the weight |
| `LLAMA_PORT` | `8081`, loopback only | `api.py:284` |

The adapter is applied **conditionally**: `adapter_applies()` compares GGUF architectures and
refuses a mismatch rather than letting llama-server fail at load. If it is on disk but not
applicable the code logs a warning loudly, because the alternative is a surface that quietly
serves without its persona.

### Environment flags

**Chat itself reads almost nothing.** `api.py` calls `getenv` for exactly two names —
`SYMONEURAL_PORT` and `SYMONEURAL_CODER_TOKEN` — plus the rate-limit family built by f-string:

```
SYMONEURAL_RATE_CHAT=<per-minute>/<per-hour>     # unset means UNLIMITED
```

Surface enablement flags that exist (`scripts/enable-surfaces.sh`):
`SYMONEURAL_ACCOUNTS_TOKEN`, `SYMONEURAL_ASIC_ENABLED`, `SYMONEURAL_ASIC_RIGS`,
`SYMONEURAL_ASIC_TOKEN`, `SYMONEURAL_CODER_ALLOW_REMOTE`, `SYMONEURAL_GATEWAY_CONTRACT`,
`SYMONEURAL_GATEWAY_ENABLED`, `SYMONEURAL_GATEWAY_NETWORK`, `SYMONEURAL_LIVE_ENABLED`,
`SYMONEURAL_MINER_CMD`, `SYMONEURAL_NEWS_ENABLED`, `SYMONEURAL_PROJECT_TOKEN`,
`SYMONEURAL_RACK_ALLOW_REMOTE`, `SYMONEURAL_SESSION_SECRET`, `SYMONEURAL_STUDIO_TOKEN`.

Accounts family (`apps/accounts/__init__.py`): `SYMONEURAL_ACCOUNTS_ENABLED`,
`SYMONEURAL_ACCOUNTS_DB`, `SYMONEURAL_SESSION_SECRET`, `SYMONEURAL_SESSION_TTL_S`.

> **Finding — there is no `SYMONEURAL_CHAT_ENABLED`.** Live, News, ASIC and Gateway each have
> an enablement flag; chat does not. **Chat is on whenever the API process is up.** There is no
> switch to turn the chatbot off without stopping the whole API, and no gate to put in front of
> commercial enablement. That is unbuilt work, and it is a hard gate in §5.

### Local, API-backed, or mixed?

**Local only, unambiguously.** `start_llama()` (`api.py:1228`) spawns llama-server as a
subprocess bound to `127.0.0.1:8081` with `-ngl 99` — every layer on the GPU.

Searched for an outbound hosted-LLM client across product code. Six files mention
OpenAI/Anthropic; **all six are about the OpenAI-compatible wire format served locally**, not
a call to a hosted provider (`api.py:1303` — *"Yield content deltas from llama-server's
OpenAI-compatible endpoint"*; `symon_client.py:2` — *"Zero-dependency client for a Symon
inference server (llama.cpp-compatible)"*).

> **There is no hosted path in this repository.** Hosted is not a flag to flip; it is
> greenfield work — a client, key handling, error mapping, cost accounting and a fallback
> policy that do not exist.

### Queue and GPU assumptions

The GPU is a **single contended resource**. `/api/chat` takes `gpu.hold("chat")` **in the
handler, not in the generator** — R-173 records why: Starlette sends `200 OK` the moment a
`StreamingResponse` is returned, so a lease acquired later could only abort the connection.
Acquiring first means a full queue is an ordinary **503 with a readable body**.

Encoded GPU assumptions, from the `start_llama()` argv and its comments:

| Assumption | Value | Status |
|---|---|---|
| All layers on GPU | `-ngl 99` | **No CPU fallback path exists** |
| Total context | `-c 65536` | split by `-np 2` → 32,768 per slot |
| Concurrent slots | `-np 2` | two in-flight chats |
| Continuous batching | `-cb` | **measured** 47.3× from batch 1 to batch 64 |
| Resident VRAM | **9,485 MiB of 16,303** | **measured 2026-08-17**; idle baseline 1,084 MiB → chat ≈ **8.2 GiB**, 6.6 GiB free |
| Card | RTX 5070 Ti, 16,303 MiB | measured |

### Free / commercial / account / credits flags

- **Accounts exist** and are flag-gated (`SYMONEURAL_ACCOUNTS_ENABLED`).
- **Metering exists** — `apps/accounts/meter.py`, reserve-then-resolve with holds, a ledger and
  `sweep_stale()`. The design note is explicit about why the balance is debited at hold time
  rather than on success: charging on success is a time-of-check/time-of-use hole that lets one
  account start twenty concurrent jobs against a balance none of them has spent.
- **Chat is not wired to it.** `/api/chat` depends on `throttled_for("chat")` and takes a GPU
  lease. It does **not** call the meter. Chat is **rate-limited, not metered** — there is no
  per-message charge, balance check or ledger row today.

Credit-gating chat is therefore unbuilt work, not configuration.

---

## 2. Runtime options

### A. Local runtime on the 5070 Ti — *what exists today*

| | |
|---|---|
| Startup complexity | **Already built.** `start_llama()` spawns and health-checks with a 120 s window |
| Monthly fixed cost | Electricity + the box. See §3 — **wattage is unmeasured** |
| Per-message variable cost | Electricity only. No per-token charge |
| Latency | **measured** 166.3 tok/s generation, 1,807.1 tok/s prompt. A real generation: 96 tokens at 165.4 tok/s gen / 454.0 tok/s prompt |
| Reliability risk | **Single card, single box, no redundancy.** Chat contends with Image, Sigils and Studio for one 16 GiB card, and chat alone holds ~8.2 GiB |
| Privacy / control | **Strongest.** No prompt leaves the box. Nothing to trust but this machine |
| Deployment risk | Low — it is the running system |
| Rollback | Stop the surface; the site stays up without it |

### B. Hosted API runtime

| | |
|---|---|
| Startup complexity | **High, and entirely unbuilt** — no client, key handling, error mapping or cost accounting exists |
| Monthly fixed cost | Typically none |
| Per-message variable cost | Real and per-token — see §3 |
| Latency | Provider- and network-bound. Unknown from here |
| Reliability risk | Provider outage becomes our outage; adds a network dependency the site does not currently have |
| Privacy / control | **Weakest.** Customer prompts leave the box. Directly contradicts the preview's confidentiality posture unless the terms are re-stated |
| Deployment risk | Moderate — new failure modes (rate limits, quota, auth expiry) with no existing handling |
| Rollback | Feature-flag off, if built behind one from the start |

### C. Hybrid — local default, hosted fallback, explicitly enabled later

| | |
|---|---|
| Startup complexity | **Highest.** Everything in B, plus routing policy, failure detection and a decision about what "local is unavailable" means |
| Monthly fixed cost | As A, plus B when it triggers |
| Per-message variable cost | Zero on the local path, B's on the fallback path |
| Latency | Bimodal — the fallback path is the slow one and users notice inconsistency more than uniform slowness |
| Reliability risk | Improves availability; **worsens predictability**. Cost becomes a function of failure rate |
| Privacy / control | **Mixed, and the honest framing is that some prompts leave the box.** A page cannot say "runs on our hardware" while a fallback is armed |
| Deployment risk | Highest — most states to test, and the fallback path is by definition the least exercised |
| Rollback | Disable the fallback flag; degrade to A |

### D. Candidate future model path (gpt-oss) — **not activated**

Tracked in `ops/docs/OPENAI-GPT-OSS-MIGRATION.md`. Relevant to this study only as a capacity
question: chat already holds **8.2 GiB of 16,303 MiB measured**, so any larger candidate has to
be checked against the card before it is a runtime option at all. **No activation, no default
change, no benchmark claimed here.**

---

## 3. Cost model

**Placeholders. Do not fill these with remembered numbers — read them off a current price page
or a meter at the time of use.**

```
HOSTED_INPUT_PRICE_PER_1M_TOKENS   = <placeholder>
HOSTED_OUTPUT_PRICE_PER_1M_TOKENS  = <placeholder>
LOCAL_KWH_COST                     = <placeholder>   # local electricity tariff
AVG_INPUT_TOKENS                   = <placeholder>   # no conversation corpus measured yet
AVG_OUTPUT_TOKENS                  = <placeholder>
GPU_DRAW_W                         = <placeholder>   # NOT MEASURED on this box
```

> **`GPU_DRAW_W` is a real gap.** `ops/docs/MEASUREMENTS.md` contains no wattage reading. The
> card's rated TDP is a vendor specification, not a measurement of this box under this workload,
> and the repo rule forbids presenting one as the other. **Measure it with `nvidia-smi` under
> sustained chat load before quoting any electricity figure.**

### Formulae

```
hosted_daily = msgs/day × ( AVG_INPUT_TOKENS  × HOSTED_INPUT_PRICE_PER_1M_TOKENS  / 1e6
                          + AVG_OUTPUT_TOKENS × HOSTED_OUTPUT_PRICE_PER_1M_TOKENS / 1e6 )

local_daily  = ( generation_seconds/day × GPU_DRAW_W / 1000 / 3600 ) × LOCAL_KWH_COST
generation_seconds/day = msgs/day × AVG_OUTPUT_TOKENS / 166.3      # measured tok/s
```

### Load table

| | 100 msg/day | 1,000 msg/day | 10,000 msg/day |
|---|---|---|---|
| Hosted token cost/day | `100 × …` | `1,000 × …` | `10,000 × …` |
| Local generation-seconds/day *(projected)* | `100 × AVG_OUTPUT_TOKENS / 166.3` | `1,000 × …` | `10,000 × …` |
| Local electricity/day | needs `GPU_DRAW_W` | needs `GPU_DRAW_W` | needs `GPU_DRAW_W` |
| Fits current rate limit? | yes | yes | **check** — suggested chat limit is **120/min, 2,000/hour** |
| Card headroom | ample | ample | **the binding constraint** |

**Worked capacity example — projected arithmetic, not a measurement.** At an assumed
`AVG_OUTPUT_TOKENS = 300` and the measured 166.3 tok/s:

- 10,000 msgs/day → 3,000,000 output tokens → **≈ 5.0 hours** of continuous single-stream
  generation per day.

That is *generation time only*. It excludes prompt processing, model load, and every second the
card is held by Image, Sigils or Studio. With `-np 2` and continuous batching the wall-clock is
lower than 5 hours, but **by how much is not measured** and must not be guessed — the 47.3×
batching figure was measured at batch 64, and this surface runs 2 slots.

**The honest summary at 10,000/day: the cost question is secondary to the capacity question.**
One card, shared with three other GPU surfaces, is the constraint that binds first.

---

## 4. Recommended Phase 0 / Phase 1

### Phase 0 — local, offline, no commerce

- Local runtime only (option A). **No hosted fallback.**
- **No billing, no credits, no commercial API flag.**
- No public availability guarantee, stated anywhere.
- Rate limits **set explicitly** — `SYMONEURAL_RATE_CHAT` unset means *unlimited*, which is not
  a Phase 0 posture.
- Measure what is missing: `GPU_DRAW_W` under load, and `AVG_INPUT_TOKENS` /
  `AVG_OUTPUT_TOKENS` from real conversations. **Phase 1 cannot be costed until these exist.**

### Phase 1 — controlled beta

- Named, capped set of users. Explicit ceiling, enforced, not advisory.
- Logging and monitoring, with a retention decision made **before** the first log is written.
- **An explicit commercial enablement gate** — which today does not exist (§1). Build
  `SYMONEURAL_CHAT_ENABLED` or equivalent first; a surface with no off switch cannot be
  responsibly commercialised.
- **Rollback to a static support page** if the runtime fails. Decide now what a visitor sees
  when the card is busy or the surface is down — 503 with a readable body is the current
  behaviour, and a beta should render that as something a human wrote.

---

## 5. Hard gates before public or commercial use

Each of these must be **true and checked**, not intended:

| Gate | Current state |
|---|---|
| **Auth / account state** | Accounts exist behind `SYMONEURAL_ACCOUNTS_ENABLED`; chat is **not** account-gated |
| **Abuse / rate limits** | Buckets exist; **unset means unlimited** — must be set explicitly |
| **Logging / privacy policy** | No decision recorded on whether prompts are retained. Must be settled before beta, not after |
| **Model disclosure policy** | Customer-facing name is **SyMon AI**. Lineage names stay internal |
| **GPU health checks** | `llama_up()` health-checks; the governor arbitrates. No alerting path — `sayalert@` exists as an identity but **nothing sends to it** |
| **Uptime expectations** | **None may be stated.** One card, one box, no redundancy. Do not imply an SLA |
| **Support mailbox readiness** | `saysupport@symoneural.com` is the customer-facing address per the identity policy. **No mail sending is implemented** (`accounts/__init__.py:457` — no sendmail, no MTA, no mail client) |
| **Cost ceiling** | Meaningless until `GPU_DRAW_W` and token averages are measured. For hosted, a hard spend cap must exist before the first request |
| **Rollback command / process** | Must be one documented command, tested, that turns the surface off without stopping the API. **Does not exist today** |

---

## 6. Open questions

Answer before implementation, not during:

1. **Target daily users and messages?** Everything in §3 is parameterised on it, and 100/day
   versus 10,000/day are different systems.
2. **Acceptable latency?** 166.3 tok/s is measured for one stream. Two concurrent slots share
   one card; the third concurrent user waits.
3. **Is hosted fallback allowed at all?** This is a **privacy decision before a cost decision**.
   Customer prompts leaving the box contradicts the preview's confidentiality posture unless
   that wording changes.
4. **Free, credit-gated, or paid?** Metering exists but chat does not use it. Credit-gating is
   real work.
5. **Are logs retained?** If yes: what, how long, who can read them, and does it need saying on
   a customer-facing page.
6. **Does the Donnie preview need a chatbot at all?** The DispatchOS preview currently describes
   SyMon AI as *proposed*, with nothing running. Adding a live chatbot to a protected preview
   changes it from a static page into a service with a GPU dependency — and the *Conversation
   record trail* section already commits to an admin copy and folder retention that are
   **planned, not built**.
7. **Is SyMon AI platform-wide or per-customer?** One shared runtime with per-customer knowledge
   is a different architecture from a runtime per customer, and the card holds one 7B model at
   8.2 GiB.

---

## What this study does not do

It activates nothing, changes no default, enables no flag, and touches no `.env`. The default
model is unchanged. gpt-oss remains candidate-only. Every number carrying a date was read off
this box; every number without one is a placeholder waiting to be measured.
