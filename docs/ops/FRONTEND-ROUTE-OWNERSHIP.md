# Frontend route ownership and migration map

**Written 2026-08-28.** The record of which surface owns which URL while `frontend/` replaces
`site/` route by route. It is a map of what is true today plus what each route will need, not
a schedule and not a promise.

Read `.claude/CLAUDE.md` first: nothing here authorises starting a migration. Work enters
through `INTAKE.md` and becomes a numbered task in `PROJECT-TASKS.md`.

---

## The three things people conflate, and the boundary between them

| | what it is | who owns it |
|---|---|---|
| `site/` | the **legacy** frontend: 26 HTML files, 12 scripts, 5 stylesheets, 51 images, flat | read-only during migration |
| `frontend/` | the **canonical** frontend: Next.js App Router, strict TypeScript | this project |
| `web/` | **not frontend source.** A Go program that imports Caddy as a library — the HTTP/TLS runtime that would eventually *serve* the other two | `ops/`, separate concern |

`web/symoneural-web` was inspected for this record: `main.go` is 6.4 KB of SyMoNeuRaL-authored
Go whose `package main` delegates request serving to Caddy, with `go.mod`, `go.sum`, a
generated SBOM and `THIRD_PARTY_NOTICES.md` beside it. It contains no page, no template and no
stylesheet. It is a serving component and must not be merged into either frontend concept.

## The architecture

```
frontend/
├── public/                     only assets actually referenced
├── src/
│   ├── app/                    OWNS URL ROUTES. Route files stay thin.
│   ├── applications/           OWNS BEHAVIOUR. One folder per application.
│   │   ├── symoneural-home/        the shared shell and the navigation model
│   │   └── symoneural-dispatchos/  /demo/dispatchos
│   ├── components/{shell,ui}/  presentational primitives, no application knowledge
│   ├── lib/{api,config}/       the one fetch wrapper, and site-wide constants
│   └── styles/globals.css      design tokens transcribed from site/symoneural.css
└── tests/                      verification for the migrated slice only
```

Two rules carry it, and `frontend/tests/route-ownership.test.mjs` asserts both:

1. **A route file imports an application's `index.ts` and nothing beneath it.** Reaching into
   `components/` or `hooks/` from a route re-creates the entanglement this structure exists to
   remove.
2. **A route file stays thin.** Both current route files are under 40 lines and the test fails
   if that stops being true.

## FastAPI is the authoritative backend

Next.js answers no `/api` path, and two things keep that true:

- there is no `frontend/src/app/api/` directory, asserted by test, because a route handler
  there would shadow the rewrite **silently** — Next matches its own filesystem routes before
  it consults `rewrites()`;
- `/api/:path*` is rewritten verbatim to the upstream.

**The rewrite is a development convenience only, and this was measured rather than assumed.**
`next build` resolves `rewrites()` and writes the destination into
`.next/routes-manifest.json`; `next start` serves that manifest and never re-reads
`SYMONEURAL_API_UPSTREAM`. In production `ops/Caddyfile` is the front door and routes `/api/*`
to the gateway on `:8000`, which forwards to FastAPI on `:8800`. Depending on the rewrite in
production would pin the API host to whichever machine ran the build.

---

## Route map

`owner` is the application that owns the behaviour once migrated. `status` is what is true
**today**: `migrated` means implemented in `frontend/` and verified; `legacy` means still
served from `site/` and untouched.

### Migrated

| URL | legacy source | owning application | target route folder | backend dependencies | auth tier | status |
|---|---|---|---|---|---|---|
| `/demo/dispatchos` | *(none — was `backend/apps/dispatchos/page.py`, still live)* | `symoneural-dispatchos` | `src/app/demo/dispatchos/` | `/api/dispatchos/*` (15 routes) | **two gates**: Caddy basicauth on the door, then the application's own operator/customer session | **migrated, not deployed** |
| `/` | `site/index.html` | `symoneural-home` | `src/app/` | none | public | **migrated as a migration index only** — it is *not* a replacement for the legacy home page and does not claim to be |

### Legacy — the remaining 25 pages

| URL | source | owning application (proposed) | target route folder | backend dependencies | auth tier |
|---|---|---|---|---|---|
| `/index.html` | `site/index.html` | `symoneural-home` | `src/app/` | `/api/status` | public |
| `/overview.html` | `site/overview.html` | `symoneural-home` | `src/app/overview/` | none | public |
| `/documentation.html` | `site/documentation.html` | `symoneural-home` | `src/app/documentation/` | none | public |
| `/credits.html` | `site/credits.html` | `symoneural-home` | `src/app/credits/` | none | public |
| `/receipts.html` | `site/receipts.html` | `symoneural-home` | `src/app/receipts/` | none | public |
| `/build.html` | `site/build.html` | `symoneural-home` | `src/app/build/` | none | public |
| `/project.html` | `site/project.html` | `symoneural-project` | `src/app/project/` | `/api/project` | public |
| `/controlboard.html` | `site/controlboard.html` | `symoneural-home` | `src/app/controlboard/` | none | public |
| `/livestack.html` | `site/livestack.html` | `symoneural-home` | `src/app/livestack/` | `/api/status` | public |
| `/chat.html` | `site/chat.html` | `symoneural-chat` | `src/app/chat/` | `/api/chat` (SSE) | public |
| `/image.html` | `site/image.html` | `symoneural-image` | `src/app/image/` | `/api/image` | public |
| `/coder.html` | `site/coder.html` | `symoneural-coder` | `src/app/coder/` | `/api/coder` | loopback-gated |
| `/live.html` | `site/live.html` | `symoneural-live` | `src/app/live/` | HLS off disk | public |
| `/exp.html` | `site/exp.html` | `symoneural-exp` | `src/app/exp/` | `/api/exp` | public |
| `/studio.html` | `site/studio.html` | `symoneural-studio` | `src/app/studio/` | `/api/studio` | public |
| `/remix.html` | `site/remix.html` | `symoneural-remix` | `src/app/remix/` | `/api/remix` | public |
| `/miner.html` | `site/miner.html` | `symoneural-miner` | `src/app/miner/` | `/api/asicminer`, `/api/gpuminer`, `/api/status`, `/api/ws` | public |
| `/gateway.html` | `site/gateway.html` | `symoneural-gateway` | `src/app/gateway/` | `/api/gateway`, `/api/status` | public |
| `/ravencalc.html` | `site/ravencalc.html` | `symoneural-ravencalc` | `src/app/ravencalc/` | `/api/ravencalc` | public |
| `/reinforce.html` | `site/reinforce.html` | `symoneural-reinforce` | `src/app/reinforce/` | `/api/train` | public |
| `/sigils.html` | `site/sigils.html` | `symoneural-sigils` | `src/app/sigils/` | `/api/sigils` | public |
| `/streamer.html` | `site/streamer.html` | `symoneural-streamer` | `src/app/streamer/` | `/api/streamer`, `/api/chat` | public |
| `/streamer-watch.html` | `site/streamer-watch.html` | `symoneural-streamer` | `src/app/streamer/watch/` | `/api/streamer` | public, **deliberately no chrome** |
| `/account.html` | `site/account.html` | `symoneural-accounts` | `src/app/account/` | `/api/accounts` | own session cookie |
| `/training.html` | `site/training.html` | `symoneural-home` | `src/app/training/` | `/api/cugraph` | public, **own inline stylesheet — no shared CSS** |
| `/share-dispatchos.html` | `site/share-dispatchos.html` | `symoneural-dispatchos` | `src/app/share/dispatchos/` | none (static document) | Caddy basicauth, four accounts |

Two of these are marked because they are **not** ordinary shell pages and a migration that
treats them as such will produce a worse page than the one it replaces: `streamer-watch.html`
carries no chrome on purpose, and `training.html` has its own inline stylesheet and is
deliberately treated as a document.

## Backend surfaces, for reference

`/api/streamer`, `/api/accounts`, `/api/gateway`, `/api/streamer/guide`, `/api/project`,
`/api/rack`, `/api/train`, `/api/voice`, `/api/sigils`, `/api/studio`, `/api/exp`,
`/api/news`, `/api/live`, `/api/dispatchos` — plus the non-`/api` UI routers
`/studio/editor` and `/demo/dispatchos`.

## Authentication tiers

1. **Public** — no gate.
2. **Caddy basicauth** — `ops/Caddyfile`, one flat tier over `/demo/dispatchos` and
   `/share-dispatchos.html`, four accounts. It authenticates; it does not authorise.
   `/api/dispatchos/*` is deliberately **not** behind it: it answers 401 to a stranger.
3. **Application session** — DispatchOS's own `symon_dispatchos` cookie, operator/customer.
   Unrelated to `/api/accounts`, which has its own cookie and its own tiers.

---

## What is verified, and what is not

`frontend/tests/` — 17 assertions, `npm run test:slice`, all passing at the commit that added
this file. They cover: the route is served; `noindex, nofollow, noarchive` on the preview;
Next claims no `/api` route; `no-store` on dispatch responses; anonymous 401; a customer
refused an operator action and shown none of another customer's trips; identical answers for a
wrong password and an unknown user; intake → quote → confirm → dispatch-with-driver → reminder
→ complete → review-request → reviewed, with the append-only trail and the illegal transition
refused; a quote carrying no figure when rate rules are unconfigured; a message recorded as
never sent; and no credential, bcrypt hash or absolute host path in any browser artifact.

### Named parity deltas against the legacy page

The 17 assertions verify what the migrated slice *does*. **None of them compares it to
`backend/apps/dispatchos/page.py`, the page it would replace**, so a missing panel cannot turn
one of them red. Parity is the gate for retiring the legacy route, and an undocumented gap
makes that gate meaningless. The two known differences, recorded rather than discovered later:

| legacy page has | migrated slice | why |
|---|---|---|
| `<h2>Rate rules</h2>` — an editor, backed by `GET`/`PUT /api/dispatchos/rules` | a **read-only status note** saying whether rules are configured. The typed client has neither call. | Defensible while "not configured" is the documented normal state and the preview promises no pricing — but it **is** a missing operator capability, not an intentional simplification of an empty one. Closing it is one typed call pair plus a form. |
| `<h2>SyMon AI</h2>` — the assistant panel over `POST /api/dispatchos/ask` | absent | Correct and deliberate. `/ask` is outside the v1 workflow list, and `#108` criterion 3 owns it. Not a parity gap to close here. |

Neither is a defect. Both must be settled before anyone calls the route at parity.

**Not verified, and no assertion above should be read as implying otherwise:**

- **Responsive rendering and visual parity with `site/`.** These need a real browser. The CSS
  uses the transcribed tokens and the two named breakpoints, and the board table scrolls inside
  its own wrapper — but *that it looks right* is unmeasured.
- **Anything about the deployed host.** Nothing was deployed, installed or restarted.
- **The SyMon AI `/ask` route.** Out of scope for the v1 workflow and untouched; `#108`
  criterion 3 still owns it.

## Before the live Donnie URL can point at Next

In order, and none of it is done:

1. **Decide whether Donnie has an application account.** He has a Caddy door password and is
   *not* one of the four seeded application accounts, so today he clears the door and meets a
   sign-in form he has no credential for. Credentials are `owner: garrett`.
2. **A browser run** establishing responsive and visual parity against the legacy surface.
3. **A serving decision.** `/demo/dispatchos` is currently a FastAPI route. Pointing it at Next
   means `ops/Caddyfile` routing that path to a Next process, which means a new systemd unit
   and a new listener — neither exists, and `ops/install-runtime.sh`'s `UNITS` array does not
   mention one.
4. **Keep the basicauth block.** Whatever serves the path, the door must not move.
5. **A rollback** that is one Caddyfile change back to the FastAPI route.

Until all five, `frontend/` is a local project. `site/` and the live `/demo/dispatchos` are
untouched and remain what production serves.
