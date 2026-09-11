# `ops/audits/reference/` — what upstream was, when we looked

Pinned facts about third-party material, taken at a point in time and **not maintained**.

```
UPSTREAM-PINS.tsv           which revision of each upstream we build from
VENDOR-CLASSIFICATION.md    FIRST_PARTY / SYMONEURAL_VERSION_OF / DEPENDENCY, per artefact
MODEL-STORAGE-RECORD.md     where the weights were, and how much
BUILDV2-OFFLOAD-RECORD.md   what was moved off this box, and where to
EXTERNAL-KNOWLEDGE-CATALOG.md
```

`UPSTREAM-PINS.tsv` is the one that earns its place: when a CVE lands against llama.cpp, the
question *"does that affect us"* has to be answerable in one lookup, and a `symoneural-*`
name with no recorded origin makes it unanswerable.

`VENDOR-CLASSIFICATION.md` records the line the doctrine draws: **"the SyMoNeuRaL version of
X" means we forked it and we changed it.** Where we imported it unchanged, saying so is the
doctrine working rather than an exception to it.
