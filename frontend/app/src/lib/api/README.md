# `frontend/app/src/lib/api/` — the one fetch

`client.ts`. Every request the Next.js app makes goes through it, and a surface's own
`api/client.ts` wraps this rather than calling `fetch`.

## Why one

The static site had thirteen fetch idioms before `js/api.js`, each with its own timeout
behaviour and its own idea of what an error was — so "it failed" meant a different thing on
every page. One client means one timeout, one non-OK throw, one SSE parse.

## What it does and does not send

It sends **no credential header.** There are none on this box. Identity is resolved by the
proxy and arrives as headers on the server side — see `../auth/README.md`.

`tests/structure/test_credential_header.py` asserts that stays true.

## In development only

`/api/*` is proxied to FastAPI by `next.config.ts`, and that rewrite is **read at build
time**, not at `next start`. In production Caddy is the front door and Next never sees an
`/api` request at all.
