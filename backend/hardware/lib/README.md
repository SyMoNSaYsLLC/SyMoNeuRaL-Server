# `backend/hardware/lib/` — Library for `hardware`

No routes. **No side effects on import** -- a module here may be imported by a test, a
tool, or another component, and one that opens a socket or reads a config file at import
time makes all three unpredictable.

Anything that needs the app, the lease or a request belongs in `../hardware.py`.

| file |  |
|---|---|
| `gpu.py` | The lease's Python side. Currently one thing: telling the governor what it evicts. |
| `hostmetrics.py` | CPU, RAM and disk, read from this host. Same contract as `modelmetrics`: readings only. |
| `layer_probe.py` | Probe every reported endpoint at all four layers and print the route matrix. |
| `modelmetrics.py` | Real numbers about the model's work, read from the hardware and the engine. Never asserted. |
| `telemetry.py` | Reading the card. One nvidia-smi exec per second at most, shared by every caller. |

See [`../README.md`](../README.md) for what `hardware` is and why.
