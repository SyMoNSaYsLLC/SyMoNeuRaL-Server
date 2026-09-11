# `backend/accounts/lib/` — Library for `accounts`

No routes. **No side effects on import** -- a module here may be imported by a test, a
tool, or another component, and one that opens a socket or reads a config file at import
time makes all three unpredictable.

Anything that needs the app, the lease or a request belongs in `../accounts.py`.

| file |  |
|---|---|
| `meter.py` | The billing half of accounts: balances, holds, and a ledger. |
| `module.py` | `AccountsModule` -- the per-instance facade the application surfaces bind to. |

See [`../README.md`](../README.md) for what `accounts` is and why.
