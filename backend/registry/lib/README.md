# `backend/registry/lib/` — Library for `registry`

No routes. **No side effects on import** -- a module here may be imported by a test, a
tool, or another component, and one that opens a socket or reads a config file at import
time makes all three unpredictable.

Anything that needs the app, the lease or a request belongs in `../registry.py`.

| file |  |
|---|---|
| `appdocs.py` | Per-application documentation, scoped by ownership and read from the live router. |
| `fabric.py` | SyMoNeuRaL Adaptive Fabric — its real status, read from the registries that define it. |
| `ports.py` | The port registry, read once. Nothing in this repository hardcodes a surface port. |
| `roster.py` | The rack roster, read from `ROSTER.md`. |
| `route_matrix.py` | Enumerate the REAL registered route table of backend/server.py, and classify a |
| `runtimes.py` | The runtime registry, read once. What runs behind each surface, and what it loads. |
| `suites.py` | Testing and benchmarking, read from the tree and from recorded results. Never asserted. |

See [`../README.md`](../README.md) for what `registry` is and why.
