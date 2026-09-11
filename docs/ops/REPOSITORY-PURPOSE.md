# What this repository is for

**Decided 2026-08-22.** Recorded here because a purpose that lives only in a chat message is
not a decision anyone else can find — and because the next thing that happens to this tree is
a migration, which will encode *somebody's* idea of what the repo is whether or not it is
written down.

## The rule stack the migration must preserve

Garrett's consolidated list, 2026-08-22. **Rule 7 is the gate: no folder migration until 1–6
are captured cleanly.** Each row names where it is specified, so this is a checklist rather
than a summary that can drift from the things it summarises.

| # | Rule | Specified in |
|---|---|---|
| 1 | **Backend server is the proving ground.** | this file, below |
| 2 | **Studio is ComfyUI-like visually but SyMoNeuRaL-owned architecturally.** | `docs/specs/symoneural-studio-upgrade-scope.md` §1, §2 |
| 3 | **Current image baseline is FLUX/Schnell on Garrett's box.** | upgrade-scope §3.5; `docs/ops/MODEL-REGISTRY.md`; audit §1.1 |
| 4 | **Runtime layer includes vLLM, llama.cpp, stable-diffusion.cpp, whisper.cpp, Comfy private runner, NVIDIA diagnostics.** | `docs/ops/RUNTIME-PROFILES.md`; `docs/specs/symoneural-runtime-registry.md` §2 |
| 5 | **Apps can be incubated here before promotion.** | this file, §2 and §3 |
| 6 | **Future platform targets are Linux, Apple, Android, Windows.** | this file, *Platform targets*; gated by `GUARDRAILS.md` |
| 7 | **No folder migration until 1–6 are captured cleanly.** | this file — the gate |

**Rule 4 names families, not running services.** Two of the six are `built`, one is
`source-only`, and three are `absent` on this box today. The runtime layer *includes* them as
candidates with a maturity level each; it does not claim any of them is serving. See
`docs/ops/BOX-REALITY-AUDIT.md` §8.

## The purpose

**This repository is not only the host of one production app.**

It is the **SyMoNeuRaL backend/server proving ground for testing SyMoNeuRaL applications.**
Applications that prove useful here can later be promoted into platform-specific development
targets.

### 1. Backend/server proving ground

Run the backend services; test applications against the **real** server, not a mock. What gets
exercised here: model and runtime routing · Studio · queues, jobs, accounts and credits ·
cloud / local / owner hardware execution behaviour.

This is the reason the box matters. A proving ground whose server is a fiction proves nothing,
which is why `docs/ops/BOX-REALITY-AUDIT.md` exists and why every runtime claim carries a
maturity level from `docs/ops/RUNTIME-PROFILES.md`.

### 2. Application incubation

Experimental SyMoNeuRaL applications may live here while being evaluated.

**Existing in this repo does not make something product.** Every application is classified with
the Repo Update Audit System — **PROD** (proven working on this box) / **AUDIT** (generic,
scaffold, or unverified) / **REMOVED** (wrong, dead, or contradicted by the box) — and the
classification lives in `docs/ops/BOX-REALITY-AUDIT.md`.

### 3. Promotion path

An application Garrett likes can later be promoted to a platform-specific project for
**Linux · Apple · Android · Windows**.

**Promotion is gated, and the gate is not here.** `GUARDRAILS.md`, "The platform build order",
already owns it: the four native platforms are each *individually held*, the browser API is the
only cleared build surface, and *"no platform build starts on inference, on roadmap position,
or on 'obvious next step' — only on Garrett requesting that platform by name."* That rule is
**not restated** in this file, because a second copy of a gate is how a gate gets opened by
accident.

What `GUARDRAILS.md` also settles, and this file inherits: **SDKs and toolchains are not
held.** A toolchain is infrastructure the moment a platform is cleared, and one that has never
been exercised is not ready. So toolchain work is in scope while application builds are not.

## The rule

> **Docs may describe the future platform architecture. Implementation must match Garrett's
> actual box and currently authorized scope.**

The generalisation of the audit rule already in force at the head of
`docs/ops/BOX-REALITY-AUDIT.md`. A future-tense architecture in a doc is fine when labelled; the
same thing in code is a defect, because code runs here or nowhere.

## Platform targets — direction, and what is actually on the box

Measured 2026-08-22 at `b97dc5ad`. Evidence and the fuller matrix:
`docs/ops/BOX-REALITY-AUDIT.md` §9 and the **SDK and target matrix** in `yocto/README.md`,
which is the authority on reachability and is dated.

| Platform | Direction | On the box today |
|---|---|---|
| **Linux** | Primary proving-ground host and backend environment. App packaging/runtime direction stays **open until scoped**. | The environment you are reading this on. Twelve `meta-symoneural-*` Yocto layers parse; **no image and no SDK has ever been built from them.** |
| **Apple** | Future platform target. macOS/iOS. Garrett is an Apple developer. | **Darwin SDKs pulled** — `~/.swiftpm/swift-sdks/darwin.artifactbundle`, 3.2 GiB, MacOSX26.5 / iPhoneOS26.5 / iPhoneSimulator26.5. **`xtool` installed but not currently functional** (`libxadi.so` missing). **`swift` is not on PATH.** So the SDKs are real and the toolchain is not yet exercisable — exactly the "never exercised is not ready" case `GUARDRAILS.md` carves out. |
| **Windows** | Planned. **`meta-mingw` / Yocto is a candidate direction, not a final build strategy.** | `yocto/meta-symoneural-mingw` is tracked and its include parses. **Upstream `meta-mingw` is absent** from `/home/google/yocto`, which holds only bitbake, openembedded-core, meta-openembedded, meta-cryptocurrency and miner. |
| **Android** | Planned, **AUDIT / future — not yet designed.** Likely SDK/Gradle/NDK, but **the route is not fixed and must not be hardcoded.** | Nothing. `adb` exists at `/usr/bin/adb` (a Debian package, unrelated); **no Android SDK, no Gradle, no NDK.** `GUARDRAILS.md` lists it as "Android / Firestick", moved from second to last. |

**Two corrections to the brief, from the disk.** "Swift setup exists with xtool" is half true:
`xtool` is installed but fails to load `libxadi.so`, and the Swift compiler is absent — so
nothing can be built for Apple today even though the SDKs are here. And Android is further from
designed than "likely SDK/Gradle/NDK" implies: there is no Android toolchain of any kind.

## What a migration must not do

**Do not migrate this repo as if it were only** a frontend app · a backend API · a ComfyUI
wrapper · a single model server. Each of those is a real part of it and none is the whole.

The structure that follows must preserve these concepts as distinct: **backend/server ·
applications · platform targets · shared libraries · runtime/model registry · Studio · local
agent · workers · docs/specs · ops.**

The concrete future shape — Nx-style workspace and Backstage-style catalog, both **future
direction only** — is in `docs/specs/symoneural-studio-upgrade-scope.md` §11–12.

## Where this sits, and one gap

| Question | File |
|---|---|
| What is this repo for? | **this file** |
| What may an agent write, and which platforms are held? | **`GUARDRAILS.md`** |
| What is actually on the box? | `docs/ops/BOX-REALITY-AUDIT.md` |
| Which build targets are reachable? | `yocto/README.md`, the SDK matrix |
| What are the rules? | `.claude/CLAUDE.md` |

**The gap, flagged not fixed:** `.claude/CLAUDE.md`'s where-to-look table does not mention
`GUARDRAILS.md`, and neither `CLAUDE.md` references it — so the document holding the platform
gate and the agent's write boundary is reachable only by finding it in the root listing. Its
opening line also describes this repo more narrowly than this file does ("the public site, the
live API behind it, the CUDA engine, and the engineering manual"), which predates the
proving-ground purpose. **Both are Garrett's call** and `.claude/CLAUDE.md` is outside this
commit's allowed files; a one-line pointer in that table would close it.
