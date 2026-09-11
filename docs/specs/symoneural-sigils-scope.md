# SyMoNeuRaL Sigils — scope, and the meter that is already wired

**Scope captured 2026-08-22.** Docs and scope only. **No engine rewrite, no model download, no
weight committed, no fold into Image, no deploy.**

## 1. What it is

> **SyMoNeuRaL Sigils is the sticker / sigil / mark generation surface.**

GPU-backed generator for compact symbolic marks — stickers, icons, seals, badges, glyph-like
outputs, branded visual tokens. **Related to Image, not identical to it.** Metered as its own
surface, governor- and queue-aware because it spends the GPU.

Classification: **PROD direction**; current implementation preserved and audited before migration.
Rack row `sigils`, `bus="gpu"`, `1U`, `/sigils.html`.

**Do not call it:** just Image · just branding · a static asset page · CPU-only · **or `ready` when
its engine or route proof is missing.**

## 2. Measured API surface — five routes, and the brief was right about the shape

`backend/apps/sigils/routes.py`, mounted at `/api/sigils`:

| Route | |
|---|---|
| `GET /packs` | themed starting prompts |
| `POST /render` | one sticker with a transparent background |
| `POST /from-image` | a sticker from a picture — background removed, or re-drawn |
| `POST /from-audio` | a sticker from speech: say what it should be of |
| `GET /state` | what this surface can do, and what it last did |

Two GETs and **three POSTs**, as the brief expected. `/state` returning *"what this surface can do,
and what it last did"* is the right shape for a real readiness endpoint rather than a decorative
one.

## 3. Rate limiting — configured **and** wired, with the trap already documented

**This is the requirement the brief was most worried about, and it is already satisfied.**

`api.py:241-251` carries `"sigil": (20, 300)` and, beside it, the reasoning in full:

> *"the name is listed here for a reason that is not cosmetic: `LIMITS` is built by iterating this
> dict, and `check_rate` returns True for any surface it does not find. A name absent from here is
> not 'unlimited by choice', it is **unmeterable**, and `SYMONEURAL_RATE_SIGIL` would be read by
> nothing. This surface is the one aimed at a phone app, so leaving it unmeterable was the wrong
> default to inherit."*

And the wiring is **tested**, not assumed. `apps/sigils/test_sigils.py:456-475` asserts three
distinct things:

1. the router is **not** mounted with no `dependencies=` at all;
2. `dependencies=` actually **throttles** (`throttled_for` is present);
3. it throttles against the **right surface** — throttling against the wrong one is its own bug,
   named separately.

**Consequences to preserve:** metering is **router-wide**, so `/packs` and `/state` are metered too
— correct, because a phone client polls them. **New `/api/sigils` routes are metered by default** by
virtue of being on that router. And **a configured bucket consulted by nothing is red**, which is
exactly what the test prevents.

## 4. Relationship to Image, and to Studio

| | |
|---|---|
| **Image** | general prompt-to-image and image-to-image; the larger generation workflow |
| **Sigils** | specialised sticker/sigil/badge/mark generation, with its **own** packs, templates, presets, state and rate bucket |

**Do not collapse Sigils into Image** unless explicitly authorized. If a future migration folds it,
**document it first and preserve route and backward compatibility.** It uses Image's engine family
under the hood — the FLUX/Schnell path (`symoneural-image-scope.md` §2) — and sharing an engine is
not the same as being the same surface.

**Studio** may eventually carry Sigils nodes — sigil prompt, template/preset, transparent
background, badge/seal export, pack generator, metadata/provenance. **Sigils stays a simple product
surface for people who do not need Studio.** Do not force a casual user into Studio, and **do not
expose raw ComfyUI as Sigils.**

## 5. Engine dependency and honest state

Sigils depends on the image engine path. **If that path or the model files are missing, Sigils must
not report `ready`** — and if the API route exists while the page does not, the status must say
*route exists, page missing*, **not** green product-ready.

GPU rules, as everywhere: acquire the lease for active generation and release it on completion ·
**residency is not active work** · respect queue limits and timeouts · **no silent CPU fallback** ·
**must not block RavenCalc**, which is CPU-only by design · **generated output must exist and be
reachable before success is returned** · **no fake preview and no stale last-known output presented
as a fresh render.**

## 6. Controls and outputs — nothing decorative

Potential controls: prompt · style/pack · seed · size · transparent background · sticker border ·
detail level · variant count · export format · safe preset · brand palette if scoped.

**Every visible control must reach the engine.** `symoneural-parameters.md` §2 is the contract, and
the prohibitions here are concrete: **no decorative sliders · no inert style pickers · no pack names
not backed by current data · no fake transparency if the output is not transparent · no fake vector
export if the output is PNG only · no SVG export unless real vectorisation exists.**

**Output vocabulary must be exact.** Raster PNG · transparent PNG *if supported* · SVG/vector *only
if implemented* · pack/batch *only if implemented* · metadata/provenance *if implemented*. **Do not
call a PNG an SVG. Do not call a generated bitmap a vector.**

Generated outputs should record: prompt · seed · pack/style · model profile · runtime · size ·
transparency flag · created time · job id · **source app: `sigils`.**

## 7. The legal boundary — this surface generates logos and seals

Sigils can generate marks that look official, so the page copy has to be careful.

**Do:** call them generated marks, stickers, sigils · allow user-owned branding experiments ·
record provenance · avoid legal claims.

**Do not:** claim trademark clearance · claim a generated logo is legally safe · claim brand
ownership · impersonate official marks · generate official-looking credentials or badges without
policy and guardrails if that path is exposed.

**No trademark or legal-clearance claim unless separately implemented and reviewed.** This is not
boilerplate — "your logo is clear to use" is a legal opinion, and nothing here produces one.

## 8. Registry direction

Sigils uses the **same** model and runtime registries as Image. **Do not create a separate hidden
Sigils model registry**, and **do not hardcode model truth in the page once the registry exists.**
A specialised Sigils model or adapter is **future AUDIT** unless the registry proves it exists.

No separate Sigils reference archive has been identified. If one is found: **AUDIT until inspected**,
do not import, do not commit, extract requirements first.

## 9. Not authorized

No engine rewrite · no control added or removed · no fold into Image · no model download · no weight
committed · no generated output committed except an explicit test fixture · no rate-bucket change ·
no folder migration · no deploy.
