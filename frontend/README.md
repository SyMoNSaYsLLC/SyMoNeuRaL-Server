# frontend/ — the two browser surfaces

```
app/     Next.js 16, App Router, TypeScript. The canonical frontend.
site/    the static site Caddy serves: pages/, css/, js/, assets/, docs/
docs/    route ownership, and the frontend and accessibility smoke records
```

Both talk to the same FastAPI on :8800 and **neither answers an `/api/*` path**. FastAPI owns
every one of them.

## Which is which

`site/` is what symoneural.com serves today: hand-written HTML, one shared `js/api.js`, one
stylesheet. It is published by `scripts/deploy.sh`.

`app/` is the Next.js application being built alongside it, surface by surface. It proxies
`/api/*` to FastAPI in development and never in production, where Caddy is the front door.

They are not competing. A page moves from `site/` to `app/` when its surface is rebuilt
there; until then `site/` is authoritative for that page.

## Publishing site/

```bash
python3 tools/build/build_pages.py        # regenerate the HTML
python3 tools/build/build_cachebust.py    # stamp the asset query strings
sudo scripts/deploy.sh                    # publish to /var/www/symoneural
```

`deploy.sh` flattens `pages/` to the webroot and keeps `css/ js/ assets/` as directories,
because every page links `/js/app.js` absolutely. It **refuses when it matches no pages** —
before that check existed it printed `staged: (0 files)` and then `deployed`, and had been
publishing nothing since the site was restructured.

## One shared client

`site/js/api.js` is the only place a `fetch` is written. It throws on a non-OK response,
carries an `AbortController` timeout, parses SSE keeping the `timings` frame, and sends **no
credential header** — there are none on this box.

`app/src/lib/api/client.ts` is the same contract in TypeScript. A surface's own
`api/client.ts` wraps it; nothing calls `fetch` directly.

## The layout must fit at 100% zoom

The one-screen fold sets `overflow:hidden` on html and body, so a panel taller than its box
loses the bottom of it. `site/js/fit.js` measures each panel and zooms it down until it fits,
with a floor below which the panel gets its scrollbar back rather than becoming unreadable.

`zoom`, not `transform:scale()` — transform leaves the layout box at the original size, so
the page still overflows and the scrollbar still lies about where things are.

## Never

- create `app/src/app/api/` — a route handler there shadows the rewrite silently, because
  Next matches its own filesystem routes before consulting `rewrites()`
- put a live figure in markup. The chat page said `SymonChat S1-7B` through three model
  changes because nothing read it; it now fills from `/api/status`
