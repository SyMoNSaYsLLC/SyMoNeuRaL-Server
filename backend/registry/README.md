# backend/registry/

The records this box reads about itself. No routes of its own — other surfaces import it.

| file | the record it reads |
|---|---|
| `lib/ports.py` | `ops/PORTS.tsv` — which surface listens where, and which are delegated |
| `lib/runtimes.py` | `ops/RUNTIMES.tsv` — what starts each runtime and what it loads |
| `lib/appdocs.py` | which application belongs to which runtime, for the API reference |
| `lib/roster.py` | the units the rack expects to exist |
| `lib/suites.py` | the test suites and their counts |
| `lib/route_matrix.py` | every mounted route, read from the app |
| `lib/fabric.py` | the MoE expert layout |

**Nothing here hardcodes a port.** That is the entire point: a port lives in `PORTS.tsv` and
four consumers read it. `ports.py` refuses to report a surface delegated unless the registry
also gives it a port, because a half-declared delegation is how a request goes to a process
that is not there.

The standing rule this component serves: **before measuring something, check whether a
registry already records it.** A fifth answer to a question four records already answer is a
fifth thing that can disagree.

<!-- generated: do not edit below -->

## Operations

None. This component is a library for others, or is driven from the desktop session rather than over HTTP.

## Library — no routes, no side effects on import

| file |  |
|---|---|
| `appdocs.py` | Per-application documentation, scoped by ownership and read from the live router. |
| `fabric.py` | SyMoNeuRaL Adaptive Fabric — its real status, read from the registries that define it. |
| `ports.py` | The port registry, read once. Nothing in this repository hardcodes a surface port. |
| `roster.py` | The rack roster, read from `ROSTER.md`. |
| `route_matrix.py` | Enumerate the REAL registered route table of backend/server.py, and classify a |
| `runtimes.py` | The runtime registry, read once. What runs behind each surface, and what it loads. |
| `suites.py` | Testing and benchmarking, read from the tree and from recorded results. Never asserted. |

## Documents

- [`symoneural-generic-contracts.md`](docs/symoneural-generic-contracts.md)
- [`symoneural-runtime-registry.md`](docs/symoneural-runtime-registry.md)
- [`symoneural-sentinel-spec.md`](docs/symoneural-sentinel-spec.md)

<!-- end generated -->
