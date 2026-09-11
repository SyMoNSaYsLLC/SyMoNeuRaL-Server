# SyMoNeuRaL commercial mode — one switch, off by default

**Scope captured 2026-08-22.** Docs only. **Paid mode is NOT enabled. No account is required for
current testing. No gate removed, no billing implemented, no price stated.**

## 0. Current mode, and it stays

> **`free_offline`. Free, offline/local-first, no forced signup for basic testing, and no
> production billing claim.**

Garrett is fine with free and offline right now. **The architecture must not need a rewrite when
commercial mode is turned on** — which is what this document is for.

## 1. The finding that changes this plan: the meter already exists

**`backend/apps/accounts/meter.py` is built**, and it is not a stub. Measured 2026-08-22:

`balance()` · `credit()` · `hold()` · `settle()` · `release()` · `sweep_stale()` · `history()` ·
`InsufficientFunds`. Its own docstring: *"The billing half of accounts: balances, holds, and a
ledger."*

And the hard part is already right. **Reserve-then-resolve, not charge-on-success**, with the
reasoning recorded:

> *"The obvious implementation charges when the job finishes, and it is wrong: the job runs for tens
> of seconds … in that window the same account can start twenty more. Each one checks a balance that
> no earlier job has yet spent, every check passes, and the account goes negative by twenty jobs.
> That is a textbook time-of-check/time-of-use hole and it costs real money."*

So the balance is debited **when the hold is taken**, in one transaction that both checks and
deducts, then **settled** or **released** — from a `finally`, so a crash cannot strand a hold. And
`sweep_stale()` returns anything past the timeout, because *"a reserved token that nothing will ever
resolve is indistinguishable from a stolen one from the account holder's side."*

Two design choices worth preserving verbatim:

- **Owners are free, expressed as `None` — no hold at all.** Not a zero-amount row. The reason:
  a zero-amount hold *"means the free path exercises different code from the paid path only in the
  amount, and every future bug in hold resolution becomes a bug the owner can trigger too. A `None`
  hold is the free path being visibly, structurally free."*
- **Integer tokens throughout. No floats anywhere near money.**

Accounts is also real: 8 routes (`status`, `signup`, `login`, `logout`, `me`, `sessions`,
`password`, `signout-everywhere`), owner token compared with `hmac.compare_digest` because *"an
early-exit comparison on a secret is a timing oracle"*, and sessions that **degrade rather than
fail the process** — `SYMONEURAL_SESSION_SECRET` unset raises rather than generating a fallback,
because *"a per-process secret logs every user out on restart and a hardcoded one is forgeable."*

**So the correct classification is not "Meter: future".** It is **built, wired to one caller
(`symoneural_dj.pipeline.run_job`), and not switched on for the main API.** The commercial work is
mostly *connecting* and *deciding*, not *building*.


### Classification — corrected against the disk

**Meter is not FUTURE-only, and this document is not written as though it does not exist.**

| Thing | Classification |
|---|---|
| **Accounts** | **BUILT / AUDIT** — 8 routes, sessions, owner bearer, `hmac.compare_digest` |
| **SyMoNeuRaL Meter** | **BUILT / AUDIT** — `backend/apps/accounts/meter.py` |
| **Credits / token ledger** | **BUILT / AUDIT** where measured — balances, holds, ledger rows |
| **App-wide metering** | **AUDIT / PARTIAL** — wired to `symoneural_dj.pipeline.run_job`; **every other app route is unmeasured** and must be checked route-by-route before any claim |
| **Commercial mode** | **DISABLED** — no code reads `SYMONEURAL_MODE` |
| **Billing / subscriptions / invoices / payment processor** | **FUTURE / DISABLED** — none exists |

**AUDIT on Accounts and Meter is not doubt that they work.** It is that their coverage is
unmeasured: a ledger that one caller uses is a ledger, not a metering system, and the gap between
those two is exactly what "app-wide metering: PARTIAL" names.

## 2. The switch

**Primary — `SYMONEURAL_MODE`. Default `free_offline`.**

| Mode | Meaning |
|---|---|
| **`free_offline`** | **the default.** No payment, no subscription, no required account for local testing, no billing claim. Every write/control/GPU-expensive path still behind its safety gate |
| `free_online` | public demo. Rate limited. **No** privileged controls, **no** filesystem, **no** base-weight mutation, **no** miner/ASIC controls |
| `metered_local` | the local user owns the compute. Usage logged, account optional. **No cloud billing unless separately enabled** |
| `commercial_cloud` | account required · credits/subscription active · queue-priority policy active · paid job metering · hosted GPU path. **No raw GPU, filesystem or model-weight exposure** |
| `commercial_hybrid` | cloud fallback + local-agent detection; the target resolver decides. Account/credit policy per product policy |
| `owner_admin` | Garrett/admin. Privileged tools **only** behind an explicit owner gate. **Never public** |

**Secondary switches, all `0` by default:** `SYMONEURAL_ACCOUNTS_ENABLED` ·
`SYMONEURAL_CREDITS_ENABLED` · `SYMONEURAL_SUBSCRIPTIONS_ENABLED` ·
`SYMONEURAL_USAGE_METERING_ENABLED` · `SYMONEURAL_BILLING_ENABLED` ·
`SYMONEURAL_COMMERCIAL_API_ENABLED` · `SYMONEURAL_CLOUD_TARGET_ENABLED` ·
`SYMONEURAL_LOCAL_TARGET_ENABLED`

**These are documented names, not implemented variables.** Nothing reads them today.

## 3. The rule that makes a mode switch safe

> **Turning on one switch must not accidentally expose the filesystem, model weights, miner
> controls, Studio command tools, or paid routes.**

**A mode must never be able to widen a security gate.** The two are orthogonal by construction:
`SYMONEURAL_MODE` selects *commercial behaviour*; the per-surface `_ENABLED`/`_TOKEN` gates select
*access*. **A mode value is not a credential and must never be read as one.**

This matters because the reverse is already a live risk. `ops/audits/SECURITY-AUDIT.md` **BLOCKER-1**
and **BLOCKER-2**: task #88 removes tokens across eight surfaces, and on a box where
`ops/Caddyfile` delegates `/studio/*`, that puts ComfyUI's editor on the public internet. **If
"testing mode" ever becomes a `SYMONEURAL_MODE` value that drops tokens, that is the same bug with
a config file in front of it.** The safe shape for #88 is loopback-only, not gate-less.

## 4. The gate on enabling any commercial mode

> **Commercial mode stays disabled until every BLOCKER and HIGH in `ops/audits/SECURITY-AUDIT.md` is
> closed or explicitly owner-accepted in writing, with a date.**

Currently open: **BLOCKER-1**, **BLOCKER-2**, **HIGH-1** (`/studio/editor/*` as product surface),
**HIGH-2** (WebSocket origin posture; `/api/ws` is HIGH in commercial mode specifically).

And a second gate, from `ops/audits/LICENSE-AUDIT.md`: **no model may be sold or its output
commercialised while its licence status is `unknown-blocked`.** Live example — three of eleven
weights have no licence text on disk (`MODEL-LICENSES.md` ML-1), and the four commercial-use fields
are unrecorded for all eleven (ML-2). **Selling output from a model whose redistribution and
commercial-use terms are unrecorded is the risk this gate exists for.**


## 4a. Distribution blockers — separate from the security gate

These block **customer or appliance distribution** specifically, and they are not security
findings, so they would otherwise be missed by a security-only gate:

| Blocker | Detail |
|---|---|
| **three weights cannot be redistributed** | the unsloth/Qwen3.x 27B, its vision tower, and 32B have `license_text: null`. Apache-2.0 §4 requires attribution to travel with a redistributed artefact, and there is no text on disk to travel. `MODEL-LICENSES.md` ML-1 |
| **`NOTICE.md` and `THIRD-PARTY-NOTICES.md` do not exist** | `LICENSES.md` §8 records the notice obligations; **there is no notice artefact to ship.** A notice obligation is discharged by delivering the notice, not by recording that one is owed. `LICENSE-AUDIT.md` LA-3 |
| **no Yocto licence manifest, SPDX or SBOM can be claimed** | **because no image has ever been built.** They are build outputs, so they are not missing — they are **not yet producible**. `YOCTO-LAYER-LICENSES.md` §0, §4 |

**The third one is the one to state carefully.** "We have no SBOM" and "we cannot yet have an SBOM"
are different positions, and only the second is true for the image scope.

## 5. Per-mode behaviour that must not drift

**`free_offline`** — no payment, no subscription, no required account for local testing; no public
write/control/GPU-expensive path without a safety gate; **no billing claim anywhere on any page.**

**`free_online`** — rate limited; no privileged controls; no filesystem; no base-weight mutation; no
miner/ASIC controls. The rate limits are the whole protection, and `symoneural-api-surface.md` §4 is
explicit that a bucket absent from `_RATE_SUGGESTED` is **unmeterable**, not unlimited-by-choice.

**`metered_local`** — usage logged, account optional, no cloud billing unless separately enabled.

**`commercial_cloud`** — account required, credits or subscription active, queue-priority policy
active, paid metering active; **and the customer never sees raw GPU, filesystem, CUDA, ComfyUI or
model weights** (`symoneural-cloud-local-targets.md` §1).

**`commercial_hybrid`** — the resolver decides Cloud or Local, and **Local requires local-agent
proof**, which does not exist (`symoneural-cloud-local-targets.md` §2). So hybrid is unreachable
before that agent exists, whatever the switch says.

**`owner_admin`** — never public. Distinct from a user account: `accounts/module.py` already
separates the owner bearer from user sessions, and that separation is the model.

## 6. What is honestly missing

| Piece | State |
|---|---|
| the meter | **built** (§1), wired to one caller, not switched on for the main API |
| accounts | **built** — 8 routes, sessions, owner token |
| the mode switch itself | **not implemented.** No code reads `SYMONEURAL_MODE` |
| per-surface pricing | **not decided, and not to be invented** |
| subscriptions | **not built.** Must not be hardcoded into a schema before a product decision |
| queue priority | not built |
| private result retention | not built |
| usage ledger with the full field set | partial — the meter has a ledger; the surface/model/runtime/target fields are not in it |
| entitlements | `backend/licensing/docs/symoneural-entitlements.md` — AUDIT |

**No pricing. No plan names. No "guaranteed revenue" language. No SLA.** Account status may expose
subscription state **only when it is real.**

## 7. Not authorized

No mode switch implemented · no billing or payments · no price or plan stated · no account
requirement added to any current surface · no gate removed or widened · no credits enabled · no
deploy.

Related: `ops/audits/SECURITY-AUDIT.md` (the gate) · `ops/audits/LICENSE-AUDIT.md` and
`MODEL-LICENSES.md` (the second gate) · `symoneural-entitlements.md` ·
`symoneural-cloud-local-targets.md` · `symoneural-revenue-edge.md`.
