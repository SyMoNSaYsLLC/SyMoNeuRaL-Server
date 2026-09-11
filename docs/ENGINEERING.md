# SyMoNeuRaL engineering rules

Moved here verbatim from `.claude/CLAUDE.md` on 2026-08-22 (R-180, Phase 0.6b).
Same words, new home: the rules are project property, not agent configuration.

These sections are load-bearing and battle-tested; every rule below was paid for by a
defect this repo actually shipped. Edit them the way you would edit code: with the reason
in the commit message.

## Parallelise builds

**Run as many agents concurrently as quality allows.** Compiles, model downloads and fine-tunes
occupy the machine for tens of minutes; that wall-clock should be filled with independent work,
not spent watching a progress bar. Launch subagents in one message so they actually run in
parallel. The GPU is available to agents that genuinely need it.

Scope agents to files nobody else is writing. The real hazard here is the generator scripts:
`tools/build/build_pages.py`, `tools/build/build_rack.py`, `tools/build/build_console.py`, `tools/build/build_cost.py`, `tools/build/build_stack.py`,
`tools/build/build_training.py` and `tools/build/build_gallery.py` all rewrite files under `site/`, so two writers in
that directory will clobber each other. Safe parallel
tracks are read-only audits, brand-new standalone files, docs, and tests.

## The GPU is a single, contended resource

One RTX 5070 Ti, 15.92 GiB. Chat (~5 GB), image (~7 GB) and a QLoRA run (~12 GB) cannot coexist.

- Everything touching the GPU goes through `scripts/gpu-governor.sh`, ideally as
  `gpu-governor.sh with <surface> -- <cmd>`, which always releases even on crash.
- **Hold the lock for a job, never for a process lifetime.** Residency (weights loaded) and
  work (using the card) are separate. Holding the lock while a model is merely resident and
  idle locks every other process out — including the CLI — until the acquire timeout.
- **Never call a bare `release`.** Name the surface (`release chat`). An unscoped release once
  destroyed a running fine-tune's lock from the API's shutdown hook.
- The governor waits between tenants for **compute** memory to drain below a 1 GB floor —
  `--query-compute-apps`, not `--query-gpu=memory.used`. The whole-card reading counts this
  box's KDE session (1336–1432 MiB, all of it `G` contexts), so a card-wide floor measured the
  desktop and `/api/chat` answered 500 to every visitor for an afternoon; R-171. `drain` takes
  an optional process substring — bare asks *is the card clear* (the eviction handoff, where a
  foreign context would OOM the incoming tenant), scoped asks *did this process let go*.
  `gpu-governor.sh status` prints both figures. Killing a process
  returns the lock before CUDA has torn down, and the next tenant OOMs at step 0.
- `train` is never evicted to serve a page view.
- RavenCalc (SymPy, CPU) deliberately never takes the lock. That is what lets it speculatively
  pre-compute while the GPU is loading.

## Python environments

The **CUDA sample venv** at `contrib/cuda-samples/python/.venv` is pinned at exactly **7 packages** and
must never be extended:

```bash
contrib/cuda-samples/python/.venv/bin/pip freeze | wc -l    # expect exactly 7
```

`numba-cuda` silently downgrades numpy, and three other packages pin conflicting
`cuda-core`/`cuda-python` versions. (Earlier revisions of this file said "the base interpreter
is pinned at 7 packages, check with `pip freeze | wc -l`". That is wrong twice over: the bare
command runs against the **system** interpreter, which is a Debian install carrying 212
packages, and the count would never have been 7. Use the full path above.)

- The serving API deliberately uses only the **system** interpreter: fastapi, uvicorn, pydantic
  and sympy are already OS packages, so there is no virtualenv in the serving path. Do not
  `pip install` into it — the deny rules in `.claude/settings.local.json` block the bare forms
  precisely because a stray install there is hard to notice and hard to undo.
- Training has its own venv at `training/.venv` (torch cu128 — Blackwell sm_120 needs it).
- Anything else that conflicts gets its own isolated venv.

## Honesty rules for anything user-facing

These are the product, not decoration. The site's entire argument is that its numbers are real.

- Label every figure: **measured** on this machine, **vendor** specification, or **projected**
  arithmetic. Never present a projection as a result.
- Never invent pricing. Direct pricing questions to symonsayadmin@symoneural.com.
- No decorative status indicators. Every LED and gauge on the site reflects a real reading; a
  fake activity light is the one dishonest pixel on a page arguing for measurement.
- Publish negative results too — the PCIe Gen 3 ×8 ceiling and the failed multi-stream overlap
  are on the site deliberately.
- Layout changes must not drop data. Fold long content into `<details>`; do not trim it.
  **This includes CSS.** `text-overflow:ellipsis` on a detail line is data loss with extra
  steps — the control board was showing `~84% of 896.1 p…` and the rack was cutting
  `built on Qwen2.5-7B-Instruct` down to `…7B-Ins…`, and that attribution is an Apache-2.0
  licence condition. Every ellipsis rule has been removed. Do not add one back; let it wrap.

## What is SyMoNeuRaL's, and must never be published

The stack is off-the-shelf and permissively licensed, so nothing here is protected by a
licence. Two artefacts are protected only by not being public, and trade secret — unlike
copyright — exists only while reasonable measures are taken to keep it that way. Once it is
out, it cannot be pulled back.

- **`training/corpus.jsonl`** — 327 hand-authored examples: the company voice, what the model
  may claim, and what it must refuse to invent (the pricing refusal is trained in, not
  prompted).
- **`training/build_dataset.py`** — the method that produces it.
- **`training/adapter/`** weights — already gitignored (`*.safetensors`, `*.gguf`).

**Never copy any of these into `site/`, never serve them from an endpoint, and never quote
their contents into a page or a commit message.** An agent asked to "publish the manual" could
reasonably mistake the corpus for documentation. It is not: it is the recipe for the product.
`docs/symoneural-manual.md` is the manual and is publishable; the corpus is not.

The line that resolves this against the site's transparency argument: **publish the numbers,
keep the methods.** "151 tok/s on a 7B Q4_K_M, measured here" is the sales argument and gives
away nothing. How the adapter was built is the asset. The site promises measurement, not open
source, and has never promised the recipe.

There is currently **no git remote** — history never leaves this box, which is doing a lot of
the protecting. If one is ever added, audit what is tracked first.

## Build and deploy

```bash
./scripts/fetch-models.sh            # weights -> models/ (ungated, Apache-2.0 sources)
python3 tools/build/build_pages.py       # chat/image/calc/remix   -> site/*.html
python3 tools/build/build_rack.py        # live rack               -> site/index.html
python3 tools/build/build_console.py     # control board           -> site/index.html
python3 tools/build/build_cost.py        # Owned vs Rented         -> site/documentation.html
python3 tools/build/build_stack.py       # Inference Architecture  -> site/documentation.html
python3 tools/build/build_training.py    # manual                  -> site/training.html
python3 tools/build/build_tabs.py        # one-screen front page   -> site/index.html
python3 tools/build/build_gallery.py     # homepage art (uses GPU) -> site/art-*.png
python3 tools/build/build_gallery.py --restamp   # redraw the watermark bar only -- NO GPU
python3 tools/build/build_cachebust.py   # ALWAYS LAST -- see below
./scripts/symoneural.sh on|off|status   # the live API (off is the kill switch)
sudo ./scripts/deploy.sh                # site/ -> /var/www/symoneural (needs a password)
```

**`build_cachebust.py` runs last, and every generator run un-does it.** The generators emit
plain `href="/symoneural.css"`; the stamper rewrites those to `?v=<content hash>` so a week-old
cached stylesheet can never be served against new markup. That means any generator you run
*strips the stamps off every page it writes*, and a commit made at that moment ships pages whose
assets are cacheable for a week with no way to invalidate them. This is not theoretical: a run of
`build_pages.py` here silently destamped seven pages, and the diff read like a harmless refresh.
So: **regenerate, then stamp, then look at `git status`** — if a page you did not touch is still
modified, you skipped the stamper. It is idempotent and cheap; there is no reason not to run it.

The generator scripts are idempotent and must stay that way — `tools/build/build_console.py` once nested
folds inside folds when run twice. **Run every generator twice and `diff` before committing.**
The BEGIN/END marker strings are the contract: change a marker in a generator and you must
change it in the HTML in the same commit, or the generator stops finding its block and appends
a second one.

`scripts/deploy.sh`'s reference check **can** fail the build — the loop reads from a process
substitution, so `missing` survives into the exit test. It used to pipe into `while read`,
which put the counter in a subshell and threw it away; that was fixed in `aa424d3` and
verified by running the block against a fake webroot with one missing reference. Earlier
revisions of this file said the bug was still live. It is not.

The general lesson stands and is what to carry forward: **a counter incremented inside a
piped `while read` is discarded.** The orphan-scan loop above it is still in a subshell, and
that is fine, because it only writes to stdout and sets nothing its caller reads.

## `run/` is runtime state, not logs

`run/` holds `gpu.lock.d` — the GPU mutex — alongside `api.pid`, the resident marker and the
logs. **Do not rename it `logs/`.** `/run` and `/var/run` are the Unix convention for exactly
this (pidfiles, locks, sockets) and the name is load-bearing: call the directory `logs` and
sooner or later someone logrotates it or clears it out, which deletes the lock directory while
a surface is holding the card. The logs happen to live there; the lock is the point.

Renders do **not** live there, and no longer live in `site/` either. They are API output,
written to `backend/output/` and served by `GET /api/gen/<name>`. They were in `site/` until
the backend restructure, which meant `deploy.sh` copied every one into the public webroot —
19 unreferenced PNGs were sitting there — even though nothing links to them.

## Serving architecture

**FastAPI does all the routing. The web server terminates TLS and hands back static files.**
That is the user's stated rule and the config enforces it — no rewrites, no aliases, no
conditional logic in `ops/Caddyfile`.

- **Caddy**, not Apache. Apache is disabled, and its config was deleted rather than left beside
  the Caddyfile. Caddy gives automatic TLS and, crucially, WebSocket upgrades with no directive
  — `mod_proxy_wstunnel` was never enabled under Apache, so the rack's "pushed live over one
  socket" claim had been silently falling back to polling.
- Anything the API generates is served by the API. Renders come back as `/api/gen/<name>`, not
  as a webroot path, because the API writes into the staging `site/` while the web server serves
  `/var/www/symoneural` — so every image generated on the live site used to 404 until somebody
  deployed.
- `api.py` mounts `site/` at `/` **last**, so it never shadows an API route. That is what lets
  the whole thing be exercised from one origin, which is the only way the real frontend works:
  `console.js` opens a WebSocket and falls back to polling, and neither survives a split origin.
- Testing a WebSocket: use `curl --http1.1` (`Upgrade:` does not exist in HTTP/2, and curl
  negotiates h2 with Caddy by default), and read the status line out of `-D` headers rather than
  trusting the exit code — a successful upgrade leaves the socket open, so curl exits 28.

## Branding

"MIT AI Training" is purged everywhere user-facing. Watch out: most `MIT` substring matches in
this corpus are ordinary words — limits, limited, submit, emits — so never blind-replace. Only
whole phrases and local filesystem paths.
