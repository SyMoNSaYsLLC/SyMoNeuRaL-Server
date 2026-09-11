# SyMoNeuRaL Entitlements — what an account may run

**Scope captured 2026-08-22.** Docs only. **AUDIT until scoped. No implementation, no tier, no
price.**

Accounts / Gateway module.

## 1. What it is, and how it differs from the two things next to it

> **Entitlements answer *may this identity run this?* — before the meter asks *can they afford
> it?* and before the resolver asks *can this box do it?***

Three questions that are easy to merge and must not be:

| Question | Owner |
|---|---|
| **may they?** | **Entitlements** — this file |
| can they afford it? | **Meter** — `accounts/meter.py`, **built** |
| can the hardware do it? | **target resolver** — `symoneural-studio-upgrade-scope.md` §6 |

**Order matters.** Entitlement first: refusing on permission is cheap and needs no hold, whereas
taking a hold and then discovering the model is not permitted means a release, a ledger row and an
explanation. **A permission check that runs after a debit is a refund waiting to happen.**

## 2. What it governs

- **model access** — which models this identity may use at all
- **runtime access** — which runtimes it may reach
- **target permissions** — Cloud / Local / owner-local
- **operation class** — read · generate · train · **base-weight mutation** (owner/admin only)
- **quota shape** — concurrency, queue priority, retention
- **surface access** — which of the thirteen rack surfaces are reachable

## 3. What already exists, and what it implies

**A two-level identity model is in place.** `accounts/module.py` separates an **owner bearer** from
**user sessions**: the owner token is *"a single high-privilege bearer from the environment"*,
compared with `hmac.compare_digest` because *"an early-exit comparison on a secret is a timing
oracle, and this one grants owner."* With it unset the app serves loopback peers only.

**The meter already encodes a role.** `hold(account_id, role, kind, amount)` takes `role`, and
**owners are free — expressed as no hold at all** rather than a zero-amount hold, deliberately:
*"a `None` hold is the free path being visibly, structurally free."*

**So `role` is the seam entitlements should grow from**, and that is the important architectural
consequence of the measurement: there is already a role flowing into the money path. Entitlements
should read that same role rather than introducing a parallel notion of who someone is.

**Also existing:** per-surface `_ENABLED`/`_TOKEN` gates on eight surfaces, and
`backend/apps/licensing/` (4 files) with `issue.py` and a **public** `contract-signing.pub` — the
private half never in the tree, never on a rig, never in a web process's environment.

**What does not exist:** any mapping from an identity to a permitted set of models, runtimes or
targets. **Nothing today can answer "may this user run the 32B?"**

## 4. Tiers without hardcoding prices

**The point of this module is paid tiers *without* baking pricing into a schema now.**

So the schema carries **capabilities**, not plan names:

```
entitlement:
  identity        account | session | owner | token
  models          allow / deny, by model_id or family
  runtimes        allow / deny, by runtime_id or family
  targets         cloud | local_customer | local_owner_nvidia
  operations      read | generate | train | mutate_base_weights
  concurrency     max in flight
  queue_priority  an ordering key, not a promise
  retention       how long results are kept
```

**A plan is a named bundle of those capabilities**, resolved at read time. **No price appears in
this schema.** A tier called "pro" that hardcodes a number is a pricing decision disguised as a
data model, and pricing has not been decided.

**`queue_priority` is an ordering key, not a promise.** On one GPU with a one-deep queue, priority
changes *who is next*, not *how fast*. Selling it as throughput would be selling capacity this box
does not have.

## 5. Hard rules

- **Base-weight mutation is owner/admin only, always.** The four `never` operations from
  `symoneural-studio-upgrade-scope.md` §1.2 — in-place mutation, overwriting an existing model file,
  arbitrary path writes, arbitrary training code — **are absent operations, not restricted ones.**
  Entitlements cannot grant what does not exist, and that is the strongest form of this rule.
- **Entitlements must not become a security gate substitute.** The per-surface `_ENABLED`/`_TOKEN`
  gates stay. An entitlement says *this account may use Studio*; the Studio gate says *Studio is on
  and you presented its token*. **Both, or neither is trustworthy.**
- **Entitlements must not become a third registry.** They *reference* `model_id` and `runtime_id`
  from the existing registries and store no model or runtime truth
  (`symoneural-generic-contracts.md` §3).
- **A licence-blocked model is not entitleable.** Three of eleven weights currently have no licence
  text on disk, and the commercial-use fields are unrecorded for all eleven
  (`models/docs/MODEL-LICENSES.md` ML-1, ML-2). **An entitlement granting commercial use of a model
  whose commercial terms are unrecorded is the exact risk the licence audit exists to stop.**
- **Deny by default.** An identity with no entitlement record gets the free/offline default, not
  everything.

## 6. Relationship to the gateway

`backend/apps/gateway/` holds settlement — `record.py`, `entitlement.py`, `store.py`,
`test_settlement.py`. **There is already a file called `entitlement.py` there**, so the first
implementation step is to read it and decide whether this module extends it or is distinct from it.
**Not decided here, and it must not be guessed:** two things called entitlement in one codebase is
how the `symoneural_accounts` / `symon_capture` / `apps.accounts` three-way spelling happened, which
`meter.py`'s own docstring cites as the reason accounts and money live in one application.

**Gateway is folded under Miner in the rack and its code stays separate** — a display fold is not a
package move.

## 7. What promotes this from AUDIT

| To claim | Proof |
|---|---|
| entitlements exist | a stored record, and a route that refuses on permission **before** any hold |
| they are not a gate substitute | a test showing a permitted account still refused by a surface's own token gate |
| tiers work without prices | a named bundle resolving to capabilities, with **no** number in the schema |
| the gateway question is settled | a written decision on `gateway/entitlement.py` — extend or distinct |
| commercial use is grantable | `MODEL-LICENSES.md` ML-2's four fields recorded per model |

## 8. Not authorized

No implementation · no schema created · no tier or plan defined · no price · no gate change · no
change to `gateway/entitlement.py` · no folder migration · no deploy.
