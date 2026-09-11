# Deploying symoneural_dj (step 3 of the sellable pass)

Three artifacts, in the order you use them:

| Artifact | Purpose |
|---|---|
| `.env.production.example` | every parameter the app reads, documented |
| `deploy/setup.sh` | fresh-machine check + setup, idempotent |
| `tools/seed_load_test.py` | load-test the money loop with fake data only |

## Fresh machine

```bash
git clone <repo> && cd symoneural_dj
./deploy/setup.sh --check                      # read-only: what is missing
./deploy/setup.sh --owner you@example.com      # set up + seed the owner
$EDITOR .env                                   # Spotify creds, VLLM_API_KEY
./deploy/setup.sh --check                      # confirm clean
systemctl --user start symoneural-dj
```

`setup.sh` refuses to finish while a dangerous setting is present. The four it
fails on are the ones that are quiet and expensive:

- `DJ_SECURE_COOKIES` not `1` — session cookies without the Secure flag ride
  any accidental plaintext request.
- `DJ_HOST=0.0.0.0` — publishes bearer tokens and OAuth codes to the LAN. Bind
  loopback and terminate TLS in front.
- `SPOTIFY_REDIRECT_URI` on `http://` — OAuth codes must ride TLS.
- Empty `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` / `VLLM_API_KEY`.

It never writes a secret for you and never starts anything.

## Load-testing the money loop

The purchase → generate → charge path is the part you cannot afford to discover
bugs in with a real customer, and it is also the part that normally needs
Spotify and Stripe to exercise. It doesn't here:

```bash
python tools/seed_load_test.py                      # 5 users, 4 playlists each
python tools/seed_load_test.py --users 50 --playlists 20
python tools/seed_load_test.py --report             # just the ledger
python tools/seed_load_test.py --reset              # delete the fake db
```

It creates real accounts in a **separate** database, credits wallets (the
"purchase"), then runs holds → settles for successful jobs and holds → releases
for failed ones, and appends journal rows shaped like the app's own so `/jobs`
history looks populated. A sample run:

```
  5 account(s), each topped up 10 token(s) (= $12.00 retail)
  ran 20 playlist attempt(s)
    charged  16 token(s)
    refunded 4 token(s) (failed jobs are never billed)
  user wallets total : 34 tokens
  savings_usd        : 19.2
```

50 purchased − 16 charged = 34 left, and 16 × $1.20 = $19.20 revenue. That the
arithmetic closes is the thing being tested.

**No Spotify call, no Stripe call, no email.** Nothing in this script can reach
a third party.

### Why it is so hard to point at the real database

Two independent guards, and the override only relaxes one:

- a non-default db path needs `--i-know-this-is-not-fake`;
- **any real (non-`@loadtest.invalid`) account present is refused outright**,
  override or not.

The second is not bypassable on purpose. Once fake top-ups and fake settlements
are interleaved with real ones in the same `txns` table, there is no honest way
to separate them again — "revenue" quietly becomes fiction. A flag is not worth
that, so the answer is always "use a different file". Fake accounts live at
`@loadtest.invalid`, a reserved TLD that can never receive mail, so a fake user
cannot be emailed by accident once a mailer exists.

## What deployment does NOT solve

From `PRODUCTION-READINESS.md`, still open and not closed by this step:

- **P0-3 Spotify commercial terms** — the gate. See `docs/LICENSING.md`.
- **P1-5 rate limiting** — not implemented. The engine serialises at ~20 tok/s,
  so one greedy account starves the rest. Billing is a partial quota, not a
  substitute.
- **P1-6 persistence at scale** — SQLite + flat files; fine for one box.
- **P1-7 secrets at rest** — the Spotify token store is 0600 but unencrypted.
- **P1-8 TLS** — must be terminated in front; this app never speaks it.
