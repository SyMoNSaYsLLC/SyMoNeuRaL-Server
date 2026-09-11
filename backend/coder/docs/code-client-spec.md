# SyMoNeuRaL Code — the client protocol

**What this file is: a reference for a protocol that is already built, not a proposal.**
`ops/backend/authority/docs/README.md` says nothing in this directory is authoritative for what the project
currently *is*, and that stands — `.claude/HANDOVER.md` is the one state document and this is
not a second one. What this file describes is narrower and does not overlap it: the wire
contract between a SyMoNeuRaL Code client and `/api/studio/agent`, which is a thing with a
right answer rather than a thing with a status. Everything below was read off the
implementation at the SHA in the next line; where it disagrees with the code, the code is
right and this file is the bug.

Read against `bin/symoneural-cli`, `backend/apps/studio/agent.py` and
`backend/apps/studio/routes.py` at `ebef4fc`, 2026-08-20.

Sibling documents, deliberately not repeated here: `backend/coder/docs/coder-spec.md` is the
2026-08-17 proposal for the agent *capability* and the security argument for keeping it off
every visitor-facing route. That argument is upstream of this one and this file assumes it.

---

## 1. The one thing a client must get right: this stream carries events, not tokens

A client written against a hosted assistant API expects a token stream: a long run of
deltas that concatenate into prose, and a UI whose job is to append characters. **That is not
what this protocol is**, and a client built on that assumption is wrong in a way that looks
like it works.

`agent.run()` yields whole events. Its granularity is a step of an agent loop, not a
token:

| event | when | carries |
|---|---|---|
| `backend` | once, first | which engine answered, and its base URL |
| `thinking` | an intermediate step produced prose | that prose, whole |
| `tool_call` | before a tool executes | `name`, `arguments` |
| `tool_result` | after it executes | the raw return value |
| `permission_required` | a gated tool was chosen | everything needed to resume — see §3 |
| `answer` | the final synthesis | the text |
| `error` | the turn failed | `code`, `detail` |
| `done` | always last | `steps`, `tools_used`, wall clock |

Two consequences a client has to be built around:

**There is no first-token latency to quote.** `inference.Backend.chat` sends
`"stream": False` and is the loop's only call site; `Backend.stream()` exists and is
unexercised. So the honest latency figure for this protocol is time-to-first-*event*, and the
first event is always `backend`. Measured 2026-08-19 over six warm turns: the `backend` frame
lands in 0.015–0.022 s, the first frame carrying model output in 0.2 s warm and 1.06 s cold,
and a whole turn takes 0.53 s with no tool, 1.0–1.9 s with one, 3.1 s with three. A client
that renders a caret and waits for characters will show nothing at all for the first fifth of
a second and then the entire answer at once. Render *progress* — which tool is running — not
a typewriter.

**`thinking` is prose the model produced on the way, not a hidden reasoning trace.** It is
safe to show and it is the only thing that makes a multi-step turn feel alive, because there
is no intra-step streaming to fill the gap.

## 2. Transport

    POST /api/studio/agent      SSE, one JSON object per `data:` line
    POST /api/studio/tool/NAME  {"arguments": {...}} -> the tool's return value
    GET  /api/studio/state      surface state, including `gated` (§3)
    GET  /api/studio/tools      the registry, or the OpenAI specs verbatim

Request body for `/agent`, fields a client actually needs:

    query          str          the user's turn
    history        list[dict]   messages BEFORE the query
    resume         list[dict]   messages AFTER the query  -- see §3.2
    permissions    str          "allow" | "deny" | "ask"  -- see §3.1
    allow          list[str]    tools exempted from the gate whatever the mode
    max_steps      int          loop bound; defaults to SYMONEURAL_STUDIO_MAX_STEPS
    model, context, temperature

**`history` and `resume` are two fields on purpose and cannot be merged.** History goes ahead
of the user query; an approved tool call and its result go after it. Send the latter as
history and the model reads its own tool call as something that happened before it was asked,
then finds the question repeated at the end of the transcript. One list cannot do both jobs.

## 3. The permission handshake

Some tools are marked `dangerous` in the registry — `delete_path`, `env_set`, `run_command`,
`write_file` at this SHA. **A client must not hardcode that list.** `GET /api/studio/state`
publishes `gated`, generated from the registry that decides it, and that is the only correct
source: a copy in a client is a list that goes stale silently and under-reports what is
dangerous, which is the direction that matters.

### 3.1 Three modes, and why an unknown string is refused twice

    allow   run it. The endpoint default, because it is what /agent did before the mode
            existed and the /studio browser page has no way to answer a prompt. Changing
            the default would have gated the browser surface by accident.
    deny    do not run it; hand the model a `not_permitted` result and KEEP GOING. For a
            caller that cannot be asked -- a pipe, a cron job. The turn still completes and
            the model is told what it was refused, rather than a client pretending to have
            asked somebody.
    ask     do not run it; emit `permission_required` and END THE TURN.

Anything else is rejected: a 400 `bad_permissions` at the endpoint, and a `bad_permissions`
error event from `run()` itself for an in-process caller. Both layers, deliberately: the gate
is written as `permissions in ("ask", "deny")`, so a string neither layer recognised would
fall through it and behave exactly like `allow`. A permission system may not fail open on a
typo.

The terminal client adds a fourth spelling of its own, `auto`, which is **not** a wire value:
it resolves to `ask` when a controlling terminal is present and `deny` when it is not, before
the request is built. That is what makes a piped invocation safe by default without making an
interactive one useless.

### 3.2 Why "ask" ends the turn, and why the client re-runs the tool itself

SSE is one-directional. The answer to a permission prompt cannot travel back up the stream
it arrived on, so the turn stops and the frame carries everything needed to continue:

    {"event": "permission_required",
     "name": "run_command", "arguments": {...}, "call_id": "...", "step": 1,
     "reason": "...",                 why it is gated, in words
     "dropped": ["write_file"],       calls chosen after this one, NOT run
     "pending": [ ... ]}              messages already appended during this step

On approval the client **runs the approved tool itself** via `POST /api/studio/tool/NAME`
with *the exact argument object it displayed*, appends the result, and re-issues the turn with
`resume` carrying `pending` plus that result.

The obvious alternative — re-issue the turn with the tool now permitted — is wrong, and this
is the load-bearing design decision in the whole protocol. Re-running lets the model
re-choose at temperature, so it can call `run_command` with different arguments than the ones
a human read and approved, and every tool that ran before the gate runs a second time. **A
prompt that displays A and executes B is worse than no prompt at all.**

`dropped` exists for the same reason. The model chose its tool calls as a set; running the
tail of a set whose head was never approved is a decision nobody made. They are named rather
than silently discarded, and they come back when the caller resumes.

A refusal is not a used tool. `tools_used` on `done` counts executions, so a denied call does
not appear in it — a figure somebody might check against must not be inflated by things that
did not happen.

### 3.3 Per-invocation, never persisted

The terminal client's "always allow this tool" answer sets an exemption for the rest of the
**invocation** and is never written to disk. A persisted "always" is a decision made once and
applied forever by a file nobody re-reads.

### 3.4 Step counts are per-segment

A resumed segment starts its step count at zero, because it is a new call. `steps` and
`tools_used` on `done` are therefore per-segment; a client that wants the whole turn adds them
up, which is what the terminal client's status line does.

## 4. The terminal client

`bin/symoneural-cli` is the engine; `bin/symoneural-code` is the entry point that spells the
product name. One interactive surface (`cmd_repl`) and one non-interactive path, selected by
`stdin.isatty()` so that `echo q | symoneural-code` and `symoneural-code q` both work without
a flag.

Slash commands, from the REPL's own table: `/help`, `/clear`, `/status`, `/tools`,
`/model`, `/resume`, `/session`, `/permissions`, `/exit`. `/permissions` with no argument
reports the gated set **fetched from `/api/studio/state`**, per §3; with `ask|deny|allow` it
sets the mode; with `+NAME`/`-NAME` it edits the exemption list.

`--output-format text|json|stream-json` is what makes this scriptable: `stream-json` is the
event stream above, one JSON object per line, which is the interface any other program should
be written against rather than the human-formatted text.

`--dangerously-allow-all` outranks `--permissions`. The name is the documentation.

## 5. What is deliberately not specified here

- **The desktop client's runtime.** Electron versus something lighter is a footprint
  question with a measured answer, and it belongs in `desktop/README.md` beside the
  measurement rather than in a protocol document.
- **Anything about the model or the adapter.** The client is protocol-only; it never loads
  weights and never takes the GPU lock. Only the API does.
