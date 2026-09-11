# tools/data/ — storage and Drive tooling

**These point at `/home/google/Symoneural` — the OLD tree — on purpose.** That is what they
operate on. They are the record of a storage migration, not a facility this server uses.

Do not "fix" those paths to point here. A tool that was written to reorganise another
directory does not become correct by being aimed at this one.

```
storage_reorg.py             the reorganisation itself
storage_reorg_supervisor.py  drives it, resumable
storage_final_report.py      what moved, what did not, and why
drive_catalog.py             what is on the Drive
drive-dedupe.py              what is on it twice
sym_drive_reorg.py
export_snapshot.sh           what may leave this box -- read ops/registry/EXPORTS.md first
offload-to-drive.sh  upstream-to-drive.sh  run_storage_preflight.sh
```

**The storage run is held.** No resume, no supervisor, no rclone. `.private/storage-reorg/`
and `.private/offload-ledger.tsv` are not touched by anything here without the owner saying
so, and nothing in this directory should be run casually — several of them move tens of
gigabytes.

Before any byte leaves this box, read `ops/registry/EXPORTS.md`.
