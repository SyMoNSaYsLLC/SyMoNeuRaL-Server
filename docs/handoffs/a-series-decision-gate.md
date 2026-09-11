# A-Series Decision Gate — What Must Be Decided Next

> **REDACTED COPY.** Protected artifact names, credential filenames, customer identifiers, and infrastructure details are masked as `*****`. Unredacted detail stays on the box.

## Continues from

`a1-committed-clean-checkpoint.md` (2026-09-01 18:35). This covers 18:35 → 18:50 — a read-only decision gate. **Nothing was modified.**

## Control point — unchanged

```
HEAD                  a5fb0fbb
tracked modifications 0
staged                0
untracked             planning file only
```

---

## 1. What blocks A-3

**One decision: the customer-app auth reconciliation (D-3).** It is the only item in A-3's dependency list.

| | |
|---|---|
| **The conflict** | The customer application runs its own login endpoints in parallel with the shared accounts authority — two auth systems |
| **Measured** | Shared accounts module: **0** entitlement references. Routes: **0**. No identity→application mapping exists anywhere |
| **Options** | (a) migrate the customer app to shared accounts · (b) keep separate, bridge entitlement · (c) leave as is |
| **Safe default on record** | **(b)** — until the customer can retest |

The route-naming decision (D-5) does **not** block A-3 — its recorded scope is A-4 only.

**A second prerequisite needs no decision:** route classification is unstarted, and A-3 itself says *"route classes first… no blanket rule."* That is read-only analysis.

---

## 2. The wrong-generator defect — measured

**Written in four places** in the planning document: the A-3 affected-files line, an A-3 `check:` line, the phase table, and the verification matrix. All four name the same generator.

**Measured reality:**

```
named generator      livestack refs: 0    actually generates: documentation page
correct generator    livestack refs: 4    line 4 declares its outputs, incl. livestack
                                          line 56 carries the page-table entry
```

Three other generators contain the string only as navigation links — they reference the page, they do not write it.

**Consequence:** the A-3 check line can never pass meaningfully, and the verification matrix aims at a generator that does not own the page.

**What decision is required: NONE.** This is a **factual defect**, not a policy question — the correct owner is measurable and measured. It needs a **document correction**, which no authorization so far permits.

---

## 3. Is A-4 unblocked by the same decision?

**No.** Resolving the auth decision unblocks A-3 but leaves A-4 blocked on more:

| Dependency | Status |
|---|---|
| A-2 | ✅ committed |
| A-3 | blocked on the auth decision |
| auth decision (D-3) | unresolved — shared with A-3 |
| frontend slot location (D-4) | unresolved — **A-4 only** |
| production route naming (D-5) | unresolved — **A-4 only** |
| signing authority (D-11) | unresolved — **undeclared dependency, see below** |

**Finding not in A-4's stated dependency list:** A-4 requires release-identity and custody records. The signing decision records that **no signing authority, key custody, or verification authority exists**. Those two indicators cannot be honestly completed until it resolves — so A-4 depends on D-11 whether or not that is written down.

---

## 4. Packaging · signing · custody

| Gap | Decision exists? | Implementation item exists? | Needs |
|---|---|---|---|
| **Packaging** | ✅ two decisions | ❌ **NONE** | new A-item |
| **Signing** | ✅ one decision | ❌ **NONE** | new A-item |
| **Custody** | ⚠️ **partial** — key custody covered; *artifact* custody has no decision | ❌ **NONE** | **new decision + new A-item** |

**Measured proof:** **0 of 25** `check:` lines across all eight A-items reference signing, custody, packaging, or package formats. The apparent matches were the words "assignment", "design", and A-4's custody *requirement* — not work any item performs.

**This is the inverse of A-3/A-4.** There, implementation items exist but decisions don't. Here, decisions exist but implementation doesn't.

---

## 5. The export-architecture conflict

| Document | Says | Architecture |
|---|---|---|
| Export policy doc, rule 4 | the tool *"excludes the above"* | **deny-list** — snapshot minus known-bad |
| Planning doc §12.3 | *"constructed from an explicit allow-list… never the repository minus a deny-list"* | **allow-list** — built up from named paths |

**The precise conflict:** they give **opposite** answers for an unclassified path. Deny-list ships it (fails open); allow-list omits it (fails closed).

**Material fact:** the **shipped exporter implements the allow-list** — it requires a manifest and has both construct and enforce stages. So the policy doc now describes something the code does not do.

**No existing decision covers this.** A **new decision** is required: which document is authoritative, and therefore which text gets corrected.

---

## 6. What the production manifest still needs

```
scope files on disk:        0
scope schema defined:       0
the item that would create it:  deferred, unauthorized
```

The shipped exporter consumes a minimal path list, documented in the script as *"deliberately not a production manifest schema."*

**Six things must be decided:** ownership · storage location · syntax/schema · per-customer isolation · generation method (hand-authored vs entitlement-driven) · **and which application files a customer may actually receive**.

That last one is a **business decision**. Nothing on disk answers it.

---

## REQUIRED USER DECISIONS

Smallest ordered set before the next implementation authorization:

1. **Auth reconciliation (D-3)** — (a) migrate to shared accounts, (b) keep separate and bridge, or (c) leave as is. *Unblocks A-3. Safe default: (b).*
2. **Authorize the generator correction** in the planning document — factual, four locations, but a doc edit no authorization permits. *Required before A-3, or A-3 ships an unpassable check.*
3. **NEW — export-architecture authority** — which document governs, policy doc or planning doc. *Determines which text is corrected. No existing decision covers it.*

Then, only if proceeding toward customer delivery:

4. **Frontend slot location (D-4)** · 5. **Route naming (D-5)** · 6. **Signing authority (D-11)** — all three block A-4; the last also gates its release/custody records.
7. **NEW — artifact custody**, plus **new A-items for packaging, signing, and custody.** Three delivery-blocking decisions have zero implementation coverage.

---

## RECOMMENDED NEXT AUTHORIZATION

**A bounded, read-only route classification for the customer application** — classify all 13 of its API routes into the five defined classes by reading each handler. Produce a table; change nothing.

Why this one: A-3 itself mandates route classes first. It is the only remaining prerequisite that **needs no decision**, changes no file, touches no auth path, and **stays valid under all three options** for the auth decision. It also reveals, before code is written, whether the naive login→shared-auth mapping in the plan survives contact with the real handlers.

Otherwise **NONE** — implementation is premature until the auth decision and the generator correction are settled.

---

## Still open from earlier

- **D-1 … D-11** all undecided; **2 new decisions** identified this pass (export authority, artifact custody)
- **A-3** blocked · **A-4** blocked on four decisions plus A-3 · **A-8** blocked on contaminated units
- Three A-item check lines **already green**, proving nothing
- Production manifest **NOT DEFINED**

## Scope audit

```
AUTHORIZED SCOPE TOUCHED:   NONE — read-only analysis
UNAUTHORIZED SCOPE TOUCHED: NONE
```

Nothing modified, staged, committed, or deleted. Both checkpoints preserved exactly.

**NEXT AUTHORIZATION: NONE** — awaiting decisions 1–3.
