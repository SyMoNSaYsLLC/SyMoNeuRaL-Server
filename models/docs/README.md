# models/docs/ — benchmarks, registry and provenance

What was measured about the weights, and where each one came from.

```
MODEL-BENCHMARKS.md            tok/s, VRAM headroom, context ceilings. Measured, dated
MODEL-REGISTRY.md              every model this box knows about
MODEL-LICENSES.md              per-model terms -- several restrict commercial use
SYMONEURAL-MODEL-BUNDLES.md    which weights ship together
PROVENANCE.md                  the prose beside models/PROVENANCE.json
OPENAI-GPT-OSS-MIGRATION.md    the gpt-oss evaluation and what it concluded
VLLM-BENCH-PARITY.md           vLLM vs this engine, on the same weights
SYMON-AI-CHATBOT-COST-RUNTIME-STUDY.md
```

## Reading a figure here

Every one carries the date and the command that produced it. The card is
**memory-bandwidth bound** — memory clock pins at 100% while power sits at 76% — so a
throughput number is only comparable against another taken with the same argv, and tok/s
across models with different active parameter counts is not a fair comparison at all.

The authoritative machine-readable record is `models/PROVENANCE.json`, one directory up.
These documents are the reading; the manifest is the record.
