# models/licenses/ — the upstream licence text for every weight

One file per upstream artefact. **These are not ours and this directory never carries the
SyMoNeuRaL licence.**

## Why the text and not a reference

Apache-2.0 §4(a) obliges the licence to travel with a redistributed work, and **renaming is
redistribution**. Every weight here carries a house name — `symon-1.0-*` — and the rename is
exactly the act the licence has terms about. A table row asserting Apache-2.0 while no text
ships is the obligation restated, not met.

A licence that does not name its licensor is not a licence, which is why this directory is
exempt from the house-naming rule and the filenames keep the upstream names.

## Adding one

When you add a weight, drop its upstream licence here and point `license_text` at it from
that weight's `models/PROVENANCE.json` row. `tests/models/test_weight_names.py` checks the
file exists.

`scripts/fetch-models.sh` fetches these automatically and **says so when it cannot** —
a missing licence does not stop a build, but it is never silent.
