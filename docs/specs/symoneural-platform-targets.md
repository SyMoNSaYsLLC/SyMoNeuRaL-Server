# SyMoNeuRaL Platform Targets — direction, and the contract a target has to satisfy

**Scope captured 2026-08-22.** Direction only. **No platform or toolchain build work is
authorized by this document**, and none is started by it.

An application that proves useful in the lab can later be promoted to a platform-specific
target: **Linux · Apple · Android · Windows.** This file says what a target *is* in SyMoNeuRaL
terms, so that promotion is a defined operation rather than an improvisation. It is the
platform half of `docs/specs/symoneural-application-lab.md`, which is the application half.

## Three things this file deliberately does not contain

Written down because each omission is load-bearing, and a future editor "completing" this file
would break something:

1. **The gate.** `GUARDRAILS.md`, *The platform build order*, owns it: the browser API is the
   only cleared build surface, the four native platforms are **each individually held**, and no
   platform build starts on inference, roadmap position, or "obvious next step" — only on
   Garrett requesting that platform **by name**. It is not restated here, for the reason
   `docs/ops/REPOSITORY-PURPOSE.md` gives: *"a second copy of a gate is how a gate gets opened
   by accident."*
2. **The measured state of each platform on this box.**
   `docs/ops/REPOSITORY-PURPOSE.md`, *Platform targets*, holds the dated, measured table —
   what SDKs are present, what parses, what is absent. Copying it here would produce two
   readings that disagree the first time one is re-measured.
3. **Which build targets are reachable.** The top-level `yocto/README.md` SDK matrix is the
   authority, it is dated, and `GUARDRAILS.md` puts it explicitly in scope now under the
   toolchain carve-out.

So: **gate → `GUARDRAILS.md`. Measured state → `REPOSITORY-PURPOSE.md`. Reachability →
`yocto/README.md`. Contract and direction → this file.**

## 1. The rule, applied to platforms

> **Docs may describe the future platform architecture. Implementation must match Garrett's
> actual box and currently authorized scope.**

For platforms this has a sharp edge: **three of the four cannot run anything on this box
today**, and the fourth is the box. A future-tense platform architecture in this file is
correct. The same thing expressed as a build script, a CI target, or a `platform-*/` directory
would be a defect, because code runs here or nowhere.

## 2. The carve-out that makes toolchain work legitimate now

`GUARDRAILS.md`: **SDKs and toolchains are not held.** The development platforms must be ready
and online; toolchains get built and kept working even though the applications do not.

The reason given there is the one that matters: *"a toolchain that has never been exercised is
not ready."* An SDK sitting on disk is not a capability. This is the difference between

- **in scope now** — installing, wiring and *exercising* a toolchain; recording in
  `yocto/README.md` what it can reach; fixing a toolchain that cannot run at all
- **held** — building a SyMoNeuRaL application for that platform

The one trap: **"the SDK is present" must never be reported as "the platform is ready."**
`REPOSITORY-PURPOSE.md`'s measured table already carries a live example — Apple's Darwin SDKs
are on disk at 3.2 GiB while `swift` is not on `PATH` and `xtool` cannot load `libxadi.so`. SDKs
real, toolchain not exercisable, platform not ready. Three distinct states, and only measurement
separates them.

## 3. Platform contract — what any target must define before it is a target

A promoted application needs answers to all of these. **A platform with unanswered rows is
direction, not a target**, and calling it one is the failure this section prevents.

| Row | What it fixes |
|---|---|
| `platform_id` | Stable identifier used by the registries and the resolver |
| Toolchain | Compiler, SDK, build system, and **where it was last exercised** |
| Reachability | Which artefacts this toolchain can actually produce today — `yocto/README.md` is the authority |
| Artefact | What ships: package, bundle, image, installer |
| Runtime availability | Which runtime families from `docs/ops/RUNTIME-PROFILES.md` exist on that platform at all |
| Acceleration | GPU/NPU path, or none — and **no CPU fallback is assumed** for a GPU workload |
| Local agent | Whether the hardware probe of `symoneural-studio-upgrade-scope.md` §5.2 can run there, since browser-only detection is approximate |
| Execution target mapping | Which of `CLOUD` / `LOCAL_CUSTOMER` / `LOCAL_OWNER_NVIDIA` / `AUTO` this platform can serve |
| Signing / distribution | Store, notarisation, or repository — and who holds the credential |
| Licence posture | What may ship, per `docs/ops/EXPORTS.md` and `LICENSES.md` |

**Two rows are structurally Garrett's**, by the `owner: garrett` categories in
`.claude/CLAUDE.md`: signing credentials, and any developer-program or store account. An agent
cannot fill those in and must not file a task pretending otherwise.

## 4. The four, as direction only

Status words below are **direction**, not readiness. Readiness is the measured table in
`REPOSITORY-PURPOSE.md`.

### Linux
**Primary proving-ground host and backend environment** — the platform this repository runs on,
and the reason the box is the reference for every implementation claim.

**App packaging and runtime direction stays open until scoped.** The repo already ships Debian
packaging machinery (`scripts/build-deb.sh`, `ops/install-service.sh`, systemd units) for *the
server*. That is not the same decision as how a promoted *application* is packaged for Linux,
and the second one is not made. Yocto/embedded appliance images are a separate route again —
`docs/specs/symoneural-application-lab.md` §3.10.

### Apple
**Future platform target only.** macOS and iOS. Garrett is an Apple developer; the Darwin SDKs
have been pulled.

The gap is the toolchain, not the SDK — see §2. Under the carve-out, making `swift` and `xtool`
actually work is legitimate infrastructure work; building a SyMoNeuRaL application for Apple is
**held** until Garrett names Apple.

### Windows
**Planned. `meta-mingw` / Yocto is a candidate direction, not a final strategy.** The brief says
so explicitly and this file does not upgrade it: *"Final Windows strategy is not locked yet."*

`GUARDRAILS.md` notes Windows is **new scope**, not among the original four. Nothing may
hardcode the mingw route while it is a candidate; if it is later chosen, that is a decision with
a date, not an inheritance from this sentence.

### Android
**Planned, AUDIT / future — not yet designed.** Likely SDK / Gradle / NDK, but **the route is not
fixed and must not be hardcoded.**

`GUARDRAILS.md` records it as "Android / Firestick", **moved from second to last** in the build
order. This is the least-designed of the four and the doc says so rather than lending it the
shape of the others.

## 5. Promotion — the operation, not the permission

Promotion is: an application proven in the lab → a platform-specific target satisfying §3.

The permission is `GUARDRAILS.md`'s and is per application and per platform. Two of its rules
bear directly on how a promotion is done:

- **No numbered tasks exist for the four.** Queueing them would present gated work as cleared.
  So there is no `PROJECT-TASKS.md` row for Apple, Windows or Android, and their absence is
  deliberate rather than an oversight to be corrected.
- **A cleared platform gets a fresh task, not a revival.** The retired `symonsaysllc` Tauri
  desktop scaffold and `mobiletv` Kotlin scaffold **stay retired**, and existing platform work
  stays exactly where it is: not advanced, not deleted.

The lesson behind "fresh task, not a revival" is already recorded in `.claude/CLAUDE.md`: #94
shipped a desktop client whose eighteen checks went green over a chat surface that was dead on
arrival, because a missing Tauri capability meant the page was never permitted to hear the
stream it had asked for. **A platform target's first task must include a check only a real run
on that platform can turn green.**

## 6. What is not authorized by this document

No platform build · no toolchain installation performed *by* this document · no SDK download ·
no `platform-*/` directory created · no folder migration · no deploy · no CI target · and no
change to which platforms are held.

`docs/specs/symoneural-studio-upgrade-scope.md` §12 holds the future Nx-style workspace shape,
including its `platform-linux/`, `platform-apple/`, `platform-android/` and `platform-windows/`
boundaries. Those are **future direction only** and creating any of them is a migration, which
is not authorized.
