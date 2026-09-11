# SMOKE — the Coder browser surface, run rather than read

`exists`, `grep` and `ngrep` ask what is written on disk. None of them can ask whether the
thing works, and this repo has now shipped two surfaces where every check went green and the
page was dead: #94's desktop client rendered one turn and then silently received nothing (a
missing Tauri capability, no error to read), and #99's Studio editor was 4% of the first
viewport at 1440x1000 while sixteen browser assertions passed. `tests/live.mjs` is the third
shape: it sat on disk for a fortnight satisfying `exists` and `grep` and could not be loaded
by `node` at all — a SyntaxError on line 17, before a single assertion ran.

This file cannot be written honestly without running the thing. That is its whole job.

---

## What was run, and against what

```bash
cd backend && SYMONEURAL_CODER_ENABLED=1 SYMONEURAL_CODER_TOKEN=devtest \
    SYMONEURAL_CODER_STATE_DIR=<throwaway> \
    python3 -m uvicorn api:app --port 8875        # a spare port, never the service
node tests/frontend.mjs http://127.0.0.1:8875
```

**A spare port, not the service.** Pointing `frontend.mjs` at the running service tests what is
*deployed*, not what was written, and a red assertion sends you hunting a bug you already
fixed.

**The surface must be switched on in the SERVER's environment**, not the browser's.
`coder.authorize()` reads `SYMONEURAL_CODER_ENABLED` and `SYMONEURAL_CODER_TOKEN` from the
process that answers, and the token never crosses to the page. Without them the page renders
its refusal panel — correctly — and every tree assertion below measures nothing.

`SYMONEURAL_CODER_STATE_DIR` is pointed at a throwaway directory so the run does not write
into `run/`, which holds the GPU mutex.

---

## The readings

**61/61 passed**, `tests/frontend.mjs`, 2026-08-21. Thirteen of those are this surface:

| Assertion | Reading |
|---|---|
| page answers at `/live-stack/coder` | 200 `text/html` |
| page answers at `/livestack/coder` | 200 `text/html` |
| `coder-instrument-first` | **100% of the readings panel visible, top = 211px** |
| gate panel renders every gate | `unread: none` — all five cells carried a value |
| tree navigates into a directory | clicked `training/` |
| denied corpus shown, not hidden | `refused — training/corpus.jsonl is denied` |
| denied corpus offers no control | `openable=false` |
| corpus refused by the API too | `training/corpus.jsonl is denied` |
| no ellipsis anywhere | `0 elements` |
| no sideways overflow at 1440px | `over=0px` |
| no sideways overflow at 1301px | `over=0px` |
| no sideways overflow at 390px | `over=0px` |

`1301x740` is in the list because it is the binding viewport for the rack, not 1855x745 — its
rows are 26.6px. See `.claude/HANDOVER.md` §0.

The six `400`/`404` lines in the run's failed-request list are all `/api/streamer/*` and are
pre-existing: the streamer surface needs a provider account this box does not have. They are
not this page's.

---

## The deliberate breaks — the part no static check can stand in for

A check that can pass without the work being finished is worse than no check, because it will
archive the task. Both of the assertions this surface most depends on were broken on purpose
and observed going red.

### 1. Hiding denied entries

One line in `site/coder.js`, filtering denied entries out of the listing — the
decorative-dishonesty regression the flag exists to prevent:

```js
d.entries.filter(function (e) { return !e.denied; }).forEach(...)
```

```
FAIL  coder shows the denied corpus rather than hiding it  -- not listed among 6 rows
FAIL  the denied corpus offers no control that would read it  -- not listed
PASS  the corpus is refused by the API, not only by the page
```

Ten rows became six. **The API assertion stayed green**, which is the point of having it: the
page lying about the tree and the module handing the file over are different failures, and one
test cannot cover both. Restored and re-verified.

### 2. Pushing the readings below the fold

One rule appended to `site/coder.css`, reproducing #99's shape exactly:

```css
.cd-grid { margin-top: 1200px }
```

```
FAIL  coder-instrument-first: the readings are on the first screen  -- 0% of the panel visible, top=1399px
PASS  coder page does not overflow sideways at 1440px  -- over=0px
```

The panel kept its correct height throughout and the page never overflowed — so a height
assertion and an overflow assertion both pass while the instrument is invisible. **That is
why the check multiplies out the on-screen area rather than reading `getBoundingClientRect().height`.**
Restored and re-verified.

### 3. Adding an `/api/coder` route

Appended to `backend/api.py`:

```python
@app.get("/api/coder/danger", include_in_schema=False)
async def _oops(): ...
```

```
FAILED CoderSurfaceTests::test_the_public_api_has_no_coder_route
AssertionError: Lists differ: ['/api/coder/danger'] != []
```

`ops/Caddyfile` delegates the whole `/api/*` subtree to the public internet and this module
executes subprocesses, so that route is remote file read on a public host the moment it
exists. Restored and re-verified.

---

## What the delegation half proves, and what it cannot

`apps/test_caddy_delegation.py` went red naming **both** coder paths before `@coder` was added
to `ops/Caddyfile`:

```
AssertionError: Lists differ: ['/live-stack/coder', '/livestack/coder'] != []
```

That red is the return on the whole test. Neither address was delegated, so Caddy's final
`handle { file_server }` would have looked both up in `/var/www/symoneural`, found nothing,
and 404'd them **without ever asking the API** — while `127.0.0.1:8800` answered them
perfectly, which is how this defect has hidden five times in this repo.

`caddy validate --config ops/Caddyfile` → `Valid configuration`.

**It has NOT been tested through a running Caddy on the public origin, and that is stated
rather than implied.** Every reading above was taken against `127.0.0.1:8875`, where FastAPI
answers directly and the Caddy config is not exercised at all. The Caddyfile says so twice in
its own comments. Testing a delegation through localhost is the mistake that let a tuner 404 be
reported as fixed.

---

## Two things that cost time and are worth writing down

**`pgrep -f "uvicorn api:app --port 8875"` matches the shell you type it in.** `pgrep -f`
searches full command lines, and the command line running the `pgrep` contains the pattern —
so `kill $(pgrep -f ...)` killed this session's own shell twice, reported only as exit code
144. Use `pgrep -f "[u]vicorn ..."`, or capture `$!` when you start the process. The bracket
only helps if no other word on the line spells the pattern out.

**`enabled()` is both switches, not one.** `coder.enabled()` returns true only when
`SYMONEURAL_CODER_ENABLED=1` **and** a token is set, so the `enabled` gate on the page reads
false when only the token is missing. The panel shows `token_set` separately for exactly that
reason — `authorize()` returns the first refusal and stops, which is useless to an operator
who would otherwise set one variable, reload, and meet the next closed gate with no warning it
was there.

---

## Version

This is a reading of the **working tree** at the moment of the run, taken immediately before
the commit that lands it. It is stamped with that commit's SHA at the top of the section below
once it exists; if that section is empty, the reading has not been reproduced against a commit
and must not be quoted as though it had. Re-run and re-stamp rather than carrying this forward
and re-dating it — a figure with no SHA cannot be checked, only believed.

### Reproduced against a commit

**61/61, `tests/frontend.mjs`, measured 2026-08-21 at `3998fc9` against
`http://127.0.0.1:8875`.**

This one carries a SHA and the readings above do not, and the difference is the whole point
of the distinction. The figures above were taken from the working tree in the minutes before
the commit — honest, and not reproducible by anybody else. This run was taken with
`git status` clean at `3998fc9`, so it is a reading of that commit and a fresh checkout of it
will produce the same thing.

`.claude/CLAUDE.md` records what happens without that discipline: a published test count that
was never true of the commit it sat beside, because somebody carried it forward and re-dated
it. A number with no SHA cannot be checked, only believed.

The thirteen coder assertions were identical across both runs, including
`coder-instrument-first` at **100% of the panel visible, top = 211px**.

Backend on the same tree: **1796 pass, 0 fail, 14 skip in 138.10 s**, `--collect-only`
collecting **1810** — 1796 + 14 = 1810, which is the arithmetic that says nothing aborted —
and `apps/remix` **28/28 in 0.43 s**. Run from `backend/`, not from the repo root.

The 38 over the previous reading of 1758 are not all this task's, and the count is deliberately
not attributed here: the 1758 was itself a working-tree figure that nobody could reproduce from
git, so there is no honest per-file delta to draw against it. What this task added is countable
on its own: **+12** `apps/coder/tests/test_coder_surface.py`, **+3** `apps/coder/test_coder.py`
(47 → 50, the second-adapter leak), **+1** `apps/test_caddy_delegation.py` and **+1**
`apps/test_deploy_routes.py`. Seventeen. Everything else in that gap landed elsewhere.
