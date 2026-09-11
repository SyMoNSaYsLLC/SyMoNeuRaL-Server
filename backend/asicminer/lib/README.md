# `backend/asicminer/lib/` — Library for `asicminer`

No routes. **No side effects on import** -- a module here may be imported by a test, a
tool, or another component, and one that opens a socket or reads a config file at import
time makes all three unpredictable.

Anything that needs the app, the lease or a request belongs in `../asicminer.py`.

| file |  |
|---|---|
| `fwcheck.py` | Pre-flight a Bitmain firmware package the way the miner's own `runme.sh` will. |
| `probe.py` | Read real telemetry off Antminer and MicroBT rigs, and print it as JSON. |
| `scan.py` | Find mining rigs on the operator's own network, then identify what they are. |

See [`../README.md`](../README.md) for what `asicminer` is and why.
