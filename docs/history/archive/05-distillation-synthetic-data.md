# Playbook 05 — Distillation & Synthetic Data
### Using big models to manufacture the training data that makes small models punch above their weight

This is how every strong small model of the 2024-2026 era was actually made. You'll build a teacher→student pipeline: generate data with a large model, filter it ruthlessly, and train your small specialist on it (with Playbook 04's machinery).

---

## Stage 0 — The three flavors of distillation

| Flavor | What transfers | Cost | You'll do it? |
|---|---|---|---|
| **Hard-label** (SFT on teacher outputs) | behavior & skills | cheap — just inference | YES — this lab |
| **Soft-label** (match teacher's full token distributions) | finer-grained knowledge | needs teacher logits + training infra | only if you control both models |
| **On-policy** (teacher corrects the *student's* attempts) | fixes student's actual mistakes | 2x inference, best results | Stage 4, the level-up |

Also check licensing: some hosted-model terms restrict training on outputs. Open-weight teachers (Llama, Qwen, Mistral families) are the clean path for local work.

---

## Stage 1 — Design the data spec before generating anything (1 hour, no code)

Distillation fails in the design, not the training. Write down:
1. **Task definition** — one sentence. "Convert messy shell command descriptions into safe, correct bash one-liners with a one-line explanation."
2. **Input distribution** — what will REAL inputs look like? List 10 subtypes and rough proportions.
3. **Output contract** — exact format, length, tone. Write 5 examples *by hand*. These are your seeds and your quality bar.
4. **Failure catalog** — what does a bad output look like? These become your filters.

**Deliverable:** a `data-spec.md` with all four sections. Twenty minutes here saves days later.

---

## Stage 2 — Generate at scale (1 evening)

Two-step generation beats one-step: first synthesize diverse *inputs*, then have the teacher answer them.

```python
# Step 1: synthesize diverse prompts by remixing dimensions (self-instruct style)
import itertools, random, json

subtypes   = ["file ops", "text processing", "networking", "process mgmt", "archives"]
difficulty = ["simple", "multi-step", "edge-case heavy"]
phrasing   = ["terse", "verbose beginner", "vague"]

seeds = [{"subtype": s, "difficulty": d, "phrasing": p}
         for s, d, p in itertools.product(subtypes, difficulty, phrasing)]

GEN_PROMPT = """Write {n} distinct user requests about {subtype} shell tasks.
Difficulty: {difficulty}. The user writes in a {phrasing} style.
Output one request per line, no numbering."""
# Feed GEN_PROMPT to the teacher for each seed combo → thousands of varied inputs.
```

```python
# Step 2: teacher answers every input, constrained by your output contract
ANSWER_PROMPT = """<your output contract from data-spec.md, verbatim>

User request: {request}"""

# Serve the teacher with vLLM (Playbook 03) and batch through it:
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8000/v1", api_key="x")

def answer(request):
    r = client.chat.completions.create(
        model="teacher", temperature=0.7,
        messages=[{"role": "user", "content": ANSWER_PROMPT.format(request=request)}],
        max_tokens=400)
    return r.choices[0].message.content
```

Practical numbers: 2,000-10,000 pairs is a strong specialist dataset. On a local 70B teacher via vLLM that's an overnight run; via a 32B teacher, an evening.

**Deliverable:** `raw_pairs.jsonl` — thousands of (input, teacher_output) pairs.

---

## Stage 3 — Filter ruthlessly (the step everyone skips, the step that matters most)

Layered filters, cheapest first:

```python
# Layer 1: mechanical — format compliance, length bounds, dedupe
import json, re
from datasketch import MinHash, MinHashLSH

def mechanical_ok(x):
    return (50 < len(x["output"]) < 2000
            and x["output"].count("```") % 2 == 0        # closed code blocks
            and not re.search(r"as an ai|i cannot", x["output"], re.I))

# Layer 2: executable verification (the killer feature when outputs are code)
# Run generated bash in a container; keep only pairs whose command parses/behaves:
#   bash -n script.sh  → syntax check, zero risk
# For math/data tasks: check the answer programmatically.

# Layer 3: LLM-as-judge for the survivors
JUDGE = """Rate this response 1-5 against the contract below. A 5 is flawless.
Contract: <contract>
Request: {inp}
Response: {out}
Reply with only the digit."""
# Keep 4-5 only. Judge with a *different* model than the teacher if possible (bias).
```

Expect to keep 40-70%. If you're keeping 95%, your judge is asleep; if 10%, your generation prompt fights your contract.

**Deliverable:** `train.jsonl` (filtered) + a filter funnel table: generated → after mechanical → after verification → after judge.

---

## Stage 4 — Train, evaluate, and the on-policy loop

1. Train the student on `train.jsonl` (exactly Playbook 04 Stage 2).
2. Evaluate student vs teacher on held-out inputs — win/loss/tie by judge. A good specialist reaches 80-95% of teacher quality *on this task* at 1/20th the size.
3. **On-policy round (the pro move):** collect the student's *failures* from evaluation, have the teacher produce corrected answers for exactly those inputs, add to training data, train one more epoch. One or two rounds of this targets the student's real weaknesses instead of re-teaching what it already knows.

```
generate → filter → train → eval → harvest failures → teacher corrects → retrain
                                  └────────────── the loop ──────────────┘
```

## Iron laws
1. The spec and the filters are the product; generation is the easy part.
2. Verify executably whenever the domain allows it — a compiler is the cheapest, most honest judge.
3. Never let the teacher grade its own homework (different judge model).
4. Distill the task, not the teacher — you want a specialist, not a tiny impressionist.
5. On-policy correction of real student errors beats more random data, every time.
