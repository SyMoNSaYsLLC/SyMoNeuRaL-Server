# symoneural_dj — Production-Readiness Audit (2026-08-09)

Scope: **symoneural_dj only.** The question this answers is not "does it work on
Garrett's LAN" (it does) but "can a **paying stranger** sign up and use it
safely, and can we charge them, without legal or security surprises." Ranked
honest gaps follow. No code was changed to produce this.

## What is actually done (works today)

- End-to-end pipeline: prompt → symon (hostile-JSON-hardened, 2× over-ask, one
  corrective retry) → Spotify resolve (field-filter + free-text fallback, fuzzy
  artist gate) → playlist create (`/v1/me/playlists`) → track add (`/items`,
  chunked 100) → procedural cover art. Adapts to the Feb-2026 Spotify changes.
- Multi-user *Spotify token* store (0600, atomic, per-user refresh) and blend.
- Jobs: async, guaranteed-terminal state machine; terminal states journaled to
  `.run/jobs.jsonl` (survive restart); `/jobs` history; phone-friendly UI in the
  family skin; gateway-prefix-safe.
- 82 CPU-only tests; systemd unit; runs under the family gateway.

## Gaps to sell to a stranger — ranked

### P0 — cannot sell without these
1. **No accounts, and a cross-tenant authz hole.** There is one shared
   `DJ_TOKEN`; *any* holder can create playlists as *any* stored Spotify user
   (README says so plainly). For multiple paying customers this is a data
   breach by construction. → needs real per-user login + per-user isolation
   (the billing/accounts merge, step 2).
2. **No billing.** No wallet, no charge, no purchase. Nothing to sell against.
   → step 2 wires the v3 billing engine; step 3 the load-test loop.
3. **Spotify Developer Terms are the existential gate — verify before selling.**
   This is business/legal, not code, and I am not a lawyer — flagging, not
   advising:
   - A new Spotify app is in **development mode, hard-capped at ~25 users**
     until you request **extended quota**, which triggers a commercial review.
   - Spotify's Developer Policy restricts **charging for access to Spotify
     content** and imposes **branding/attribution** rules. A "pay us to make
     Spotify playlists" product may need explicit Spotify commercial approval.
   - Each customer must connect **their own** Spotify account (their OAuth), and
     we may act **only** on that account. The current single-app shared-store
     model must become genuinely per-customer OAuth.
   **Action: confirm the commercial terms + request quota extension before any
   paid launch.** Everything below is moot if this gate isn't cleared.
4. **No LICENSE / third-party license inventory.** → step 4.

### P1 — needed for real, safe use
5. **No rate limiting / quota / abuse control.** The engine serializes (~20
   tok/s, 40–90 s/job); one abusive or paying-but-greedy stranger trivially
   DoSes everyone. Needs per-user concurrency + rate caps (and billing itself
   becomes a natural quota).
6. **Persistence won't scale past one box.** Jobs live in memory (only the
   journal survives); the Spotify token store and (soon) accounts are flat
   files. No real DB, no locking story for concurrent writers. Fine for one
   user; wrong for many.
7. **Secrets at rest.** `.env` holds the Spotify client secret; the token store
   is 0600 but unencrypted. A stranger's refresh tokens sitting in plaintext on
   disk is a real liability at multi-tenant scale.
8. **Transport is plaintext HTTP.** Bearer tokens and OAuth codes must ride
   TLS. Must sit behind the gateway/Caddy/Cloudflare with HTTPS enforced;
   document it as a hard requirement, not an option.
9. **Thin observability.** Only `/health` + the journal. No metrics, no
   per-user audit log, no error aggregation — you won't know why a paying
   customer's job failed.
10. **Cover art needs a per-user scope re-consent** (`ugc-image-upload`).
    Onboarding must request it up front, or covers silently 403 per user.

### P2 — polish before it feels finished
11. No streaming progress (poll only). 12. Fuzzy match lets tribute/karaoke
    acts through. 13. No account deletion / data export (a paying stranger will
    eventually ask; some jurisdictions require it). 14. No Terms/Privacy pages.

## Honest completeness call

As a **personal LAN tool: done.** As a **product for paying strangers: ~35%** —
the engine and Spotify mechanics are solid, but the entire commercial surface
(identity, isolation, billing, abuse control, legal, Spotify commercial terms)
is absent. Steps 2–4 build the code parts; **P0-3 (Spotify commercial terms) is
a decision only you can clear** and gates a real launch.

## What steps 2–4 will and won't cover

- **Step 2** closes P0-1 and P0-2 (accounts + per-user wallet + 1-token charge,
  owner free), tested with fake users + fake Spotify.
- **Step 3** gives the deploy recipe + fake-data load-test loop (P1-6/8 partly).
- **Step 4** closes P0-4 (LICENSE + third-party inventory + ours-vs-theirs memo).
- **Not covered by code:** P0-3 (Spotify commercial approval/quota), full DB
  migration (P1-6), secret encryption (P1-7), TLS termination (P1-8) beyond
  documentation. These are flagged for you.
