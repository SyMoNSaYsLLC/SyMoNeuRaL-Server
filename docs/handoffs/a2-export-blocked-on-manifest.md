# A-2 Export Tool — BLOCKED on manifest definition

> **REDACTED COPY.** Credential filenames, security tooling, internal ports, infrastructure posture, and customer identifiers are masked as `*****`. Unredacted detail stays on the box in `Sept1.md`.

## Continues from

`sept1-authorization-gate.md` (2026-09-01 17:20). That handoff recommended **A-2** as the next authorization. You authorized it. This covers 17:20 → 17:45.

## Control point — unchanged

| | At last handoff | Now |
|---|---|---|
| HEAD | `1df394f0` | `1df394f0` |
| tracked modifications | 0 | **0** |
| untracked | `Sept1.md` | `Sept1.md` only |
| `Sept1.md` sha256 | `d36d7258e43e…` | `d36d7258e43e…` (unmodified) |

**No files created or modified this window.**

---

## Verdict: A-2 BLOCKED — POLICY DECISION REQUIRED

I stopped before writing code. The prompt's stop condition was met exactly: *"If the required export boundary is ambiguous, stop implementation of the ambiguous portion and report the ambiguity rather than choosing a permissive interpretation."*

---

## What I found

**No existing exporter.** The tool does not exist; the task-archival script is unrelated; no duplicate machinery risk.

**Two authorities specify different architectures:**

| Authority | Architecture | Exclusion set |
|---|---|---|
| Export policy doc, rule 4 | "excludes the above" — **deny-list** over a snapshot | Fully enumerated |
| `Sept1.md` §12.3 | **Allow-list** construction from a scope manifest | Enumerated for stage 2 only |

**The deny side is fully defined.** Protected training material, mode-600 ledgers, internal review material, secrets/tokens, runtime state, other customers' data, canonical source history.

**The allow side is defined nowhere.** I searched the docs tree, the referenced spec, and the whole repository:

```
scope manifest defined in docs/   → NO
any scope file on disk            → NONE
allow-list wording in policy      → no matches
```

This is by design, not an oversight. `Sept1.md` §12.4 lists the exporter as **REQUIRED** but the per-application scope manifest as **PROPOSED** — and that manifest belongs to **A-4**, which the authorization gate deferred and this prompt does not authorize.

---

## Why I didn't just pick one

| Option | Why rejected |
|---|---|
| Invent a manifest format | Inventing business policy — the prompt forbids it |
| Deny-list only | A-2 explicitly excludes this, and it **fails open** on unclassified paths |
| Manifest reader with no manifest | Untestable; no positive export path can be proven |

The decisive detail: the two architectures give **opposite** answers for an unclassified path. Allow-list excludes it; deny-list ships it. A-2's entire purpose is to fail closed, so this is not a stylistic fork — it determines whether the tool is safe.

---

## The decision I need

**Recommended — authorize a fixture-only scope manifest.** I define a synthetic manifest **for the negative test only**, never for a real customer. This keeps A-2 narrow, requires no business-policy invention, and delivers a working, provably fail-closed exporter. Real manifests still wait for A-4.

**Alternative — you define the manifest format.** Even minimally (a line-per-path allow file). A-2 then implements the reader, both stages, and the negative test fully in scope.

---

## Documentation inconsistency (not fixed)

The export policy doc and `Sept1.md` §12.3 currently describe different architectures. Whichever you choose, one document should be updated so a future reader doesn't hit the same fork. That edit is outside this authorization; I have not made it.

---

## Still open from earlier

- **D-1 … D-11** all undecided
- **A-3** blocked — an unresolved decision *and* a wrong-generator defect in the assignment
- **A-8** blocked — installed units are contaminated rewrites from my earlier outage
- Three A-item check lines are **already green** and prove nothing
- **No A-item covers packaging, signing, or custody** — three delivery-blocking decisions sit uncovered

---

## Scope audit

```
AUTHORIZED SCOPE TOUCHED:   NONE — read-only inspection only
UNAUTHORIZED SCOPE TOUCHED: NONE
```

Nothing staged, nothing committed, no service changes, no build-tree or customer-app modification.

## To resume

Reply with either **"fixture-only manifest"** (recommended) or your manifest format, and A-2 proceeds immediately. **A-1** remains available as an alternative — additive, reversible, no policy blockers.

**NEXT AUTHORIZATION: NONE** — awaiting your policy decision.
