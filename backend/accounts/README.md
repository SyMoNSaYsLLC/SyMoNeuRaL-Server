# backend/accounts/

> **Write this paragraph.** What is this surface for, who calls it, and what will bite
> someone changing it? The table below is generated and cannot answer any of those.
> Delete this block when you have.

<!-- generated: do not edit below -->

## Operations — 8

|  | path | what it does |
|---|---|---|
| POST | `/api/accounts/login` | Sign in |
| POST | `/api/accounts/logout` | Sign out |
| GET | `/api/accounts/me` | The signed-in account |
| POST | `/api/accounts/password` | Change the password |
| GET | `/api/accounts/sessions` | Live sessions for the signed-in account |
| POST | `/api/accounts/signout-everywhere` | Revoke every session for this account |
| POST | `/api/accounts/signup` | Create an account |
| GET | `/api/accounts/status` | Whether accounts are open on this box |

## Library — no routes, no side effects on import

| file |  |
|---|---|
| `meter.py` | The billing half of accounts: balances, holds, and a ledger. |
| `module.py` | `AccountsModule` -- the per-instance facade the application surfaces bind to. |

## Documents

- [`README.md`](docs/README.md)
- [`accounts-spec.md`](docs/accounts-spec.md)

<!-- end generated -->
