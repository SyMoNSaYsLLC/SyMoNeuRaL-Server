# scripts/model-staging/ — swapping the model a live surface loads

One script. It is the highest-consequence change on this box: the weights are ~50 GB, the
active default is four lines in `backend/core/config.py`, and **git records neither**.

```bash
symoneural-model-stage.sh --dry-run            # say what each mode would do; change nothing
symoneural-model-stage.sh --inventory          # what is on disk vs models/PROVENANCE.json
symoneural-model-stage.sh --smoke-plan         # what a smoke run would do
symoneural-model-stage.sh --stage-<name>       # prepare a directory; print, do not fetch
symoneural-model-stage.sh --smoke-candidate    # run the candidate in isolation
symoneural-model-stage.sh --activate-candidate # promote it. Refuses on six conditions
symoneural-model-stage.sh --rollback           # the only one safe to reach for in a hurry
```

## The rule it exists to enforce

**Nothing is downloaded, activated, moved or deleted without an explicit flag.** The first
four modes are read-only. `--stage-*` prepares and prints the download command but does not
run it without the confirmation phrase. `--activate-candidate` refuses on six separate
conditions. Every mode is safe to run on a live box.

`--rollback` restores `backend/core/config.py` from the backup written at promotion time.

## It runs from anywhere now

It used to be `ROOT="$(pwd)"` behind a refusal, so the most consequential script here worked
only if you happened to be standing in the repository root — and it had already moved a
level deeper into this directory by then. It sources `../lib/repo.sh`, which walks up for
`backend/server.py`. Proven by running `--inventory` from `/tmp`.

Read `models/README.md` before using any mode that writes.
