# Home-directory consolidation — 2026-09-08

The project lived in a repository *and* in about thirty loose directories beside it. This
records what moved where, why, and what deliberately did not move. It is the map to read
before looking for something that used to be in `/home/google`.

## The three destinations, and the rule that picks one

| Destination | Tracked? | Rule |
|---|---|---|
| `docs/` | **yes** | First-party writing: decisions, rulings, manifests, diagnostics. Small. |
| `references/` | no (`.gitignore:68`) | Somebody else's code or a saved document. Read-only. The standing owner rule quoted in `tools/lib/index_references.py` is *"we cannot use code in references its for reference only we must rebrand if we want to use it"*. |
| `archive/` | no | Bulk that is neither: workspace archives, backups, build outputs, weight staging, session transcripts, evidence trees. |

Nothing needed inventing. `references/` and the `incoming/` adoption path already existed,
with `incoming/*/PROVENANCE.md` tracked and the copied tree not — which is exactly the
"record the provenance, not the payload" shape this consolidation needed.

## What moved

**Into `references/`** — `oss/` (46 upstream trees: linux, llvm, chromium, openssl, nginx,
mongo, mysql…), `TensorRT-LLM`, `ComfyUI-Installs`, `ComfyUI-Shared`, `bentoml`,
`ninjatraining`, `Toolchains`, `Platforms`, `symoneural_tbd`, and the vendor agent material.
`references/ComfyUI-Shared` had been a symlink out to `/home/google`; it is now the real tree.

**Into `archive/`** — 253 GB of workspace archives, 16 GB of backups, 4.4 GB of build
outputs, 3.2 GB of source candidates, the model and LoRA weight staging directories, the
2026-09-02 never-deployed build evidence (both worktrees moved with `git worktree move`, so
their metadata is intact), the session transcripts, and the project material that was living
on the Desktop — including `symoneural-buildv2`, the native ELF auditor that found the
hardening gaps fixed at `941d756d`.

**Into `docs/`** — the 24 SymonSaysLLC decision records, the 37-file handoff chain, the
LoRA restoration manifest, the host diagnostic dump, the 2026-09-03 home cleanup audit, and
`RAVENCALC.docx`, which had been a Word document unzipped in place under a `.md` name.

## What did not move, and why

- **`training/` protected artefacts** were never in scope. `ops/docs/EXPORTS.md` rule 2.
- **`Symoneuraltree.md`** — a 101 MB filesystem listing that had been sitting in the handoff
  directory. It names `training/corpus.jsonl` and `training/build_dataset.py`. Committing it
  would have put the protected inventory in history permanently. Quarantined to
  `archive/tree-dumps/`, caught by the grep `EXPORTS.md` publishes as its own acceptance check.
- **`symoneural-cutover-rollback-20260826-154113`** and **`AI_PURGE_PSEUDOFS`** — both are
  root-owned and could not be moved by this user. The first holds a live credential file and
  is better left where it is than worked around. Recorded rather than forced.
- **Personal material in `Desktop/` and `Downloads/`** — resumes, screenshots, unrelated
  tooling. A work repository is not the place for it, and the 2026-09-03 audit already
  classified PERSONAL separately. Only `symon*`-matching project material was taken from the
  Desktop; `Downloads/` (34 GB, 408 entries) has not been swept and needs a classified pass.

## Cost

Zero disk. Every move was a same-filesystem rename: 618 GB used before, 618 GB after. The
repository directory is larger; the repository is not, because `references/` and `archive/`
are both ignored.

## What this does not do

It consolidates. It does not make anything first-party — see `ProjectStatus.md` for the
runtime position, and the handoff of this date for the licence wall that stops the fifth
engine from following the other four.
