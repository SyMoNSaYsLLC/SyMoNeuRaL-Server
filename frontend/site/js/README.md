# `frontend/site/js/` — the static site's JavaScript

Plain ES5-compatible scripts. No bundler, no framework, no build step — a file here is
served byte for byte, and `build_cachebust.py` stamps its URL with a content hash.

| file | what it does |
|---|---|
| `api.js` | **the only place a fetch is written.** Throws on non-OK, AbortController timeout, SSE parser that keeps `timings`, and no credential header |
| `app.js` | the shared shell: navigation, theme, the bits every page needs |
| `shell.js` | the page chrome |
| `fit.js` | scales the one-screen fold so it fits at 100% browser zoom |
| `ui.js` | the rack, and the maintenance banner |
| `console.js` | the operator console |
| `dashboard.js` `visualizer.js` | the metrics pages |
| `image.js` `coder.js` `studio.js` `reinforce.js` `exp.js` `live.js` | one per surface |
| `hls.js` | the video player shim |

## Two rules

**Never write a second fetch.** `api.js` exists because thirteen different fetch idioms did,
each with its own timeout behaviour and its own idea of what an error was.

**Never type a live figure.** The chat page said `SymonChat S1-7B` through three model
changes because it was in the markup. Anything that can change is read from `/api/status` or
`/openapi.json`.
