# Account security audit — 2026-08-26

Scope: the public `/api/accounts` boundary and DispatchOS application accounts. This is a
repository audit and local patch, not a claim about the currently deployed host. No live
database, password, session secret, Caddy configuration, or systemd unit was read or
changed.

## Result

The account core already failed closed, used salted scrypt hashes, stored only keyed
session verifiers, compared secrets in constant time, revoked sessions on password change
and disable, and kept account/IP login backoff in SQLite. DispatchOS already enforced its
operator/customer roles and stored only hashes of session tokens.

This patch closes the material gaps found during the review:

- new and changed single-factor passwords require 15 characters;
- new scrypt hashes use N=2^17, r=8, p=1 (128 MiB); older hashes remain valid and upgrade
  after a successful login;
- a bounded semaphore permits at most two scrypt operations per process, preventing the
  web thread pool from multiplying 128 MiB by an unbounded number of concurrent requests;
- every password hash invoked by an async account or DispatchOS login route runs in a
  worker thread rather than blocking the API event loop;
- account and DispatchOS API responses use `Cache-Control: no-store` and `Pragma: no-cache`;
- DispatchOS uses a precomputed equal-cost dummy hash for unknown users instead of making
  a fresh hash and then checking it on every request;
- DispatchOS now persists separate username and client-address failure counters with
  exponential backoff and a `Retry-After` response;
- an operator-set DispatchOS password revokes every existing session for that user.

## Verification performed locally

```text
python3 backend/apps/accounts/test_accounts.py
  48 tests (real production scrypt parameters)

python3 backend/apps/test_account_security.py
  6 tests

python3 backend/apps/test_dispatchos_security.py
  9 tests
```

The FastAPI/TestClient DispatchOS suite cannot run in the extracted scratch environment
because its optional FastAPI runtime is absent. It must be run on the project host before
merge or deployment:

```bash
python3 -m unittest backend.apps.test_dispatchos -v
```

## Host checks before enabling or deploying

These commands read public or process topology only; they do not print credentials.

```bash
# Both application listeners should be loopback-only. Do not enable the surface if either
# appears as 0.0.0.0 or [::] until the intended proxy topology is reviewed.
sudo ss -ltnp | grep -E ':(8000|8800)\b'

# Validate the Caddy configuration without reloading it.
sudo caddy validate --config /etc/caddy/Caddyfile

# The public status body is safe: it contains switches, not accounts or secrets.
curl -fsS https://symoneural.com/api/accounts/status
curl -fsS https://symoneural.com/api/dispatchos/status

# A stranger must not receive DispatchOS board data.
curl -sS -D - -o /dev/null https://symoneural.com/api/dispatchos/board

# The public response should still carry the route-wide cache policy.
curl -sS -D - -o /dev/null https://symoneural.com/api/accounts/status
```

After an authorized test login, use the browser's Network panel to confirm authenticated
responses carry `Cache-Control: no-store` and the session cookie is HttpOnly, SameSite=Lax,
and Secure over HTTPS. Do not copy or paste the cookie value to perform that check.

Do not paste a session secret, password, `Set-Cookie` value, environment dump, or database
file into an issue or chat. A missing or short `SYMONEURAL_SESSION_SECRET` is intentionally
fail-closed; generate and install it through the host's approved secret path, not a shell
argument or committed `.env` file.

## Deliberately unresolved

- There is no MFA/TOTP, email verification, or automatic password recovery. Those need a
  product decision and, for recovery, an approved mail path.
- Public signup remains a product choice. The two-hash cap bounds memory, but an open
  signup endpoint can still queue CPU work and fill the account table. Invite-only signup
  removes that class of abuse; otherwise add an explicitly approved route-level limit.
- Trusted-forwarded-header behavior depends on the real Caddy/tunnel topology. Do not
  change it from repository assumptions alone; verify the live hop chain first.
- Account data still needs an explicit backup/retention decision before it becomes
  valuable. A secure password database that is accidentally deleted is still a failure.
