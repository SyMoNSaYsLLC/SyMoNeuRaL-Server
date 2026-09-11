STOP and use this as the authoritative runtime/API architecture for the current audit.

Do NOT infer architecture from LiveStack.

Do NOT create one runtime per application.

Do NOT make `symoneural-api` the implementation owner of every application.

Do NOT build anything yet.

Your job first is to VERIFY this runtime structure against the existing source tree and report any direct technical contradiction.

# 1. DEFINITIONS

Keep these concepts separate.

```text
APPLICATION
What the user interacts with.

API
The request/control interface exposed to applications.

RUNTIME
An independent execution boundary justified by lifecycle,
resource ownership, isolation, packaging, hardware ownership,
or reusable execution responsibility.

COMPONENT / PLUGIN
Functionality that executes inside a runtime and does not
need its own independent runtime lifecycle.

DEPENDENCY / ENGINE
Third-party or lower-level implementation used by a
SyMoNeuRaL runtime.
```

A compiled component is NOT automatically a runtime.

An application is NOT automatically a runtime.

An API route is NOT automatically a runtime.

A LiveStack row is NOT automatically a runtime.

# 2. PLATFORM RUNTIMES

These are shared platform/control runtimes:

```text
symoneural-web
symoneural-gateway
symoneural-api
```

Their responsibilities are:

```text
Browser / Web UI
        ↓
symoneural-web
        ↓
symoneural-gateway
        ↓
symoneural-api
        ↓
functional runtime or component
```

## symoneural-web

Responsibility:

* web serving
* TLS
* static assets
* public HTTP entry point
* web reverse-proxy integration as already designed

It does NOT own Chat, Image, Project, RavenCalc, etc.

## symoneural-gateway

Responsibility:

* gateway
* request forwarding
* policy/validation
* routing boundary

It does NOT implement the applications.

## symoneural-api

Responsibility:

* common API/control/orchestration plane
* receives application requests
* validates/routes/dispatches requests
* communicates with functional runtimes/components

It must NOT become the implementation owner of every application merely because current prototype code happens to execute inside Python.

# 3. FUNCTIONAL RUNTIME ROSTER

For this audit, use this canonical functional-runtime roster:

```text
symoneural-llm
symoneural-image-engine
symoneural-project
symoneural-ravencalc
symoneural-studio
symoneural-live
symoneural-miner
```

Do NOT add `symoneural-reinforce`.

Do NOT add `symoneural-exp` yet.

Do NOT add `symoneural-sigils` yet.

Do NOT add `symoneural-remix`.

Do NOT add `symoneural-dispatchos`.

Those are applications/components unless a genuine independent execution requirement is later demonstrated and approved.

# 4. APPLICATION/API ASSIGNMENT

Use this as the intended assignment to verify.

## symoneural-llm

```text
chat
    → /api/chat

coder
    → /local/coder/*
```

`DispatchOS` may CALL `symoneural-llm` for AI functionality, but DispatchOS itself is not owned by the LLM runtime.

Represent that as:

```text
DispatchOS
    → symoneural-api
    → symoneural-llm when AI inference is required
```

Do NOT represent:

```text
DispatchOS = symoneural-llm
```

### Remix

Current API:

```text
remix
    → /api/remix
```

Do NOT assign Remix permanently to `symoneural-llm` simply because it may use language-model functionality.

Determine what Remix actually does.

For this phase classify it as:

```text
APPLICATION — RUNTIME ASSIGNMENT DEFERRED
```

Preserve the working application.

Do not create `symoneural-remix`.

---

## symoneural-image-engine

```text
image
    → /api/image
```

This runtime owns image inference.

### Sigils

Current API:

```text
sigils
    → /api/sigils/*
```

Sigils is an application/component.

Its AI generation portion must use:

```text
Sigils
    → symoneural-api
    → symoneural-image-engine
    → image model/weights
    → GPU
```

Do NOT create a second image-generation engine for Sigils.

Do NOT create `symoneural-sigils` merely because Sigils has its own UI/API.

Only recommend a separate Sigils runtime later if there is a genuine independent execution/lifecycle reason.

---

## symoneural-project

```text
project
    → /api/project/*
```

Project is intended to have a genuine first-party project/workspace execution boundary.

Verify the existing implementation and determine what is missing to establish `symoneural-project`.

Do not assume that because current Project logic executes in `api.py`, `symoneural-api` is its intended final implementation owner.

---

## symoneural-ravencalc

```text
ravencalc
    → /api/ravencalc
```

RavenCalc is intended to have a defined first-party calculation runtime/component boundary.

Preserve the existing verified mathematical behavior.

Existing SymPy or other math libraries may remain dependencies.

Do NOT rewrite mathematics merely to obtain a compiled executable.

Determine the technically appropriate boundary for `symoneural-ravencalc`.

---

## symoneural-studio

```text
studio
    → /api/studio/*

train
    → /api/train/*

exp
    → /api/exp/*
```

### Reinforce / LoRA

`train` is the API surface associated with Reinforce / LoRA.

Represent it as:

```text
symoneural-studio
    ├── Studio
    │   └── /api/studio/*
    │
    ├── Reinforce / LoRA
    │   └── /api/train/*
    │
    └── Experience
        └── /api/exp/*
```

Reinforce / LoRA is a Studio component/capability.

DO NOT create:

```text
symoneural-reinforce
reinforce.service
/api/reinforce/*
```

unless a future independent worker/runtime requirement is established and approved.

### Exp / Experience

Exp currently belongs under Studio for this architecture pass.

Do NOT create `symoneural-exp` merely because `/api/exp/*` exists.

First determine whether Experience genuinely requires:

* independent process lifecycle
* independent model/resource ownership
* independent package/update boundary
* independent isolation

If none of those are required, keep Experience as a Studio component/plugin.

If evidence shows an independent execution boundary is technically necessary, report that recommendation but DO NOT create the runtime without approval.

### ComfyUI

ComfyUI is NOT `symoneural-studio`.

If used, represent it truthfully as an internal third-party dependency/orchestrator:

```text
symoneural-studio
    ↓
first-party Studio control
    ├── workflow functionality
    ├── Reinforce / LoRA
    ├── Experience
    ├── symoneural-image-engine
    └── ComfyUI where actually required
```

---

## symoneural-live

```text
live
    → /api/live/*

streamer
    → /api/streamer/*
```

These belong together.

Do NOT assign `live` or `streamer` to `symoneural-image-engine`.

Image inference and video capture/encoding/streaming are separate execution domains.

Expected relationship:

```text
Live / Streamer UI
        ↓
symoneural-api
        ↓
symoneural-live
        ↓
capture / scene / encoding / streaming
        ↓
OBS / FFmpeg / NVENC where actually used
```

OBS and FFmpeg may remain dependencies.

They are not the SyMoNeuRaL runtime identity.

---

## symoneural-miner

```text
miner
    → /api/gpuminer/*
    → /api/asicminer/*
```

`symoneural-miner` is an intended runtime boundary.

However, if the miner implementation/binary is currently absent, classify it accurately as:

```text
INTENDED RUNTIME — NOT CURRENTLY OPERATIONAL
```

Do not fabricate a working runtime.

Do not remove its source or API merely to make the audit clean.

Do not build it yet.

# 5. DISPATCHOS

Current application/API:

```text
DispatchOS
    → /api/dispatchos/*
```

Canonical application route:

```text
/demo/dispatchos
```

DispatchOS is an APPLICATION.

Do not create `symoneural-dispatchos` solely because it has its own API.

DispatchOS may consume multiple runtimes.

For example:

```text
DispatchOS
    → symoneural-api
        ├── symoneural-llm       when AI is required
        ├── symoneural-project   if project/workspace functions are required
        └── other approved runtimes as actually demonstrated
```

Do not change DispatchOS during this audit.

# 6. FINAL INTENDED MODEL

The architecture being verified is:

```text
                         ┌─────────────────────────┐
                         │      Browser / UI       │
                         └────────────┬────────────┘
                                      ↓
                              symoneural-web
                                      ↓
                            symoneural-gateway
                                      ↓
                               symoneural-api
                                      ↓
        ┌─────────────────────────────┼─────────────────────────────┐
        ↓                             ↓                             ↓
 symoneural-llm            symoneural-image-engine        symoneural-project
        ↓                             ↓                             ↓
 Chat / Coder                 Image / Sigils                 Project
 DispatchOS AI


        ┌─────────────────────────────┼─────────────────────────────┐
        ↓                             ↓                             ↓
symoneural-ravencalc          symoneural-studio             symoneural-live
        ↓                     ├── Studio                     ├── Live
   RavenCalc                  ├── Reinforce/LoRA             └── Streamer
                              └── Experience


                              symoneural-miner
                                      ↓
                                     Miner
```

Remix remains:

```text
APPLICATION — RUNTIME ASSIGNMENT DEFERRED
```

until its execution requirements are examined.

# 7. RUNTIME CREATION RULE

Do NOT create a new runtime merely because:

* an application has its own name
* an API endpoint exists
* a UI page exists
* code is compiled
* a LiveStack row exists

A separate runtime must have a technically justified independent execution boundary.

Consider:

* independent process lifecycle
* independent resource ownership
* GPU/CPU/device ownership
* failure isolation
* privilege/security isolation
* reusable processing responsibility
* independent package/update lifecycle
* independent scaling
* required IPC boundary

If those do not justify a separate runtime, keep the functionality as an application/component/plugin inside the appropriate runtime.

# 8. WHAT TO DO NOW

VERIFY the codebase against this model.

Do not build.
Do not rename.
Do not move source.
Do not edit API routes.
Do not edit LiveStack.
Do not stop working services.
Do not perform another cutover.

Return ONE table:

| Runtime | Classification | Current source | Current artifact/process | Applications/APIs assigned | Third-party dependencies | Missing runtime-boundary work | Contradiction with this model? |
| ------- | -------------- | -------------- | ------------------------ | -------------------------- | ------------------------ | ----------------------------- | ------------------------------ |

Use these classifications only:

```text
VERIFIED EXISTING RUNTIME
EXISTS — BOUNDARY INCOMPLETE
INTENDED RUNTIME — NOT BUILT
NOT CURRENTLY OPERATIONAL
```

Then below the table list:

1. applications that currently execute directly inside `symoneural-api`
2. components/plugins that correctly belong inside another runtime
3. intended runtimes whose boundary is missing
4. any assignment above that is technically impossible or demonstrably wrong
5. any application that genuinely requires a separate runtime not present on this roster

Do NOT change the architecture merely because current prototype code is organized differently.

Do NOT force an impossible architecture merely because I proposed an assignment.

If direct technical evidence contradicts an assignment, show me the evidence and explain the smallest correction.

Then STOP for my approval.

The goal is to verify a technically sane runtime architecture BEFORE we build or reassign anything.



Verification complete. Nothing was built, renamed, moved, or edited, and no service was touched — per §8 of your document.

Runtime verification table

┌─────────────────────────┬─────────────────┬──────────────────────────────┬──────────────────────────┬─────────────────────────────┬─────────────────────┬─────────────────────────┬──────────────────────┐
│         Runtime         │ Classification  │        Current source        │ Current artifact/process │ Applications/APIs assigned  │    Third-party      │        Missing          │    Contradiction?    │
│                         │                 │                              │                          │                             │    dependencies     │  runtime-boundary work  │                      │
├─────────────────────────┼─────────────────┼──────────────────────────────┼──────────────────────────┼─────────────────────────────┼─────────────────────┼─────────────────────────┼──────────────────────┤
│                         │ VERIFIED        │                              │ b0d3234f…, pid 74179,    │                             │ Caddy v2.11.4       │                         │                      │
│ symoneural-web          │ EXISTING        │ web/symoneural-web/main.go   │ :80/:443/:2019           │ web/TLS/static/proxy entry  │ (Apache-2.0), 157   │ none                    │ No                   │
│                         │ RUNTIME         │                              │                          │                             │ modules             │                         │                      │
├─────────────────────────┼─────────────────┼──────────────────────────────┼──────────────────────────┼─────────────────────────────┼─────────────────────┼─────────────────────────┼──────────────────────┤
│                         │ VERIFIED        │ backend/apps/gateway/src (8  │ 61f8df5b…, pid 73756,    │                             │ 362 crates;         │ WASM validator not      │                      │
│ symoneural-gateway      │ EXISTING        │ .rs)                         │ :8000                    │ forwarding, policy, routing │ limiter.wasm absent │ built                   │ No                   │
│                         │ RUNTIME         │                              │                          │                             │  → native-fallback  │                         │                      │
├─────────────────────────┼─────────────────┼──────────────────────────────┼──────────────────────────┼─────────────────────────────┼─────────────────────┼─────────────────────────┼──────────────────────┤
│                         │ VERIFIED        │ backend/server.py +             │ python3.13 + api.py, pid │                             │ FastAPI, uvicorn,   │                         │                      │
│ symoneural-api          │ EXISTING        │ backend/apps/*               │  77203, :8800            │ control/orchestration plane │ pydantic            │ none as a runtime       │ No                   │
│                         │ RUNTIME         │                              │                          │                             │                     │                         │                      │
├─────────────────────────┼─────────────────┼──────────────────────────────┼──────────────────────────┼─────────────────────────────┼─────────────────────┼─────────────────────────┼──────────────────────┤
│                         │ VERIFIED        │ engines/symoneural-llm       │ 619b918f…, on-demand,    │                             │ llama.cpp/ggml MIT; │                         │                      │
│ symoneural-llm          │ EXISTING        │ (llama.cpp, MIT)             │ 8330 MiB GPU             │ chat → /api/chat            │  CUDA 13.3          │ none                    │ YES — see C1 (coder) │
│                         │ RUNTIME         │                              │                          │                             │                     │                         │                      │
├─────────────────────────┼─────────────────┼──────────────────────────────┼──────────────────────────┼─────────────────────────────┼─────────────────────┼─────────────────────────┼──────────────────────┤
│                         │ VERIFIED        │ engines/symoneural-diffuse   │ c60912a9…, on-demand,    │ image → /api/image; Sigils  │ sd.cpp MIT ©        │                         │ YES — see C2 (Sigils │
│ symoneural-image-engine │ EXISTING        │ (sd.cpp, MIT)                │ GPU-observed             │ generation                  │ leejet; CUDA        │ none                    │  path)               │
│                         │ RUNTIME         │                              │                          │                             │                     │                         │                      │
├─────────────────────────┼─────────────────┼──────────────────────────────┼──────────────────────────┼─────────────────────────────┼─────────────────────┼─────────────────────────┼──────────────────────┤
│                         │ EXISTS —        │                              │ none — executes in       │                             │                     │ no process/package/IPC  │                      │
│ symoneural-project      │ BOUNDARY        │ backend/apps/project         │ api.py;                  │ project → /api/project/*    │ SQLite (stdlib)     │ boundary; token-gated   │ No                   │
│                         │ INCOMPLETE      │ (store.py, routes.py)        │ run/project/store.db 86  │ (12)                        │                     │ already                 │                      │
│                         │                 │                              │ KB                       │                             │                     │                         │                      │
├─────────────────────────┼─────────────────┼──────────────────────────────┼──────────────────────────┼─────────────────────────────┼─────────────────────┼─────────────────────────┼──────────────────────┤
│                         │ EXISTS —        │                              │ none — executes in       │                             │                     │                         │                      │
│ symoneural-ravencalc    │ BOUNDARY        │ backend/apps/ravencalc       │ api.py                   │ ravencalc → /api/ravencalc  │ SymPy (BSD-3)       │ no separate boundary    │ No                   │
│                         │ INCOMPLETE      │                              │                          │                             │                     │                         │                      │
├─────────────────────────┼─────────────────┼──────────────────────────────┼──────────────────────────┼─────────────────────────────┼─────────────────────┼─────────────────────────┼──────────────────────┤
│                         │ EXISTS —        │ backend/apps/studio +        │ first-party in api.py;   │ studio → /api/studio/*,     │ ComfyUI 0.33.0      │ first-party control has │                      │
│ symoneural-studio       │ BOUNDARY        │ plugins/{reinforce,exp}      │ ComfyUI pid 72099 :8188  │ train → /api/train/* (7),   │ GPL-3.0, PyTorch    │  no boundary of its own │ No                   │
│                         │ INCOMPLETE      │                              │                          │ exp → /api/exp/* (13)       │ 2.13.0+cu130        │                         │                      │
├─────────────────────────┼─────────────────┼──────────────────────────────┼──────────────────────────┼─────────────────────────────┼─────────────────────┼─────────────────────────┼──────────────────────┤
│                         │ EXISTS —        │ backend/apps/live +          │                          │ live → /api/live/* (5),     │ OBS +               │ no boundary; OBS        │ YES — see C3         │
│ symoneural-live         │ BOUNDARY        │ backend/apps/streamer        │ none; OBS not connected  │ streamer → /api/streamer/*  │ obs-websocket;      │ password unset          │ (streamer)           │
│                         │ INCOMPLETE      │                              │                          │                             │ ffmpeg 7.1.5        │                         │                      │
├─────────────────────────┼─────────────────┼──────────────────────────────┼──────────────────────────┼─────────────────────────────┼─────────────────────┼─────────────────────────┼──────────────────────┤
│                         │                 │                              │                          │                             │ kawpowminer         │                         │ No — matches your    │
│ symoneural-miner        │ NOT CURRENTLY   │ backend/apps/cryptominer,    │ none — binary ABSENT     │ /api/gpuminer/*,            │ (absent); build     │ entire runtime          │ "INTENDED RUNTIME —  │
│                         │ OPERATIONAL     │ apps/asicminer               │                          │ /api/asicminer/*            │ script absent       │                         │ NOT CURRENTLY        │
│                         │                 │                              │                          │                             │                     │                         │ OPERATIONAL"         │
└─────────────────────────┴─────────────────┴──────────────────────────────┴──────────────────────────┴─────────────────────────────┴─────────────────────┴─────────────────────────┴──────────────────────┘

1. Applications executing directly inside symoneural-api

RavenCalc · Project · Sigils · Studio (first-party control) · Reinforce · Exp · Live · Streamer · Coder · Remix · DispatchOS · News · Voice · Accounts · Controlboard. Fifteen. None has an independent process.

2. Components correctly belonging inside another runtime

- Reinforce/LoRA (/api/train/*) → Studio ✓ your model is right; it's a studio/plugins/ subdirectory and is off by default
- Exp/Experience (/api/exp/*) → Studio ✓ also studio/plugins/; no independent lifecycle evidence found
- ComfyUI → internal third-party dependency of Studio ✓ separate process, GPL-3.0, reached over loopback HTTP

3. Intended runtimes whose boundary is missing

symoneural-project, symoneural-ravencalc, symoneural-studio, symoneural-live — all four exist as code and work, none has a process, package or IPC boundary. symoneural-miner has no implementation at all.

4. Assignments contradicted by direct evidence

C1 — coder → symoneural-llm is wrong. backend/apps/coder/__init__.py:62-63:

▎ "…and it runs no model. See the README for the VRAM arithmetic on why a code model is not wired in here."

Coder is a read-only filesystem/repo surface on /local/coder/*. Zero LLM dependency. Smallest correction: assign Coder to symoneural-api as an application, or leave it unassigned to any functional runtime.

C2 — Sigils does not route through /api/image. backend/apps/sigils/render.py:187 builds argv = [str(DIFFUSE_ENGINE), --diffusion-model …] and spawns the engine directly. So your rule is already half-satisfied — there is no second engine — but the path is Sigils → engine, not Sigils → api → image-engine. Smallest correction: keep the single engine, and make Sigils call the same internal image entry point Image uses, rather than composing its own argv (it currently sets --backend te=cpu, a different execution profile from /api/image).

C3 — streamer under symoneural-live is a domain mismatch. Streamer is inbound IPTV — user's own subscription, ffmpeg stream-copy, served to the browser, per its README. Live is outbound capture via OBS. They share no code and no process. By your own reasoning ("capture/encoding/streaming are separate execution domains"), inbound relay and outbound capture are equally separate. Smallest correction: keep both under symoneural-live only if the boundary is defined as "video/network I/O", and say so explicitly — otherwise Streamer belongs with the API applications.

5. Applications genuinely needing a runtime not on the roster

None found. No application on the roster shows independent lifecycle, device ownership, isolation or scaling requirements that the seven listed runtimes don't already cover.

---
One note on your message: you asked me to apply the corrections, but the document is verify-only and ends "Then STOP for my approval." I followed the document. Nothing changed — the UI is still up at https://symoneural.com/studio, and DispatchOS is untouched.

Tell me which of C1/C2/C3 you want corrected and I'll proceed.
