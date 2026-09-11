# Accounts and user setup — spec

**Status: implemented in the repository, off by default.** The core, routes and account
page exist. The core has 48 passing tests plus focused route/security contracts. Whether
the public host has the required switches is a live reading and must be verified; this
document does not claim deployment.

Written 2026-08-17. Security decision updated 2026-08-26.

---

## 0. The short version

- `backend/apps/accounts/` is a self-contained signup/login/session module on the
  **standard library only** — no bcrypt, no argon2, no passlib, no python-jose, no
  sqlalchemy, no authlib. `hashlib.scrypt`, `secrets`, `hmac`, `sqlite3`.
- It is **off by default** and needs two switches, `SYMONEURAL_ACCOUNTS_ENABLED=1` and
  `SYMONEURAL_SESSION_SECRET`, the same shape as `backend/apps/asicminer/`.
- It **fails closed at every entry point**. No secret means `AccountsUnavailable`, raised —
  never a `None` that a caller can mistake for "wrong password".
- It carries **no price, no plan, no tier and no amount**, anywhere. An account may hold an
  opaque `quote_id`; a test asserts the schema has no price-shaped column.
- Storage is `run/accounts/accounts.db`. It cannot touch `run/gpu.lock.d`.
- The routes remain closed unless both configuration switches are present. §3 records the
  boundary requirements and the host-side checks needed before enabling them.

---

## 1. What was built, and what each decision cost

### 1.1 Password hashing — scrypt, and the parameters are measured

    SCRYPT_N = 131072, r = 8, p = 1    -> 128 MiB, 248 ms   [MEASURED candidate]

Measured on the serving machine: Intel i9-10900KF @ 3.70 GHz, `hashlib.scrypt`, best of five.
The full sweep, all **measured**, none projected:

| N | r | p | memory | time |
|---|---|---|---|---|
| 2^14 | 8 | 1 | 16.0 MiB | 26.1 ms |
| 2^15 | 8 | 1 | 32.0 MiB | 60.7 ms |
| 2^16 | 8 | 1 | 64.0 MiB | 122.8 ms |
| **2^17** | **8** | **1** | **128.0 MiB** | **248.3 ms** |
| 2^15 | 8 | 2 | 64.0 MiB | 113.7 ms |
| 2^16 | 8 | 2 | 128.0 MiB | 231.0 ms |
| 2^14 | 8 | 4 | 64.0 MiB | 103.4 ms |

**Why not RFC 7914's own example.** RFC 7914 §2 gives N=16384, r=8, p=1 for "interactive
logins". That recommendation is from 2016 and costs 26 ms / 16 MiB on this hardware — an
order of magnitude cheaper than it was meant to be, because the hardware moved and the
constant did not.

**Why the OWASP baseline now ships.** Current OWASP guidance starts at N=2^17, r=8, p=1
(128 MiB). Every route sends the hash to a worker thread, so the status WebSocket is not
blocked. A process-wide bounded semaphore permits no more than two hashes concurrently,
bounding scrypt working memory to roughly 256 MiB even if the thread pool has a queue.

**Requirement, not advice:** any call from an async route **must** go through
`asyncio.to_thread`. `create_account_async()`, `verify_async()` and
`change_password_async()` exist for exactly this and are what the routes in §3 call.

**Parameters live inside the hash string:**

    scrypt$n=131072,r=8,p=1$<b64url salt>$<b64url dk>

so raising the cost later is a per-user upgrade on next login (`needs_rehash()` +
re-hash inside `verify()`) rather than a flag day that invalidates every password.

**`maxmem` is not optional and this is the trap.** `hashlib.scrypt` defaults to
`maxmem=0`, which OpenSSL reads as a 32 MiB ceiling — so the bare call raises
`ValueError: [digital envelope routines] memory limit exceeded` at N=2^15 and above.
Verified on this box. Every scrypt call in the module passes `maxmem` explicitly and a test
asserts the bare call still fails, so a future OpenSSL that changes the default tells us.

**Salting and comparison.** A fresh 128-bit `secrets.token_bytes` salt per hash, so two
people who choose the same password store two different strings — asserted, and asserted
down to the salt field rather than the whole string. Comparison is
`hmac.compare_digest` on the derived key. No function that feeds a response ever returns
the hash: `account_public()` builds from an **allowlist** (`PUBLIC_FIELDS`), so a column
added in six months is invisible until somebody adds it there deliberately.

**Password length.** New and changed single-factor passwords require at least 15
characters, matching NIST SP 800-63B-4. Existing shorter passwords are not invalidated;
they continue to verify and can be changed normally.

### 1.2 Sessions — server-side rows, keyed verifier

Chosen: **server-side session rows in sqlite**, token = `symses1.<sid>.<256 random bits>`,
database stores `hmac_sha256(SYMONEURAL_SESSION_SECRET, token)`.

**Why not a stateless signed token.** `revoke_session()` and expiry both have to be real.
A stateless token can only be revoked against a revocation list, which is server-side state
with a worse shape — it grows forever, and losing it brings revoked tokens back to life. If
the state is unavoidable, own it.

**Why the secret still matters when the rows are authoritative.** Two things, both of which
would be absent if the database simply stored the token:

1. Reading the file — a backup, a stray copy, an SQL-injection read in some future route —
   yields verifiers, not usable cookies.
2. **Rotating `SYMONEURAL_SESSION_SECRET` invalidates every session at once.** That is the
   emergency lever you want to exist, and it is one `systemctl restart` away.

Both are asserted in the tests.

**Fail-closed shape, and why it is spelled out.** `.claude/HANDOVER.md` §5 item 1 is the
worst open finding in this repo: a DRM whose fallback is `return True` unconditionally, so
blocking a network call *grants* a licence. The equivalent mistake here is subtler than a
hardcoded secret — it is a function that returns `None` on a missing secret, which to a
route handler is indistinguishable from "bad cookie". So:

- `_secret()` raises `AccountsUnavailable` when `SYMONEURAL_SESSION_SECRET` is absent or under 32
  characters. There is **no generated-per-process default** either: that would look like it
  worked until the first `systemctl restart symoneural-api` silently logged everyone out.
- **Every** public function calls it first. A test enumerates all eight entry points and
  asserts the exception **type**, not merely that the result was falsy.
- `None` from `read_session()` and `verify()` means one thing only: this credential is not
  valid.

Default TTL 12 hours (`SYMONEURAL_SESSION_TTL_S` overrides). Changing a password or disabling an
account revokes every live session — a password change that leaves the attacker's session
alive has done nothing.

### 1.3 Throttling — account-scoped, and why that is not the limiter he removed

**Rate limiting is off across the entire API today, deliberately, at the owner's
instruction** (`backend/api.py` ~line 131: "nothing here is to cap what he can send until he
has decided himself what should pass"). `_rate_for()` reads `SYMONEURAL_RATE_<SURFACE>` and a
surface with no variable set has no bucket at all.

**Nothing in this module re-enables that.** No `SYMONEURAL_RATE_ACCOUNTS`, no global limiter, no
change to `check_rate()`. What is here instead is a per-account failed-attempt lockout, and
the distinction is real rather than a technicality:

| | The limiter he removed | This throttle |
|---|---|---|
| counts | **requests** | **failed logins only** |
| keyed on | client address | the **account**, plus a looser address counter |
| a correct request | is counted and can be refused | is never counted; a success clears the counter |
| what it protects | GPU queue capacity | one specific person's password |
| turning it off means | he can hammer his own hardware | anyone can guess anyone's password at line rate |

A login endpoint with no failed-attempt cost is brute-forceable by definition: an unmetered
attacker at ~8 attempts/second/core against a 15-character minimum is still slow, but the
first person to reuse a breached password loses their account and we will not know.

Shape, all constants at the top of the module:

- **Account scope** — 3 free failures, then `5s · 2^(n−4)` capped at **15 minutes**.
- **Address scope** — 20 free failures (a NAT or an office is one address), same curve and
  cap. This catches spraying one password across many accounts, which the account counter
  cannot see.
- **A locked account refuses even the correct password.** Otherwise the lockout throttles
  nothing.
- **A clean hour forgets the counter**, so someone who mistypes once a month is never
  locked out. The cost is that a patient attacker gets 3 free guesses per hour.
- **A success clears both counters**, so an office behind one NAT cannot lock itself out.
  Accepted consequence: somebody holding one valid account can reset their own address
  counter. The account-scoped backoff on every *other* account is untouched, and that is the
  control that matters.
- **The counters are rows in sqlite, not in memory.** `systemctl restart symoneural-api` is
  a routine step in this project; an in-memory counter would mean the attacker's cost is
  "wait for the next deploy", which is no cost at all.
- The lockout **lifts**, and there is a test for it. A lockout with no exit is a self-DoS
  and a "does it engage" test passes on that bug.
- **`change_password()` shares the account key**, so it is not a second, unmetered oracle
  for the current password. It requires a session already, so the exposure is narrow — but
  narrow is not none: an attacker holding a stolen session would otherwise be able to
  confirm the real password at line rate before changing it. The consequence to know is
  that four wrong guesses there also lock login, which is correct: they were four wrong
  guesses at the same password however they arrived.

**This is a security decision the owner can veto**, and vetoing it is one edit:
`ACCOUNT_FREE_FAILS` and `IP_FREE_FAILS` to a very large number, or delete the two
`_throttle_fail` calls in `verify()`. It is written this way rather than as a global limit
precisely because he asked for the global limits to be gone.

### 1.4 Enumeration cost

`verify()` runs a full scrypt against a precomputed dummy hash when the address is unknown,
so a wrong address and a wrong password take the same wall-clock and the endpoint does not
answer "is this person a customer" for free. `create_account()` **does** reveal that an
address is taken — that is unavoidable for a usable signup form, and it is called out in
the threat model rather than papered over.

---

## 2. What is deliberately NOT built

State these to the owner before anything reaches a page, because two of them are product
facts rather than engineering gaps.

1. **No billing, no payments, no plans, no tiers, no subscription state, no prices.**
   `.claude/CLAUDE.md` is absolute and the site's whole argument rests on it. There is no
   price column, and a test asserts the accounts table contains none of
   `price / amount / plan / tier / cost / usd / cents / subscription / seats / billing`.
   An account may carry an **opaque `quote_id`** referring to a quote handled by a human
   over mail. It carries no figure. Everything price-shaped goes to
   **symonsayadmin@symoneural.com**.

2. **No password reset, because this box cannot send mail.** Verified, not assumed: no
   `/usr/sbin/sendmail`, no postfix/exim/sendmail/opensmtpd/msmtp unit, no `mail`/`mailx`
   client. **The consequence is a product fact: a forgotten password is unrecoverable
   today.** The only recovery path is the operator running `change_password` or
   `set_disabled` by hand on the box. Nothing should ship to a visitor-facing page that
   implies otherwise, and a signup form that does not say so is dishonest by omission.

   If reset is wanted it needs a decision first — an SMTP relay (a third-party dependency
   and a secret to hold) or operator-issued one-time links. Neither is built.

3. **No email verification**, for the same reason. `validate_email()` checks shape and says
   so; it claims nothing about deliverability.

4. **No OAuth, no "sign in with", no SSO, no 2FA/TOTP.** TOTP is the one of these that is
   genuinely cheap on the standard library (`hmac` + `base64` is the whole of RFC 6238) and
   is the obvious next step if accounts ever gate anything valuable. It is not here because
   nothing has been decided about what accounts are *for*.

5. **Cookie handling exists; CSRF tokens and a route-specific CORS policy do not.** Cookies
   are HttpOnly, SameSite=Lax, Secure on HTTPS, and sensitive responses are `no-store`.
   §3.2 records the remaining CSRF trade.

6. **No admin UI.** `set_disabled()`, `revoke_all_sessions()` and `sessions_for()` exist as
   functions. There is no page and no route for them, and an admin route on a public origin
   is a bigger decision than this module.

7. **No account deletion.** Worth flagging as a real gap the moment a real person signs up.

---

## 3. Implemented API routes

All under `/api/accounts/`. Nothing outside `/api`.

| Method | Path | Body | Returns |
|---|---|---|---|
| `GET` | `/api/accounts/status` | — | `{enabled, signup_open}`. No counts, no emails. |
| `POST` | `/api/accounts/signup` | `{email, password, display_name?}` | `201` + public account + session cookie |
| `POST` | `/api/accounts/login` | `{email, password}` | `200` + public account + session cookie |
| `POST` | `/api/accounts/logout` | — | `204`, cookie cleared |
| `GET` | `/api/accounts/me` | — | public account, or `401` |
| `POST` | `/api/accounts/password` | `{old, new}` | `204`; every other session dies |
| `GET` | `/api/accounts/sessions` | — | live sessions for the caller (sid/created/expires) |

Status codes: `503` when `enabled()` is false — the same answer the ASIC surface gives, and
the honest one for a surface that is switched off. `401` for a bad credential or an absent
session. `409` for a duplicate address. `400` for a malformed address or a weak password.
**`429` with `Retry-After` for `Throttled`**, carrying `exc.retry_after` — and note this is
the *only* 429 the API emits, since the global limiter is off.

### 3.1 Wiring requirements — the four that have bitten this repo

1. **Routes must be declared BEFORE the `StaticFiles` mount** in `backend/api.py`. The mount
   at `/` matches everything, so a route added after it is unreachable. `api.py` already
   says this at the mount (`~line 1948`) and the section pages shipped broken for a related
   reason.

2. **`ops/Caddyfile` should need NO change for these routes** —
   `handle /api/* { reverse_proxy 127.0.0.1:8800 }` already delegates the whole `/api`
   subtree, so `/api/accounts/*` is covered the day the routes exist.

   **That is read from the file, not exercised, and the distinction is the point of
   HANDOVER §3.0d.** Caddy is not in the path locally — against `127.0.0.1:8800` the API
   answers directly — so no local test can confirm it. The four section pages shipped
   404ing in production under an equivalent "it obviously matches" assumption while the
   local suite passed 25/25. **Curl `/api/accounts/status` against
   `https://symoneural.com` the first time a route ships**, and treat that, not this
   paragraph, as the verification.

   **This stops being true the moment a non-`/api` path is proposed.** A `/login` or
   `/account` *route* (as opposed to the existing `account.html` *file*) would need adding
   to the `@sections` matcher, and `is_route()` in `scripts/deploy.sh` too. HANDOVER §3.0c
   is emphatic that a local test cannot catch that omission: against `127.0.0.1:8800` the
   API answers directly and the Caddyfile is not exercised at all. The four section pages
   shipped 404ing in production while the local suite passed 25/25.
   **Keep everything under `/api` and the problem does not exist.**

3. **The route passes the client address in.** `backend/api.py` already has
   `client_key(request)` (~line 440), which reads `X-Forwarded-For` because Caddy fronts
   everything. Pass its result as `ip=`; do not reimplement header parsing inside the
   accounts module, or the project has two versions of it to drift apart.

4. **Use the `_async` wrappers.** `await accounts.verify_async(...)`, not
   `accounts.verify(...)`. Hundreds of milliseconds of synchronous CPU in a handler is
   time the status WebSocket is not being served. Static regression tests assert this for
   both account routers.

### 3.2 Cookie requirements

`HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`, `Max-Age` matching the session TTL.
`SameSite=Lax` rather than `Strict` so a link from an email lands logged in; `Strict` is
defensible and is the owner's call. `Secure` is safe in both environments — Caddy gives TLS
in production and `127.0.0.1` counts as a secure context locally.

**CSRF:** `SameSite=Lax` covers cross-site POST for current browsers, and every mutating
route above is a POST with a JSON body, which is not reachable from an HTML form
cross-origin.

**That second half depends on a choice somebody has to keep making.** A cross-origin HTML
form can only send `application/x-www-form-urlencoded`, `multipart/form-data` or
`text/plain`; FastAPI rejects all three when the handler takes a Pydantic body model, and
accepts the first two the moment anyone adds a `Form(...)` parameter. **So: body models
only on these routes, never `Form(...)`.** If the owner wants belt and braces regardless, a
double-submit token is a small addition and should be decided before the routes ship, not
after.

Every account route also sets `Cache-Control: no-store` and `Pragma: no-cache`, including
the bound application router, so authenticated account and session data is not reusable
from a browser cache.

### 3.3 What must never appear in a response or a log

- the hash, the salt, the session verifier, or any password. `account_public()` is the only
  thing that should reach a response body.
- **Never log a password or a token.** The failure that would produce it is an over-eager
  `log.info("login body %r", body)`, and the fix is not to write it in the first place.
  `throttle_state()` exists for the operator view so nobody reaches for the raw table.

---

## 4. Page changes — `site/account.html`

The page is not generated — it is hand-maintained HTML with the site's normal
header/footer and inline account controller. Implemented behavior:

1. **Signed-out state:** one form toggles between sign-in and signup while keeping the
   normal eyebrow/`h1`/`lede` page structure.

2. **Add a signed-in state** rendered from `GET /api/accounts/me`: the address, when the
   account was created, live sessions with a "sign out everywhere" button, and change
   password. No plan, no invoice, no usage meter with a currency on it.

3. **Keep the Billing section exactly as it is.** "Pricing is quoted, not published" and
   the mailto are the correct copy and must survive the redesign. An account panel that
   sits above a section explaining there is no price list is coherent; one that implies a
   subscription is not.

4. **Say the recovery truth in the signup form**, next to the password field, not in a
   footnote: there is no password reset email on this box, so a lost password means mailing
   symonsayadmin@symoneural.com. That is unusual enough that a visitor must be told before
   they choose a password, and it is exactly the kind of thing this site says out loud.

5. **The forms need inline JS**, which means `tools/build_pages.py` conventions apply if it
   is ever generated there. **THE ESCAPING BUG (HANDOVER §2f):** those JS blocks are normal
   triple-quoted Python strings, not raw — write `\\n`, not `\n`, or the emitted JavaScript
   contains a real newline inside a string literal and the whole page's script dies
   silently. It shipped to production once and the suite passed 22/22 while the page was
   dead.

6. **No decorative indicators.** If a "signed in" dot is added it reflects a real
   `/api/accounts/me` response. `.claude/CLAUDE.md`: a fake activity light is the one
   dishonest pixel on a page arguing for measurement.

7. **Add assertions to `tests/frontend.mjs`** — the project rule is one per frontend bug
   fixed, and the ones worth having up front: the signed-out page renders a form and not a
   stack trace when the surface is off (`503` is the normal answer); nothing spills past
   the right edge at 390px; no page throws a script error.

---

## 5. Threat model

Assets, in the order they matter: **the password database** (people reuse passwords, so a
leak here damages them elsewhere, not just us), **live sessions**, **the email list**, and
**availability of the box**.

| Threat | Control | Residual risk |
|---|---|---|
| Online password guessing | account-scoped exponential backoff (§1.3), address counter, 15-char minimum | 3 guesses/hour/account survive the decay window. Accepted; the alternative is locking people out permanently. |
| Password spraying across many accounts | address-scoped counter | `X-Forwarded-For` is client-settable if anything ever reaches `:8800` without going through Caddy, so this is a speed bump. **The account-scoped backoff is the real control** and does not depend on the address being truthful. |
| Offline cracking after a database leak | scrypt, 128 MiB per candidate, per-user 128-bit salt, no reversible storage | A weak or reused password still falls; memory-hard hashing buys time, not immunity. |
| Session theft via XSS | `HttpOnly` cookie; the module never puts a token in a response body | The site has inline JS on several pages; an XSS anywhere on the origin can still act *as* the user even without reading the cookie. Not solved here. |
| Session theft from the database file | DB stores `hmac_sha256(secret, token)`, not the token | Anyone who can read the DB file can usually read the environment too, and that has the secret. This defends against a *copy* of the file, not against root. |
| Forged session | 256-bit random token + keyed verifier + server-side row | none worth stating |
| Stale/leaked token | 12-hour TTL, `revoke_session`, revoke-on-password-change, revoke-on-disable, secret rotation as the global kill switch | a token is valid until one of those happens |
| Account enumeration via login | unknown addresses pay a full scrypt against a dummy hash | timing is equalised; error strings must not differentiate, and that is on the route |
| Account enumeration via signup | none — a duplicate returns 409 | **accepted and deliberate.** A signup form that will not say "that address is taken" is unusable. The email list is the asset at risk and it is low value. |
| CSRF | `SameSite=Lax` + JSON-only mutating POSTs | see §3.2; a double-submit token is the upgrade if wanted |
| Memory-exhaustion DoS via login | 128 MiB per attempt; process-wide cap of two concurrent scrypt calls; per-address counter; `MAX_PASSWORD_CHARS` caps input | Memory is bounded, but an attacker can still queue work and burn CPU. A route-level request bucket remains an operator decision. |
| Memory/CPU DoS via **signup** | `MAX_PASSWORD_CHARS`; process-wide two-hash cap | **Still unthrottled.** A signup flood can queue hashes and fill the accounts table even though memory is bounded. This is the concrete reason §6 item 4 matters and invite-only signup removes the problem rather than mitigating it. |
| A wedged lockout as self-DoS | the lockout lifts; tested with an injected clock | none |
| Privilege escalation via a leaked hash in a response | `PUBLIC_FIELDS` allowlist, tested against a column added after the fact | none |
| SQL injection | parameterised queries throughout; no string-built SQL | none |
| Path traversal / arbitrary file access | no caller-supplied paths anywhere in the module | none |
| Misconfiguration on a public box | two switches, both required; `_secret()` raises rather than defaults | none — this is the fail-closed property, and it is the one the DRM finding in HANDOVER §5 got wrong |
| Storage loss | — | **see §6. This is the open risk, not a solved one.** |

**Out of scope and worth saying:** anyone with root on this box, or with the environment of
the running service, has the session secret and can mint sessions. Nothing in a
single-server design changes that.

---

## 6. Decisions for the owner

Numbered so they can be answered individually.

1. **Is `run/` the right home for account data?** `.claude/CLAUDE.md` argues the name
   `run/` is load-bearing *precisely because* someone will eventually clear it out —
   pidfiles, locks and logs are meant to be disposable. Account data is not. The module
   puts the database in its own subdirectory, `run/accounts/accounts.db` (mode 0700), so a
   `rm run/*.log` sweep does not catch it, and `run/` is gitignored wholesale so nothing
   reaches git. **But if accounts ever hold anything you care about, this needs a backup or
   a different home.** Today the file does not exist and losing it costs nothing.

2. **Re-measure scrypt after deployment.** The repository now uses N=2^17, r=8, p=1 with
   two concurrent hashes maximum. The historical 248 ms reading is from the named host;
   verify latency and memory on the actual serving runtime before increasing the cap.

3. **Keep the account throttle?** §1.3. It is not the limiter you removed and the table
   there says why, but it is your call and disabling it is one edit.

4. **Turn on `SYMONEURAL_RATE_ACCOUNTS`?** Separate question from 3. The mechanism already exists
   in `api.py` and is off everywhere. These are the two endpoints where a request limit
   buys something the account throttle cannot, because it caps CPU and RAM burned by
   attempts against *many* accounts from one address:

   - **login**, where the account throttle is the primary control and a bucket is depth;
   - **signup**, where there is currently no failed-attempt counter and every call queues a
     128 MiB hash (see the threat table).

   Recommend a loose one (e.g. `30/300`) if you want any global limit anywhere; recommend
   nothing if you would rather keep the API uniformly unmetered — in which case take
   item 6 (invite-only) seriously, because it closes the signup lever by removing the
   endpoint.

5. **What is an account actually for?** Nothing gates on it yet. The answer changes whether
   this needs TOTP, an audit log, or per-account API tokens. HANDOVER §5 items 12–13 note
   an iPhone app is coming and `/api/chat` is currently open to whatever can reach the
   origin — **account-issued API tokens are the obvious next piece**, and they are a
   different thing from a browser session (no cookie, no CSRF, long-lived, revocable). Not
   built, and it should be specified before it is.

6. **Signup open, or invite/operator-created only?** The module does not decide. If the
   answer is "operator-created", the `/api/accounts/signup` route simply does not ship and
   the surface is much smaller — no enumeration question, no spam signups, no reset problem
   worth solving.

7. **Session TTL of 12 hours** — arbitrary and adjustable via `SYMONEURAL_SESSION_TTL_S`.

8. **`SameSite=Lax` vs `Strict`**, and whether you want a CSRF token on top (§3.2).

---

## 7. Operating it

```bash
# generate a secret -- keep it out of git, out of /tmp (that is how the contract signing
# key was lost, HANDOVER §2d) and set it in the systemd unit's environment
openssl rand -base64 48

export SYMONEURAL_ACCOUNTS_ENABLED=1
export SYMONEURAL_SESSION_SECRET='<the value above>'

python3 backend/apps/accounts/__init__.py         # selftest as JSON
                                                  # (the file, not the directory --
                                                  #  a package has no __main__.py)
python3 backend/apps/accounts/test_accounts.py    # 48 tests, ~45s here (real scrypt)
python3 backend/apps/test_account_security.py     # focused policy/route contracts
```

`selftest()` reports `ok:false` with a clear error when the secret is missing. **That is
the fail-closed path working, not a fault.**

Rotating `SYMONEURAL_SESSION_SECRET` signs everybody out. That is the intended emergency lever.
