# backend/runtime/

> **Write this paragraph.** What is this surface for, who calls it, and what will bite
> someone changing it? The table below is generated and cannot answer any of those.
> Delete this block when you have.

<!-- generated: do not edit below -->

## Operations

None. This component is a library for others, or is driven from the desktop session rather than over HTTP.

## Library — no routes, no side effects on import

| file |  |
|---|---|
| `ratelimits.py` | The per-surface rate budgets. One dict, published from and enforced from. |
| `runtimeconfig.py` | Load this box's runtime configuration from a user-owned directory, not from `/etc`. |
| `symoneuralenv.py` | Legacy env-var promotion: `SYM_FOO` becomes `SYMONEURAL_FOO` at startup. |

<!-- end generated -->
