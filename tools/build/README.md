# tools/build/ — generators

Read a record, write a rendering. Never the other way round, and never by hand.

Every one takes `--check`, which fails instead of writing. That is the CI form.

**Run each twice and diff.** They re-read their own output; one that does not recognise what
it emits accumulates it, one copy per run. Three separate generators in this repository have
had that bug.

`build_component_readmes.py` writes only between its markers and never touches a line
outside them — the factual half of a component README is a reading of the tree and the
schema, the reason it exists is not.
