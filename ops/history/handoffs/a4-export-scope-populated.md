# A-4 EXPORT_SCOPE Populated — Verification Gate

> **REDACTED COPY.** Protected artifact names, credential filenames, customer identifiers, and infrastructure details are masked as `*****`. Unredacted detail stays on the box.

## Continues from

`a4-export-scope-content-decision.md`. You authorized **Option B**. This covers the populate + verify step. **Stopped at the gate — not committed.**

## Control point

```
HEAD          ef1a4af4   (unchanged — no A-4 commit)
tracked mods  1          (pre-existing policy doc)
new untracked 1          (the manifest)
staged        0
archives      0          produced
```

---

## 1. Manifest contents — 7 entries

```
# the customer-facing page
  <app>/page.py

# application-specific source
  <app>/__init__.py
  <app>/routes.py
  <app>/store.py
  <app>/quotes.py
  <app>/ai.py
  <app>/authz.py
```

The manifest's own header records what is absent **and why**, so the next reader does not mistake a deliberate exclusion for an oversight.

## 2. Classification of every included path

| Path | Category | Evidence |
|---|---|---|
| page module | **1 — application-specific** | Serves the live customer route; the authorized `FRONTEND_SLOT` (D-4) |
| package init | **1** | Application package definition |
| routes | **1** | This application's HTTP surface |
| store | **1** | This application's persistence: users, bookings, lifecycle |
| quotes | **1** | The operator's own rate rules — customer-specific domain logic |
| assistant | **1** | The application's managed assistant layer |
| authz | **1** | This application's route classes (A-3) |

**All 7 are category 1.** Each lives in the application package, is named for this application, and has exactly one consumer — this application.

## 3. Application-specific vs shared platform — the boundary finding

**One dependency crosses the boundary and is EXCLUDED.**

`apps/accounts` is **category 2 — shared platform source**:

| Test | Result |
|---|---|
| Named in the architecture as a shared consumed service | yes |
| Number of consumers | **more than one** |
| Located inside the application package | **no** |

Two application modules import it: the store takes password primitives, and authz consults it for entitlement. **"Imported by the application" is not "owned by the application."** Per your ruling I did not broaden the scope to satisfy the import.

> ### Returned for authorization
> A recipient of this manifest receives source that **imports a module they do not receive**. That is the correct boundary under Option B, not a defect — but it is a real consequence and it is your call, not mine. **Returning `apps/accounts` for separate authorization** rather than adding it.

## 4. Exporter verification

```
stage 1: 7 file(s) selected by manifest
stage 2: 0 protected paths -- passed
dry run -- no archive written        exit 0
```

**Exclusion proof** — prohibited patterns in the selected set:

| Pattern | Occurrences |
|---|---|
| shared platform source | **0** |
| tests | **0** |
| runtime state | **0** |
| infrastructure config | **0** |
| operator tooling | **0** |
| prior internal archives | **0** |
| build artefacts | **0** |
| static site tree | **0** |

### The finding worth your attention

I tested what happens if the shared dependency is added to the manifest:

```
stage 1: 8 file(s) selected
stage 2: 0 protected paths -- passed        ← NOT flagged
```

**Stage 2 would not catch it.** Shared platform source is not a *protected class* — it is neither a secret, nor training material, nor runtime state. So the exclusion rests **entirely on manifest discipline**, which is precisely why your boundary-verification requirement was load-bearing rather than ceremonial. This confirms the caveat I raised before populating.

**Practical consequence:** a future contributor adding a shared module to this manifest gets no automated objection. If you want mechanical enforcement, that needs a new check — a separate decision, not done here.

## 5. Test results

| Suite | Result |
|---|---|
| A-3 entitlement + route authorization | **35 passed** |
| A-2 exporter (the manifest's consumer) | **7 passed** |
| Full regression | **98 passed** |

## 6. Repository state

```
$ git status --short
 M ops/registry/EXPORTS.md                    ← PRE-EXISTING, prior authorization
?? (planning document)                    ← PRE-EXISTING, untracked
?? <app>/EXPORT-SCOPE.manifest            ← A-4, new

$ git diff --stat
 ops/registry/EXPORTS.md | 30 ++++--    ← pre-existing only
 1 file changed
```

**Zero implementation files modified.** Routes, authz, store, exporter: all unchanged.

## 7. Proposed commit scope

**One file:**
```
<app>/EXPORT-SCOPE.manifest        (new)
```

Plus, if you want the record committed, the planning document — though it is untracked and has been kept out of every commit so far, so I would leave it.

**Explicitly not in scope:** the pre-existing policy-doc modification (separate prior authorization), and any implementation file.

**Not committed.** Stopping at the gate as instructed.

---

## Boundaries held

```
customer export or distribution   NO — dry-run only, 0 archives produced
external release                  NO
signing / key generation          NO
shared accounts enabled           NO  (enabled() = False)
entitlement provisioning          NO
route / auth / runtime / proxy     0 files modified
exporter weakened or bypassed     NO — stage-2 rejection left intact
unrelated cleanup or refactor     NONE
```

**D-11 remains OPEN. External release remains NOT authorized. A-4 completion is not release readiness.**

## Still open

- **D-1, D-2, D-6 … D-11** undecided
- **A-8** blocked on contaminated units
- Packaging/signing/custody: decisions exist, **zero implementation coverage**
- **New:** shared platform dependency returned for authorization (§3)
- **New:** no mechanical guard against shared source entering a manifest (§4)
- Shared accounts disabled — every entitlement route returns 403

## To resume

Two things need you: **(a)** the `apps/accounts` dependency ruling, and **(b)** whether to authorize the A-4 implementation commit.

**NEXT AUTHORIZATION: NONE**
