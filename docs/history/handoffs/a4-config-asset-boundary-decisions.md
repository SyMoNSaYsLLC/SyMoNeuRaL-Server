# D-A4-CONFIG and D-A4-ASSET — Evidence, Options, Recommendations

> **REDACTED COPY.** Protected artifact names, credential filenames, customer identifiers, and infrastructure details are masked as `*****`. Unredacted detail stays on the box.

## Continues from

`a4-regression-repaired.md`. Read-only decision resolution from HEAD `eaaa9d6a`. **Nothing created, moved, renamed, edited, classified, or committed.**

## Control point

```
HEAD          eaaa9d6a
tracked mods  1  (pre-existing policy doc, untouched)
staged        0
```

---

# D-A4-CONFIG — Configuration boundary

## 1. Evidence found

**Configuration reaches this application through exactly two mechanisms**, and they land in different places:

| Mechanism | Carries | Location |
|---|---|---|
| **Environment variables** — 4 read by the package | surface on/off, database path, plus two belonging to the shared subsystem | process environment, set from an operator-owned env file |
| **In-application settings table** — key/value | **one key only: the operator's rate rules** | inside the runtime database |

**The single most consequential finding:** the only customer-specific configuration that exists — the rate rules — lives **inside the runtime database**, which the exporter refuses at stage 2 as runtime state. So customer configuration is *already unexportable*, not by policy choice but by where it is stored.

**No shipped application defaults.** The quote engine has one display constant and no default rule set; an unconfigured application deliberately shows a blank rather than a confident zero. There is nothing to hand a customer as "defaults".

## 2. Existing seams

| Seam | What it establishes |
|---|---|
| Settings table in the application store | customer-authored configuration, one key |
| 4 environment variables | operator/runtime configuration, not application data |
| Operator-owned env file | the operator configuration boundary; agent reads of it were correctly denied earlier this session |
| Exporter stage 2 — 17 protected patterns | protected internal configuration, mechanically enforced: secrets, `.env`, credentials, private keys, signing material, api keys, runtime state, ledgers, internal review material, repository history |
| Export scope manifest (7 entries) | contains **no** configuration file — configuration is already outside the authorized export |

## 3. The boundary is already complete — options concern *documentation*, not mechanism

| | Option | What it does |
|---|---|---|
| **A** | **Record the measured boundary as-is** | Five categories documented from evidence; no file changes |
| **B** | Record, and add a customer-configuration export path | Would require exporting rate rules from the runtime DB — a new mechanism |
| **C** | Introduce a separate customer-config file outside the runtime DB | Restructures where configuration lives |
| **D** | Defer | Slot stays DEFINED |

## 4. Tradeoffs

- **A** — free, true, and closes the slot. Its honest limitation: a customer receiving the export gets **no configuration**, so the application arrives unconfigured. Consistent with Option B export scope already ruled ("not a self-contained distribution").
- **B** — the customer could receive their own rate rules, which is arguably *their* data. But it means extracting from the runtime database, i.e. building an exception to the runtime-state refusal. **That refusal is a safety property, and carving a hole in it for convenience is the exact shape of failure this project keeps guarding against.**
- **C** — cleaner in the abstract; a real change to a working application for no current need.
- **D** — leaves a boundary undefined that the evidence already answers.

## 5. Recommendation — Option A

Record what is measured. The boundary is not missing; it was never written down.

**If you later want the customer to receive their own rate rules, that is a distinct decision** — "may customer configuration leave the runtime database" — and it deserves its own gate rather than arriving inside a documentation task.

## 6. Proposed `CONFIG_SLOT` definition

```
CONFIG_SLOT — configuration boundary (proposed, measured 2026-09-02)

  CUSTOMER-SPECIFIC CONFIGURATION
      the operator's rate rules, one key in the application settings table,
      customer-authored at runtime through an operator-only route
      → stored in the runtime database → NOT exportable (stage 2 refuses it)

  APPLICATION DEFAULTS
      none. No default rule set ships; unconfigured renders blank by design
      → nothing to export

  SHARED / PLATFORM CONFIGURATION
      the shared subsystem's enable flag and session secret
      → platform-owned, never customer content

  RUNTIME / OPERATOR CONFIGURATION
      surface enable flag and database path, from the operator-owned env file
      → operator-owned, never customer content

  PROTECTED INTERNAL CONFIGURATION — never in a customer export
      secrets, .env files, credentials, private keys, signing material, api keys,
      runtime state, mode-restricted ledgers, internal review material,
      repository history, internal infrastructure configuration
      → enforced mechanically by exporter stage 2, independent of any manifest

  RESULTING EXPORT POSITION
      no configuration of any category enters the customer export.
      The manifest contains zero configuration files, and that is correct.
```

---

# D-A4-ASSET — Asset boundary

## 1. Evidence found

**The application owns no assets.** Measured:

| Check | Result |
|---|---|
| Asset directory in the package | **none** |
| Non-source files in the package | **2** — a smoke record and the export manifest, neither an asset |
| External asset references in the page | **0** — no `src=`, `href=`, or `url()` |
| Inline style blocks / script blocks | 1 / 1 — **the page is self-contained** |
| Upload or file handling in routes | **0** |
| Generated output directory | **none** |
| Binary columns in the application store | **0** |

**For contrast, the shared platform holds 135 brand assets** plus 3 shared CSS/JS files. The application uses none of them: it renders as one self-contained document.

**Prior-archive precedent points the other way.** The one internal archive that carried non-document files carried the **static preview page and internal infrastructure configuration** — and its own manifest labels it internal-only, not customer-deliverable. It is precedent for what *not* to ship.

## 2. Existing seams

| Seam | What it establishes |
|---|---|
| Self-contained page module | the application's presentation is source, not assets |
| Shared brand directory (135 files) | shared platform assets, one authority, not per-customer |
| Shared CSS/JS in the site tree | shared platform presentation |
| Exporter stage 2 | protected assets — adapter weights, signing material, secrets |
| Export scope manifest | contains **no** asset entry, only source |
| Absence of upload handling | **no customer-uploaded asset class exists** |

## 3. Options

| | Option | What it does |
|---|---|---|
| **A** | **Record that the application has no assets** | Five categories documented; the customer-asset class is empty *today* |
| **B** | Declare the static preview page a customer asset | Adds one file to the export |
| **C** | Reserve an asset directory for future customer assets | Creates structure with no current occupant |
| **D** | Defer | Slot stays DEFINED |

## 4. Tradeoffs

- **A** — matches measurement exactly. Records the empty class explicitly, so a future contributor adding branding knows the boundary already exists.
- **B** — tempting, because the static page *looks* like a deliverable. But D-4 established it **serves nothing**: the live route renders from the page module, and the static file is unreferenced by the backend. Shipping it would deliver a **stale duplicate** of the real page — worse than shipping nothing, because it can silently diverge.
- **C** — structure without an occupant. Empty directories acquire whatever the next person needs, which is how a boundary erodes.
- **D** — leaves a slot undefined when the evidence is unambiguous.

## 5. Recommendation — Option A

The measured answer is *there are no customer assets*, and that is a legitimate slot value rather than an incomplete one. Recording the empty class is more useful than inventing an occupant.

**Explicitly reject B**: the static preview page is not the served page. D-4 already measured that.

## 6. Proposed `ASSET_SLOT` definition

```
ASSET_SLOT — asset boundary (proposed, measured 2026-09-02)

  CUSTOMER-OWNED / CUSTOMER-SPECIFIC ASSETS
      none exist. No upload path, no asset directory, no binary storage.
      → the class is EMPTY, not unknown

  APPLICATION-DEFAULT ASSETS
      none. The page is self-contained: one inline style block, one inline
      script block, zero external references
      → presentation is source, and travels as source

  SHARED PLATFORM ASSETS
      the shared brand directory and shared site CSS/JS
      → platform-owned, single authority, never per-customer, never exported

  PROTECTED INTERNAL ASSETS — never in a customer export
      adapter weights, signing material, secret material, model payloads
      → enforced mechanically by exporter stage 2

  GENERATED / TRANSIENT ASSETS
      none for this application. No output directory, no generated media

  RESULTING EXPORT POSITION
      no asset of any category enters the customer export. The manifest
      contains source only, and that is correct.

  NOT A CUSTOMER ASSET, explicitly
      the static preview page in the site tree. D-4 measured that the live
      route renders from the page module and this file serves nothing;
      exporting it would deliver a stale duplicate that can silently diverge.
```

---

## Both decisions ready

| Decision | Recommendation | Files changed if authorized |
|---|---|---|
| **D-A4-CONFIG** | **Option A** — record the measured boundary | documentation only |
| **D-A4-ASSET** | **Option A** — record that the asset class is empty | documentation only |

**Both slots resolve to the same export position: nothing enters the customer export.** The manifest containing source only is already correct under both definitions — no manifest change would follow from either.

**One decision deliberately not folded in:** whether customer configuration may ever leave the runtime database. The evidence says it currently cannot, and carving an exception into the runtime-state refusal is a safety decision, not a documentation one.

## Gates preserved

```
shared accounts enabled      NO
customer account created     NO
entitlement provisioned      NO
D-11                         OPEN
D-12                         unimplemented
external release             NOT authorized
policy document              untouched  (still M, uncommitted)
services restarted           NO
runtime/configuration change NO
exporter behaviour changed    NO
archive produced             NO
files created/moved/renamed/edited/classified  NONE
committed                    NO
```

**NEXT AUTHORIZATION: NONE** — awaiting rulings on D-A4-CONFIG and D-A4-ASSET.
