# SyMoNeuRaL Studio

A local reasoning agent that can touch the machine it runs on, and the image bench it drives.
Route `/studio`, API `/api/studio/*`, embedded editor `/studio/comfy/*`.

Nothing here calls a hosted model, a hosted queue or a hosted vector store. The agent runs on
this box's own Qwen2.5-7B through `llama-server`; renders run in ComfyUI on the same single
RTX 5070 Ti that chat and training queue for.

---

## Switching it on

Off unless **both** are set in the API's environment, then restart the service:

```bash
SYMONEURAL_STUDIO_ENABLED=1
SYMONEURAL_STUDIO_TOKEN=<secret>          # presented as X-Symoneural-Token
                                          # (X-Sym-Token, the name it replaced, is
                                          #  still read -- see gate.HEADER_LEGACY)
```

This is the structural switch `apps/voice` and `apps/asicminer` already use, and it is the
only gate in the package. As of 2026-08-20 there is **no content filter, no path allow-list and
no command blocklist** implemented on this surface. That is a deliberate pre-launch state, not
a cleared posture — the standing instruction this used to cite is held (request ledger R-98,
2026-08-20) and is being re-scoped per surface. With both variables set, `run_command` and
`write_file` reach the whole host. The switch is the difference between that being reachable by
him and being reachable by anyone who finds the box's IP.

`GET /api/studio/state` stays tokenless and reports presence and absence only, so the page can
say "the surface is off" without holding a secret.

Prerequisites for the two heavy paths:

```bash
bash scripts/symoneural-ui.sh start        # the bench; loopback :8188, no GPU lock held
# llama-server is started on demand by the chat surface -- this package never spawns it
```

---

## What is in here

| Module | Does |
|---|---|
| `gate.py` | the two switches, `hmac.compare_digest`, and where a token may be presented |
| `workspace.py` | finds the live stack at import and resolves relative paths against it |
| `registry.py` | typed Python functions → JSON Schema tool specs, standard library only |
| `tools_impl/` | the 26 tools themselves: filesystem, host, stack, ComfyUI |
| `inference.py` | one interface over llama.cpp and Ollama; neither is spawned here |
| `agent.py` | the loop: call, execute, feed the **raw** result back, synthesise |
| `comfy.py` | ComfyUI HTTP + WebSocket, wrapped in the GPU lease cycle |
| `graph.py` | canvas document ⇄ ComfyUI prompt graph, validated against `/object_info` |
| `workflows.py` | the stock FLUX.1-schnell graph, built for the weights on this disk |
| `routes.py` | the two routers: the API, and the reverse proxy for the editor |
| `mcp_server.py` | the same functions over MCP/FastMCP, from an isolated venv |
| `page.html` / `page.js` | the surface; `tools/build/build_studio.py` deploys them to `site/` |
| `custom_nodes/symoneural_gguf/` | our ComfyUI node — see *The custom node* below |

---

## The decision worth reading first: there is no hand-written canvas

The original plan had one — snap-to-grid, SVG wires, port-type checking, roughly a thousand
lines. It was deleted before it shipped, because `comfyui_frontend_package 1.49.6` is installed
in `engines/symoneural-ui/.venv` and is the same production editor ComfyUI serves itself: searchable palette,
typed wiring, link-release node suggestions, per-node progress, inline results, 863 node
classes on this box. It also computes its API base as

```js
api_base = location.pathname.split('/').slice(0, -1).join('/')
```

which makes sub-path hosting a **supported upstream configuration**, not a trick. So
`ui_router` reverse-proxies it at `/studio/comfy/` and the Studio page frames it same-origin.

A hand-written canvas would have been a permanently worse editor maintained here instead of a
better one maintained upstream, and every ComfyUI node release would have been a bug in it.
What this package ships instead is the SyMoNeuRaL chrome around it: the agent transcript with
raw tool results, the render form, the status strip and the tool registry.

---

## The GPU, which is the hard part

One card, 15.92 GiB, shared by chat (~5 GB), image (~7 GB) and QLoRA training (~12 GB) behind
`scripts/gpu-governor.sh`. CLAUDE.md: *hold the lock for a job, never for a process lifetime.*

`scripts/symoneural-ui.sh` therefore takes **no** lock. A running-but-idle ComfyUI would otherwise
lock every other surface out of the card for as long as somebody left the editor open. The
lease is taken per render inside `comfy.lease()` and given back with
`POST /free {"unload_models":true,"free_memory":true}` plus a drain wait below the 1500 MiB
floor.

Renders started **inside the embedded editor** are the interesting case, because the editor
queues them itself and knows nothing about a mutex. `routes.py` intercepts
`POST /studio/comfy/api/prompt` and runs it through `_LeaseKeeper`, which reference-counts:

* first in-flight job acquires the lease;
* further jobs queued while it is held share it, rather than each unloading and reloading
  12 GB of weights;
* when the count reaches zero the keeper waits `SYMONEURAL_STUDIO_LEASE_LINGER` (default 8 s) before
  releasing, so a burst of queued renders is one lease, not six;
* if the governor refuses, the editor gets a 409 shaped exactly like ComfyUI's own error
  (`{"error": {...}, "node_errors": {}}`), so its UI reports it rather than hanging.

Completion is detected by polling `GET /history/{prompt_id}`, **not** by watching the
WebSocket. ComfyUI routes execution events only to the `client_id` that queued the prompt
(`server.py` dispatches by sid), the editor queues with its own id and needs those frames
itself, so this proxy must not substitute one.

---

## Tools

26, in four groups, all introspected — the system prompt the model sees is generated from the
same `inspect` pass that produces the HTTP schema and the MCP schema, so the three cannot
disagree.

| Group | Tools |
|---|---|
| `workspace` | `workspace_root` `list_dir` `read_file` `write_file` `delete_path` `search` `find_files` |
| `host` | `run_command` `env_get` `env_set` `service_status` `gpu_status` `disk_usage` `python_packages` |
| `stack` | `list_apps` `app_status` `read_app_config` `list_routes` `list_models` `list_generators` |
| `comfyui` | `generate_image` `run_workflow` `list_workflows` `list_comfy_nodes` `comfy_status` `read_image_file` |
| `cleanroom` | `extract_spec` `generate_native_code` |

The five counts are 7 · 7 · 6 · 6 · 2 and they are read out of `registry.TOOLS` rather than
counted by eye — `read_image_file` sat under `workspace` in this table for two weeks because it
lives in a file about images and reads from disk, while `comfy_tool.py:393` registers it
`@tool("comfyui")`. The group is what the model is shown, so the table being wrong meant the
document disagreed with the prompt.

`dangerous: true` on a tool is a **label**, surfaced in the UI and the prompt so the operator
can see which tools write. It restricts nothing.

Relative paths resolve against the repository root, not the process working directory. That is
deliberate: an agent that says `read_file("backend/server.py")` means the repo, and resolving
against a cwd that happens to be `/` is how it would silently read nothing.

---

## The MCP surface

`mcp_server.py` iterates the registry and registers every entry with FastMCP. It contains no
tool logic — add a decorated function to `tools_impl/` and it appears on the HTTP surface, in
the agent's prompt and over MCP without being named in any of the three.

FastMCP must never be installed into the system interpreter (that is the serving path), so it
lives in an isolated venv, by full path:

```bash
python3 -m venv backend/apps/studio/.venv
backend/apps/studio/.venv/bin/pip install -r backend/apps/studio/requirements.txt
```

Claude Desktop / Claude Code config:

```json
{"mcpServers": {"symoneural-studio": {
  "command": "/home/google/Symoneural/backend/apps/studio/.venv/bin/python",
  "args": ["/home/google/Symoneural/backend/apps/studio/mcp_server.py"],
  "env": {"SYMONEURAL_STUDIO_ENABLED": "1", "SYMONEURAL_STUDIO_TOKEN": "..."}}}}
```

An MCP client presents no header, so the gate is on the *process*: `SYMONEURAL_STUDIO_ENABLED` must be
in the environment the server is launched with. Without it the server still starts and still
lists its tools — listing is how a client discovers why it is being refused — and every call
returns the same `studio_disabled` structure.

**Verified against the venv**: 26 tools listed, 2 resources (`symoneural://workspace`,
`symoneural://tools`), `list_dir` exposing `path` and `show_hidden`, `run_command` carrying the
`[writes to the host]` marker, calls refused with the switch off and answering with it on.

Two things had to be discovered by running it rather than by reading the docs, and both are in
the code as comments:

1. FastMCP rejects `**kwargs` wrappers outright. `functools.wraps` on the registry's own
   function is what makes the client see the real typed signature.
2. `apps/studio/__init__.py` cannot eagerly import `routes.py`, because that imports
   FastAPI and this venv has only `fastmcp`. `router`/`ui_router` are resolved through a PEP
   562 `__getattr__` instead.

---

## The custom node

`custom_nodes/symoneural_gguf/` provides `DualCLIPLoaderSDCPP`, which loads this box's
`symoneural-image-t5-q8_0.gguf`. Upstream's `DualCLIPLoaderGGUF` validates fine against `/object_info` and
then fails at execution with *"This gguf file is incompatible with llama.cpp!"* — the local
file is a stable-diffusion.cpp export with no `general.architecture` key and original
HuggingFace tensor names, which upstream's text-model branch rejects. That was found by running
a render, not by reading the catalogue.

It lives **in this repo**, not in the ComfyUI tree, because `ComfyUI/` is gitignored in full
(8.5 GB, carries its own `.git`). `scripts/symoneural-ui.sh start` symlinks it into
`engines/symoneural-ui/custom_nodes/` on every start, so deleting and recloning ComfyUI loses nothing of ours.

Moving it there broke it once, immediately and instructively: the module located its sibling
`ComfyUI-GGUF` with `Path(__file__).resolve()`, and `.resolve()` walks *through* the symlink —
so it looked for the pack next to itself inside `backend/apps/` and every node in the pack
500'd on `/object_info`. It now matches on the tail of the path instead and does not care where
it lives. Confirmed by restarting the server and fetching
`/object_info/DualCLIPLoaderSDCPP`, which returns the node.

---

## Building the page

```bash
python3 tools/build/build_studio.py      # -> site/studio.html + site/studio.js
python3 tools/build/build_cachebust.py   # ALWAYS LAST
```

The generator is idempotent (verified: two runs, identical MD5s) and asserts every step of the
fragment unwrap. `page.html` is a section fragment whose every selector is namespaced
`#studio .st-*`; the generator refuses to build if the outer `<section id="studio">` changes
shape, because losing that id renders the page unstyled rather than broken — the failure mode
hardest to notice.

`/studio` is **not** in `tools/build/build_pages.py`'s `NAV`, matching `/reinforce`: operator
surfaces are reached from the rack row, and an eighth nav item for a page that is off by
default for every visitor would be noise.

---

## Deploying

`/studio` is a **new top-level path**, so unlike `/api/*` it needs a Caddy block — Caddy
resolves unknown paths against `/var/www/symoneural` first and would 404 before FastAPI ever
saw it. `ops/Caddyfile` has one, validated with
`caddy validate --config ops/Caddyfile --adapter caddyfile`. `symon-gateway` needs no change:
it forwards `/api/*` opaquely, including WebSocket upgrades on any path.

Only Garrett runs these:

```bash
sudo scripts/deploy.sh --prune
sudo systemctl restart symoneural-api      # picks up the two environment variables
sudo ./scripts/install-caddy.sh            # picks up the /studio block
```

---

## Tests

```bash
cd backend && python3 -m pytest apps/studio/test_studio.py -q     # 63
cd backend && python3 -m pytest apps/ -q --ignore=apps/studio/plugins/reinforce/tests --ignore=apps/remix/tests
```

`test_studio.py` holds **63 tests** and they all pass in 3.52 s (`pytest --collect-only -q`
says "63 tests collected", both measured 2026-08-19 06:40 EDT). It said 61 until the tokenless
`/state` grew two tests of its own; treat the figure as a dated reading, which is why the
command is printed above it. The whole-suite before/after pair that used to sit here —
"941 collected before, 973 after" — was measured against a tree that has since moved on twice,
and a delta is not durable either once both ends of it are stale: run the second command above
for the current total rather than reading one off this page. `test_studio.py` imports nothing
outside the serving path, deliberately: a third `--ignore` would turn a four-figure collection
into "collected 12" and read exactly like a broken suite.

What it asserts, and why each one exists rather than being a shape check:

* every tool's schema has a description and every `required` name is a real property — a
  required entry with no property makes llama.cpp's grammar compiler reject the **whole**
  tools array, taking all 26 down together;
* `workspace.root()` returns the checkout — regression: it raised on failure but had no
  `return` on success, so it handed back `None` and every filesystem tool resolved against it;
* the FLUX graph carries schnell's parameters (`cfg 1.0`, `steps 4`, `EmptySD3LatentImage`)
  and every link points at a node that exists;
* every `PARAMETER_MAP` address lands on a real input, and `graph.inject` reports a bad
  address instead of raising — the caller is an LLM, and a traceback ends its turn over a typo
  it could have corrected;
* `registry.check` names an invented parameter and a missing required one, refuses `true`
  for an integer (`isinstance(True, int)` is `True` in Python, so the obvious check would
  render one step), and accepts `"4"` — which `_coerce` then makes `4`;
* every selector in `page.html` is namespaced to `#studio`, and no `text-overflow` rule
  survives comment-stripping.

There is also a browser check, which is **not** part of `tests/frontend.mjs` and must not be
folded into it — it needs the surface switched on and it takes the GPU for a real render:

```bash
# One token for this run, and not a fixed literal. It is the whole boundary in front of
# `run_command`, it travels in URLs (`gate.py`), and nothing rate-limits guesses at it
# (`api.py:2346`). This example used to say `devtest`, which is a credential worth pasting
# nowhere -- least of all into an env file that outlives the test.
export SYMONEURAL_STUDIO_TOKEN=$(openssl rand -hex 32); echo "$SYMONEURAL_STUDIO_TOKEN"
cd backend && SYMONEURAL_STUDIO_ENABLED=1 python3 -m uvicorn server:app --port 8875    # blocks

# Second shell, with SYMONEURAL_STUDIO_TOKEN exported to the value the line above printed:
bash scripts/symoneural-ui.sh start
node tests/studio.mjs http://127.0.0.1:8875
```

It asserts the strip populates from the API, the tool table has a row per tool, the ComfyUI
editor boots inside the iframe and reaches its own API through the proxy, nothing on the page
truncates text, the page does not scroll sideways at 390 px, and — the two that matter — a
render started from the page **decodes in the browser** and its `src` is `/api/studio/image`
rather than port 8188, which no visitor's browser can reach.

---

## Argument validation, and why it is not a safeguard

`registry.check()` runs before every dispatch and `registry._coerce()` runs after it. Neither
restricts what any tool may do — `run_command` still runs anything. They exist because the
caller is a 7B model:

* a hallucinated parameter name used to reach the function and raise `TypeError`, which arrives
  as a traceback and ends the turn. It now comes back as
  `{"error": "bad_arguments", "unknown": [...], "accepts": [...]}` — a `tool` message the model
  reads and corrects on the next step.
* `"steps": "4"` is a text-completion artefact local models produce constantly and will produce
  again next turn. It is rewritten to `4` rather than bounced, because a round trip that
  teaches the model nothing is the more expensive option.

This is the one idea worth taking from the Cordis-style plugin-harness blueprint (zod/joi
schema validation at the boundary); the rest of that design is compared against what this
package already does in `ops/registry/integration-sources.md`.
