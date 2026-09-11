# Studio, against its two references: the gap, as observable behaviour

#89's first deliverable. R-163: *"Studio needs major work it should mirror what deepseek harness
provides."* R-132, earlier and still standing: *"studio is being designed with reference to
comfyui and deepseek harness."* Two references, not one, and Studio currently matches neither.
2026-08-22, Garrett again: *"studio needs same thing its nothing like requested with comfy
desktop and comfyui."*

#89 says what this file has to be and it is worth restating, because the temptation is to skip
it: *"writing down, as a checklist of observable behaviour, what it gives a user that we do not.
That list is the task; guessing at 'major work' is not."*

**Read-only boundary.** `references/deepseek-harness/` and `references/ComfyUI/` are reference
material. Nothing here is imported, linked, served or vendored. What ships is ours. This file
records *behaviour a user can see*, which is not a licensed artefact.

---

## The finding in one line

**Studio is a render bench with a chat box bolted on. Both references are shells that host
things.** The distance is not styling and it is not features — it is that in both references the
page is a container with slots, and in Studio the page *is* the feature. Everything below falls
out of that one difference.

The second finding is more useful, because it is cheap: **we have already built most of the
missing runtime, on the wrong page.** `/exp` has a manifest format, four plugin shapes, fiber
lifecycle with pending/active/failed/disposed, `ctx.effect` teardown in reverse, hot reload by
`importlib.reload` + rebind, diff-not-rebuild apply, and a UI that can enable, disable, reload,
mount, patch and call. `/studio` has none of it and cannot see any of it. #89's stated dependency
— Exp migrating *into* Studio — is therefore not a sequencing preference, it is the whole job:
the surface exists, it is pointed at a toy plugin graph instead of at Studio's own.

---

## 1. Plugins — the gap #89 is actually about

| # | What a user can do in the reference | Studio today |
|---|---|---|
| 1.1 | See a list of every plugin, with per-plugin state | nothing on the page |
| 1.2 | Search that list | — |
| 1.3 | Expand a row for its id, effective config and lifecycle phase | — |
| 1.4 | Configure a plugin from a form, staged, written on **Save** | — |
| 1.5 | See per-field whether *you* set it, and reset to the composed default | — |
| 1.6 | Watch a plugin hot-reload without restarting the process | exists at `/exp`, invisible at `/studio` |
| 1.7 | See a failed plugin named, with the services it is still waiting for | `/exp` only |
| 1.8 | Have one crashing plugin black out one card, not the page | no slots, so nothing to isolate |

**What a plugin even is here is the root of it.** `backend/apps/studio/plugins/__init__.py:17-34`
says so in its own words: *"This is a conformance contract, NOT a loader."* The registry is a
hardcoded tuple — `PLUGINS = ("discovery", "exp", "reinforce")` at `:93` — and adding a fourth
means editing that tuple *and* hand-writing an import and an `include_router` in
`backend/api.py`. Required exports are two functions. There is no manifest, no registration API,
no mount/configure/teardown, no version, and no UI.

That contract was a correct decision for what it was for — the reasoning at `:17-34` is that
`api.py` mounts thirteen surfaces with per-surface `prefix=` and `tags=`, and a loop would
flatten the OpenAPI groups. It is simply not a plugin system, and #89 asks for one.

**The reference's contribution surfaces, for scope.** A plugin there is a module exporting
`apply(ctx)` with `inject: [...]`; the framework will not call `apply` until every injected
service exists, and a plugin whose service never arrives stays PENDING with no timeout and is
named at the boot sweep. It can contribute model-facing tools, human-only slash commands, browser
UI into ~30 named slots, per-tool renderers keyed by wire tool name, a settings namespace, LLM
adapters, subagent backends, MCP bridges and hooks.

**Do not copy the slot inventory.** Thirty named slots is the shape of a product that has had
plugins for a year. The observable behaviour to match first is 1.1, 1.4 and 1.8 — see a plugin,
configure it, and have its failure be local.

---

## 2. The agent, as a thing you converse with

`site/studio.js:241-245` sends `{query}` and nothing else. No `history`, no `resume`, no
`permissions`, no `max_steps`, no `model`, no `context`. **The web page is a single-turn,
no-memory, fully-permissive client**, and every one of those capabilities already exists behind
it in `bin/symoneural-cli`.

| # | Reference behaviour | Studio today |
|---|---|---|
| 2.1 | A session list you can return to | no sessions on the page at all |
| 2.2 | Resume a conversation where you left it | CLI only (`-c/--continue`, `run/agent-<session>.json`) |
| 2.3 | Fork a session from a completed turn | — |
| 2.4 | Rename, delete, group sessions | — |
| 2.5 | Full-text search across sessions | — |
| 2.6 | Export a session | — |
| 2.7 | Answer a permission prompt in the browser | **impossible today**, and `routes.py:503-506` says why: *"the /studio page cannot answer a `permission_required` frame"*, so `:507` defaults to `"allow"` |

**2.7 is the one to fix first and it is not a feature request, it is a safety inversion.** The
agent has four `dangerous=True` tools — `write_file`, `delete_path`, `run_command`, `env_set` —
and the only surface that can say *no* to any of them is the CLI. The browser, the surface an
operator actually opens, runs every one of them unasked. `PERMISSION_MODES = ("allow", "deny",
"ask")` already exists at `agent.py:59` and the resume protocol already exists at
`agent.py:242-307`. The missing piece is a card in the transcript with two buttons.

The reference's own version of this is worth reading for the failure modes rather than the
design: a model-driven run that has a browser half **suspends with no timeout** until a human
answers, any tab may answer, first answer wins, and the refusal vocabulary is closed —
`definition-missing`, `host-half-failed`, `client-half-failed`, `rejected`, `cancelled`,
`not-running`.

---

## 3. Reading what the agent did

| # | Reference behaviour | Studio today |
|---|---|---|
| 3.1 | Tool calls render as cards, one renderer per tool | one shape for all 28 |
| 3.2 | The whole row toggles, keyboard-operable, `aria-expanded` | not expandable |
| 3.3 | A failing call is marked on the collapsed row | — |
| 3.4 | Diffs render as diffs — per-file header, `+`/`-` lines, `└ +A -R · N file(s)` | raw JSON |
| 3.5 | Long output caps with head+tail and a count of what is hidden | uncapped |
| 3.6 | Reading position survives switching tabs | — |

`site/studio.js:178-230` prints `tool result` as **the raw JSON return value**. That was an honest
choice — it is what the tool actually returned, and this repo prefers that to a summary that
might lie. It stops being honest at `write_file` and `run_command`, where the thing a person needs
to see is *what changed on their disk*, and a JSON blob is where that gets lost.

**3.4 is the highest value item in this section** and it is nearly free: `generate_native_code`
and `write_file` already return structured data.

---

## 4. The shell

| # | Reference behaviour | Studio today |
|---|---|---|
| 4.1 | Three columns — sidebar / conversation / details — with drag handles | one static column |
| 4.2 | Sidebar collapses to a control rail rather than vanishing | — |
| 4.3 | Details concedes width first on squeeze, auto-closes, restores | — |
| 4.4 | A settings surface at all | **none — every switch is an environment variable** |
| 4.5 | A boot screen projecting real per-plugin state, then one flip to the UI | a gate panel |

**4.4 is worth stating plainly** because it is the whole of #88 in one row: today the only way a
person changes anything about Studio is to export an environment variable and restart the API.

---

## 5. ComfyUI — and the one concrete thing that makes it "nothing like Comfy Desktop"

The proxy is good work and should not be re-litigated: `routes.py:878-903` forwards seven methods
to 127.0.0.1:8188, `:823-875` pumps the WebSocket both ways, and `_intercept_prompt` at `:755-804`
takes a reference-counted shared GPU lease so a render started *inside* the editor cannot bypass
`scripts/gpu-governor.sh`. `tests/studio.mjs:80-91` proves >800 node classes arrive through it.
The user gets the real upstream editor, not a reimplementation.

**And then the Workflows panel says "No workflows found."**

That is the answer to *"nothing like comfy desktop and comfyui"*, and it is one gap, not a class
of them. `SMOKE-bench.md:117-123` measured it: Node Library 29 rows, Model Library 58, Templates
488, **Workflows 0**. `engines/symoneural-ui/user/default/workflows/` is empty, because our one
stock workflow lives in *prompt* format in `workflows.py:110-111` and the editor reads *graph*
format. Opening Comfy Desktop and then opening ours, the first difference a person meets is that
one panel — the one that holds your work.

The converter is not even missing. `GET /api/studio/workflow/{name}` exists at `routes.py:424-436`
and `graph.py` does canvas↔prompt, and `routes.py` records that **nothing calls it — the editor
has never seen it.**

| # | Behaviour | Studio today |
|---|---|---|
| 5.1 | Your workflows listed in the editor's Workflows panel | **empty** — the conversion is written and unwired |
| 5.2 | Save a workflow from the editor and have it persist as ours | — |
| 5.3 | A queue view / history of past runs | upstream's only |
| 5.4 | Render results reachable from the editor and the page as one gallery | two separate lists |
| 5.5 | More than one stock workflow | exactly one, `flux-schnell` |
| 5.6 | More than three sizes | three hardcoded options, `site/studio.html:254-257` |

---

## 6. What Studio already does that neither reference does

Recorded so the rebuild does not throw it away. Every one of these is load-bearing here and absent
there.

- **A GPU lease shared between the framed editor and the page**, reference-counted, honouring one
  governor. The reference has no single contended device to arbitrate.
- **Six status cells that are all real readings** — surface, inference, render UI, tools, GPU
  lease, workspace — with no decorative indicator among them, and `/state` answering *tokenless*
  so the strip renders even when the surface is off.
- **A refusal that explains itself.** 503 `studio_disabled` rather than 404, and the rack row
  naming the two variables to set. The MCP server deliberately starts and lists all 28 tools while
  switched off, because *"listing is how a client discovers why it is being refused"*
  (`mcp_server.py:36-42`).
- **The bench before the strip.** #99 moved it and `SMOKE-bench.md` records the reason: the editor
  was 4% of the first viewport at 1440x1000. Do not let a sidebar push it back down.
- **Tool schemas derived from Python signatures and docstrings**, not hand-authored JSON
  (`registry.py:173-206`).

---

## 7. Order to build in

1. **Permissions in the browser** (2.7). Smallest, and it closes a real hole rather than adding a
   feature. The protocol exists; it needs a card with two buttons.
2. **Wire the workflow converter** (5.1). One unwired function stands between us and the panel
   that makes Comfy Desktop feel like Comfy Desktop.
3. **Sessions on the page** (2.1-2.2). The CLI already threads them; the page needs to list and
   resume.
4. **Tool cards, starting with diffs** (3.1, 3.4).
5. **The plugin surface** (1.1, 1.4, 1.8) — Exp's runtime moved onto Studio, per #89's stated
   dependency. Largest, and it is the one that makes Studio a host rather than a page.

**Deliberately not recommended:** copying the slot inventory, the three-column shell for its own
sake, or a marketplace. The reference has no in-UI install either — discovery is a GitHub topic
and installing is a CLI verb plus a restart.

---

## 8. What this file is not

It is a reading of two reference trees and of our own source, on 2026-08-22. **No behaviour below
`references/` was executed to produce it** — the Harness was not run, and the ComfyUI comparison
is against `SMOKE-bench.md`'s measured panel counts plus the upstream source, not against a live
Comfy Desktop session side by side.

Where a row says a thing is absent, that is absent *from the code as read*, and the citations are
there so the next person can check rather than believe. The measured numbers that are quoted —
28 tools, 6 status cells, >800 node classes, Workflows 0 — each come from a test or a smoke record
that names the tree it was read on.
