# `backend/studio/lib/` — Library for `studio`

No routes. **No side effects on import** -- a module here may be imported by a test, a
tool, or another component, and one that opens a socket or reads a config file at import
time makes all three unpredictable.

Anything that needs the app, the lease or a request belongs in `../studio.py`.

| file |  |
|---|---|
| `agent.py` | The cognitive loop: prompt, detect a tool call, execute it, feed the result back, synthesise. |
| `comfy.py` | The ComfyUI bridge: HTTP queueing, WebSocket monitoring, and the GPU lease around both. |
| `graph.py` | Canvas document -> ComfyUI prompt graph, and the validation that happens on the way. |
| `httpclient.py` | Facade over the upstream HTTP client (httpx). |
| `inference.py` | The inference adapter: one interface, two local backends, no cloud. |
| `mcp_server.py` | The MCP surface: the same tools, over FastMCP, for clients that are not this website. |
| `registry.py` | Tool registry and JSON Schema introspection, on the standard library alone. |
| `rows.py` | Lifted from server.py, 2026-09-11. |
| `workspace.py` | Where SyMoNeuRaL Studio thinks it is. |

See [`../README.md`](../README.md) for what `studio` is and why.
