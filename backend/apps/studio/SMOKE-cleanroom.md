# Clean-room pipeline — smoke record

Written after running it, not before. Everything below is a reading taken on this box on
**2026-08-21**, at the commit this file lands in, with the SHA of the tree beside each figure
that came from a suite.

The rule this file exists for: `archive_tasks.py` reads checks, not notes, and `exists`,
`grep` and `ngrep` all ask what is written on disk. None of them can ask whether the thing
works. #94 shipped a desktop client whose eighteen checks went green over a chat surface that
was dead on arrival. So the check on this feature is `exists backend/apps/studio/SMOKE-cleanroom.md`,
and this file is only writable by somebody who ran the four things below.

## What was run

The subject is `references/Projects_Crypto/CGMiner-master/dm_fan_ctrl.c` — 7744 bytes, a PID
fan controller, **GPL-3.0-or-later**, copyright Duan Hao and Con Kolivas. Chosen because it is
real, small enough to describe honestly, and copyleft, so it exercises the branch that matters.
Nothing was copied out of `references/` and nothing was built from it; it was read.

### 1. `extract_spec` over the operator route

```
POST http://127.0.0.1:8876/api/studio/tool/extract_spec      3.165 s
  X-Symoneural-Token: devtest
  {"source_path": "references/Projects_Crypto/CGMiner-master/dm_fan_ctrl.c",
   "max_bytes": 60000, "temperature": 0.2}
```

Against **my own API on a spare port**, never the service — `SYMONEURAL_STUDIO_ENABLED=1
SYMONEURAL_STUDIO_TOKEN=devtest python3 -m uvicorn api:app --port 8876`. Answered
`ok: true` with 7 logic steps and 5 edge cases, `backend: llamacpp`,
`base: http://127.0.0.1:8081`, `model: models/llm/symon-1.0-7b-q4_k_m.gguf`.

Provenance as read:

| field | value |
|---|---|
| `license` | `GPL-3.0-or-later` |
| `license_source` | `file header (licence text)` |
| `license_determined` | `true` |
| `copyleft` | `true` |
| `attribution_required` | `true` |
| `project` / `identified_by` | empty / `unavailable` |
| `sha256` | `58e8facc504b321e06c8c1130221e24a0aac66fb9ec3b509ab25a8ea2cfc277c` |
| `bytes_read` | 7744 |

### 2. `generate_native_code`, GPL C to Swift for Apple

```
POST http://127.0.0.1:8876/api/studio/tool/generate_native_code   6.461 s
  {"spec": <the object above>, "target_os": "Apple", "target_lang": "swift"}
```

81 lines of Swift with the attribution header prepended, not offered.

### 3. The FastMCP surface, from Studio's own venv

`backend/apps/studio/.venv/bin/python3.13`, `await mcp.get_tool(...)`:

```
extract_spec:          PRESENT, params ['max_bytes', 'source_path', 'temperature']
generate_native_code:  PRESENT, params ['spec', 'target_lang', 'target_os', 'temperature']
   spec -> {"$ref": "#/$defs/FunctionalSpec"}
   $defs FunctionalSpec: edge_cases inputs leakage logic_steps module_name outputs
                         provenance purpose
   $defs Provenance:     attribution_required bytes_read copyleft identified_by layer
                         license license_determined license_source project recipe sha256
                         source_path
   $defs Leakage:        leaked leaked_count leaked_raw_count method ratio source_identifiers
```

28 tools in the registry. The `$ref` is why the schema is a stdlib dataclass and not the
`pydantic.BaseModel` the original script used: `registry._json_type` renders primitives, enums
and dataclasses, so a BaseModel would have rendered as an untyped object and the "connection
wire" would have had no shape to validate. A dataclass in a module carrying
`from __future__ import annotations` fails the same way and silently, because
`dataclasses.fields()[].type` is then the annotation's source text — which is why that import
is absent from `cleanroom.py` on purpose and why a test asserts the field types are types.

### 4. The drag-and-drop surface, for real

`symoneural-ui.sh start` printed **`linked symoneural_cleanroom into custom_nodes/`** — the
relink loop, which replaced a hardcoded pack name that would have left this pack unlinked and
failed as "the node is not in the menu" with nothing anywhere to read.

`GET /object_info` reported all three nodes loaded under `symoneural/cleanroom`, with
`SymoneuralExtractSpec` output `['FUNCTIONAL_SPEC', 'STRING', 'STRING']` against
`SymoneuralGenerateNativeCode` required input `spec: FUNCTIONAL_SPEC`. Note what that proves:
inside ComfyUI's venv the repo is not importable, so the socket name came from the pack's
**fallback literal**, not from the import — the branch the test process never takes.

Then a real graph, `POST /prompt`:

```
1 SymoneuralExtractSpec  ->  2 SymoneuralGenerateNativeCode  ->  3 SymoneuralSpecReport
                         \_______________________________________/
prompt_id c20886a5-15d7-4650-995b-0ca787a98111   node_errors {}
execution_start 1787339553544 -> execution_success 1787339565476   (11.9 s)
status success, completed true, outputs from node 3
```

`node_errors: {}` is ComfyUI's own validator accepting the `FUNCTIONAL_SPEC` edge. The canvas
text from node 3, verbatim:

```
module: fan control using simple PID
purpose: Maintain a target temperature by adjusting fan speed based on temperature readings
         from multiple chains.
steps: 5, edge cases: 5
source: unidentified [GPL-3.0-or-later] sha256 58e8facc504b
leakage: 22 source identifier(s) appeared in the spec: PID, below, control, fan, g_chain_tmp,
         g_fan_cfg, g_tmp_cfg, hot, max, mode, normal, overheat, preheat, profile, read,
         simple, sleep, speed, temperature, tolerance, unchanged, using -- the no-identifiers
         instruction did not hold. Ratio 0.1176 of 187.
barrier: none -- one model read the source and wrote this spec.
residual: 10 spec-leaked identifier(s) survived into the code: g_chain_tmp, g_fan_cfg,
          g_tmp_cfg, max, mode, preheat, sleep, speed, temperature, tolerance
attribution header:
// Derived from: an unidentified source file (unavailable)
// Source licence: GPL-3.0-or-later (read from file header (licence text))
// Source sha256: 58e8facc504b321e06c8c1130221e24a0aac66fb9ec3b509ab25a8ea2cfc277c
// Written from a behavioural specification, by a model that also read the source. Not a
// clean-room reimplementation.
// The source licence is copyleft. Passing through a specification does not clear that
// obligation; this needs a human decision.
code: 117 lines generated
```

## What the run found, which is the point of running it

**1. A GPL-3.0 file was reported as not copyleft.** The first invocation returned
`copyleft: false` about the GNU General Public License. `_oematch` was the only licence source,
and oematch fingerprints packages: handed one `.c` file it answers `unsupported artifact`, so on
this tool's *actual* input it could never contribute a licence, and `_license_flags("")`
returned `copyleft=False`. The module whose whole job is licence hygiene was silent exactly
where it owed a warning. Fixed three ways: the file's own header is now the primary signal
(`_license_from_text`, SPDX tag first, licence prose second, header-only so a `--version`
banner 4000 lines down is not read as a licence), oematch is the fallback, and an undetermined
licence now reports `copyleft: true` with its own sentence saying it was not determined. An MIT
file mislabelled copyleft costs a human thirty seconds; a GPL file mislabelled permissive costs
a licence breach.

**2. A wrapped licence paragraph was invisible.** A test fixture split
`GNU General Public\n * License` across a line — which is where an 80-column GPL header wraps
about half the time — and the substring search missed it entirely. The scanner now strips
leading comment furniture and collapses whitespace before matching. This was found because a
fixture was written badly; it is a real defect all the same.

**3. Queueing the obvious graph ran nothing.** ComfyUI executes backwards from output nodes
only. `SymoneuralGenerateNativeCode` returns plain strings and is not an `OUTPUT_NODE`, so
extract → generate with nothing downstream is `execution_success` with an empty output set —
which a user reads as a broken editor. `SymoneuralSpecReport` now takes the code, attribution
and residual figure as *optional* inputs, so it is the pipeline's single terminus and pulls the
generator into the execution set, while a spec-only graph stays valid.

**4. The original variable names came through.** `g_chain_tmp`, `g_fan_cfg` and `g_tmp_cfg` are
CGMiner's own globals. They survived the analyst prompt's "CRITICAL: Do NOT output any original
code syntax, variable names, or structural artifacts", appeared in the specification, and then
appeared again in Swift written by a turn that never saw the C. That is the single most useful
output of this whole exercise, and it is a number on a canvas rather than an assumption.

## Two things this record does not claim

**This is not a clean room, and the code says so in four places.** A clean room is an
institutional barrier: one team reads the source and writes a specification, a second team that
has never seen the source implements it, and the separation is auditable. Here both turns are
one model in one process on one box. The prompt telling the second turn it has "never seen the
original source code" is a string, not a barrier. So the module measures what leaks instead of
asserting that nothing does, and every artefact it emits — the attribution header, the node's
provenance output, the report node's `barrier:` line — says
*"Not a clean-room reimplementation"* in those words. **Passing copyleft source through this
does not launder it.**

**The two leak figures err in opposite directions, and both directions are stated.** The spec
figure is an **upper bound**: it is a whole-word identifier intersection against a 182-word
stoplist, so ordinary domain vocabulary a spec of a fan controller cannot avoid — `fan`,
`speed`, `temperature`, `PID` — is counted as leakage. Of the 22 above, five (`g_chain_tmp`,
`g_fan_cfg`, `g_tmp_cfg`, `overheat`, `preheat`) are the ones that would matter to a lawyer and
the rest are English. The residual figure is a **lower bound** and labels itself one: the second
half never sees the source, so only identifiers already visible in the spec can be counted, and
anything the model reconstructed independently cannot be. Over-counting the first and
under-counting the second is deliberate — a leak measure that errs high is honest, one that
errs low is dangerous. **Neither figure is stable across runs.** Three runs of the same file at
`temperature: 0.2` gave 15, 21 and 22 leaked identifiers. It is a measurement of one run, not a
property of the file, and it must never be quoted as one.

## The suites

`apps/studio/test_cleanroom.py` — **52 pass in 0.26 s**. Nine deliberate breaks were verified
red before this file was written, and two of them are why two of the tests exist:

- the pack's fallback `_SOCKET` literal changed → **green**, because this process imports the
  repo fine and ComfyUI does not. The literal is now regexed out of the source.
- `license_determined=bool(licence)` hardcoded to `True` → **green**, because every licence row
  called the helpers directly and nothing reached the builder that wires them in. A correct
  helper with a call site that ignores it is #94's shape; `TheProvenanceBuiltByARealExtractionTests`
  stubs the backend and exercises the builder on real temp files.

Whole-directory reading, with the standing `reinforce`/`cupy` exclusion:

```
cd backend && python3 -m pytest apps/studio -q --ignore=apps/studio/plugins/reinforce/tests
```

## Reproducing this

```bash
cd backend && SYMONEURAL_STUDIO_ENABLED=1 SYMONEURAL_STUDIO_TOKEN=devtest \
    python3 -m uvicorn api:app --port 8876          # a spare port, never the service
SYMONEURAL_STUDIO_TOKEN=devtest SYMONEURAL_API_BASE=http://127.0.0.1:8876 \
    bash scripts/symoneural-ui.sh start            # the node pack reads both
```

**The nodes need both variables in ComfyUI's environment**, and that is the failure to expect:
without the token every node raises `SYMONEURAL_STUDIO_TOKEN is not set`, and without
`SYMONEURAL_API_BASE` they default to `http://127.0.0.1:8800`, which is the **live service** —
so a graph queued from a dev editor would run against production. They raise with the reason
rather than returning an empty string, because a node that outputs `""` on a 401 produces a
graph that looks like it ran.

`llama-server` must be resident on `:8081`. Warm it through the chat surface, never by spawning
it — `api.py` owns that process inside `gpu.hold("chat")` and `inference.py` deliberately only
probes:

```bash
curl -sS -X POST http://127.0.0.1:8800/api/chat -H 'Content-Type: application/json' \
    -d '{"prompt":"ready","max_tokens":8}'
```

**That command returned `Internal Server Error` after 61 s when this run started, and the cause
was not the engine.** It is written up in full in `.claude/HANDOVER.md`: the governor's 1500 MiB
drain floor sits below this box's own KDE + Chrome + OBS graphics baseline of 1336 MiB, so with
any second tenant resident the card can never drain and `acquire chat` fails. `/api/chat` was
answering 500 to every visitor. These tools take no GPU lease of their own — they ride
`inference.pick()`, which probes — so they contend for the card like any other tenant rather
than deadlocking beside a render.
