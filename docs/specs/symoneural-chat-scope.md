# SyMoNeuRaL Chat — scope, and the privileged surface it is becoming

**Scope captured 2026-08-22.** Docs and scope only. **No implementation, no public filesystem
route, no token or gate change, no archive import, no deploy.**

## 1. What it is

> **SyMoNeuRaL Chat is the primary conversational surface for this server.**

Local infrastructure assistant · GPU-backed LLM surface · hardware-aware and measurement-bound ·
model/runtime-routed through the SyMoNeuRaL stack · **shares the one GPU** with Image, Remix,
Studio/Reinforce, Sigils and Miner · can receive verified CPU-side RavenCalc results · **future
host for Project / cowork / coder capabilities.**

Classification: **PROD direction**, current implementation preserved and audited before
migration. Rack row `chat`, `bus="gpu"`, `/chat.html`.

## 2. Model and adapter labels — say only what the files prove

The page currently carries **`SymonChat S1-7B`** (`site/chat.html:85`) and **`persona adapter`**
(`:336`).

**These are preserved only while current files and tests still prove them.** Anything not proven
is marked AUDIT rather than restated. The registry is the eventual home for this truth
(`docs/ops/MODEL-REGISTRY.md`), and once it exists **the page must not hardcode a model label** —
`symoneural-parameters.md` §4 is the general form of that rule.

**Forbidden without current proof:** token/sec · pricing · throughput · multi-user capacity ·
cloud capacity · model benchmark numbers · revenue · any hidden model claim.

**Allowed, because measured:** RTX 5070 Ti · 15.92 GiB VRAM · one GPU shared across the surfaces
above · chat and image weights do not both fit at once · decode is memory-bandwidth bound ·
RavenCalc is CPU-only and does not queue behind the GPU. The API's own description already states
most of this (`api.py:1391-1396`) and it is the model to follow.

## 3. GPU rules

- **Acquire the lease for active generation; release it when the request ends** — on normal
  finish, on error, **and on client disconnect.**
- **Residency is not the work lock.** A resident-but-idle chat model **must not** be reported as
  actively holding the GPU unless the governor says it is doing work. This distinction is the one
  most easily lost in a status line, and getting it wrong makes the rack read *busy* forever.
- Respect queue limits and timeout behaviour; report queue-full clearly.
- **No silent CPU fallback.** `BOX-REALITY-AUDIT.md` §2.2 records that the code has none, and
  that it is PROD.
- **Must not block RavenCalc**, which is CPU-only by design.

## 4. RavenCalc as a verified math co-processor

Direction, captured as target architecture. **The rule is one line: the model routes and explains;
the algebra engine answers.**

- Chat prompts are inspected for math-like content by a **conservative** parser.
- **False positives are worse than misses.** A wrong "verified result" injected into an unrelated
  answer is more damaging than not offering one, because it carries the authority of a check.
- A candidate must survive the **strict** parser before anything is handed to Chat.
- If RavenCalc computes an exact result, Chat receives it as **verified context** and should quote
  or explain it rather than recomputing algebra from model weights.
- Streamed responses may expose a RavenCalc assist event carrying operation, input, result, check
  and timing — **where implemented.**
- **Never inject a verified result into a non-math answer.**

## 5. Project / cowork / coder inside Chat — and why this makes Chat privileged

Garrett, 2026-08-22: *"SyMoNeuRaL Project / cowork / copilot belongs inside Chat"*, the coder
should be reachable from the browser, and a browser coder may need filesystem access to the
machine it runs on.

**That combination is the important part.** A conversational surface plus filesystem tools plus a
browser is a privileged local surface, and **`/api*` is proxied to the public internet by
`ops/Caddyfile`.** So:

- **Filesystem and coder routes do not live under public `/api`** unless a specific authenticated
  gateway is designed and approved. There is no `/api/coder/*` today and a test asserts its
  absence.
- The gate posture is **already built** for Coder and is the pattern to reuse rather than
  reinvent: enable flag **and** non-empty token (constant-time compared), loopback-only unless
  `ALLOW_REMOTE`, configurable workspace root, every path `resolve()`d so symlinks are followed,
  and a denylist applied to the **resolved** absolute path. Detail and line numbers:
  `symoneural-coder-project-cli-scope.md` §4.
- **Read-only and write modes stay separate**; destructive operations need explicit confirmation
  and logging; **no raw shell**, no arbitrary Python or Bash for public users; the browser route
  must not bypass server-side checks.

**Protected and unreachable through a browser coder:** `training/corpus.jsonl` ·
`training/build_dataset.py` · `training/adapter*` · `.env` and secrets · private ledgers · model
weights · raw archives · proprietary references · anything outside the workspace root.

**No token posture is changed by this document.** If the posture is being changed elsewhere, it is
not changed here.

**Project/cowork is AUDIT until implemented and tested.** Open task **#83** carries it; the
capability's scope is `symoneural-coder-project-cli-scope.md` §2, and the reference archive
`@symoneural code.tar.gz` is **AUDIT** — and, as §1 of that file records, contains **no
first-party code**, so it is behaviour reference only. **No proprietary Claude/Codex source may be
copied.**

## 6. API behaviour to preserve or document

Streaming behaviour and server-sent events where used · max-token clamp · temperature clamp ·
model label emitted at completion **only if the code supports it** · adapter flag likewise ·
RavenCalc assist event likewise · **rate limiting against the `chat` bucket, not a generic one**
(120/2000 suggested; `symoneural-api-surface.md` §4 explains why an absent name is *unmeterable*
rather than unlimited) · no-cache streaming headers · **clean lease release on normal finish,
error, or client disconnect.**

**Do not claim OpenAI-compatible API behaviour.** None is implemented; `/v1` belongs to the
gateway.

## 7. Runtime direction

Chat fits the wider ModelOps/RuntimeOps scope: **vLLM** as a cloud/high-throughput candidate,
**llama.cpp** as the local/GGUF candidate — and **the current local runtime must be audited before
it is labelled.** Of seven runtime families, two are built, one is source-only and four are absent
(`BOX-REALITY-AUDIT.md` §8), and **no document may claim a runtime is running.**

Model registry owns model id, path, provenance, format, VRAM estimate and adapter status; the
runtime registry owns runtime id, health, API style and load/swap behaviour. **Hot swap and model
selection belong to Studio/RuntimeOps, not to hidden Chat-only behaviour.**

## 8. Page copy direction

The page should make plain that Chat is the conversational surface, is local/server-backed, uses
the GPU, **may queue behind other GPU work**, and that **RavenCalc stays available for exact math
while the GPU is busy**. Project/cowork is future/AUDIT unless implemented and tested.

If a Project mode ever becomes visible, it says what it is and what it is not: a browser-based
cowork surface for repo-aware planning and review, whose **filesystem access is privileged, rooted
and gated — not a public shell.**

## 9. Not authorized

No implementation · no filesystem route under `/api` · no gate or token change · no model label
change · no archive import · no proprietary source copied · no folder migration · no deploy.
