# SyMoNeuRaL RavenCalc — scope, and why its CPU is not a fallback

**Scope captured 2026-08-22.** Docs and scope only. **No engine work, no rename, no restructure, no
`@simpy.tar.gz` import, no deploy.**

## 1. What it is

> **SyMoNeuRaL RavenCalc is the CPU-only symbolic mathematics surface.**

Exact symbolic algebra · **computed rather than predicted** · SymPy-backed unless the current audit
proves otherwise · **CPU-only by design** · never queued behind GPU surfaces · safe to use while
Chat, Image, Remix, Sigils, Studio or Miner are busy · a verified math co-processor for Chat where
applicable.

Classification: **PROD direction**; current implementation audited before migration
(`BOX-REALITY-AUDIT.md` §10.4).

## 2. The architecture distinction that must be written down

**RavenCalc using the CPU is not a fallback. It is CPU by design.**

This needs stating explicitly because the repo carries a strong, correct, adjacent rule:
`BOX-REALITY-AUDIT.md` §2.2 and §7 record **"no CPU fallback in any GPU serving path"** as PROD.

**That rule does not touch RavenCalc.** It forbids silently *downgrading a GPU workload* to the
CPU. RavenCalc is not a GPU workload. Without this paragraph a future audit reads §7 alone and
marks RavenCalc's CPU path as a violation of a rule it is unrelated to — so the carve-out now lives
in the audit itself, at §10.4.

**The consequence is the product benefit:** RavenCalc stays available while the card is held. That
is why it is the surface Chat can lean on for exact math during a long render.

## 3. The claims that are load-bearing and must survive any layout change

Open task **#84** (R-157) asks for the calculator at the top of the page, and it is explicit that
this is **not a trim**: *"layout changes must not drop data."*

**These must remain visible somewhere on the page:**

1. RavenCalc is **SymPy** underneath.
2. It is **exact symbolic mathematics**.
3. It is **not a language model guessing algebra**.
4. It runs on **CPU**.
5. It **never waits for the GPU**.

Rules: **fold long content into `<details>`** · **merge duplicate copy rather than deleting one
copy** · **do not trim meaningful text** · **no `text-overflow`** — #84: *"that rule has no
exceptions here."*

#84 also refuses to do the standing SymPy rebrand request on the same page, and the reason
generalises: *"that is its own task, and re-typing the word here is the edit that would hide it."*

## 4. Page direction

The calculator must appear at the top of `/ravencalc.html`; the visitor should land on the working
calculator, not on paragraphs. Keep a short one-line identity statement near the top and move the
longer explanation below the tool or into `<details>`. **Avoid duplicate preamble blocks saying the
same thing twice** — there are currently two.

**Top copy.** Garrett's preferred wording, and his own fallback if it overclaims:

> *"Exact symbolic mathematics, computed on the CPU. RavenCalc uses SymPy-style symbolic algebra
> instead of asking a language model to guess. It never takes the GPU, so it stays available while
> Chat, Image, Remix, Studio, or Miner are queued."*

> *"Exact symbolic mathematics, computed on the CPU. RavenCalc is the SyMoNeuRaL math surface; it is
> designed around SymPy-style symbolic algebra, not language-model guessing. It never takes the
> GPU."*

**Measured 2026-08-22 — it is SymPy, so the stronger wording is factually safe.**
`backend/apps/ravencalc/symbolic.py:1-7` is a *"facade over the upstream symbolic engine
(sympy)"* and declares itself *"the ONLY file in the `ravencalc` package allowed to `import
sympy`"*; **sympy 1.13.3 is installed**; and `ravencalc.py:47-49` imports `parse_expr`,
`standard_transformations`, `implicit_multiplication_application` and `convert_xor` directly, under
a comment marking that as a deliberate exception — *"Keep the parser direct until we wrap it."*

The package is five tracked files — `ravencalc.py`, `steps.py`, `symbolic.py`, `test_ravencalc.py`,
`test_steps.py` — and is deliberately **not** a Python package, reached by inserting its directory
on `sys.path`.

**But there is a second consideration that is not a measurement, and it points the other way.**
There is a **standing SymPy rebrand request**, which #84 names and deliberately declines to act on:
*"Same page as the standing SymPy rebrand request, and deliberately not doing it: that is its own
task, and re-typing the word here is the edit that would hide it."* The repo also carries a vendor
facade and its guards — `symbolic.py`, `backend/apps/test_brand_boundary.py`,
`tools/prove_vendor_facade.py`.

So the choice is **not** technical, and it should not be made by whoever next edits the page:

- **naming SymPy is accurate**, and #84 lists the SymPy claim among the load-bearing claims a
  layout change must not delete;
- **naming SymPy on a public page may be exactly what the rebrand request wants stopped.**

**Garrett's call, and the two are reconcilable** — the *claim* that survives is "exact symbolic
algebra, computed, not guessed", and whether the vendor is named is the rebrand question.
**Recorded rather than decided.** #84 owns the page change.

## 5. Chat co-processor direction

Target architecture, captured — implementation depends on current code proof. **The rule: the model
routes and explains; the algebra engine answers.**

RavenCalc can observe math-like Chat prompts · **parse conservatively** · **false positives are
worse than misses** · on a real expression it computes an exact result · it attaches its own check
where cheap · Chat receives a **verified result, not a vague hint** · Chat should quote or explain
that result rather than recomputing algebra from model weights.

**Parser rule.** Keep parsing conservative. Supported operations include evaluate, simplify, solve,
differentiate, integrate, limit, and series/expand **where implemented**. A candidate must survive
the **strict** parser before being handed to Chat, and **a verified result is never injected into an
unrelated answer** — a wrong result carrying the authority of a check is worse than no result.

## 6. Rack identity — first-class, and it stays that way

`ravencalc` · SyMoNeuRaL RavenCalc · `1U` · **`bus="cpu"`** · `/ravencalc.html` · spec *exact
symbolic algebra* · detail *cpu only, never queues* · ready when app, import and route tests pass.

`backend/api.py:1974` writes `state="ready"` as a **literal**, not derived from a GPU probe — it is
the only row that does, and that is the CPU-only claim expressed in code.

**RavenCalc must not be folded into Studio, Chat or Runtime/ModelOps as a hidden subfeature.** It
may integrate with Chat as a verified math co-processor and **remains its own surface.**

## 7. Rate limits and security

Cheap relative to GPU work but **still meterable**: suggested bucket 240/6000, and it is present in
`_RATE_SUGGESTED` — **absence from that dict would mean *unmeterable*, not unlimited by choice**
(`symoneural-api-surface.md` §4). **No public paid pricing claim**; pricing questions go to the
existing channel.

**RavenCalc should not require a GPU token, a Studio token, or a Miner/ASIC token.** Read and
compute paths stay simple unless current security policy says otherwise; if write, export or
history features are added later, **those are gated separately.**

## 8. Archive mapping

`references/simpy.tar.gz` — 4,002,603 B, **unopened**, **AUDIT until inspected**. Treat it as a
reference/business-calculator archive.

**Do not import it blindly. Do not commit it. Do not replace the existing RavenCalc route or app
from it** unless explicitly authorized. Extract requirements first, and **preserve current working
RavenCalc behaviour** unless a scoped upgrade authorizes replacement.

## 9. Not authorized

No engine work · no page layout change (that is **#84**) · no rename or restructure · no SymPy
rebrand · no archive import or commit · no folder migration · no deploy.
