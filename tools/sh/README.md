# tools/sh/ — forks, restores and cleanup

```
fork_engines.sh        produce the SyMoNeuRaL build of an upstream engine
fork_render_ui.sh      the same for the render UI
restore-upstream.sh    put an upstream tree back at its pinned revision
cleanup-pipeline.sh    the tree cleanup, v1
cleanup-pipeline-v2.sh v2
```

## fork_engines.sh executes the doctrine

Three buckets, and nothing may stay unclassified:

| bucket | meaning | what it carries |
|---|---|---|
| `FIRST_PARTY` | written here | the SyMoNeuRaL licence header |
| `SYMONEURAL_VERSION_OF` | forked, modified, renamed | our header **and** upstream copyright, licence text, the fork revision, and a statement of what we changed |
| `DEPENDENCY` | imported unchanged | upstream notice carried; **our name does not go on it** |

*"The SyMoNeuRaL version of X"* means **we forked it and we changed it**. Where we did not,
saying so is the doctrine working, not an exception to it. `symoneural-web` is 146 lines of
first-party Go that **imports** Caddy as a library — it is not a fork, and calling it one
would be a false authorship claim.

A `symoneural-*` directory name is a **runtime or build identity, not a claim of
authorship**. Three such directories contain upstream source under its own licence. They are
deliberately not renamed: naming and copyright ownership are separate questions, and renaming
a tree to satisfy a licensing assumption would destroy the provenance the record exists to
keep.

See `LICENSES.md` and `ops/audits/LICENSE-AUDIT.md`.
