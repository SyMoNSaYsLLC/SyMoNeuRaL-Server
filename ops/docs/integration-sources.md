# Upstream sources — what to reuse, what to mine, what to leave alone

Recorded 2026-08-18 from Garrett's source list. This is a **standing backlog**, not a plan of
record: nothing here is scheduled, and nothing here is committed to. It exists so the next
person (or the next context window) does not have to re-derive why a given upstream project was
or was not adopted.

`.claude/HANDOVER.md` remains the one state document. This file answers only *"what did we look
at, and what did we decide about it."*

---

## The framing problem with the blueprint

The accompanying architecture blueprint — Kubernetes, Envoy, Temporal, Ray, Triton, vLLM,
Milvus, Keycloak, ELK, MinIO, BentoML, MLflow — is a **good design for a multi-node cluster with
elastic GPUs**. It is written for a fleet.

This is one box: a single RTX 5070 Ti, **15.92 GiB**, behind `scripts/gpu-governor.sh`, serving a
public site from one FastAPI process. Roughly two thirds of the blueprint's rows are either
already implemented here in a smaller form, or would actively make this machine worse. That is
not a criticism of the blueprint; it is a statement about which machine it was written for.

The honest summary: **adopt the data layers, skip the orchestration layers.**

---

## Row-by-row: what this stack already has

| Blueprint row | Their pick | What is already here | Verdict |
|---|---|---|---|
| API / gateway | Envoy, Kong, Traefik | **Caddy** (TLS, WS upgrade, no rewrites) + **`symon-gateway`** (Rust, payload validation, forwards `/api/*` opaquely) | done, and smaller |
| Service framework | FastAPI / NestJS | **FastAPI**, one process, `backend/server.py` | done |
| LLM serving | vLLM, Triton, BentoML, KServe | **llama.cpp** `llama-server` + persona LoRA, started on demand inside `gpu.hold("chat")` | done — see the vLLM note below, and the BentoML note |
| Model registry | MLflow, BentoML | **`run/registry.json`**, built out-of-band by `tools/build/build_registry.py`, read by `/api/studio/models` | done, deliberately minimal |
| Image models | diffusers, A1111, ComfyUI, InvokeAI | **ComfyUI** (+ `ComfyUI-GGUF`, `custom_nodes/symoneural_gguf`) and **stable-diffusion.cpp** | done |
| Agents / tools | LangChain, AutoGen, Semantic Kernel | **`apps/studio/agent.py`** + a stdlib tool registry + FastMCP | done, no framework |
| Orchestration | Temporal, Ray, Celery, Airflow | **`scripts/gpu-governor.sh`** — a mutex, because there is one worker | see below |
| Object store | S3 / MinIO | the filesystem, `backend/output/`, served by `/api/gen/<name>` | done |
| Metadata | Postgres | SQLite (`apps/project`), JSON files | adequate |
| Observability | Prometheus, Grafana, OTel, ELK | `/api/status`, the rack, `run/` logs | **gap, but a small one** |
| Auth | Keycloak, Auth0, Okta | `apps/accounts` + per-surface `SYMONEURAL_*_TOKEN` | gap: no self-serve keys |
| **Vector store / RAG** | Qdrant, Milvus, Weaviate, Chroma | **nothing** | **real gap** |
| **Embeddings** | sentence-transformers | **nothing** | **real gap** |
| **Web search** | SerpAPI, Bing, MeiliSearch | **nothing** | **real gap** |
| **Scraping / ingest** | Scrapy, Playwright | Playwright is installed (`contrib/llama.cpp/tools/ui/node_modules`) but only drives tests | **real gap** |
| **Evaluation** | W&B, MLflow evals | `training/` measures loss, nothing measures answer quality | **real gap** |
| Human-in-the-loop | Label Studio | `training/corpus.jsonl` is hand-authored — the same job, done by hand | fine at this size |

### Why not vLLM, Triton, Ray, Temporal or Kubernetes here

Not dogma — each one loses on this specific box:

- **vLLM / Triton** hold weights resident for the process lifetime. That is the exact pattern
  `.claude/CLAUDE.md` forbids: *"Hold the lock for a job, never for a process lifetime."* With
  a 7B model resident there is not enough of 15.92 GiB left for an image render or a QLoRA run,
  and `chat`, `image` and `train` would sit blocked on `acquire` until it timed out. vLLM's
  throughput advantage is a *batching* advantage, and there is no concurrent batch here.
- **Ray / Temporal** are for coordinating many workers. There is one GPU. A durable workflow
  engine in front of a mutex is a queue in front of a queue.
- **Kubernetes** on a single node adds an API server, etcd, a CNI and a scheduler to a machine
  whose scheduler is a 200-line shell script that everyone in this repo can read.
- **Milvus / Weaviate** are distributed vector databases. For a corpus this size, **sqlite-vec**
  or **Chroma** is the correct scale, and sqlite-vec needs no new process at all.

The pieces worth taking are the ones that carry **data or method**, not the ones that carry
infrastructure.
## The BentoML note

BentoML lost both rows above, and that verdict stands: `llama-server` serves the model and
`run/registry.json` is the registry. Nothing in `backend/` imports BentoML and `api.py` is
untouched by it.

There is nevertheless a BentoML pipeline in `deploy/bento/`, and it is not a quiet reversal.
It is a **build** artefact, not a serving one: `bentoml build` + `bentoml containerize` produce
an OCI image for a small `text_gen_runner` service that holds no weights, takes no GPU lease,
and forwards to the `llama-server` this stack already runs. What it actually buys is a
generated Dockerfile — the image's build recipe comes from `bentofile.yaml` rather than from a
hand-maintained file that drifts, which is the one thing BentoML does here that the existing
`ops/deploy/Containerfile` does not.

Two things to know before touching it: the workflow that drives it
(`.github/workflows/bento-containerize.yml`) **has never run**, because this repository has no
git remote; and the service is written against the Runner API, which BentoML deprecated in 1.4,
so `requirements.txt` pins `bentoml==1.4.39` deliberately. `deploy/bento/DECISIONS.md` is the
full record, including the four bugs that produced a green build and a broken image.

---

## The specific repos

### `thoughtindustries/helium` — MIT
React + GraphQL + Tailwind, Vite, Jest, **Storybook**, npm workspaces, Volta-pinned Node. A
frontend framework their *customers* use to build learning experiences against their platform.

- **Not applicable wholesale.** This repo has no bundler and no `node_modules` in `site/` by
  design; its richest page, `site/reinforce.js` (984 lines), is a vanilla `'use strict'` IIFE
  emitted by a Python generator. Adding npm workspaces would break the
  generator → `build_cachebust.py` discipline the whole site rests on.
- **Worth mining: Storybook.** A component gallery that renders every UI piece in isolation is
  exactly what would have caught the three CSS collisions this repo has already paid for
  (`.bar`, `.live`, `#console .sub`). It does not need Storybook itself — a generated
  `site/components.html` rendering every `.mh-*`, `.rack-*`, `.st-*` block against the real
  stylesheet would do the same job with a Python generator and no npm.

### `mongodb-labs/helium-ti-poc`
A UI prototype of the same idea: atoms/components split, Vite, `ti-config.json`
instance config, CLI for authenticate / dev / deploy. **Confirms the pattern, adds nothing new.**
Its one transferable idea is the **config-driven instance file** — a single JSON that names which
backend a build talks to.

### `cortexapps/cli` — the most directly useful of the set
An Internal Developer Platform CLI: `catalog` (services, domains, teams), `scorecards`,
`queries` (CQL), `deploys`, `workflows`, `backup`. Auth via `~/.cortex/config` with `[default]`
tenant sections, overridable by `CORTEX_API_KEY` / `CORTEX_BASE_URL`. YAML entity descriptors in,
JSON/CSV out, `-f-` for stdin piping.

- **The scorecard idea is already half-built here.** The rack on the front page *is* a service
  catalogue: twelve units, each with `id`, `label`, `state`, `bus`, `href`, `spec`, `detail`,
  produced by each app's own `status()`. What it lacks is the second half — a **scorecard**: does
  this surface have a page, a test, a README, a rate-limit bucket, an honest `detail` line?
  That is a genuinely good idea and it is cheap: one generator walking `backend/apps/` and
  emitting a compliance grid. It would have caught the Voice surface shipping a rack row with no
  page (the failure that produced the "page first" rule).
- **The multi-tenant config-file pattern** (`~/.cortex/config`, env override, `-t/--tenant`) is a
  better shape than this stack's current per-surface `SYMONEURAL_*_TOKEN` sprawl, and is the obvious
  model if `apps/accounts` ever issues self-serve keys.

### `ever-works/awesome-mcp-servers` — CC-BY-SA-4.0
A curated MCP server directory (`mcpserver.ever.works`). The README did not come through the
fetch, so the categories and count here are **unread, not summarised** — do not quote a number
from this line.

- Directly relevant: `apps/studio/mcp_server.py` exposes 26 tools over FastMCP. This
  list is where to look for servers worth *consuming* (search, browser, filesystem) rather than
  writing, and where a SyMoNeuRaL MCP server would eventually be listed.
- **Licence note:** CC-BY-SA-4.0 is share-alike. Fine to read, fine to link. Copying its list
  structure into a page here would drag the share-alike terms along with it.

### `enthec/webappanalyzer` — **GPL-3.0**
The community continuation of Wappalyzer, which went private in August 2023. Technology
fingerprints as JSON in `src/technologies/`, validated against `schema.json`: `cats`, `website`,
`description`, and regex detection across `headers`, `js`, `dom`, `cookies`, `meta`, `scriptSrc`,
`text`, `css`, `url`, plus `implies` / `requires` / `excludes` relationships.

- **This is a real data asset** and the single most immediately useful thing in the list: it turns
  "scrape a page" into "scrape a page and know what it is built with." That is the enrichment
  step the blueprint's ingest row is missing.
- **Licence discipline required.** GPL-3.0 is copyleft. Reading the fingerprints at runtime as
  *data* is one thing; vendoring the files into this tree, or deriving code from their matcher,
  is another, and this repo is not GPL. If it is adopted: fetch at runtime or into a gitignored
  cache, keep it out of `site/`, and write the licence line down where the fetch happens.

### `duckduckgo/tracker-radar-wiki`
Node scripts that turn the Tracker Radar dataset into a static site — `build-history`,
`build-api-history`, `build-pages` — templates in Tailwind, output to `docs/` for GitHub Pages.

- **This is the same architecture as `tools/build_*.py`**, in a different language: data in,
  generator, static HTML out, no server. Useful as external confirmation that the generator
  discipline scales to a large dataset, and as a model for what a generated
  `site/models.html` or a fingerprint browser would look like here.
- The **dataset** (the sibling `duckduckgo/tracker-radar` repo) is the part with value: per-domain
  tracking behaviour, owners, prevalence. Pairs naturally with `webappanalyzer`.

### `codetocloudorg/platform-engineering`
A curated hub: `/docs` guides (IaC, Kubernetes, CI/CD, security, observability), `/seed_data` IaC
templates, `.devcontainer`, `/scripts`. Covers IDPs, golden paths, GitOps, and — usefully —
**comparisons of Backstage vs Port vs Cortex**.

- **Reading material, not code to adopt.** Its Azure/OpenShift reference architectures are for a
  different machine. The IDP comparison is the part worth reading before building any more of the
  scorecard idea above.

### `iamtheozzy/DNA-Leader`
A Gatsby starter, 22 commits, 1 star, README still the default boilerplate. **Nothing to take.**
Recorded here so nobody spends time re-checking it.

### `collinvandyck/resume` — MIT
Markdown source (`5xx.engineer.md`) → **five formats** (md, html, pdf, docx, txt) via a `.justfile`
task runner, `style.css`, and an AppleScript for PDF generation.

- **The idea is good and it is small:** one authored source, many rendered outputs, driven by a
  task runner. This repo already believes that (`tools/build_*.py`), and the obvious place to
  apply it is `frontend/site/docs/symoneural-manual.md` → HTML + PDF, so the manual can be *sent* to someone
  rather than only linked. The AppleScript step is macOS-only and would be a headless Chrome
  print here — Playwright is already installed and already drives Chrome for the test suite.

---

## If any of this gets built, build it in this order

Cheapest first, and each one is independently useful:

1. **Surface scorecard generator** (from `cortexapps/cli`). Walks `backend/apps/`, asserts each
   surface has a page, a test, a README, a rate bucket and a non-decorative `detail`. Pure Python,
   no dependency, and it enforces a rule this repo already has and has already broken once.
2. **`docs/` → PDF** (from `collinvandyck/resume`). Headless Chrome print via the Playwright
   already on disk. One script.
3. **sqlite-vec RAG over `docs/`** — embeddings with a small sentence-transformers model in an
   isolated venv, vectors in SQLite, retrieval wired as two more registry tools
   (`search_docs`, `read_doc`). No new process, no new port, no Qdrant. This is the one real
   capability gap that changes what the agent can answer.
4. **Playwright scrape tool** — the browser is installed; the tool is a thin wrapper plus a
   politeness delay. Feeds 3.
5. **`webappanalyzer` enrichment** — only after 4, and only with the GPL-3.0 handling above.
6. **Web search** — needs an external API key and therefore a policy decision, not just code.

Deliberately **not** on this list: Kubernetes, Ray, Temporal, vLLM, Triton, Milvus, Keycloak,
ELK, MinIO. See the section above for why each loses on this box.

---

# Third source list — the Cordis-style plugin harness (2026-08-18)

Garrett sent a design for a Cordis-like runtime: a `Context` service container, plugins as
`(ctx, config) => Disposable`, reversible effects, declarative `inject`, fibers with a
lifecycle, a YAML loader with process/session presets, reactive reload on provider change,
session forks, and sandboxing (Landlock / WASI / vm2 / worker processes). TypeScript reference
implementation, three two-week sprints.

Sources: `cordiverse/cordis` · `cordiverse/paper` · `deepseek-ai/deepseek-harness` ·
`deepseek.com/harness` · `landlock-lsm/landlock` + the kernel Landlock docs · `wasi.dev` ·
`patriksimek/vm2` · `pnpm` · `colinhacks/zod` · `sideway/joi` · `ts-node` · TypeScript ·
Node · Rust · Go · `webassembly.org`.

## The honest verdict

**The architecture described is one this app already has, in Python, in about 300 lines.**

| Cordis concept | What it already is here |
|---|---|
| `Context` service container | `registry.TOOLS`, populated at import |
| Plugin | a function in `tools_impl/` with `@tool(group=…)` |
| Plugin manifest / declared schema | generated, not declared — `inspect` + `get_type_hints` |
| `inject` (declared dependencies) | ordinary Python imports, checked by the interpreter |
| Loader / presets | `api.py`'s `include_router` calls, and `run/registry.json` |
| Mount / unmount | `systemctl restart symoneural-api`, ~2 s |
| Session fork | one process, one operator; there are no sessions to fork |

Taking the TypeScript version would mean a **second serving runtime**. This repo deliberately
has none: the API runs on the system interpreter with Debian's own FastAPI, and the only Node
on the box is Playwright's, inside llama.cpp's UI `node_modules`, used by the test suite.
Adding `pnpm` + `ts-node` + a plugin graph would add a build step, a second dependency tree and
a second place a route can be defined — and `.claude/CLAUDE.md`'s first rule is that there is
exactly one of each thing.

Three specific problems with the blueprint as written:

- **Its payoff is untrusted third-party plugins. There are none.** Reversible effects, capability
  tokens, sandboxing and an approval gatekeeper all pay for themselves when you are running
  somebody else's code. Every tool in `tools_impl/` was written in this repo and is read by the
  person who runs it. The whole safety apparatus is protecting against a threat this deployment
  does not have.
- **`vm2` is not a sandbox.** Its author archived it after unfixable escapes; recommending it in
  2026 is a sign the blueprint was not checked against the present.
- **Landlock and seccomp are not built here as of 2026-08-20.** A deliberate pre-launch state,
  not a cleared posture — the instruction this bullet used to quote is held (request ledger
  R-98), awaiting re-scope per surface, so this is a "not yet" and not a rejection. The
  substantive objection to the blueprint stands on its own and is the bullet above: this
  deployment runs only code written in this repo, read by the person who runs it.

Hot-reload deserves its own line, because it is the one item that sounds unarguable. It is not
free: it means every plugin must declare how to snapshot and restore state, and the failure
mode is a half-reloaded graph that is worse than a restart. `Restart=always` under systemd
restarts this API in about two seconds, and the GPU governor already handles the case that
actually hurts — a tenant holding the card across a restart.

## What is worth taking from it

Two items, both small, both Python, both real:

1. **Validate tool arguments against the generated schema before dispatch.** This is the zod/joi
   idea, and it is the one gap the comparison table above does not cover. `registry.call` hands
   the LLM's arguments straight to the function, so a hallucinated parameter name is a
   `TypeError` in the traceback rather than a message the model can recover from. Validating
   first turns that into a correctable tool result, which is the difference between a wasted
   turn and a corrected one. ~40 lines against the schema `registry.schema_for` already
   produces. **Highest value per line of anything in the three blueprints Garrett has sent.**
2. **An append-only session trace.** `agent.run()` already emits structured frames
   (`backend`, `thinking`, `tool_call`, `tool_result`, `answer`, `done`); writing them to
   `run/studio-sessions.jsonl` costs one open-append and gives replay, a record of what the
   agent actually did to the host, and — the part that matters later — the input to any
   evaluation of whether it is getting better. It is also the only one of the three blueprints'
   observability proposals that does not require Prometheus, Grafana, OTel or ELK.

Deliberately not taken: TypeScript, `pnpm`, `ts-node`, vm2, WASI, Landlock, seccomp, the fiber
lifecycle, session forks, reactive reload, the YAML preset loader, the capability gatekeeper,
and the three-sprint plan.

