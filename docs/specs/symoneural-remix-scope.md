# SyMoNeuRaL Remix — scope, and the two things called Remix

**Scope captured 2026-08-22.** Docs and scope only. **No rename, no secret rotated, no credential
name changed in running code, no archive import, no deploy.**

## 1. What it is

> **SyMoNeuRaL Remix is the playlist / track-sequencing surface for this server.**

A playlist and sequencing assistant that generates **ordered** sets of songs, not a pile of
recommendations — tempo, key and flow matter where the prompt and model support it. **It has no
model weights of its own**, uses the Chat/model runtime underneath, and therefore **queues behind
GPU work.**

## 2. Two distinct things share the name, and conflating them is the trap

| | What it is | Classification |
|---|---|---|
| **the live surface** | `/api/remix` in `backend/api.py:2646`, a **client of the Chat surface** | **PROD direction** — preserve current candidate-generation behaviour |
| **the older Spotify DJ app** | `backend/apps/remix/symoneural_dj/`, its own sub-project with `pyproject.toml` and 28 tests | **AUDIT** — stale internal naming and Spotify-service code |

**They fail independently, and the rack row belongs to the first one.** So:

- **The rack row being `ready` does not prove `symoneural_dj` imports or serves.**
- **Do not mark Remix offline merely because `symoneural_dj` is stale or broken.** The row is
  honest if `/api/remix` works as a chat-surface client.
- **Do not mark the old Spotify DJ service production merely because the rack row is ready.**

Rack identity: `remix`, `bus="gpu"` (because it uses Chat underneath), `/remix.html`, spec *client
of the chat surface*, detail *no weights of its own*.

## 3. The public/private split is already implemented and documented

`api.py:2646`'s own docstring states both halves, and it is the model to preserve verbatim in
spirit:

> *"Remix has no weights of its own — it asks the chat surface, which is what 'one server
> underneath' means in practice, and why it queues behind chat and image."*
>
> *"Generation only. Resolving tracks against Spotify and writing a playlist needs OAuth against a
> real account, and a stranger's prompt should not reach one; that half runs on the box behind
> admin auth."*

**Public Remix may:** generate ordered candidate tracklists · return artist/title/why JSON ·
explain that candidates are locally generated · show copy/export text if scoped.

**Public Remix must not:** write playlists into Spotify without account or admin auth · expose
stored OAuth tokens · expose `DJ_TOKEN` or owner-token behaviour · act as an unauthenticated
account mutator · **claim it created a playlist when it only generated candidates.**

**Admin/account-auth Remix may later:** resolve tracks against Spotify · write a playlist · manage
the OAuth connection · save history · export · sync metadata · charge credits if product policy
says so. **Each is separate scoped work.**

## 4. Current API behaviour — measured

`POST /api/remix`, throttled against the **`remix`** bucket (40/600 suggested):

- **`prompt`** — clamped to `MAX_PROMPT_CHARS`
- **`count`** — `12` by default, `ge=1, le=500`
- returns **`tracks`** (`artist`, `title`, `why`), **`seconds`**, and a **`note`**

The model is asked for a JSON array; `why` should be short; the sequence should flow.

**Do not claim stronger behaviour than this:** no Spotify write from the public page · no track-ID
resolution from it · no BPM or key verification · no audio analysis · no DJ mixing or audio
generation · no account connection. **None of those is implemented.**

## 5. DJ → Remix naming drift — recorded, not fixed

The product was renamed; **the internals were not.** Measured 2026-08-22:

- `backend/apps/remix/symoneural_dj/` still exists
- `symoneural_dj/config.py:42-44` reads `VLLM_API_KEY`, `DJ_TOKEN`, `DJ_TOKEN_PATH`
- `symoneural_dj/app.py:78` treats `DJ_TOKEN` as the break-glass owner token
- `run.sh:7-8` documents `DJ_TOKEN`, `DJ_HOST`, `DJ_PORT`
- `tests/conftest.py:16` and `tests/test_routes.py:12` assert on `DJ_TOKEN`
- **`backend/apps/accounts/module.py:18` documents `DJ_TOKEN` as the owner bearer** — so the name
  has reached a **second app**
- `scripts/lib/archive-guard.sh:74` lists all four DJ keys in `_AG_SECRET_KEYS`, so the leak
  guard's regex is part of the contract too

**This is `AUDIT.md` Q12 and it is not a task.** The open decision is whether `DJ_TOKEN` survives
as a backward-compatible alias, is replaced by `SYMONEURAL_REMIX_TOKEN`, or is aliased with a
stated removal date. **A package rename is an import-path change across the app and is the one
piece that cannot be done incrementally** — it wants its own task rather than riding along on a
docs pass.

**Rules until scoped:** do not bulk-replace `DJ_TOKEN` · do not rename inside a secrets task · do
not change secrets while doing page or spec cleanup.

## 6. The `DJ_TOKEN_PATH` correction — it is not a token file

**`DJ_TOKEN_PATH` is the Spotify OAuth token cache path**, defaulting to
`.run/spotify_tokens.json` (`symoneural_dj/config.py:44`). The name reads like "the file the DJ
token lives in" and it is not that.

So: **do not write `DJ_TOKEN` into `DJ_TOKEN_PATH`**, and do not treat `DJ_TOKEN` as file-backed
unless the code is explicitly changed and tested. Corrupting that path costs the OAuth session,
not a token comparison.

Further credential rules, carried from the paused #75:

- **Do not rotate the Spotify client secret from a repo script** — that is the Spotify dashboard,
  one of the five `owner: garrett` categories.
- **Do not report old-token rejection as proven** unless a running acceptor actually rejected it.
  In particular, **do not claim `VLLM_API_KEY` old-value rejection when no local server exists to
  reject it.**
- Real `.env` files stay **untracked and mode 600**; `.env.example` stays tracked. Both are true
  today: `.gitignore` carries `.env`, `*.env`, `!*.env.example`, and the two live files are mode
  600 and untracked.
- The leak guard must cover `DJ_TOKEN`, any future `REMIX_TOKEN`/`SYMONEURAL_REMIX_TOKEN`,
  `VLLM_API_KEY` and the Spotify secrets. The first, third and fourth are already in
  `_AG_SECRET_KEYS`; **a new name must be added there in the same change that introduces it.**

## 7. Runtime direction

Remix has no weights and uses Chat's runtime to produce structured JSON, so it is GPU-contended
and shares Chat's queue and rate-limit story. A future specialised music/playlist model or adapter
is **AUDIT/future** — **do not claim one exists unless the registry proves it**, and do not train
or attach a Remix adapter without scoped authorization.

## 8. Page copy direction

Say that Remix builds ordered playlist candidates through the local Chat/model stack, has no
weights of its own, and that **public Remix generates candidates only** — Spotify resolution and
playlist writing need authenticated/admin paths.

**Visible product copy may be corrected to Remix** under an authorized page cleanup; **internal env
and module names stay** until the scoped naming task. Do not call it *SyMoNeuRaL DJ*, *DJ app*, *a
standalone music model*, *a Spotify writer* or *an authenticated account product* — except when the
context is explicitly the old internal code or an audit note.

## 9. Not authorized

No rename of any module, token or route · no secret rotated or read · no `DJ_TOKEN_PATH` write · no
Spotify write path · no adapter trained · no archive import · no folder migration · no deploy.
