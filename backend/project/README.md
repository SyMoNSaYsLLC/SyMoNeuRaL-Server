# SyMoNeuRaL Project

A workspace surface. Named projects, each holding work items, notes, references to files in
the repository, and the history of what was done to them across sessions. It answers the
question that currently has no home on this box — *what am I working on, what is the state
of it, what did the last session do, and what is next* — for a person and for the models on
this machine working on the same body of files.

**It owns no weights and it never takes the GPU lock.** That is not a saving, it is the
feature: a workspace that queued behind a fine-tune would be useless, because the moment you
most want to write down what you were doing is the moment the card is busy for three hours.
Same decision as RavenCalc, and the rack unit uses RavenCalc's words for it.

Standard library plus `fastapi` and `pydantic`, which the system interpreter already has.
Nothing was installed, no venv was created. `sqlite3` 3.46.1 under Python 3.13.5 is the store,
FTS5 is the search.

```
backend/apps/project/
  __init__.py       exports `router`, `status`, `set_ask_model` — the whole contract with api.py
  store.py          SQLite, the gates, the path guard, the borrowed model, the rack reading
  routes.py         the APIRouter and the rack `status()`
  test_project.py   102 tests, offline, no GPU, no network
  README.md         this
```

Built against `backend/project/docs/project-spec.md`. Where this implementation departs from the spec,
it says so below and gives the reason.

---

## Wiring — the three lines `backend/server.py` needs

```python
from apps import project    # noqa: E402  -- workspace surface, brings its own APIRouter

app.include_router(project.router, prefix="/api/project", tags=["project"])

Unit(**project.status()),
```

and one **optional** line, if you want the drafting endpoints to work:

```python
project.set_ask_model(lambda prompt: ...)      # str -> str, your own route to /api/chat
```

Points that matter:

- **The include must come BEFORE the `StaticFiles` mount.** That mount is at `/` and matches
  everything; a route declared after it is unreachable. Put it beside the tuner's include.
- **`ops/Caddyfile` needs no change.** `handle /api/*` already delegates the whole subtree, so
  `/api/project/*` is covered the moment the router exists. Worth knowing rather than
  trusting: Caddy answers everything *else* off disk without asking the API, which is why the
  four section pages 404'd in production while returning 200 on `127.0.0.1:8800`.
- **Do not add an extensionless `/project` route.** That costs edits to `tools/build/build_split.py`,
  `backend/server.py`, `ops/Caddyfile` **and** `is_route()` in `scripts/deploy.sh`, and gets you
  a `MISSING project` from the deploy check if you forget the last one.
- **`status()` is synchronous, cheap and safe to call on every rack poll.** It opens the store
  read-only, or not at all. It takes no lock, creates no file and does no work when the
  surface is switched off.
- **`status()` returns a plain dict, not a `Unit`.** Its keys match `api.py`'s `Unit` fields
  exactly — a test asserts the key set — so `Unit(**project.status())` works. It deliberately
  does not import `Unit`; that would put this module inside `api.py`'s import graph.
- **No shutdown hook, no background task, no lifespan participation.** There is nothing
  running. A connection is opened per request and closed at the end of it.

### The rack unit it produces

| Field | Value |
|---|---|
| `id` | `project` |
| `label` | `SyMoNeuRaL Project` |
| `slot` | `1U` |
| `bus` | `cpu` |
| `href` | `/project.html` — **see below** |
| `spec` | `SQLite · FTS5 · no weights` |
| `state` / `detail` | computed, three cases below |

```
surface disabled (SYMONEURAL_PROJECT_ENABLED unset)  -> offline   "surface disabled on this installation"
enabled, store missing or unreadable          -> offline   "no project store initialised"
enabled, store answers                        -> ready     "cpu only, never queues"
```

**There is no `busy` state and no `queued` state, and that is correct rather than an
omission.** `busy` on this rack means holding the card. This surface never holds it, and a
workspace that flashed `busy` while a SQL query ran would be exactly the decorative indicator
the house rules forbid. There is nothing to queue behind either.

**`href` points at `/project.html`, which `tools/build/build_project.py` generates.** It pointed at
`/documentation.html` until that page existed, because `scripts/deploy.sh`'s reference check
can fail the build on a link to a page that is not there and a rack tile linking to a 404 is
a dishonest pixel; the page and this link changed in one commit, which is what that rule
asks for. A test in `test_project.py` asserts the target file exists, so the two cannot drift
apart again. **`apps/coder` still points at `/documentation.html`** and for the original
reason — it has no page and is not mounted in `api.py` at all.

**`bus` is `cpu` and there is deliberately no fifth value.** `site/console.js` maps the four
known buses to plate text and prints `--` for anything else. Inventing `db` or `store` would
put a `--` on the one plate the page asks a visitor to trust and would add nothing over `cpu`
— the work genuinely is CPU work. The `spec` field carries the detail for anyone who wants it.

**The rack `detail` line carries no live count, on purpose.** `semantic_etag` in `api.py`
hashes unit *states*, not their detail strings, so a number carried there would be cached away
as a 304 and sit stale on the page. Live counts are `GET /api/project/state`.

---

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SYMONEURAL_PROJECT_ENABLED` | unset | Must be exactly `1`. Off is the default. |
| `SYMONEURAL_PROJECT_TOKEN` | unset | The shared secret. `secrets.token_urlsafe(32)`, never chosen by hand. |
| `SYMONEURAL_PROJECT_DB` | `run/project/store.db` | Where the store lives. |
| `SYMONEURAL_PROJECT_ROOT` | the repo root | The tree a file reference may name. |
| `SYMONEURAL_PROJECT_BACKUP_DIR` | `<store>/../backups` | Where `POST /backup` writes. |

**Both switches are required and that is the design, not belt-and-braces.** It fails closed on
a misconfiguration, which matters on a box with a public IP where the difference between
"enabled with no token" and "off" is the difference between a private workspace and a public
one. Copied from `backend/apps/asicminer/`, which says the same thing in its own words.

Set the token in the systemd unit's environment. Not in a shell profile, not in the repo, and
never in a URL — `ops/Caddyfile` writes `/var/log/caddy/symoneural.log` and uvicorn logs the
request line, so a token in a query string is a token written to disk on every request. It
travels in the `X-Symoneural-Token` header, and a test walks `router.routes` asserting no path
segment is ever named for a credential.

**No rate limiting is implemented across this API as of 2026-08-20, so the token is the only
gate.** A deliberate pre-launch state, not a cleared posture — request ledger R-98, held. One
part of the original reasoning is worth carrying into that re-scope on its own merits: on one
GPU a rate limit never bought throughput, because the queue rations the card by itself. Either
way it is an argument for the token's length and entropy, which are carrying the whole load. One
asymmetry worth knowing: this surface is CPU-only, so unlike the GPU surfaces there is no
one-deep queue implicitly rationing it. An unauthenticated flood of `/api/project/search`
would be served as fast as SQLite can answer. FTS5 over a few hundred rows is cheap enough
that this is not a serious denial of service, and it is stated here rather than fixed with a
limiter.

### Where the store lives, and where the spec says it should

The spec proposes `backend/project/store.db` and argues `run/` is the wrong home because
`.claude/CLAUDE.md` describes `run/` as runtime state somebody will eventually clear out. That
argument is sound. The default here is still `run/project/store.db`, for a reason that is not
a disagreement: **`run/` is already in `.gitignore` and `backend/project/` is not.** A store
that defaults to an untracked path cannot be committed by accident on its first write, and a
workspace committed by accident is in the history permanently. `backend/apps/accounts/` made
the same call and keeps its database at `run/accounts/accounts.db`.

To take the spec's placement instead: add `backend/project/` to `.gitignore` and set
`SYMONEURAL_PROJECT_DB=backend/project/store.db`. Both are one line. Neither is this package's to
write, which is why the default is the safe one.

---

## Endpoints

Everything is under the mount prefix, everything requires `X-Symoneural-Token` (or
`X-Sym-Token`, the name it replaced — `routes._deny` reads both, new first), and every response
carries `api_version`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/state` | Live readings: counts, store size, whether anything is initialised |
| `POST` | `/backup` | Write a dated `.backup` copy |
| `GET` | `` | List projects. ETag + `Last-Modified` |
| `POST` | `` | Create a project |
| `GET` | `/search?q=` | FTS5 over projects, items and events |
| `GET` | `/{pid}` | One project with its items, file references and event count |
| `PATCH` | `/{pid}` | Rename, re-summarise, archive |
| `DELETE` | `/{pid}` | Delete — **archived projects only** |
| `GET` | `/{pid}/items` | Work items, `?state=` filterable. ETag |
| `POST` | `/{pid}/items` | Add one |
| `PATCH` | `/{pid}/items/{iid}` | Edit, re-state, reorder |
| `DELETE` | `/{pid}/items/{iid}` | Remove one; the deletion is recorded as an event |
| `GET` | `/{pid}/files` | Referenced paths, each with a live `stat` |
| `POST` | `/{pid}/files` | Reference a repository path |
| `DELETE` | `/{pid}/files/{fid}` | Drop a reference |
| `GET` | `/{pid}/events` | History, newest first. Append-only. ETag |
| `POST` | `/{pid}/events` | Record a session's work |
| `POST` | `/{pid}/draft/summary` | Ask the chat surface to summarise. **Returns, never stores** |
| `POST` | `/{pid}/draft/items` | Turn a note into candidate titles. **Returns, never stores** |

`/search` is declared **before** `/{pid}` or it would be captured as a project id and 404 on
every query. A test asserts it answers.

**Use `/api/project`, not `/api/project/`.** The list route is declared as `""`, so with the
prefix it answers on the bare path. In production the trailing-slash form is claimed by the
`StaticFiles` mount at `/` — which matches everything — and 404s off disk rather than
redirecting here. `test_project.py` mounts the router on a bare app with no static mount, so
that difference does not show up in the suite; it is stated here instead. Do **not** add a
route for the slashed form.

### The JSON contract

Success is `{"ok": true, "api_version": 1, ...}`. Failure is **always** the same envelope:

```json
{"ok": false, "api_version": 1, "code": "stale", "error": "this item is at version 3, ..."}
```

The `code` is what a client branches on; the `error` is for a human. One table in `routes.py`
maps codes to HTTP status, so a code cannot mean 404 on one route and 400 on another.

| code | status | |
|---|---|---|
| `disabled` | 503 | the surface is switched off |
| `unauthorized` | 401 | bad or missing `X-Symoneural-Token` |
| `not_found` | 404 | |
| `bad_field` / `bad_path` / `bad_query` / `outside_root` | 400 | |
| `denied` | 403 | the path is on the denylist |
| `duplicate` / `not_archived` / `stale` | 409 | |
| `too_large` | 413 | a size cap |
| `cap` | 507 | a row-count cap |
| `no_model` | 503 | nothing has been injected via `set_ask_model` |
| `model_error` / `model_unusable` | 502 | the chat surface failed or answered unusably |
| `store_error` | 500 | |

**Every pydantic field on every request body has a default.** That is a 422-avoidance measure,
not laziness: a *missing required* field makes pydantic raise, and FastAPI serialises that
into a body shaped `{"detail": ...}` — a second error shape a shipped app cannot parse, and,
as `apps/streamer` found the hard way, one that echoes the whole request back. With defaults
there is no validation path that can fire and the handlers check by hand. A test asserts it
for every model.

### Designed for a client that is not this website

There is no `site/project.html` yet, and the API does not assume there ever will be. No
cookies, no server-side session, no login flow, no hidden "currently open project" — the
client names the project in every request, so a phone and a laptop can interleave with no
notion of whose turn it is. If a page wants to remember which project was open, that is
`localStorage`, the same call chat already makes for conversations.

`ETag` and `If-None-Match` are honoured on the three list endpoints, and `Last-Modified` /
`If-Modified-Since` alongside them. A phone polling on a mobile connection is the difference
between a workspace that feels instant and one that spins. `If-None-Match` wins when both are
present, because an ETag is exact and a one-second HTTP date is not.

### Concurrent writes

`PRAGMA journal_mode=WAL`, a 10-second busy timeout, and **optimistic concurrency on every
mutable row**. `PATCH` may carry `if_version`; a mismatch is a `409 stale` that hands back the
current row so the client can merge, never a silent last-write-wins. Omitting `if_version` is
allowed and means "I did not read a version" — the escape hatch for a script, stated here
rather than pretended away. `404` and `409` are kept distinct, because answering "stale" for a
row that was deleted sends a client into a retry loop against something that will never exist.

The events log is append-only — no `PATCH`, no `DELETE`, asserted structurally — and is
therefore free of all of this.

One implementation note worth carrying: the schema is applied only when `PRAGMA user_version`
says it is not there. Running `executescript` on every connection, which the neighbouring
`apps/accounts` does, opens a **write** transaction even when every table already exists — so
every read queues behind every write and WAL's whole benefit is handed straight back. Fixing
that took the test suite from 11 s to 1 s.

---

## What this surface will and will not do with your files

**It references files. It never holds a copy, and no endpoint returns file contents.** Two
copies of a file drift, and this repository has a documented history of losing rounds to
exactly that. Reading and writing files is `backend/apps/coder/`'s job; it has the journal and
the rollback store that make that safe. Project stores the name and a live `stat`.

A path arriving from a client is:

1. rejected if it is empty, over-long, not a string, or contains a NUL;
2. joined onto the root unless already absolute;
3. **`resolve()`d**, which follows every symlink including the last component;
4. checked for containment against the **resolved** root;
5. checked against the denylist, against the **resolved absolute path**.

**Step 5 after step 3 is the whole point.** Denylisting the input string is the classic bypass:
a symlink named `notes.txt` pointing at `training/corpus.jsonl` walks straight past it. A test
creates exactly that symlink and asserts the refusal, and reverting the order turns it red.

The denylist, matched as segment runs anywhere in the resolved path:

| Denied | Why |
|---|---|
| `training/corpus.jsonl` | Trade secret. 327 hand-authored examples: the company voice, and what the model must refuse to invent. |
| `training/build_dataset.py` | Trade secret. The method that produces it. |
| `training/adapter/` | Trade secret. The weights. |
| `run/gpu.lock.d` | The GPU mutex. `mkdir` of that directory **is** the lock; there is nothing else. |
| `run/project/` | This store and its backups. A workspace item pointing at its own database is a loop with an exfiltration path on the end of it. |
| `.git/config` | Remotes and any credential helper configured against them. |
| `*.key`, `.env`, `.env.*` | Signing keys, TLS keys, secrets. |

A denied entry is **reported as denied, not hidden**. Telling an operator the corpus is not
there would be a lie; telling them it exists and is refused is the truth and is more useful.

A reference is re-checked on the way out as well as on the way in, so a path that was legal
when it was linked and has since become a symlink into `training/` reads back as `denied`
rather than as a live file. There is a test for that too.

**Nothing in this package reads, copies, serves or quotes any of those files.** A test parses
the package with `ast` and `tokenize`, strips docstrings and comments, and asserts the only
*code* that names the corpus is the denylist entry that refuses it.

## No content filtering is implemented. Structural guards only

As of 2026-08-20: no keyword list, no profanity check, no prompt-injection heuristic, no rate
limiter, no content inspection of any kind. **A deliberate pre-launch state, not a cleared
posture** — the standing instruction this section used to quote is held (request ledger R-98,
2026-08-20), awaiting re-scope per surface.

What is asserted is the store's data-integrity contract: a note is stored byte for byte — a
test round-trips a string containing script tags, shell metacharacters, SQL, ANSI escapes, a
right-to-left override and the literal words *"ignore previous instructions"* and asserts it
comes back unchanged, and another asserts a hundred writes are all persisted and readable back.

There used to be a further test here that scanned the package's own code for anything that
looked like a filter or a throttle and failed if one appeared. It was deleted on 2026-08-20: it
asserted the *absence of a mechanism* rather than any behaviour, which made it a ratchet against
ever adding a safety control — and the instruction behind it was "not yet", not "never". It also
contradicted the test two paragraphs up, which requires this package to carry a denylist
protecting the corpus.

What **is** enforced is structural, and the README calls it that rather than dressing it as
policy: path containment (above), and size caps that stop one request pinning memory.

| Cap | Value | |
|---|---|---|
| `MAX_NAME` | 400 chars | a project name, an item title, a search query |
| `MAX_TEXT` | 200,000 chars | an item body, a note, an event record |
| `MAX_PATH` | 1,024 chars | |
| `MAX_PROJECTS` | 2,000 | |
| `MAX_ITEMS_PER_PROJECT` | 20,000 | |
| `MAX_ROWS` | 500 | rows in one list response |
| `MAX_SEARCH_ROWS` | 200 | |

## Search is FTS5, and there is no embedding model

CPU, exact, built in, and it works while a fine-tune owns the card. There is a real temptation
to add embeddings — a small model is a few hundred MiB, which makes it feel free — and the
cost is not the VRAM. It would make this surface **evictable**, it would need its own arm in
`evict()` or it eats the `*)` default that pkills `llama-server|sd-cli`, and it would be a
tenth or eleventh governor surface on a card that already serialises five. Substring and
full-text search over a personal workspace of a few hundred items is not a problem that needs
a neural network. If semantic search is genuinely wanted later, run the embedding model **on
CPU**.

A malformed MATCH expression — `foo"`, a bare `AND`, an unbalanced paren — raises
`sqlite3.OperationalError`, which without a handler is a 500 on the one endpoint a flood would
hit. It is caught and reported as `bad_query` (400). That is robustness, not a filter: the
query is not inspected for *what it asks about*, only for whether SQLite can parse it.

## Where a model is involved, and where it is not

Project owns no weights. `POST /{pid}/draft/summary` and `POST /{pid}/draft/items` ask the
chat surface through an injected `str -> str` callable, exactly as `apps/streamer/guide` and `remix()`
in `api.py` do. This package never imports the API, never touches `scripts/gpu-governor.sh`
and never opens a socket; whatever the caller does about the GPU lock is the caller's
business. That is what keeps it importable and fully testable with no card, no network and no
service running — all 102 tests run in about a second.

If nothing has been injected, the answer is `503 no_model` saying exactly that. That is an
honest reading of a surface that is not wired, not a silent empty summary.

**A draft is returned and never stored.** It does not become the project summary and it does
not become work items on its own; recording it is a separate, deliberate call. That seam is
held open on purpose — see the security note below.

The prompt asks for **plain lines, never JSON**, and the parser rejects the JSON-loop shape
outright. That is measured, not theorised: asking this 7B for a JSON object made it loop
`{"match":["premier league","nfl","nba","mlb","f1","nfl","nba",...` until the token cap, so
nothing ever parsed and the fallback fired on every request while the feature looked fine. A
test asserts the refusal against that literal string.

## The coupling with Coder — read this before loosening anything

`backend/coder/docs/coder-spec.md` recommends Coder be local-only: no route, nothing bound beyond
loopback. **Project is an input to Coder.** If Project holds work items and Coder reads them
to decide what to do, then a writable Project is a way to put instructions in front of an
agent that executes commands — **a world-writable Project plus a local Coder is remote code
execution in two hops**, with the network step and the execution step in different modules, so
a reviewer looking at either sees something reasonable and neither sees the whole path.

Two rules, neither negotiable:

1. **Coder reads Project; Project never invokes Coder.** One direction only. Nothing in this
   package imports, spawns or calls Coder, and a test asserts the package imports no
   `subprocess`, `socket` or `urllib`.
2. **Coder must treat Project content as untrusted input**, exactly as it would treat a
   fetched web page. A work item is data describing a task, never an instruction obeyed
   verbatim. A human starts every Coder session.

If Coder is ever made to poll Project for work, **this module's security argument is void**:
that change would silently promote Project's token into an RCE gate, and both this file and
both specs need revisiting before it lands.

## Never taking the card, asserted rather than documented

The design argument is the whole reason to build this CPU-only, so it is a test rather than a
paragraph. `test_project.py` parses the package and asserts that no *code* line names the
governor, `nvidia-smi`, `llama-server`, `sd-cli`, `torch`, CUDA, an embeddings library or
`run/resident`; that the only code naming `run/gpu.lock.d` is the denylist entry refusing it;
and that the package imports nothing that could reach the card or the network. A future change
adding an embedding model **fails the suite** rather than quietly making the surface evictable.

`GET /api/project/state` reports `gpu: {holds_lock: false, vram_mib: 0}`. That zero is by
construction, not by measurement, and the note beside it says so.

---

## Tests

```bash
python3 backend/apps/project/test_project.py        # 102 tests, ~1s
```

No network, no GPU, no service running. Every test points `SYMONEURAL_PROJECT_DB` at a temp directory
— the real `run/` holds `gpu.lock.d`, and a test that wrote in there could destroy a lock
while a surface held the card — and `SYMONEURAL_PROJECT_ROOT` at a temp tree containing a *fake*
`training/corpus.jsonl`, so the trade-secret assertions never have the real one in reach.

33 of the guards were verified by reverting them one at a time and confirming the relevant
test goes red, then restoring. Two findings from doing that, both fixed:

- `test_a_rack_poll_does_not_create_the_store` passed with **both** probe guards removed,
  because the temp store's parent directory did not exist and `sqlite3.connect` failed for an
  unrelated reason. The test now creates the parent first, so it fails for the reason it
  claims.
- The obvious WAL test — read while another connection holds a write transaction — passes in
  rollback-journal mode too, because a RESERVED lock does not block readers. It was replaced
  with the assertion WAL actually buys: a **write** landing while another connection holds an
  open **read** transaction.

One case is intentionally green: removing the `projects_ad` trigger alone leaves the search
index correct, because `delete_project` also sweeps by `project_id`. Removing both goes red.

---

## What is NOT implemented

Blunt list. Nothing here is hidden behind a "coming soon".

1. ~~**There is no page.**~~ **Done.** `tools/build/build_project.py` generates `site/project.html`
   and the rack unit links to it. The generator writes that one new file and nothing else, so
   it cannot clobber the writers that share `site/index.html`; it imports `build_pages` for
   `SHELL` and `NAV` but never calls `page()`. `tests/project.mjs` drives the page in real
   Chrome against `tests/project-harness.py` — 15 assertions, including that the token gate
   actually hides the workspace, that the denylist refusal for `training/corpus.jsonl` reaches
   the UI, and that a draft with no model wired says why instead of rendering empty.
   **What the page does not do:** there is no pagination control (item 5 below is unchanged),
   no editing of a file reference (item 6), and it is single-user because the API is (item 7).
2. **Nothing schedules the backup.** `POST /api/project/backup` and `store.backup()` work and
   write a dated, consistent copy. There is no cron entry and no systemd timer, so until
   somebody adds one the backup is only as good as remembering. Given there is no git remote
   and the store is gitignored, this is the largest operational risk in the module. This
   project has already lost a contract signing key that lived somewhere nobody backed up.
3. **`.gitignore` was not touched.** The default store path is already covered by the existing
   `run/` entry, which is why the default is what it is. Moving to the spec's
   `backend/project/` requires an ignore line somebody else has to write.
4. **The second-state-document question is not resolved, and `.claude/CLAUDE.md` as written
   today forbids this surface.** It says *"Do not create a second state document. Update
   `.claude/HANDOVER.md`."* A project surface holding "what is left to do" is structurally a
   second state document, and the two will diverge within days. The recommended resolution is
   the spec's first: **Project holds session-scoped working state — what I am doing right now,
   what I tried, what the next step is — and HANDOVER stays authoritative for project state.**
   That sentence needs adding to `.claude/CLAUDE.md` by whoever owns it, in the commit that
   wires this in, or a future agent will read the rule and correctly refuse to use the
   surface. It is not an agent's call to make.
5. **No pagination cursor on `/{pid}`.** `GET /{pid}` returns up to `MAX_ROWS` items and files
   with no `next` token. Fine for a personal workspace; wrong for one with 20,000 items, which
   the cap allows.
6. **No `PATCH` on a file reference.** Change the note by unlinking and relinking.
7. **No multi-user model.** One shared token, one workspace. If "like the claude cowork" turns
   out to mean *shared with other people*, that is a materially different surface — real
   accounts, per-user authorisation, an audit trail of who wrote what — and the auth design
   here would need rewriting rather than adjusting. `backend/apps/accounts/` exists and would
   be the place to start.
8. **`GET /state`'s search-latency figure does not exist**, deliberately. The spec lists query
   latency as a figure to measure; it has not been measured on realistic content, so no number
   is reported rather than a flattering guess.
9. **The "works while the GPU is busy" claim is untested end to end.** The design guarantees it
   and the code asserts the surface never asks for the card, but the actual measurement — hold
   the lock with an image render, hit `/api/project` and confirm 200s and no `wait` line for
   `project` in `run/governor.log` — belongs in `tests/frontend.mjs`, which is owned by another
   writer. It is the one measurement worth making, because it is the actual claim.
10. **No `ETag` on `GET /{pid}`, `/state` or `/{pid}/files`.** Only the three list endpoints.
11. **File-reference notes are not in the search index.** FTS5 covers project names and
    summaries, item titles and bodies, and event text. The `note` on a `files` row is stored
    and returned but not indexed, so `/search` will not find it. The spec asks for search over
    "items and notes"; this is the part of that not done.
12. **`readings()` includes a `note` key only when there is nothing to report** — "no project
    store initialised", or "no workspaces open" — and omits it once the store has content.
    That is a wobble in a contract advertised as stable. A client must treat `note` as
    optional; a later `api_version` should make it always present and empty.

## Open questions for the user

- **Does Project hold the queue, or does HANDOVER?** Item 4 above. This is the decision that
  has to be made first and it changes what `.claude/CLAUDE.md` says.
- **Does Coder read Project?** If yes, the two modules' security arguments are coupled and
  "Coder never polls Project" becomes load-bearing rather than advisory.
- **Does "like the claude cowork" mean shared with other people?** Item 7. It changes the auth
  design completely, and it is worth answering before a page is built against this API.
- **The rack goes to twelve units, and the layout budget was already blown at nine.**
  `backend/project/docs/project-spec.md` §5.5 counts nine and measures Live stack **76px over at
  1301×740** with that many, `train`'s label already wrapping to five lines. That count is
  stale: `backend/server.py` now builds **eleven** — chat, image, remix, ravencalc, train,
  asicminer, gpuminer, tuner, coder, gateway, guide — counted directly, not from the spec.
  This unit makes twelve. Live stack must be re-measured at 1301×740 and 1855×745 in the same
  change, reading computed styles rather than reasoning about the cascade, and folded into
  `<details>` rather than trimmed if it does not fit. Bind any fold handler to `#rack`, never
  to `#units`, which `renderRack()` rewrites on every status push.

<!-- generated: do not edit below -->

## Operations — 19

|  | path | what it does |
|---|---|---|
| GET | `/api/project` | List projects |
| POST | `/api/project` | Create a project |
| POST | `/api/project/backup` | Write a dated copy of the store |
| GET | `/api/project/search` | Full-text search over projects, items and events |
| GET | `/api/project/state` | What this surface is holding, read from the store |
| DELETE | `/api/project/{pid}` | Delete an archived project |
| GET | `/api/project/{pid}` | One project, with its items and file references |
| PATCH | `/api/project/{pid}` | Rename, re-summarise or archive a project |
| POST | `/api/project/{pid}/draft/items` | Turn a note into candidate item titles |
| POST | `/api/project/{pid}/draft/summary` | Ask the chat surface to summarise a project |
| GET | `/api/project/{pid}/events` | What happened, newest first |
| POST | `/api/project/{pid}/events` | Record a session's work. Append-only |
| GET | `/api/project/{pid}/files` | Files this project references, with a live stat |
| POST | `/api/project/{pid}/files` | Reference a repository file from this project |
| DELETE | `/api/project/{pid}/files/{fid}` | Drop a file reference |
| GET | `/api/project/{pid}/items` | Work items, filterable by state |
| POST | `/api/project/{pid}/items` | Add a work item |
| DELETE | `/api/project/{pid}/items/{iid}` | Delete a work item |
| PATCH | `/api/project/{pid}/items/{iid}` | Change, reorder or re-state a work item |

## Library — no routes, no side effects on import

| file |  |
|---|---|
| `store.py` | The store. SQLite via the stdlib, CPU only, and it never asks for the card. |

## Documents

- [`project-spec.md`](docs/project-spec.md)

<!-- end generated -->
