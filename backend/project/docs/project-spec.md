# SyMoNeuRaL Project — design spec

**Status: PROPOSAL. Nothing here is built. Nothing here is state.**
`.claude/HANDOVER.md` is the one state document; this is an input to a decision, in the
sense `ops/backend/authority/docs/README.md` describes.

Written 2026-08-17 against the working tree at `595835d` plus uncommitted changes.

Requested by Garrett as **"like the claude cowork"** — a project/workspace surface for
organising work across files and sessions.

**Read `backend/coder/docs/coder-spec.md` alongside this.** The two are coupled, and the coupling is
a security property rather than a convenience: §4.1 here is the sharpest thing either
document says.

---

## 1. What it is, and what it is not

### 1.1 What it is

A **workspace**: named projects, each holding work items, notes, references to files in the
repository, and the history of what was done to them across sessions. It answers the
questions that currently have no home on this box — *what am I working on, what is the state
of it, what did the last session do, and what is next.*

That question genuinely does not have a home. `.claude/HANDOVER.md` §5 is a hand-maintained
queue in a Markdown file, and it works, but it drifts. Two drifts found while writing this
spec, both verified directly: **§0 says eight rack units where `backend/server.py` builds
nine**, and **§5b carries two different items both numbered 10** (HANDOVER lines 1025 and
1090 — one about CDI and containers, one recording the `deploy.sh` subshell bug as already
fixed). Neither is serious; both are the signature of a hand-maintained list outgrowing its
format. That drift is the argument for this surface, and it is a better argument than
"Claude has one."

### 1.2 What it is not

- **It is not a GPU surface.** This is the central conclusion and §2 argues it rather than
  assuming it.
- **It is not a second state document.** `.claude/CLAUDE.md` is explicit: *"Do not create a
  second state document. Update `.claude/HANDOVER.md`."* If Project starts holding
  authoritative project state alongside HANDOVER, the exact failure that produced that rule
  — three files all claiming to describe current state, agents acting on the stale one —
  comes back with a database attached and a REST API in front of it. §7.1.
- **It is not an issue tracker to be sold.** Nothing here is a public product surface. It is
  an operator tool, like `backend/apps/asicminer/`.
- **It is not a file store.** It references files in the repo by path; it does not hold
  copies. Two copies of a file drift, and this project already has a documented history of
  losing rounds to exactly that (two copies of a breakpoint, two web-server configs, three
  state documents).
- **It is not a chat surface.** It stores and organises. Any summarising or drafting is a
  call to the existing `/api/chat`, not new weights. §2.4.

### 1.3 Why it is specified separately from Coder

They look like one feature and they are not. Coder **executes**; Project **stores**. They
have opposite risk profiles — Coder's risk is arbitrary code execution, Project's is data
exposure — and opposite resource profiles, since Coder is a GPU tenant and Project is not.
Specifying them together would have produced a document where the GPU constraint applied to
half the content and the security argument to the other half, and the seam between them is
exactly where §4.1's two-hop problem hides.

---

## 2. The hard constraint, and why it mostly does not apply

### 2.1 The constraint, restated

One **RTX 5070 Ti**. `nvidia-smi` reports `memory.total = 16303 MiB` (15.92 GiB), read
directly on 2026-08-17; idle baseline measured **1,012 MiB**. One tenant at a time, via a
`mkdir` lock at `run/gpu.lock.d` arbitrated by `scripts/gpu-governor.sh`. `run/resident`
holds exactly one surface name and `evict()` is a `case` statement over single surfaces.

Measured occupancy of the existing tenants: chat **≈5.4 GiB** (16,303 − 9,778 free at
`acquire`, less the idle baseline, from `run/governor.log` 2026-08-17 08:39:23 — this
confirms the rack's `~5 GB resident` as a measured figure); image `~7 GB`; a QLoRA run
~10–13 GB. No two of them co-fit. See `backend/coder/docs/coder-spec.md` §2 for the full arithmetic,
including the important caveat that the working tree's uncommitted `-c 65536` change
projects chat at ~8.7 GB and that figure **has never been run**.

### 2.2 Project is not a GPU surface — the conclusion, argued

**It should never take the GPU lock.**

Work through what a workspace actually does: create a project, list projects, add a work
item, mark one done, attach a note, link a file path, record what a session changed, show
history. Every one of those is a read or a write to a small structured store. **None of them
involves a model.** There is no inference in the definition of the feature.

The precedent is already in the repo and is explicitly framed as a design decision rather
than an accident. `.claude/CLAUDE.md`:

> RavenCalc (SymPy, CPU) deliberately never takes the lock. That is what lets it
> speculatively pre-compute while the GPU is loading.

And `backend/server.py`'s unit for it: `bus="cpu"`, `detail="cpu only, never queues"`.

The Tuner makes the same point from a different direction — `bus="net"`, because *"the work
is network I/O and muxing, so it never contends for the card,"* and `Unit.bus` carries a
comment saying `asic` and `net` are distinct values precisely because neither contends for
the GPU lock.

Project belongs in that family. **The benefit is not that it saves VRAM — it is that Project
is always available.** A workspace that queues behind a fine-tune is useless: the moment you
most want to record what you were doing is the moment the card is busy for three hours. A
surface that never takes the lock cannot be blocked by one that does, and it can be read and
written *while* chat, image or a training run owns the card. That is the same property
RavenCalc has and the same reason it is valuable.

**VRAM arithmetic for Project: 0 MiB. It loads no weights.** That is the whole calculation,
and it is worth stating in those terms because every other surface spec on this box has had
to fight for room.

### 2.3 The one place the GPU could creep in, and the recommendation

There is a real temptation and it should be named rather than left for someone to discover:
**semantic search over project content**, or auto-summarising a session, or embedding notes
so that "what did I do about the Caddyfile" finds the right item.

Embeddings are a model. A small embedding model is only a few hundred MiB, which makes it
feel free — and that is exactly the reasoning that turns a CPU surface into a GPU tenant.
The costs are not the VRAM:

1. **It makes Project evictable.** The moment it needs the card it can be queued behind a
   fine-tune, and the always-available property in §2.2 — the main reason to build it this
   way — is gone.
2. **It needs a `project)` arm in `evict()`**, or it falls through to the `*)` default which
   pkills `llama-server|sd-cli` — the collateral-kill bug the `miner)` arm was added to
   prevent (see `scripts/gpu-governor.sh`).
3. **It is a tenth or eleventh governor surface** on a card that already serialises five.

**Recommendation: no embeddings in v1. Use SQLite FTS5, which is CPU, exact, and built in.**
Substring and full-text search over a personal workspace of a few hundred items is not a
problem that needs a neural network. If semantic search is genuinely wanted later, run the
embedding model **on CPU** — the same call `.claude/HANDOVER.md` §5 item 12 tells the Voice
surface to make about `whisper.cpp` and Piper, and for the same reason.

### 2.4 Where a model *is* legitimately involved

Project may want to draft a summary of a session or turn a rambling note into a work item.
That is a chat completion, and it should be **a call to the existing `/api/chat`**, not new
weights and not a new tenant.

Consequences, and they are all good ones:

- Project itself still never touches the governor. The chat surface does, as it already does
  for every other caller, and Project waits on an HTTP request like any client.
- No second chat path. `.claude/HANDOVER.md` §5 item 12 gives Voice the same instruction —
  reuse `/api/chat` with its `history` array rather than growing a second route — and the
  same reasoning applies.
- The `role` field on `/api/chat`'s `history` is `Literal["user","assistant"]`, so a client
  **cannot inject a `system` turn** and override the trained persona and refusals. That is
  deliberate per `.claude/HANDOVER.md` §2f. Project inherits it and must not work around it.
- **It degrades correctly.** If the card is held by a fine-tune, drafting a summary fails or
  waits — and *everything else in Project still works*, because the store is CPU. A workspace
  whose read path depended on the GPU would go dark entirely.

### 2.5 Storage, and why it needs no new dependency

**SQLite, via the `sqlite3` module in the standard library.** Verified on this box:
`sqlite3 3.46.1` under `python 3.13.5`, along with `json`, `uuid`, `secrets`, `hmac` and
`pathlib` — all stdlib, all importable from the system interpreter with no install.

That is load-bearing, not incidental. `.claude/CLAUDE.md` is emphatic that the serving API
uses **only the system interpreter** — fastapi, uvicorn, pydantic and sympy are OS packages,
there is no virtualenv in the serving path, and `.claude/settings.local.json` carries deny
rules blocking bare `pip install` because a stray install there is hard to notice and hard to
undo. **A workspace surface that needs SQLAlchemy, Postgres or a migration framework would
violate that rule for a feature that a single stdlib module already covers.**

`backend/apps/asicminer/` shows what the alternative costs: pyasic needs 31 packages, so it
lives in its own `.venv` behind a subprocess that prints JSON. That boundary is correct for
rig protocols and would be absurd for a to-do list.

**Where the file goes.** Not `run/` — `.claude/CLAUDE.md` is explicit that `run/` is runtime
state, holds the GPU mutex, and that the name is load-bearing because *"call the directory
`logs` and sooner or later someone logrotates it or clears it out, which deletes the lock
directory while a surface is holding the card."* **A project database is durable data and
must not live next to a thing that is designed to be safe to delete.** Not `site/` either —
`scripts/deploy.sh` publishes from there and would push it to the public webroot, which is
exactly how 19 unreferenced renders ended up in `/var/www/symoneural`.

Proposal: **`backend/project/store.db`**, with `backend/project/` added to `.gitignore`
alongside the existing `run/` and `backend/output/` entries. It is durable, it is outside the
deploy path, and it is not runtime scratch.

**It must be backed up, and nothing on this box currently is.** There is **no git remote** —
history never leaves this machine, which `.claude/CLAUDE.md` notes is doing a lot of the
protecting for the trade secrets. For a gitignored database that protection is just absence
of a backup. `sqlite3 store.db ".backup"` into a dated file is one line and should be part of
the spec rather than an afterthought. §7.4.

---

## 3. The API shape

### 3.1 Where the routes go, and the two ways this has already broken

Routes at **`/api/project/*`**, matching the convention every surface already follows —
`/api/chat`, `/api/image`, `/api/ravencalc`, `/api/tuner/*`, `/api/asicminer/*`,
`/api/gpuminer/*` — and matching the Backstage plugin shape `.claude/HANDOVER.md` §5 item 13
records as the direction of travel, where a surface answers at `/api/<pluginId>`.

**Declared BEFORE the `StaticFiles` mount in `backend/server.py`.** That mount is at line 1988,
mounted at `/`, and it matches everything — a route declared after it is unreachable. Follow
the tuner: a self-contained `APIRouter` in `backend/apps/project/routes.py`, included as

```python
app.include_router(project.router, prefix="/api/project", tags=["project"])
```

next to the tuner's include at line 1937, whose comment already states this rule.

**`ops/Caddyfile` needs no change, and the reason is worth knowing rather than trusting.**
Caddy only delegates specific paths to FastAPI — `/api/*`, `/docs*`, `/openapi.json`, and the
exact-match set `/ /overview /livestack /controlboard /receipts`. Everything else is answered
off disk by `file_server` and **never reaches the API**. `handle /api/*` already covers
`/api/project/*`, so nothing there changes.

**This has shipped broken once.** The four section pages 404'd in production while returning
200 on `127.0.0.1:8800`, because the routes existed in `backend/server.py` and Caddy answered
from the webroot without asking. The rule that follows:

| What you add | Caddyfile change? |
|---|---|
| `/api/project/...` | **None.** |
| `site/project.html`, linked as `/project.html` | **None** — falls through to `file_server`. |
| An extensionless `/project` | **Yes**, plus three other files. |

The last row costs edits to `tools/build/build_split.py`, `backend/server.py`, `ops/Caddyfile` **and**
`is_route()` in `scripts/deploy.sh` — which otherwise reports `MISSING project`, because
pages link `/project` while the file is `project.html`. **Do not add an extensionless route.**

And note: **a local test run cannot catch a mistake in that list.** Against
`127.0.0.1:8800` the API answers directly and the Caddyfile is not exercised at all;
`tests/frontend.mjs` passed 25/25 locally while all four section URLs were dead in
production. Run it against `https://symoneural.com` after any routing change.

### 3.2 The routes

```
GET    /api/project                     list projects
POST   /api/project                     create a project
GET    /api/project/{pid}               one project, with its items
PATCH  /api/project/{pid}               rename, archive
DELETE /api/project/{pid}               archive-then-delete, never a silent drop

GET    /api/project/{pid}/items         work items, filterable by state
POST   /api/project/{pid}/items         add one
PATCH  /api/project/{pid}/items/{iid}   change state, edit, reorder
DELETE /api/project/{pid}/items/{iid}

GET    /api/project/{pid}/events        what happened, newest first -- append-only
POST   /api/project/{pid}/events        record a session's work

GET    /api/project/search?q=           FTS5 over items and notes -- CPU, exact
```

`{pid}` and `{iid}` are opaque server-generated ids (`uuid4` hex, or a short random from
`secrets`), never a name and never a filesystem path. The reason is `.claude/HANDOVER.md`
§3.3: `/api/gen/{name}` takes an attacker-controlled name that hits the filesystem and is
matched against the exact shape the generator emits, because traversal is a real attack on a
public box. **Project ids should never reach a path join at all** — they are database keys,
which removes the class of bug rather than guarding it.

### 3.3 No browser session assumptions — this is a stated constraint, not a preference

`.claude/HANDOVER.md` §5 records that items 12 (Voice) and 13 (Stickers) are for **an iPhone
app Garrett intends to build against this server**, and that this *"is a real constraint on
the API design and it lands before the UI work: the routes have to be usable by something
that is not this site — no session-shaped assumptions, a stable JSON contract, and a clear
answer on authentication."*

**Project is the surface where this matters most**, more than Voice or Stickers, because a
workspace is the thing you most want on a phone — glance at the queue, add an item, check
what last night's session did. So it is designed for a non-browser client from the first
line, not adapted later:

- **No cookies. No server-side session. No login flow.** Authentication is the `X-Symoneural-Token`
  header (§4), which any HTTP client can set. There is nothing a browser provides that a
  Swift `URLRequest` does not.
- **Every request is self-contained.** No hidden "currently open project" on the server. The
  client names the project in the path. Two clients — laptop and phone — must be able to
  interleave requests with no notion of whose turn it is.
- **Credentials never appear in a path or a query string.** `backend/apps/streamer/` already
  enforces this with `test_router_paths_never_carry_a_credential`, which walks
  `router.routes` and asserts it structurally. **Copy that test, not just the intention** —
  an intention is not checked at the next refactor. It matters more here: a token in a path
  lands in `/var/log/caddy/symoneural.log`, which the Caddyfile configures.
- **A stable JSON contract with an explicit version field** in the response, so a shipped app
  binary that cannot be updated on demand can detect a change rather than misparse one.
- **Consistent error shape.** Every failure returns the same JSON envelope with a machine
  code, not sometimes a FastAPI `detail` string and sometimes a bare 500. A phone app cannot
  read a stack trace.
- **`If-Modified-Since` / `ETag` on the list endpoints.** A phone polls on a mobile
  connection; a 304 is the difference between a workspace that feels instant and one that
  spins.

### 3.4 Concurrency, which a phone plus a laptop makes real

Two clients means simultaneous writes, and SQLite's default journal will serialise them into
`database is locked` errors under exactly the pattern this surface invites.

- **`PRAGMA journal_mode=WAL`** so a reader never blocks a writer. This is the single most
  important line in the storage layer.
- **Set `timeout` on the connection** rather than letting a lock error surface as a 500.
- **`PATCH` carries the version it read** and the server rejects a stale write with 409
  rather than silently applying last-write-wins. Losing a note because two devices were open
  is the thing that makes people stop trusting a workspace.
- The events log is **append-only** and therefore free of all of this.

---

## 4. Reachability and authentication

### 4.1 The coupling with Coder — read this before choosing a gate

`backend/coder/docs/coder-spec.md` recommends Coder be **local-only**: a process in Garrett's xrdp
desktop session, per `.claude/HANDOVER.md` §2g, with no route, nothing bound beyond loopback,
and no Caddy delegation. The security property there is structural — it depends on a socket
not existing rather than on a check being correct.

**Project is an input to Coder.** If Project holds work items and Coder reads them to decide
what to do, then a writable Project is a way to put instructions in front of an agent that
executes commands. **A world-writable Project plus a local Coder is remote code execution in
two hops**, with the network step and the execution step in different specs — so a reviewer
looking at either one sees something reasonable and neither sees the whole path. That is how
this kind of hole gets shipped.

Two consequences, and neither is negotiable:

1. **Project's gate can never be looser than Coder's**, for as long as Coder consumes
   Project. Since Coder's gate is "no route at all," any route to Project is already the
   weaker link and must be gated on its own merits, not on Coder's.
2. **Coder must treat Project content as untrusted input**, exactly as it would treat a web
   page. A work item is data describing a task, never an instruction the agent obeys
   verbatim. If Coder ever executes what a Project item says without a human in the loop,
   Project's authentication *is* Coder's authentication, and §4.3's token is standing in for
   the missing socket.

The clean way to hold this line: **Coder reads Project; Project never invokes Coder.** One
direction only, and a human starts every Coder session. That keeps Project's blast radius to
its own data even if its gate fails.

### 4.2 (a) Local-only

The safest option and the one Coder takes. For Project it is **too restrictive**, and the
reason is the iPhone app in §3.3 — a workspace reachable only from one desktop session
defeats the main thing a workspace is for. Unlike Coder, where the limitation is acceptable
because agentic sessions are a desk activity, here the limitation removes the feature.

Worth stating because the asymmetry is the point: **the two surfaces get different answers
because they have different risk profiles, not because the rules were bent.** Project stores
text. Coder runs commands.

### 4.3 (b) Operator-gated route, `SYMONEURAL_PROJECT_ENABLED` + `SYMONEURAL_PROJECT_TOKEN` — RECOMMENDED

The pattern is already in this repo at `backend/apps/asicminer/__init__.py` and should be
copied rather than reinvented:

```python
def enabled() -> bool:
    return os.environ.get("SYMONEURAL_PROJECT_ENABLED") == "1" and bool(os.environ.get("SYMONEURAL_PROJECT_TOKEN"))

def token_ok(presented: str | None) -> bool:
    """Constant-time compare, so a wrong token cannot be found a character at a time."""
    import hmac
    want = os.environ.get("SYMONEURAL_PROJECT_TOKEN") or ""
    if not want or not presented:
        return False
    return hmac.compare_digest(presented, want)
```

with the route dependency mirroring `_asic_auth` in `backend/server.py`: **503** when the
surface is off, **401** on a bad or missing `X-Symoneural-Token`. `X-Sym-Token`, the name it replaced,
is still accepted.

**Requiring both variables is the design, not belt-and-braces.** It fails closed on a
misconfiguration — which matters on a box with a public IP, where the difference between
"enabled with no token" and "off" is the difference between a private workspace and a public
one. The asicminer module says so directly: *"Without a token there is no route, so a
misconfiguration fails closed rather than open."*

**Why this is sufficient here where it is not sufficient for Coder.** The worst case for a
leaked Project token is that someone reads and writes Garrett's work notes — bad, genuinely
bad, but bounded, recoverable from a backup, and it does not execute anything. The worst case
for a leaked Coder token is arbitrary code execution as the user that owns the repository,
the site and the model weights. `.claude/HANDOVER.md` §2g's *"'behind a password' is not
sufficient on its own for that capability"* is a statement about **that capability**. Project
does not have it — **provided §4.1 holds.**

**Additional requirements, given rate limiting is off (§4.5):**

- **A long random token**, generated with `secrets.token_urlsafe(32)`, never chosen by hand.
  With no throttle, entropy is the only thing standing between the token and a guess.
- **Set it in the systemd unit's environment**, not in a shell profile and not in the repo.
- **Never log it.** The Caddyfile writes `/var/log/caddy/symoneural.log`; a token in a query
  string would be written to disk on every request. This is why §3.3 puts it in a header.
- **Off by default in the committed configuration**, so a fresh clone or a rebuilt box is
  private until someone deliberately enables it.

### 4.4 (c) Public — rejected

A public workspace is a public record of what is being built, when, and what is broken. That
is competitive information at best. Combined with §4.1 it is worse than that. There is no
version of this surface that is honestly public, and unlike the site's measurements —
published deliberately, including the negative results — none of this content is part of the
argument the site makes.

### 4.5 Rate limiting is off, so the token is the only gate

Per-endpoint rate limits were **switched off across the API on 2026-08-17 at Garrett's
instruction**. `backend/server.py` builds `LIMITS` from `SYMONEURAL_RATE_*` environment variables; unset
yields `(0, 0)`, which means **no limiter object at all** — a surface with no configured
budget is unmetered rather than getting a zero-capacity bucket, which the code notes would be
the exact inversion of "no limit."

`backend/server.py` states the consequence plainly for the GPU miner gate: *"The token IS the
gate now… there is no second layer catching a brute-force attempt."* The same is true here.

**This is not an argument to turn rate limiting back on.** Garrett's reasoning is recorded in
the code and it holds: on one GPU a rate limit never bought throughput, because the queue is
one job deep and rations the card by itself. It is an argument for the token requirements in
§4.3 — length, entropy, and never being logged — since they are now carrying the whole load.

One asymmetry worth noting: Project is **CPU-only**, so unlike the GPU surfaces there is no
one-deep queue rationing it implicitly. An unauthenticated flood of `/api/project/search`
would be served as fast as SQLite can answer. FTS5 over a few hundred items is cheap enough
that this is not a serious denial of service, but it is the one place where "the card rations
it" — the reasoning behind switching limits off — does not apply. Worth a sentence to Garrett
rather than a limiter.

---

## 5. The rack unit

### 5.1 Naming — and the live defect not to copy

The convention in `backend/server.py`'s `Unit` list: **`label` is the product name and nothing
else.** SyMoNeuRaL Chat, SyMoNeuRaL Image, SyMoNeuRaL Remix, SyMoNeuRaL RavenCalc, SyMoNeuRaL
Miner, SyMoNeuRaL Miner GPU, SyMoNeuRaL Gateway. The technique goes in `spec`; footprint and
attribution go in `detail`.

`Unit(id="train", label="SyMoNeuRaL Quantized Low-Rank Adaptation Tool", …)` **is a defect**.
It prefixes our name onto a generic technique expansion instead of being a product name, and
it is **wrapping to five lines** in a section already measured as over its vertical budget.
Its own `spec` field already carries `SymonChat persona adapter · QLoRA`, so the technique is
stated correctly one line below the label that states it badly.

So: **`label="SyMoNeuRaL Project"`**. Not "SyMoNeuRaL Project Workspace and Session
Organiser." Two words, one line, done.

### 5.2 The unit

```python
Unit(id="project", label="SyMoNeuRaL Project", slot="1U",
     state=project_state,        # computed -- see 5.3
     bus="cpu",
     href="/project.html",
     spec="SQLite · FTS5 · no weights",
     detail="cpu only, never queues")
```

| Field | Value | Why |
|---|---|---|
| `id` | `project` | Matches the route prefix `/api/project`, the page, and the module. One name. |
| `label` | `SyMoNeuRaL Project` | Product name only. §5.1. |
| `slot` | `1U` | The smallest unit. It is a database. RavenCalc is 1U for the same reason. |
| `bus` | **`cpu`** | §5.4 — this is the important field. |
| `state` | computed | §5.3. |
| `spec` | `SQLite · FTS5 · no weights` | Honest and informative: it says outright there is no model here, which is the surface's defining property. |
| `detail` | `cpu only, never queues` | **Deliberately the same words as RavenCalc**, because it is deliberately the same design decision. |

### 5.3 The honest default state

**`offline` until the store exists and answers; `ready` after that. Computed, never
hardcoded** — the way `gateway_state`, `asic_state` and `gpuminer_state` already are.

```
surface disabled (SYMONEURAL_PROJECT_ENABLED unset)  -> "offline",  "surface disabled on this installation"
enabled, store missing or unwritable          -> "offline",  "no project store initialised"
enabled, store answers                        -> "ready",    "cpu only, never queues"
```

**It has no `busy` state and that is correct, not an omission.** `busy` on this rack means
*holding the card*. Project never holds it. A workspace that flashed `busy` while a SQL query
ran would be a decorative indicator — the thing `.claude/CLAUDE.md` forbids outright, and the
thing `.claude/HANDOVER.md` §2c-ter warns is indistinguishable from a working one in a
screenshot. It also has no `queued` state, for the same reason: there is nothing to queue
behind.

**`ready` is genuinely honest here once built**, in a way it is not for several neighbours.
The Tuner's unit comment makes the distinction: *"`ready` is honest here — unlike the mining
surfaces this one is functional right now."* Project is in the Tuner's position, not the
Gateway's: no missing hardware, no undeployed contract, nothing pending. A SQLite file either
opens or it does not.

### 5.4 `bus="cpu"` — do not add a fifth value

`Unit.bus` is `Literal["gpu", "cpu", "asic", "net"]`.

Adding `asic` and `net` for the mining and IPTV surfaces **exposed a live bug**:
`site/console.js` rendered `u.bus === 'cpu' ? 'CPU' : 'GPU'`, so an ASIC surface printed
"GPU" — the wrong hardware on the one plate the page asks a visitor to trust. It is a `BUSES`
lookup now, printing `--` for anything unrecognised, which fails honestly rather than
lying — but it still fails.

There is a temptation to invent `db` or `store` for this surface. **Resist it.** The work is
CPU work; `cpu` is accurate. A new value means editing `console.js` in the same commit or
shipping a `--` on the plate, and the value it would add over `cpu` is zero. The `spec` field
already says `SQLite · FTS5 · no weights` for anyone who wants the detail.

### 5.5 The layout cost, which is real

`backend/server.py` currently builds **nine** units — chat, image, remix, ravencalc, train,
asicminer, gpuminer, tuner, gateway. (`.claude/HANDOVER.md` §0 says eight; `gpuminer` was
added after that line was written. Counted directly for this spec.)

`.claude/HANDOVER.md` §3.0 measures Live stack as fitting at 1920×1080, 1855×745 (Garrett's
window) and 1440×900, but **over by 76px at 1301×740** — with nine units, and with the
`train` label already wrapping to five lines.

**A tenth unit is a layout regression, not a cosmetic one.** If Coder is also added
(`backend/coder/docs/coder-spec.md` §5.4), that is eleven. Implementing this **requires re-measuring
Live stack at 1301×740 and 1855×745 as part of the same change**, reading computed styles
rather than reasoning about the cascade, per `.claude/CLAUDE.md`. Folding rather than
trimming if it does not fit — `.claude/CLAUDE.md` allows folding into `<details>` and
forbids dropping, and the rack already folds per-unit detail inside the one-screen layout.

Also note the fold handlers bind to `#rack` / `#console` and **never to `#units`**, because
`renderRack()` rewrites `#units` on every status push and a class toggled on a descendant is
undone by the next update.

Unlike Coder, **Project should appear on the rack as soon as it is built**, because it will
genuinely be `ready` and genuinely usable, and the rack is a list of what this machine
offers. There is no waiting-for-hardware caveat.

---

## 6. What must be measured before any figure about it reaches the site

`.claude/CLAUDE.md` requires every figure be labelled **measured** on this machine,
**vendor** specification, or **projected** arithmetic.

**Project's saving grace is that it has almost no figures to get wrong** — no tok/s, no VRAM,
no hashrate. That removes most of the risk. What is left:

| Figure | Status | How to measure |
|---|---|---|
| "never takes the GPU lock" | **verifiable, not a number** | Assert `project` never appears in `run/resident` or `run/governor.log`. A test, and a genuinely good one |
| VRAM used | **0 MiB, by construction** | Load no weights. Confirm by absence from the governor log |
| Query / search latency | **unmeasured** | Time real requests against a store with realistic content; label `measured` |
| "works while the GPU is busy" | **unmeasured, and it is the main claim** | §6.1 |
| Store size on disk | unmeasured | `stat`, once there is real content |
| Item / project counts on a page | must be **live** | Read from the store, never a hardcoded number. A count that does not change is decoration |

Two things **not** to do:

- **Do not put an uptime or availability percentage on the page.** It would be projected,
  it would be flattering, and it would be exactly the kind of decorative number this site's
  argument forbids.
- **Do not reuse RavenCalc's timings.** Same bus, different work. SymPy integration and an
  FTS5 query have nothing measurable in common.

### 6.1 The one measurement worth making, because it is the actual claim

**"SyMoNeuRaL Project answers while the card is busy."**

That is the whole design argument from §2.2, it is the reason to build it CPU-only, and it is
directly testable:

1. Start something that takes the lock and holds it — an image generation is ~11.2 s and
   sufficient; a fine-tune is the honest stress case.
2. While `run/resident` reads `image` (or `train`), issue `GET /api/project` and
   `POST /api/project/{pid}/items`.
3. Assert both return 200 within a normal latency budget, and that `run/governor.log` records
   **no `wait` line for `project`** — the surface never even asked for the card.

That belongs in `tests/frontend.mjs` alongside the existing assertions, and it is the kind
this project values: it asserts the **property**, not the markup. `.claude/CLAUDE.md` says to
add an assertion whenever a frontend bug is fixed; this one is better still, because it
locks in a design decision so that a future change adding an embedding model **fails the
suite** rather than quietly making the surface evictable.

---

## 7. What could go wrong

### 7.1 It becomes a second state document — the most likely failure

`.claude/CLAUDE.md` opens with this and it is the rule most at risk here:

> Three files once all claimed to describe "current state" and agents kept acting on the
> stale one. There is now one of each… **Do not create a second state document. Update
> `.claude/HANDOVER.md`.**

A project surface holding "what is left to do" is, structurally, a second state document —
with a database, an API, and no reviewer. HANDOVER's §5 queue and Project's item list will
diverge within days, and then an agent reads one while Garrett reads the other. This is not
hypothetical: it is the documented history of this exact repository.

**Resolutions, in order of preference:**

1. **Project holds session-scoped working state; HANDOVER stays authoritative for project
   state.** "What I am doing right now, what I tried, what the next step is" belongs in
   Project. "What the project is and what is left" belongs in HANDOVER. The boundary is that
   HANDOVER is what a fresh agent with zero context reads first, and Project is what a
   session accumulates.
2. **If Project is to hold the queue, HANDOVER §5 must be generated from it**, not
   maintained beside it. One source, one direction. That is more work and it is the honest
   version.
3. **What must not happen:** both maintained by hand.

Whichever is chosen, **say so in `.claude/CLAUDE.md` in the same commit that builds this**,
because the rule as written today forbids the surface and a future agent will correctly
refuse to use it.

### 7.2 The data leaks

The store contains what is being built, what is broken, and quite possibly credentials pasted
into a note. The token is the only gate (§4.5).

- **Never serve the store file itself.** No `GET /api/project/export` returning the raw `.db`,
  no path under `site/`. `scripts/deploy.sh` publishes web assets from `site/` and a database
  that found its way there would be published — the same mechanism that put 19 unreferenced
  renders in the public webroot.
- **`.gitignore` it before the first write**, not after. `run/` and `backend/output/` are
  already there; add `backend/project/`. A workspace committed by accident is in the history
  permanently, and `.claude/HANDOVER.md` §9 records that a 296-file reference tree was
  committed by accident once already.
- **The store must never reference `training/corpus.jsonl` content.** It may reference the
  *path* — it is a file in the repo like any other — but a note quoting examples from it is
  the trade secret in a second, less-guarded location. §7.5 of `backend/coder/docs/coder-spec.md`
  has the full reasoning.

### 7.3 The two-hop escalation

Covered in §4.1 as a design constraint; here is the failure mode. Someone with the Project
token writes a work item saying "run this command." Coder, reading Project for context,
treats it as an instruction. Nobody reviewed the seam because the network step is in this
spec and the execution step is in the other one.

**Mitigations:** Coder reads Project, Project never invokes Coder; a human starts every Coder
session; Coder treats Project content as untrusted data, the way it would treat a fetched web
page. If Coder is ever made to poll Project for work, **this spec's security argument is void
and both documents must be revisited** — that change would silently promote Project's token
into an RCE gate.

### 7.4 The store is lost

It is gitignored, so `git` does not protect it. There is **no git remote**, so nothing leaves
this box. `run/` is explicitly documented as a directory someone will eventually clear out —
which is precisely why the store does not live there (§2.5) — but a database in
`backend/project/` has no backup either, only better odds.

This project has already lost exactly this way: **the contract signing key's private half
lived in `/tmp` and did not survive the 2026-08-17 reboot** (`.claude/HANDOVER.md` §2d, §5
item 0). The note there is blunt: *"Not `/tmp` this time. That is what lost it."*

**A dated `sqlite3 .backup` is one line and must be in the spec, not a follow-up.** A
workspace people trust and then lose is worse than one they never adopted, because they
stopped writing things down elsewhere.

### 7.5 It grows into a GPU surface by increments

§2.3's temptation, arriving as three reasonable-looking requests: semantic search, then
auto-summarising a session, then suggesting the next item. Each is small. Together they make
Project a governor tenant, at which point it can be evicted, it can queue behind a fine-tune,
and it needs a `project)` arm in `evict()` or it eats the `*)` default that pkills
`llama-server|sd-cli`.

**The assertion in §6.1 is the defence** — it fails the moment Project asks for the card,
which turns an architectural drift into a red test. That is worth more than a paragraph in a
document nobody re-reads.

### 7.6 The API grows a session

`.claude/HANDOVER.md` §5 is explicit that the iPhone app means **no session-shaped
assumptions**. The way this breaks is small and plausible: a "current project" stored
server-side because it made the web page simpler. Then the phone and the laptop fight over
it, the bug is intermittent, and it is expensive to unpick after an app binary has shipped
against it.

**The client names the project in every request. Always.** If the web page wants to remember
which project was open, that is `localStorage` — the same decision `.claude/HANDOVER.md` §2f
records for chat conversations, which *"live in the browser. No history endpoint, no
conversation id on the server."*

### 7.7 Concurrent writes silently lose data

§3.4. Without WAL and version checks, two clients editing the same item is last-write-wins
with no error and no trace. A workspace that loses a note once loses the user's trust
permanently — and the loss is invisible, which is the worst property a bug can have.

### 7.8 It ships with an inline-JS escaping bug

If `site/project.html` is generated by `tools/build/build_pages.py`, note the trap that has now
bitten twice: `TUNER_JS` and `CHAT_JS` are **normal triple-quoted Python strings, not raw**,
so a `\n` written in the source becomes a real newline in the emitted JavaScript — inside a
string literal, leaving it unterminated and killing the entire page's script. It reached
production once on `tuner.html` and the suite passed 22/22 while the page was dead, because
every assertion checked markup, CSS and endpoints and none cared whether the script ran.

**Write `\\n`, not `\n`.** The `no page throws a script error` assertion now loads every page
and fails on any `pageerror`; make sure a new page is added to its list.

---

## 8. Recommendation, in one paragraph

Build Project as a **CPU-only surface that never takes the GPU lock** — the RavenCalc
precedent, adopted deliberately and asserted in the test suite (§6.1) so it cannot drift.
Store in **SQLite via the stdlib `sqlite3` module** (verified present: 3.46.1 under Python
3.13.5, no new packages, so the system-interpreter rule holds) at **`backend/project/store.db`**,
gitignored, WAL mode, with a dated `.backup`. Expose it at **`/api/project/*`, declared before
the `StaticFiles` mount, with no `ops/Caddyfile` change** and **no extensionless route**. Gate
it with **`SYMONEURAL_PROJECT_ENABLED` + `SYMONEURAL_PROJECT_TOKEN`**, copying `backend/apps/asicminer/`
exactly — both required, `hmac.compare_digest`, 503 off / 401 bad token — with a
`secrets.token_urlsafe(32)` token, since rate limiting is off and the token is the only gate.
Design every route for a **non-browser client**: header auth, explicit ids in the path, no
credentials in paths (copy the tuner's test), a versioned JSON contract. Add the rack unit as
`label="SyMoNeuRaL Project"`, `bus="cpu"`, `slot="1U"`, `spec="SQLite · FTS5 · no weights"`,
`detail="cpu only, never queues"`, state computed and **`offline` until the store answers** —
and re-measure Live stack at 1301×740 and 1855×745 in the same change, because a tenth unit
lands on a section already 76px over budget.

**The two things that will actually go wrong** are the second-state-document collision (§7.1)
and the two-hop escalation with Coder (§4.1, §7.3). Both are decided before the first line of
code, not after.

---

## 9. Open questions for Garrett

1. **Does Project hold the queue, or does HANDOVER?** §7.1. This is the decision that has to
   be made first, and it is not an agent's to make — it changes what `.claude/CLAUDE.md`
   says.
2. **Does Coder read Project?** §4.1. If yes, both specs' security arguments are coupled and
   the "Coder never polls Project" rule becomes load-bearing.
3. **What does "like the claude cowork" mean concretely to him?** This spec reads it as
   projects, work items, session history and search. If he means shared/multi-user, that is a
   materially different surface — multi-user means real accounts, not one shared token, and
   §4 would need rewriting rather than adjusting.
4. **iPhone app first, or web page first?** §3.3 designs for both, but the order decides
   what gets built. The API is the same either way, which is the point of designing it
   session-free.
5. **What should the `train` unit be called?** `SyMoNeuRaL Quantized Low-Rank Adaptation
   Tool` is wrong and wrapping to five lines (§5.1). It is a product name, so it is his call
   — and it is a one-line fix worth taking while the rack is being touched anyway.
