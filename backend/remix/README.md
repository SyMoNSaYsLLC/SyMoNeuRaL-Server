# symoneural_dj

Playlist orchestrator on `:8090`. The iOS app sends a prompt; symoneural_dj asks
the local **symon** engine (`:9001`) for a track list, resolves each track
against the **Spotify Web API**, and creates the playlist on the chosen
user's account. The phone talks only to symoneural_dj — the engine's port and
`VLLM_API_KEY` never leave loopback.

```
iOS app ──bearer DJ_TOKEN──> symoneural_dj :8090 ──VLLM_API_KEY──> symon :9001 (loopback)
                                   └──────OAuth tokens──────> api.spotify.com
```

## Setup

1. Dependencies (already satisfied by `~/.venvs/vllm` on this box):

   ```bash
   ~/.venvs/vllm/bin/pip install -r requirements.txt
   ```

2. Create a Spotify app at <https://developer.spotify.com/dashboard>.
   **Add the redirect URI exactly as** `http://127.0.0.1:8090/auth/callback`
   under the app's settings. It must be `127.0.0.1`, **not** `localhost` —
   Spotify rejects `localhost` redirect URIs for new apps, and the string must
   match `SPOTIFY_REDIRECT_URI` byte for byte.

3. Configure:

   ```bash
   cp .env.example .env    # fill SPOTIFY_CLIENT_ID / SECRET, set a DJ_TOKEN
   ```

   **Set `VLLM_API_KEY` in `.env`** (copy it from `~/.bashrc:181`). Do not
   rely on the bashrc export: it sits below an interactive-shell guard, so
   daemons and scripts never inherit it and every engine call 401s. With
   `DJ_TOKEN` unset, symoneural_dj answers loopback peers only and the phone will
   get 401s.

4. Run — normally you don't: `symon-dj.service` is part of `symon.target`
   and comes up with the stack (`systemctl --user start symon.target`).
   For one-off/dev runs:

   ```bash
   ./run.sh             # foreground
   ./run.sh --daemon    # background, .run/dj.{pid,log}
   ```

## The flow, in curl

```bash
curl http://127.0.0.1:8090/health
# {}
```

Authorize a Spotify account (opens a browser; repeat once per account —
the token store is multi-user):

```bash
xdg-open http://127.0.0.1:8090/auth/login
# after consenting: {"authorized": "<user-id>", "display_name": "...", ...}
```

See who is authorized and pick the `user` for playlist jobs:

```bash
curl -H "Authorization: Bearer $DJ_TOKEN" http://127.0.0.1:8090/users
# {"users": [{"user": "spotify-alice", "display_name": "Alice", "expires_at": ...}]}
```

Start a job (returns immediately; generation takes 40–90 s):

```bash
curl -X POST http://127.0.0.1:8090/playlist \
  -H "Authorization: Bearer $DJ_TOKEN" -H "Content-Type: application/json" \
  -d '{"prompt": "rainy-day indie for a long train ride",
       "user": "spotify-alice", "track_count": 30, "public": false}'
# {"job_id": "a1b2c3d4e5f6"}
```

Poll it:

```bash
curl -H "Authorization: Bearer $DJ_TOKEN" http://127.0.0.1:8090/playlist/a1b2c3d4e5f6
# {"state": "resolving", "progress": "resolved 12/30", ...}
# ...eventually:
# {"state": "done", "playlist_id": "...", "playlist_url": "https://open.spotify.com/playlist/...",
#  "tracks_added": 27, "tracks_dropped": [{"artist": "...", "track": "...", "reason": "artist mismatch"}]}
```

Job body fields: `prompt` (required), `user` (required — from `/users`),
`track_count` (5–100, default 30), `name` (optional; symon suggests one
otherwise), `public` (default false), `use_taste_profile` (default true —
folds the user's top artists/tracks into the prompt), `blend_with` (optional
list of other authorized user ids — their taste profiles are blended in with
per-person sections and a balance instruction; the playlist is still created
on `user`'s account. A blend member whose token has died is skipped and noted
in the result's `blend_skipped`, never fatal; unknown ids 404 up front).

Every playlist gets **procedural cover art** (640×640 JPEG, seeded from the
playlist name + prompt, generated with Pillow — no external assets). Cover
upload needs the `ugc-image-upload` scope, added 2026-08: **accounts
authorized before then must visit `/auth/login` once more to re-grant**,
or uploads 403 — the job still succeeds and reports
`"cover": "skipped: <why>"` instead of `"ok"`.

## Tests

```bash
~/.venvs/vllm/bin/python -m pytest tests -q
```

CPU-only, no network, no sockets: both outbound clients ride
`httpx.MockTransport`, the app is exercised in-process. Under a second.

## Limits

Written plainly, in the house style:

- **One generation at a time.** The engine serializes requests; concurrent
  jobs queue behind each other at the `generating` step. A job takes 40–90 s
  mostly in that step.
- **Finished jobs survive restarts; in-flight jobs do not.** Every job that
  reaches done/failed is journaled to `.run/jobs.jsonl`, so polling a
  finished job keeps answering after a restart and `GET /jobs` lists the
  last 20. A job that was mid-generation when the process died never reached
  a terminal state and is simply gone — resubmit it.
- **Accounts, not a shared token (fixed 2026-08-09).** Users sign up / log in
  (`/auth/*`, session cookie) or use a per-user API token; each account may
  only act on the Spotify connections **it** made (`/spotify/connect`), and
  each playlist debits `DJ_PLAYLIST_COST` SyMoN tokens (owner free). `DJ_TOKEN`
  is now a break-glass **owner** key, not a shared user token. Powered by the
  shared `symoneural_accounts` module. (Deploy/DB scaling notes: see
  `docs/PRODUCTION-READINESS.md`.)
- **Tracks can be dropped.** A suggestion only makes the playlist if
  Spotify's search returns it *and* the credited artist fuzzy-matches. The
  fuzzy gate also means tribute/karaoke acts whose name *contains* the real
  artist's name can slip through.
- **Model output is untrusted and sometimes unusable.** One corrective retry
  is built in; if both attempts fail to parse, the job fails and the raw
  output is returned on the job for debugging.
- **No streaming progress.** Poll `GET /playlist/{job_id}`; `progress` is a
  human string like `resolved 12/30`.
- **Taste profile is best-effort.** If the top-artists/tracks calls fail, the
  job proceeds without them rather than failing.

<!-- generated: do not edit below -->

## Operations — 1

|  | path | what it does |
|---|---|---|
| POST | `/api/remix` | Build a sequenced tracklist. |

## Documents

- [`DEPLOY.md`](docs/DEPLOY.md)
- [`LICENSING.md`](docs/LICENSING.md)
- [`PRODUCTION-READINESS.md`](docs/PRODUCTION-READINESS.md)
- [`symoneural-remix-scope.md`](docs/symoneural-remix-scope.md)

<!-- end generated -->
