# How the model is actually called — measured 2026-09-11

Part 1 of `MODEL-API-MAP.md`. **Evidence, not proposals.** Every number here was read off the
running system, not from a comment. Where a source comment disagreed, the source comment is
named and corrected.

Engine PID 73205, up 3 h 00 m at the time of measurement. Build `b574-941d756d`.

---

## 1 · The spawn — read from `/proc/73205/cmdline`

```
symoneural-llm
  -m      models/llm/symon-1.0-30b-a3b-q2_k_l.gguf
  -ngl    99
  --host  127.0.0.1
  --port  8081
  -c      33792
  --no-warmup
  -cb
  -np     2
```

| flag | effect |
|---|---|
| `-ngl 99` | every layer on the card. Not "99 layers" — a ceiling above the model's layer count |
| `-c 33792` | **total** context across all slots |
| `-np 2` | two slots, so **16,896 tokens per slot** — confirmed by `/props` and `/slots` |
| `-cb` | continuous batching: the two slots interleave rather than queueing |
| `--no-warmup` | no dummy decode at startup. Saves ~4 s; first real token pays it instead |

**Three flags the spec expected are not there.** `MODEL-API-MAP.md` §1 describes
`-c 65536 -np 2` giving 32,768 per slot, plus `-md`/`--spec-draft-n-max` for speculative
decoding and `--lora` for the persona adapter. None is in the live argv:

- context is **33,792 total / 16,896 per slot**, not 65,536 / 32,768. It changed when the
  model changed to the 30B-A3B on 2026-09-11 — that is the ceiling the card fits.
- **no draft model.** Speculative decoding is off.
- **no adapter.** `GET /lora-adapters` returns `[]`.

`backend/core/engine.py:190-237` still builds all three conditionally. The conditions are
false for this model, which is the correct behaviour and not a defect — but any statement
that this box runs speculative decoding today is wrong.

Resident: **1,026,296 KiB RSS**, 28 threads.

## 2 · The protocol — probed, every path, both methods

`symoneural-llm` serves HTTP on `127.0.0.1:8081`. This is the real inventory:

| path | method | status | present |
|---|---|---|---|
| `/health` | GET | 200 | yes |
| `/props` | GET | 200 | yes |
| `/slots` | GET | 200 | yes |
| `/v1/models` | GET | 200 | yes |
| `/models` | GET | 200 | yes |
| `/lora-adapters` | GET | 200 | yes |
| `/completion` | POST | 400 | yes — 400 is the empty body, not a missing route |
| `/v1/completions` | POST | 400 | yes |
| `/v1/chat/completions` | POST | 400 | yes |
| `/tokenize` | POST | 200 | yes |
| `/detokenize` | POST | 200 | yes |
| `/apply-template` | POST | 400 | yes |
| `/infill` | POST | 500 | route exists; this model has no infill template |
| `/embedding`, `/v1/embeddings` | POST | **501** | **not built into this binary** |
| `/reranking`, `/v1/rerank` | POST | **501** | **not built** |
| `/metrics` | GET | **501** | **not built** — `endpoint_metrics: false` in `/props` |

**This is larger than anything written down**, which is what the spec suspected. `/tokenize`,
`/detokenize` and `/apply-template` are free and unused. `/props` alone answers most of
`model/config` and `config-summary`.

Three 501s are the finding that matters: **embeddings and reranking are not compiled in**, so
`model/eval-rag` and the document group cannot be built on this engine as it stands. That is a
build-flag decision, not an endpoint to write.

## 3 · What `/props` already tells us

```
model_path      models/llm/symon-1.0-30b-a3b-q2_k_l.gguf
model_ftype     Q2_K - Medium
total_slots     2
n_ctx           16896        per slot
modalities      vision:false  video:false  audio:false
bos_token       ","          eos_token  <|im_end|>
build_info      b574-941d756d
endpoint_props  false        endpoint_metrics  false   endpoint_slots  true
```

Plus the full default sampler set — 30 parameters with live values — and the chat template.

## 4 · The call chain for `POST /api/chat`

```
POST /api/chat                       backend/chat/chat.py:117
  -> chat(body, request)                              :118
  -> ctx.gpu.hold("chat")                             :138   the lease
  -> ctx.start_llama()   if not resident              :196   -> core/engine.py:190
  -> ctx.chat_deltas(messages, max_tokens, temp)      :247   -> core/engine.py:276
       POST http://127.0.0.1:8081/v1/chat/completions
  <- SSE back to the caller
```

The lease is taken **before** the engine is checked, so a cold request holds the card for the
whole load. `start_llama()` is a no-op when the engine already answers `/health`.

## 5 · The streaming shape

`chat_deltas` posts to the engine's **`/v1/chat/completions`** — OpenAI-shaped upstream — and
re-frames the result as first-party SSE:

```
data: {"delta": "..."}      per token
data: {"done": true, "tokens": N, "ms": M}
```

So the surface is **not** OpenAI-compatible; only the hop to the engine is. Measured round
trip straight to the engine:

```json
{"role":"assistant","content":"measured"}
usage: {"prompt_tokens":15,"completion_tokens":3,"total_tokens":18,
        "prompt_tokens_details":{"cached_tokens":0}}
```

`cached_tokens` is live — that is `model/context_cache` reporting itself already.

## 6 · What the gateway forwards — **the spec's assumption is wrong**

`MODEL-API-MAP.md` §1.5 expects `/v1/chat/completions` and `/v1/{*path}` to be forwarded
verbatim, and concludes an OpenAI surface "may already be reachable from outside". Measured
against the running gateway on :8000:

```
GET  /api/status              200     FastAPI, forwarded
GET  /v1/models               404
GET  /v1/chat/completions     400
POST /v1/chat/completions     405     {"detail":"Method Not Allowed"}
```

405 with a FastAPI error body means the gateway forwarded to **FastAPI**, which has no `/v1`
routes — not to the engine. **`symon-openai` does not exist today and no part of it is
already built.** The whole of that group is new work.

## 7 · What this changes about the thirty-five endpoints

| already answered, do not rebuild | by what |
|---|---|
| `listmodels` | engine `GET /v1/models` — OpenAI-shaped, upstream |
| `model/config`, `getconfig`, `config-summary` | engine `GET /props` — 30 live sampler values |
| `model/exists`, `list-files` | `models/PROVENANCE.json` — 12 weights with upstream, licence, bytes |
| `model/context_cache` | `usage.prompt_tokens_details.cached_tokens`, per response |
| `model/metrics` | `/api/metrics/*`, already mounted |

| blocked on the engine build | why |
|---|---|
| `model/eval-rag`, `docs`, `count-docs` | `/embedding` and `/reranking` return 501 |

| genuinely new | |
|---|---|
| `symon-openai` | nothing forwards `/v1` to the engine today — measured, §6 |
| `model/download`, `job-status` | LocalAI's shape: one call returns a job id you poll |
| `model/ask`, `evaluate`, `summarize`, `cluster`, `visualize` | no equivalent exists |

`model/security`, `ismanager`, `isauthorized`: **there are no tokens on this box and there
will not be** — see `tests/structure/test_no_tokens.py`. `MODEL-API-MAP.md` §4 predates that
decision when it proposes token-gating the operator group. These three can report state
(who the process runs as, what it may reach) but they cannot gate.

---

## How to re-take these measurements

```bash
PID=$(pgrep -f symoneural-llm | head -1)
tr '\0' '\n' < /proc/$PID/cmdline            # the argv, not the source
curl -s 127.0.0.1:8081/props  | python3 -m json.tool
curl -s 127.0.0.1:8081/slots  | python3 -m json.tool
curl -s 127.0.0.1:8081/lora-adapters
for e in /health /props /slots /v1/models /lora-adapters; do
  printf "%-20s %s\n" "$e" "$(curl -s -o /dev/null -w '%{http_code}' 127.0.0.1:8081$e)"
done
```

Everything above is reproducible from those five commands. Nothing in this document was
copied forward from an earlier one.
