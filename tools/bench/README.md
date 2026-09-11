# tools/bench/ — measuring the card

Real runs. Every number in `models/docs/MODEL-BENCHMARKS.md` came from here.

```bash
python3 tools/bench/bench_maxfit.py --model models/llm/<file>   # the context ceiling
python3 tools/bench/bench_config.py --model models/llm/<file>   # sweep the argv
python3 tools/bench/bench_models.py                             # compare models
python3 tools/bench/qa_run.py                                   # is it still correct
```

`bench_maxfit.py` **overshoots and backs off** — raise `-c` until the allocation fails, then
step back to the largest that fits with headroom. Trying a list of plausible values finds a
value that works, not the ceiling.

**Fix the seed.** A token count that is not reproducible is not a measurement. And normalise
before comparing: tok/s across models with different active parameter counts is not a fair
comparison, which is how a 57% compute-efficiency difference was missed once.

The `moe_*.py` tools capture and prune expert routing. The result is **negative and
recorded** — pruning yields broken models and router healing does not fix them. Read
`models/README.md` before spending a week on it.
