# `tests/component/accounts/` — what the accounts surface must do

Run: `python3 -m pytest tests/component/accounts -q`

| file |  |
|---|---|
| `test_account_security.py` | Focused security contracts for both accounts routers. |
| `test_accounts.py` | Tests for SyMoNeuRaL Accounts. System interpreter, no network, no venv, no GPU. |
| `test_accounts_runtime.py` | `scripts/accounts-runtime.sh` — the account/session domain owner. |
| `test_entitlement.py` | Shared-store entitlement: grant, revoke, re-grant, and the audit trail. |

## Two things that bite here

These moved out of `backend/` on 2026-09-11. **`from . import X` has no package to be
relative to** — import the component by name: `from accounts import accounts`. And **`HERE`
and `ROOT` are the repository root**, not this directory; the root `conftest.py` puts
`backend/` on the path, in exactly one place.

## What a test here has to do

Exercise the surface, not the file. A test that reads source and asserts a string is a
grep with a test's authority — #94 archived on eighteen such checks over a surface that
was dead on arrival.

Prove the behaviour changed: break it on purpose, watch this fail, then fix it. A test
that passes before and after your change tested nothing.

See [`../README.md`](../README.md) for the convention and
[`../../../backend/accounts/README.md`](../../../backend/accounts/README.md) for what
`accounts` is.
