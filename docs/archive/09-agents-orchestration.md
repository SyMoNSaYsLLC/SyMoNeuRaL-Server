# Playbook 09 — Agents & Orchestration on Local Models
### Tool use, routing, and multi-worker systems built on small models — the engineering, not the hype

An agent is just a loop: model → decides an action → environment executes → result goes back in. Small local models CAN run agents reliably if you engineer the loop for them. This lab builds that loop from scratch, then scales it to routed multi-worker patterns.

---

## Stage 1 — The bare-metal agent loop (build it yourself first, 1 evening)

No framework. Understanding the loop naked is worth more than any library.

```python
import json, subprocess
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8080/v1", api_key="x")  # llama.cpp/vLLM server

TOOLS = [{
  "type": "function",
  "function": {
    "name": "run_bash",
    "description": "Run a read-only shell command and return stdout+stderr.",
    "parameters": {"type": "object",
      "properties": {"command": {"type": "string"}},
      "required": ["command"]}}}]

def run_bash(command):
    # SANDBOX: allowlist, no writes. Never hand a raw shell to a model.
    if any(t in command for t in [">", "rm ", "sudo", "mv ", "curl", "wget"]):
        return "DENIED: read-only tool."
    r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=15)
    return (r.stdout + r.stderr)[:4000]           # ALWAYS truncate tool output

def agent(task, max_steps=8):
    msgs = [{"role": "system", "content":
             "You solve tasks using tools. Think briefly, act, observe, repeat. "
             "When done, answer with FINAL: <answer>."},
            {"role": "user", "content": task}]
    for step in range(max_steps):
        r = client.chat.completions.create(model="local", messages=msgs,
                                           tools=TOOLS, temperature=0.2)
        m = r.choices[0].message
        if m.tool_calls:
            msgs.append(m)
            for tc in m.tool_calls:
                out = run_bash(**json.loads(tc.function.arguments))
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": out})
        else:
            return m.content
    return "STOPPED: step budget exhausted."

print(agent("How many .py files under ~/AI_Local_NVIDIA are larger than 10KB?"))
```

The five load-bearing details (each one, removed, breaks small-model agents):
1. **Low temperature** (0-0.3) — agents need determinism, not creativity
2. **Truncated tool output** — one fat `ls -R` can flood the context
3. **Step budget** — small models loop forever without one
4. **Explicit stop token** (`FINAL:`) — an unambiguous exit
5. **Grammar-constrained tool calls** where the engine supports it (P07) — malformed JSON is THE small-model agent failure; grammars eliminate it

**Deliverable:** your loop completing 5 multi-step read-only tasks; note which of the five details each failure traced to when you relax them (do relax them — instructive).

---

## Stage 2 — Reliability engineering (what separates demos from tools)

- **Verify claims against ground truth.** Models report success that didn't happen. After any state-changing action, CHECK: file exists? tests pass? exit code 0? Treat completion as a hypothesis to verify, not a fact to log.
- **Retries with feedback**: on malformed/failed calls, append the error and let it try again (2-3 max), then fail loudly.
- **Structured scratchpad**: for tasks > ~5 steps, have the agent maintain a `STATE.md`/plan it re-reads each step — context is not memory; the file is the memory.
- **Idempotent tools**: design tools so running twice is safe; agents WILL run things twice.
- **Observability**: log every step (prompt, call, result) as JSONL. Debugging agents without transcripts is archaeology without a shovel.

**Deliverable:** add verification + retry + JSONL logging to Stage 1's loop; show one transcript where verification caught a false success.

---

## Stage 3 — Routing: right-size the model per step (the local superpower)

You have MANY models (P00-P04). Route by difficulty instead of paying the big model for everything:

```python
ROUTES = {
    "classify/extract/format":       "qwen2.5-1.5b (or your P04 specialist)",
    "tool-use steps, simple code":   "7-8B class",
    "planning, hard debugging":      "32B+ class (or slow big model on CPU)",
}
# Router = the small model itself with a one-line classification prompt,
# or embeddings + nearest-centroid over example tasks (faster, cheaper).
```

Serve two models at once (e.g., 1.5B always-resident + 8B on demand) with llama.cpp's multi-model support or two servers. Measure: total tokens × model-cost vs single-big-model baseline on a 20-task suite. Typical result: ~70-80% of steps route small with no quality loss on the suite.

**Deliverable:** routing table + before/after cost-quality comparison.

---

## Stage 4 — Multi-worker orchestration (careful, here be dragons)

Patterns that work locally, in ascending complexity:
1. **Pipeline**: fixed stages (extract → transform → verify), each possibly a different model/specialist. Most reliable; start here.
2. **Orchestrator-workers**: a planner decomposes, workers execute in parallel, planner integrates. Use when subtasks are independent.
3. **Reviewer pattern**: generator + a separate verifier model that must approve (different model to avoid self-agreement bias — same principle as P05's judge).

Hard-won rules for multi-worker systems:
- **Single owner per resource.** Two agents writing one file/repo = corruption. Route all writes through one worker; respect the routing protocol even when a shortcut looks faster — raise exceptions with the owner explicitly rather than working around it.
- **Handoffs are documents, not vibes**: a handoff = task, context, acceptance criteria, and current verified state. (Your consolidation-script instinct is exactly right — formalize it.)
- **Shared state lives on disk** (files, sqlite), never in "the conversation."
- Parallelism multiplies throughput AND failure modes; add workers only after the single-agent loop is boringly reliable.

**Deliverable:** a 2-worker pipeline (e.g., small-model extractor → specialist formatter → verifier) with document handoffs, run on a real task from your own projects.

## Iron laws
1. An agent is a loop plus discipline: budget, truncation, verification, logs.
2. Malformed output is the #1 small-model failure — constrain with grammars.
3. Completion claims are hypotheses; disk state is truth.
4. Route by difficulty: most steps are small-model steps.
5. One writer per resource; handoffs as documents; state on disk.
6. Multi-agent is an optimization of a working single agent, never a substitute for one.
