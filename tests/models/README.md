# tests/models/ — weights, names and provenance

Two files, and they guard the one thing on this box that git does not hold.

```
test_weight_names.py   the naming rule, the manifest, and the fetch script's promote order
test_nim_models.py     the NIM model set
```

## The rules enforced

**Nothing under `models/` keeps an upstream filename.** Language weights are `symon-1.0-*`,
everything else `symoneural-*`, and a file that appears without a `PROVENANCE.json` row
fails. A house name with no recorded origin is an unfalsifiable claim about what the bytes
are — and it is also how "does this CVE affect us" becomes unanswerable.

**`bytes_on_disk` is measured**, checked against the real file whenever it is present, so a
truncated or substituted download fails a test instead of serving quietly.

**Download, verify, promote — in that order.** Four cases are named after what goes wrong
without it, including `test_same_size_corrupt_download_is_not_promoted`: a truncated file
matching the expected byte count will load, and produce noise.

## The trap in this file

`ActiveModelParseTests` reads the **first two `llm/` entries positionally**. Appending to
`PROVENANCE.json` is safe; sorting it is not, and sorting it is what broke these tests when
the 30B-A3B was recorded.
