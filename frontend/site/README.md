# frontend/site/ — the static site

What symoneural.com serves. Published by `scripts/deploy.sh`.

```
pages/    the HTML. Flattened to the webroot: pages/chat.html -> /chat.html
css/      published at /css/
js/       published at /js/
assets/   published at /assets/
docs/     the manual and hardware dossier this site publishes
```

The asset directories keep their names because every page links `/js/app.js` and
`/css/symoneural.css` **absolutely**.

## One client, one stylesheet

`js/api.js` is the only place a `fetch` is written. It throws on a non-OK response, carries an
`AbortController` timeout, parses SSE keeping the `timings` frame, and sends **no credential
header** — there are none on this box.

`js/fit.js` makes the one-screen fold fit at 100% browser zoom by measuring each panel and
zooming it down, with a floor below which the panel scrolls instead.

## Publishing

```bash
python3 tools/build/build_pages.py       # regenerate
python3 tools/build/build_cachebust.py   # stamp the ?v= query strings
sudo scripts/deploy.sh
```

`build_cachebust.py` stamps a content hash on every asset URL. An unstamped asset is
cacheable for a week against markup that changed, which is how a page ships new HTML against
last week's JavaScript.

## Never put a live figure in markup

The chat page said `SymonChat S1-7B` through three model changes because it was typed, not
read. Anything that can change is fetched from `/api/status` or `/openapi.json`.
