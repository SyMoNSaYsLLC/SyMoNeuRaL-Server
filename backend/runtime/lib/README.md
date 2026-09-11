# `backend/runtime/lib/` — Library for `runtime`

No routes. **No side effects on import** -- a module here may be imported by a test, a
tool, or another component, and one that opens a socket or reads a config file at import
time makes all three unpredictable.

Anything that needs the app, the lease or a request belongs in `../runtime.py`.

| file |  |
|---|---|
| `ratelimits.py` | The per-surface rate budgets. One dict, published from and enforced from. |
| `runtimeconfig.py` | Load this box's runtime configuration from a user-owned directory, not from `/etc`. |
| `symoneuralenv.py` | Legacy env-var promotion: `SYM_FOO` becomes `SYMONEURAL_FOO` at startup. |

See [`../README.md`](../README.md) for what `runtime` is and why.
