# ops/registry/ — the current state of how this box serves

**Regenerated, never edited by hand.** Every file here is a rendering of a machine-readable
record, and the record is the authority.

| rendering | generated from | by |
|---|---|---|
| `PORTS.md` | `ops/PORTS.tsv` | `tools/build/build_ports.py` |
| `RUNTIMES.md` | `ops/RUNTIMES.tsv` | `tools/build/build_runtimes.py` |
| `SERVING-MANIFEST.md` | the running service | `tools/build/build_serving_manifest.py` |
| `SBOM.md` | the installed package set | `tools/lib/dependency_inventory.py` |
| `MEASUREMENTS.md` | the test suites, with the commit each count was read on | by hand, dated |

The rest — `SERVING-PATH.md`, `EXPORTS.md`, `MAINTENANCE-SURFACES.md`, `BUILD-BOUNDARY.md`,
`example-env.md`, `integration-sources.md`, `upgrading.md` — are written, but they describe
**what is true now** and are corrected when it changes. That is what separates this directory
from `ops/audits/`.

## The distinction that matters

```
ops/registry/   what is true NOW.      Wrong => fix it.
ops/audits/     what was true THEN.    Wrong => it was already wrong when taken; leave it.
```

A dated finding does not belong here even if it is still accurate, and a current record does
not belong in `audits/` even if it was first written on a particular day. The two were mixed
in one flat directory of 97 files and nobody could tell which kind they were reading.

## Regenerating

```bash
python3 tools/build/build_ports.py        # then run it AGAIN and diff
python3 tools/build/build_runtimes.py
```

**Run every generator twice and diff.** These re-read their own output, and one that does not
recognise something it emits accumulates it — one copy per run. That has happened three times
in this repository.

## Reading a figure here

Every number must carry the commit it was measured on. This project has published a test
count that was never true of the commit beside it, because somebody carried it forward and
re-dated it. **A figure with no SHA is the one thing to be suspicious of.** Re-measure
anything you are about to rely on; `MEASUREMENTS.md` carries the commands.

Never hand-edit a `.md` in this directory that the table above calls generated. Edit the TSV.
