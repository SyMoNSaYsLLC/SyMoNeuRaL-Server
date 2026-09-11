# ops/authority/ — the rules

```
PROJECT-AUTHORITY.md   the operating contract for this repository
GLOSSARY.md            the house vocabulary. Use these words, not synonyms
TOOL-POLICY.json       what is refused, machine-readable
START-HERE.txt         the first thing an arriving agent reads
```

**One canonical source for the rules.** Three files once claimed to describe current state
and agents kept acting on the stale one. Do not create a fourth thing here that also states
a rule.

`TOOL-POLICY.json` is enforced by `tests/structure/test_tool_policy.py`. A refusal written in
prose and not in that file is a refusal nothing checks.

`GLOSSARY.md` is not decoration. Reports use the house words because each was chosen after a
specific confusion — see `ops/architecture/README.md` for the ones that matter most.
