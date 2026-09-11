# symoneural_dj — what's ours vs what we call

*One page, written to be read in ten minutes. Prepared 2026-08-09 by the
engineering side. **Not legal advice** — it is a factual map of the code plus
the questions a lawyer should answer.*

---

## In one sentence

symoneural_dj is **our own code end to end**; it *calls* two things we don't
own — Spotify's Web API and our local `symon` model — and it **redistributes
nothing** belonging to anyone else.

## Ours outright

Written for this project, no third-party code copied in:

| Piece | What it is |
|---|---|
| Prompt → playlist pipeline | Hostile-JSON-hardened parsing, 2× over-ask, one corrective retry |
| Track matching | Field-filtered Spotify search, free-text fallback, fuzzy artist gate |
| Job engine | Async, guaranteed-terminal state machine, journalled to disk |
| Accounts + billing integration | Per-user isolation, wallet, flat per-playlist charge |
| Cover art | Procedurally generated from shapes and colours (Pillow). No bundled image or font assets. |
| Web UI | Single file, no build step, no third-party framework |
| The SyMoNeuRaL brand and skin | Ours |

Licensed proprietary — see `LICENSE`.

## Ours, shared across the family

`symoneural_accounts` (accounts, sessions, wallet/billing) and `symon_capture`
(training-data pump) are our packages, used by several apps in this repo. Same
proprietary licence, same owner.

## What we call, but do not own

### 1. Spotify Web API — the commercial gate

We hold **no** Spotify code. The app is an HTTP client: each customer connects
**their own** Spotify account via OAuth, and we act only on that account, only
with the scopes they grant.

What we never do: store, cache, transcode or redistribute audio; redistribute
album art; act on an account without its owner's live OAuth grant.

The relationship is governed by Spotify's **Developer Terms** and **Developer
Policy** — agreements between Spotify and the *operator* of this software. No
licence we write can grant them. **This is the item that gates a paid launch.**
See the open business item below.

### 2. The symon model

The app calls our local engine over loopback HTTP. Weight provenance — base
model, licence, what may and may not be claimed — is
`../models/PROVENANCE.md`, deliberately kept in one place rather than restated
here where it would drift.

### 3. Open-source libraries

Twenty-two packages, enumerated with versions and licences in
`THIRD-PARTY-LICENSES.md`. All permissive (MIT / BSD / PSF) except `certifi`
(MPL-2.0, used unmodified, file-level copyleft that does not reach our source).
**No GPL. No AGPL. Nothing obliges us to publish this project's source.**

### 4. User content

Prompts customers type and playlists they generate. Ours to process on their
instruction; theirs in substance. Terms/Privacy pages do not exist yet
(P2-14) — a paying customer will eventually ask, and some jurisdictions
require deletion and export (P2-13).

---

## 🔴 OPEN BUSINESS ITEM — Spotify commercial terms

**Status: NOT CLEARED. This gates a paid launch regardless of code readiness.**

Engineering cannot close this. It is a business/legal decision, and everything
below is a flag rather than advice.

### Why it matters

1. **Development-mode cap.** A new Spotify app is capped at roughly **25
   users** until *extended quota* is granted. That request triggers a
   commercial review. Customer 26 simply cannot connect.
2. **Charging for access to Spotify content** is restricted by the Developer
   Policy. Our product charges for *our* generation work, not for Spotify
   content — a distinction that reads well and has **not been confirmed with
   Spotify**. It needs to be, in writing, before money changes hands.
3. **Branding and attribution** rules govern how Spotify is named and shown.
   The current UI has had no compliance pass.
4. **Per-customer OAuth** is required — we may act only on an account whose
   owner granted us access. Step 2 moved us to per-user OAuth, so this one is
   believed satisfied; it should be confirmed as part of the same review.

### Checklist — tick before charging anyone

- [ ] **Request extended quota** in the Spotify developer dashboard; record the
      submission date and the reviewer's response verbatim.
- [ ] **Get written confirmation** that a paid product which *creates playlists
      in the customer's own account* is permitted, and that our charge is
      understood as being for generation, not for Spotify content.
- [ ] **Branding/attribution pass** on the UI against the current Developer
      Policy (logo use, "powered by", required attribution on generated
      playlists).
- [ ] **Confirm per-customer OAuth** satisfies the "act only on the connected
      account" requirement, including the `ugc-image-upload` scope used for
      cover art (P1-10: it needs to be requested at onboarding or covers 403).
- [ ] **Re-read the Developer Terms as of the launch date** — they change, and
      the audit above was written 2026-08-09.
- [ ] **Have a lawyer review** this page plus the Developer Terms together.
- [ ] **Record the outcome here with a date**, so the next person does not have
      to re-derive it.

### If the answer is no

The pipeline is not Spotify-specific in principle. The prompt → tracklist half
is entirely ours; only the resolve-and-create half is Spotify. A different
backend (a self-hosted library, or another service with friendlier commercial
terms) would preserve most of the value. Worth knowing before the review, so
"no" is a pivot rather than a dead end.

---

## Quick answers

**Can we sell this today?** Not until the Spotify item above is cleared. No code
change alters that.

**Does any dependency force us to open-source?** No. Nothing is GPL or AGPL.

**Do we owe attribution?** To the OSS packages, yes — ship their licence texts
with any distributed artifact (keeping the `.dist-info` directories satisfies
it). Server-side-only deployment triggers none of them.

**Do we redistribute music or album art?** No. Neither is ever stored or served
by this code.

**Who owns a generated playlist?** It lives in the customer's own Spotify
account, created under their own OAuth grant. We hold no copy.
