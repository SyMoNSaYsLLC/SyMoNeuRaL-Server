# External knowledge catalogue — what lives on Drive, and how to find it from here

This is the **tracked, local** pointer into the Google Drive knowledge store. It is
deliberately a document and not a code path: the running server must work with Drive
unmounted, so nothing in the product may read this or depend on `/mnt/gdrive` existing.

The authoritative, generated index lives at `gdrive:INDEX.md` with `gdrive:CATALOG.tsv`,
`gdrive:MIGRATION-MAP.tsv` and `gdrive:DUPLICATES.tsv` beside it. This file is what you read
when Drive is *not* available and you need to know whether something exists before going
looking for it.

Regenerate the Drive-side files with `tools/data/drive_catalog.py build` then `upload`.

## The split, in one sentence each

**Local (`/home/google/Symoneural`)** — the running server: first-party source, the runtime
weights under house names, unique training assets, private state, and restore authority.

**Drive** — history, third-party reference, completed build output, upstream snapshots,
model originals, and personal material. Nothing the server needs to start.

**`/yocto`** — the active build workspace, and it is *itself a git repository* (11 commits,
254 tracked files, no remote). Its bundle is backed up to
`gdrive:Symoneural/Restore-Recovery/Yocto-Git`, because until that existed it was an
unprotected sole copy of first-party build authority.

## Where to look for what

| If you need… | Look at | Notes |
|---|---|---|
| Original upstream model distributions | `gdrive:Models/` | The **running** weights are local at `backend/models/` under house names. `backend/models/PROVENANCE.json` maps each house name to `upstream_repo` + `upstream_file`; 11 of 11 are re-fetchable, 9 of 11 carry a recorded sha256. |
| Old SyMoNeuRaL source snapshots | `gdrive:Symoneural/History/Source-Snapshots/` | Includes the dismembered pre-2026-08-20 repo, routed per collection. |
| Old build output and build history | `gdrive:Symoneural/History/Build-History/`, `gdrive:Build-Outputs/` | Yocto packages are keyed by architecture. |
| Pinned third-party upstream source | `gdrive:Symoneural/Upstream-Source/<project>/<revision>/` | Revision is in the path, so a snapshot is identifiable rather than merely dated. See `docs/specs/reference/UPSTREAM-PINS.tsv` for the local record of every pin. |
| Apple SDK / Xcode / OSXCross | `gdrive:Development-Reference/Apple/` | Not redistributable under Apple's terms; held as a private archive and reacquired from Apple. Identity in `docs/specs/reference/BUILDV2-OFFLOAD-RECORD.md`. |
| CUDA / NVIDIA reference | `gdrive:Development-Reference/NVIDIA-CUDA/` | TensorRT, cutlass, samples, Nsight, Blackwell GEMM kernels. |
| Toolchains and IDE installers | `gdrive:Development-Reference/Toolchains/` | Version-pinned in filenames; hashes in `archive/buildv2/vendor/checksums/`. |
| Miner / firmware / crypto | `gdrive:Projects/Crypto/`, `gdrive:Build-Outputs/Yocto/Firmware/` | cgminer trees under `Projects/Crypto/Reference-Source`. Recipes fetch upstream, so no local tree was a build source. |
| Prior UI, screenshots, task history | `gdrive:Symoneural/History/Screenshots-and-UI-History/`, `…/Task-and-Terminal-History/`, `…/Agent-Sessions/` | |
| VM and host setup | `gdrive:Virtualization/`, `gdrive:Development-Reference/Linux-System/Host-Setup/` | |
| Archived projects by domain | `gdrive:Projects/Archived/` plus the domain collections | |
| Whole-machine backups | `gdrive:Historical-Archive/Machine-Backups/` | The three largest single objects anywhere: 73 GB, 70 GB, 34 GB. |
| Network configs and credentials | `gdrive:Private/` | Filed by path and metadata only. Values are never printed, logged or catalogued. |
| Something inspected but genuinely unclassifiable | `gdrive:Historical-Archive/Unclassified-Reviewed/<date>/` | Catalogued, which is what distinguishes it from a folder called `misc`. |

## Two conventions that will otherwise confuse you

**Large collections travel as one archive per semantic leaf, each beside a
`.CONTENTS.tsv`.** `/yocto/artifacts` is 105,851 files and the Drive mount runs at eight
requests per second, so uploading it file-by-file would spend hours on API calls before any
bytes moved. It therefore became six objects keyed by architecture — which is also what
"preserve architecture/package-manager layout" means. The sibling manifest records `TYPE`,
`RELPATH`, `SIZE_BYTES`, `SHA256`, `MODE` and `LINK_TARGET` for every entry, so you can see
inside an archive without downloading it, and dedupe can compare content instead of
guessing from filenames. Symlinks are recorded by target, never followed.

**Drive permits two folders with the same name at the same path.** This bit us: a top-level
rename reported success with eight objects verified while a twin of the same name still sat
at the root holding seven more. If a collection looks half-moved, check for a twin before
concluding the move failed.

## What Drive is *not*

It is not a backup of the running server, and it is not on the restore critical path for
starting the service. The restore authority is `restore/` plus
`.private/git-backup/Symoneural-all.bundle`. Drive holds the things you would want *after*
the server is running again: the history, the reference material, and the originals of
things that were renamed.
