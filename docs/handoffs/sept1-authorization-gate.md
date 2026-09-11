# Sept 1 Authorization Gate — Handoff

> **REDACTED COPY.** Credential filenames, security tooling, internal ports, cloud-mount details, and customer identifiers are masked as `*****`. Unredacted detail stays on the box in `Sept1.md`.

**Status:** read-only decision gate complete. No implementation. Awaiting your authorization.

---

## Control point (verified by measurement)

```
HEAD                 1df394f0
tracked modifications 0
untracked            Sept1.md only
Sept1.md             1436 lines · sha256 d36d7258e43e…
A-items / D-items    8 / 11
API                  active · 0 restarts · HTTP 200
learned model payloads  0
```

---

## The eight proposals, reviewed

| Item | Recommendation | Depends on | Why |
|---|---|---|---|
| **A-1** control/models | AUTHORIZE WITH MODIFICATION | D-2, D-6 | Additive, zero collision. Defer the acquire launcher until D-2; omit conversion/quantization per D-6 |
| **A-2** export_snapshot.sh | **AUTHORIZE** | none | Highest value, no collision, unblocks A-4 |
| **A-3** entitlement | BLOCKED | D-3 | D-3 undecided **and** the assignment names the wrong generator |
| **A-4** complete customer slot | DEFER | A-2, A-3, D-3, D-4, D-11 | Most dependent item |
| **A-5** Studio model lifecycle | DEFER | A-1 | Must not precede A-1 or it grows a duplicate backend |
| **A-6** UI pass | AUTHORIZE WITH MODIFICATION | A-3 | Fix generator mapping; two checks are already green |
| **A-7** miner dashboard | DEFER | A-6 | Cleanest item technically; only blocked upstream |
| **A-8** gateway/web verification | **BLOCKED** | unit reconciliation | Installed units are contaminated; would produce a false result |

---

## Three findings that changed the recommendations

**1. Wrong generator named (affects A-3 and A-6).**
`Sept1.md` says `tools/build_stack.py` owns `livestack.html`. Measured: that file has **zero** `livestack` references and generates `documentation.html`. The real owner is **`tools/build_split.py`**. As written, A-3's third check can never pass meaningfully.

**2. Three check lines are already green.**
They would pass with no work done and prove nothing:

| Item | Check | Measured today |
|---|---|---|
| A-6 | `grep -c "generated" livestack.html` | 3 |
| A-6 | `exists SMOKE-APPLICATIONS.md` | already exists |
| A-7 | `grep hashrate miner.html` | 10 |

Your repo's own rule: *"a check that can pass without the work being finished is worse than no check, since it will archive the task."*

**3. A-8 is blocked by my own earlier damage.**
The installed gateway and web units **do not match the repo templates** and do not run the built binaries:

| Unit | Installed | Repo template |
|---|---|---|
| gateway | runs a generic reverse proxy | runs the built Rust binary |
| web | serves a static dir via python | runs the built Go binary |

The static directory the web unit points at **does not exist**, so it would fail instantly. These installed units are my rewrites from this session's outage — contaminated artifacts. **Verifying them would produce a false success record**, which is worse than not testing at all.

---

## Figures in Sept1.md that measurement contradicts

| Claim | Measured |
|---|---|
| Studio ~2,704 lines | **6,091** (package total; 2,704 counted only 6 top-level modules) |
| Studio 56 tests | **50** files |
| asicminer 34 tests | **32** files |

Not corrected in the document — you asked for review only.

---

## Missing controls

Requirements in D-1…D-11 with **no A-item at all**:

- **D-9** arch-neutral packaging on native binaries — nothing fixes the deb builder
- **D-10** primary-arch package gap (no IPK, missing feed index) — unaddressed
- **D-11** **no signing authority exists** — 76,208 unsigned packages, no A-item establishes signing
- **D-1** provenance enforcement at acquisition — only partially implied
- **model-free engine verification** — named in Core Identity, no tooling exists, and with 0 payloads it is the *only* way to verify the engine

**The biggest structural gap: A-1…A-8 contain no packaging, signing, or custody work whatsoever, yet three delivery-blocking decisions live there.**

---

## Conflicts

- **A-3 + A-6** — both edit the Live Stack generator; sequential only
- **A-1 + A-5** — strict order; A-5 first would grow the duplicate backend it forbids
- **A-8 + A-6** — A-6 may decide whether the missing static dir should exist; verifying first could enshrine the wrong answer
- **A-4 + D-11** — A-4 needs release/custody records; no signing authority exists to produce them

---

## Dependency order (not executed)

```
Phase 0   intake gate
   ├── A-2  exporter            ← independent
   ├── A-1  control/models      ← independent
   │     └── A-5  Studio
   └── [unit reconciliation]
         └── A-8  verification

   D-3 resolved
     └── A-3  entitlement  (fix generator first)
           ├── A-4  customer slot
           └── A-6  UI pass
                 └── A-7  miner
```

---

## NEXT AUTHORIZATION

**A-2 — write the export tool (exporter + fail-closed negative test only; no UX, no wiring).**

Zero dependencies, zero collision with control/, the customer app, generators, the build tree, or runtime. Unblocks A-4. It is the one item whose absence is cited as blocking *all* customer delivery.

**A-1** is an equally safe alternative if you'd rather start with something purely additive. A-2 is higher value but carries the trade-secret boundary, so it deserves the more careful pass.

*Not performed. This was a decision gate only.*

---

## To resume

Say **"authorize A-2"** (or A-1), or return `Sept1.md` with decisions filled in.

Nothing was changed: HEAD `1df394f0`, 0 tracked modifications, `Sept1.md` untracked, no commits, no service changes, no build-tree or customer-app modification.
