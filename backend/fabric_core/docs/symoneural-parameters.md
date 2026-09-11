# SyMoNeuRaL Parameters — the control contract, and why a fake slider is a defect

**Scope captured 2026-08-22.** Docs only. **AUDIT until scoped. No implementation.**

Studio-family / RuntimeOps concept. Named explicitly so a migration cannot erase it.

## 1. What it is

> **Parameters is the contract between a control a person can see and a value an engine actually
> reads.**

One schema serving Studio, Image, Sigils, Chat, Remix and Reinforce, so each app stops
hardcoding its own idea of what a knob means.

It owns: **defaults · bounds · locked values · hidden values · inert values · validation · UI
control metadata · docs and API links per parameter.**

## 2. The rule that makes it worth having

> **Every visible control must reach the engine.**

**No fake sliders. No inert control presented as active.** This is not a style preference — it is
the same defect class as a decorative status LED, and this repo has shipped that defect
repeatedly enough to have a name for it. `.claude/CLAUDE.md` records #94: eighteen checks green
over a chat surface that was dead on arrival. A slider that moves and changes nothing is that
failure at the widget level.

There are three honest states for a control that does not do what it looks like it does, and
**a doc must say which one applies**:

| State | Meaning | Presentation |
|---|---|---|
| **locked** | the engine reads it, but only one value is valid here | shown, fixed, and the reason given |
| **inert** | the engine accepts it and it has no effect on this model profile | hidden, disabled, or **explicitly labelled inert** |
| **unsupported** | the engine does not read it at all | absent |

**A fourth state — shown, active-looking, and ignored — is the defect.**

## 3. The worked example that already exists: FLUX/Schnell

The current image baseline is FLUX/Schnell (`BOX-REALITY-AUDIT.md` §1.1, §1.2), and it makes the
distinction concrete rather than theoretical:

- **`cfg` is locked at 1.0 for Schnell.** Shown fixed, or shown with the reason it cannot move.
- **`negative prompt` is inert at cfg 1.0.** It is accepted and does nothing. So it is hidden,
  disabled, or labelled inert — **never presented as a way to improve output.**
- **Raising cfg is not a quality improvement for Schnell.** A doc or tooltip suggesting otherwise
  is wrong.
- **FLUX guidance is embedded conditioning**, not SDXL-style classifier-free guidance. The two
  are not the same mechanism and must not share one control's copy.

**SDXL controls must not leak into FLUX/Schnell as false knobs.** SDXL is not installed —
`BOX-REALITY-AUDIT.md` §7 lists "SDXL as the current baseline" under **REMOVED**. So SDXL
parameter behaviour is *future/example only*, and a control designed for it is a fake knob here
by construction.

## 4. Who owns which half

| Owner | Owns |
|---|---|
| **model registry** | which controls a model **supports**, its defaults, its locked values |
| **runtime registry** | which parameters a runtime **accepts** |
| **API** | **server-side clamping** — always, regardless of what the UI sent |
| **Parameters** | the shared schema, the UI metadata, and the docs/API link per parameter |

**Server-side clamping is not a duplicate of UI validation.** The UI is a suggestion; the API is
the boundary. `symoneural-api-surface.md` §6 states it as a standing rule.

**Parameters must not become a third registry.** It describes and validates; it does not store
model or runtime truth. Same rule as `symoneural-generic-contracts.md` §3.

## 5. The parameter set to carry forward

Named so migration preserves them, **not** as an implementation list:

`prompt` · `seed` (expose it — reproducibility matters) · `steps` (with model-specific guardrails;
Schnell is a 4-step model) · `size` / aspect (within known safe bounds) · `cfg` / guidance
*where valid* · `negative prompt` *where valid* · `denoise` / strength (image-to-image) ·
`adapter` / LoRA selection · runtime target · hardware profile · batch / variant count *where
supported*.

Each entry needs, when scoped: type · default · bounds · locked? · inert-on-which-profiles? ·
which runtimes accept it · `docs_href` · `api_href`.

## 6. Not authorized

No parameter schema implemented · no control added, removed or relabelled on any page · no
registry field added · no model or runtime change · no folder migration · no deploy.

Related: `symoneural-studio-node-system.md` §2 (node fields) · `ops/docs/MODEL-REGISTRY.md` ·
`ops/docs/RUNTIME-PROFILES.md` · `symoneural-generic-contracts.md` (`GenericParameter`).
