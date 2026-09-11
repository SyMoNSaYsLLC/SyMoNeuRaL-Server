# frontend/app — the Next.js frontend

Next.js 16 App Router over the FastAPI backend. TypeScript, React 19, CSS Modules,
no UI framework and no state library.

FastAPI owns every `/api/*` path. This app never answers one — see `next.config.ts`,
which is the only file here that can break the live API.

## Setup

```bash
cd frontend/app
npm ci                  # package-lock.json is committed; use ci, not install
npm run dev             # http://localhost:3000, proxying /api to 127.0.0.1:8800
```

The backend must already be up, because `/api/*` is proxied, not mocked:

```bash
cd ../../backend && python3 server.py     # :8800
```

## Layout

```
src/app/            routes. Nothing but page.tsx / layout.tsx / error.tsx.
src/applications/   one directory per surface: components, hooks, types, styles, api.
src/components/     shared shell and UI primitives.
src/lib/api/        the single fetch client. Every request goes through it.
src/lib/config/     environment reads, in one place.
tests/              node:test slices against a fixture API, never against production.
public/             static assets served at /.
```

A surface is self-contained under `src/applications/<name>/`. Its `api/client.ts` wraps
`src/lib/api/client.ts`; it does not call `fetch` directly. Adding a surface means adding
a directory there and a thin `src/app/<route>/page.tsx` that renders it — no edits to the
shell, no central registry to update.

## Reconfiguring

| What | Where | When it is read |
|---|---|---|
| API upstream | `SYMONEURAL_API_UPSTREAM` | **`next build`**, not `next start` |
| Port | `PORT` | `next start` |
| Telemetry | already off in every script | — |

`SYMONEURAL_API_UPSTREAM` is baked into `.next/routes-manifest.json` at build time.
Setting it before `next start` does nothing. This was measured after an earlier comment
claimed the opposite and a test suite authenticated fixture credentials against the live
API on :8800 as a result.

In production this rewrite is not used at all: `ops/Caddyfile` is the front door and sends
`/api/*` to the gateway on :8000, which forwards to FastAPI on :8800. The rewrite is a
development convenience so `npm run dev` needs no CORS.

## Commands

```bash
npm run dev          # development server
npm run build        # production build; resolves SYMONEURAL_API_UPSTREAM
npm run start        # serve the build
npm run lint         # eslint
npm run typecheck    # tsc --noEmit
npm run test:slice   # node --test tests/*.test.mjs
```

`tests/route-ownership.test.mjs` asserts two things that must stay true together: that
`src/app/api/` does not exist, and that `/api/:path*` passes through verbatim. A route
handler under `src/app/api/` would shadow the rewrite silently, because Next matches its
own filesystem routes before consulting `rewrites()`.

## Adding a page

1. `src/applications/symoneural-<name>/` — components, hooks, types, styles, `api/client.ts`.
2. `src/app/<route>/page.tsx` — imports the application's entry component and nothing else.
3. A slice test in `tests/` that runs against `tests/support/fixture_api.py`.

Do not create `src/app/api/`. Do not call `fetch` outside `src/lib/api/client.ts`.
