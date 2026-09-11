# DispatchOS preview — archive plan

**Plan only. Nothing has been archived, committed, installed or deployed.**
Read at `main` / `3e4a4353`, 2026-08-23.

## 0. Read this before running anything

`docs/ops/EXPORTS.md` rule 1 is unambiguous: **"No whole-repo zip exports, ever. Not for
review, not for backup, not 'just this once'."** The suggested command pattern in the request —
`git archive --format=tar.gz ... HEAD` with no pathspec — is a whole-repo export, so it is
exactly the thing that rule forbids.

It is not a theoretical objection. `EXPORTS.md` was written **because this already happened**:
*"every whole-repo zip shared for review carried `training/corpus.jsonl` (the 327 hand-authored
examples) and `training/build_dataset.py`, because both are tracked and the zips were built
from tracked files."*

Measured again just now, and the condition has not changed:

| Protected artefact | Tracked? | Would a bare `git archive HEAD` include it? |
|---|---|---|
| `training/corpus.jsonl` (320,642 B) | **yes** | **yes** |
| `training/build_dataset.py` (21,899 B) | **yes** | **yes** |
| `training/adapter/` | yes — 4 config/README files | yes (the **weights** are gitignored, so those are safe) |

So the premise in the request — *"use `git archive` from committed state … that avoids
accidentally archiving secrets"* — is **half right**. It correctly excludes untracked material
(`GARRETT-REQUESTS.md`, `INTAKE.md`, `review/`, `run/`, `.env`, node_modules, `__pycache__`,
`.pytest_cache`, venvs, model weights and `/tmp` scratchpads are all untracked or ignored, so
none of them can reach a `git archive`). It does **nothing** about material that is tracked and
protected, which is the category that actually leaked last time.

The sanctioned path, `tools/export_snapshot.sh`, **does not exist** — it is still Phase 1 work.

## 1. Recommendation

**Archive the preview, not the repository.** Everything this work produced is four paths
totalling under 100 KB; a whole-repo archive is 125.5 MB across 16,279 tracked files, and
99.9% of it is unrelated to DispatchOS.

A scoped archive is smaller, is reviewable by eye, sidesteps the `EXPORTS.md` prohibition
entirely, and cannot carry the corpus because the corpus is not in the pathspec.

If Garrett genuinely wants a full-repo checkpoint, that is a different decision with a
different owner: it needs either an explicit exception to `EXPORTS.md` or
`tools/export_snapshot.sh` built first. **A git tag is the better instrument for that** — it
marks the state permanently, costs nothing, and moves no bytes off the box.

## 2. Stages

| # | Stage | When | Instrument |
|---|---|---|---|
| 1 | `pre-dispatchos-preview` | Last clean state before this work | **Tag only** — it is `3e4a4353`, today's HEAD (0 commits made) |
| 2 | `dispatchos-preview-staged` | Preview staged outside `site/`, repo Caddyfile updated, nothing installed or live | Tag + scoped archive, **after commit** |
| 3 | `dispatchos-preview-tested` | Focused tests and checks pass, before install/deploy | Tag + scoped archive — **the preferred archive point** |
| 4 | `dispatchos-preview-auth-installed` | Caddy config installed, validated, reloaded; page still not in `site/` | Tag + scoped archive |
| 5 | `dispatchos-preview-live` | Page deployed under auth; live access test confirms the password prompt; noindex / no-referrer / private footer confirmed | Tag + scoped archive |

**Stages 1 and 2 collapse into one commit.** Nothing has been committed, so
`pre-dispatchos-preview` and the parent of the staged commit are the same object. Tag stage 1
*before* committing, or it stops being distinguishable.

Stages 4 and 5 are **later, separate approvals**. They describe states that do not exist yet:
nothing is installed, nothing is reloaded, nothing is deployed.

## 3. Commands

Every archive is gated on a clean tree. `git archive` reads committed state, so a dirty tree
silently archives something other than what is on disk — the check is what makes the archive
mean what its SHA says.

```bash
cd /home/google/Symoneural

# --- gate: refuse to archive a dirty tree -------------------------------------
[ -z "$(git status --porcelain)" ] || { echo "tree is dirty — commit first"; exit 1; }

SHA=$(git rev-parse --short HEAD)
STAMP=$(date +%Y%m%d-%H%M)
STAGE=dispatchos-preview-tested          # or -staged / -auth-installed / -live
NAME=symoneural-${STAGE}-${STAMP}-${SHA}
mkdir -p archives

# --- the scoped pathspec: this work and nothing else ---------------------------
PATHS="docs/share-previews \
       docs/ops/SYMONEURAL-EMAIL-IDENTITY-POLICY.md \
       docs/ops/example-env.md \
       ops/Caddyfile"

# --- fail closed: prove no protected path is in the pathspec BEFORE writing -----
git archive --format=tar HEAD -- $PATHS \
  | tar -t \
  | grep -E 'corpus\.jsonl|build_dataset\.py|GARRETT-REQUESTS|INTAKE\.md|\.env|adapter/' \
  && { echo "UNSAFE — protected path in archive, aborting"; exit 1; }

# --- write it ------------------------------------------------------------------
git archive --format=tar.gz --prefix="${NAME}/" -o "archives/${NAME}.tar.gz" HEAD -- $PATHS
# optional, for easier sharing:
git archive --format=zip -9    --prefix="${NAME}/" -o "archives/${NAME}.zip"    HEAD -- $PATHS

# --- verify what actually landed ------------------------------------------------
tar -tzf "archives/${NAME}.tar.gz"
```

**Tags** — these cost nothing and are the right record for stages nobody needs a tarball of:

```bash
git tag -a pre-dispatchos-preview  3e4a4353 -m "last clean state before DispatchOS preview work"
git tag -a dispatchos-preview-staged   -m "preview staged outside site/; repo Caddyfile updated; nothing installed or live"
git tag -a dispatchos-preview-tested   -m "focused tests pass; not installed, not deployed"
# stages 4 and 5 tagged only when those states actually exist
git tag -n99 -l 'dispatchos-*' 'pre-dispatchos-*'
```

`archives/` must be gitignored, or the next archive contains the previous one.

## 4. Manifest

Written **beside** the archive, not inside it — committing a manifest so it lands inside the
tarball changes the SHA the manifest is describing, which is a small paradox that makes the
document wrong the moment it is right.

`archives/<NAME>.ARCHIVE-MANIFEST.txt`:

```
archive         <NAME>.tar.gz
sha256          <sha256sum of the archive>
stage           dispatchos-preview-tested
git branch      main
git commit      <full 40-char SHA>
created         <YYYY-MM-DD HH:MM ZZZ>

INCLUDED (scoped pathspec, committed state only)
  docs/share-previews/                              preview page, README, this plan
  docs/ops/SYMONEURAL-EMAIL-IDENTITY-POLICY.md      mailbox identity policy
  docs/ops/example-env.md                           placeholder env, secret values blank
  ops/Caddyfile                                     repo copy, bcrypt hashes only

EXCLUDED (deliberately, and why)
  training/corpus.jsonl, training/build_dataset.py  protected trade secret (EXPORTS.md rule 2)
  training/adapter/                                 protected
  GARRETT-REQUESTS.md, INTAKE.md                    mode 600, never committed
  review/, run/                                     untracked runtime and review state
  .env and any credential file                      never committed
  node_modules, __pycache__, .pytest_cache, venvs    untracked / ignored
  backend/models weights, references/                not in pathspec
  /tmp scratchpads, session transcripts              outside the repo entirely
  /etc/caddy/Caddyfile                               installed runtime copy, not archived

TESTS RUN            <suite: result, with the SHA each was read on>
DEPLOY STATE         nothing deployed
CADDY INSTALLED      no
CADDY RELOADED       no
PREVIEW LIVE         no
CREDENTIALS          bcrypt hashes only, in ops/Caddyfile; no plaintext anywhere

RESTORE
  tar -xzf <NAME>.tar.gz
  # scoped archive: copy paths back over a checkout of <git commit>, or read in place.
  # It is NOT a runnable repo on its own and is not meant to be.

WARNING
  No plaintext passwords are included in this archive. If one is ever found in one,
  rotate the credential at source — deleting the archive does not un-share it.
```

## 5. Exclusions, and which mechanism enforces each

| Excluded | Enforced by |
|---|---|
| Untracked: ledgers, `review/`, `run/`, `.env`, scratchpads, transcripts | `git archive` reads committed state only |
| Ignored: `node_modules`, `__pycache__`, `.pytest_cache`, venvs, model weights | never committed |
| **Tracked but protected: `corpus.jsonl`, `build_dataset.py`, `adapter/`** | **the scoped pathspec — and the `grep` guard above, which aborts rather than warns** |
| Installed `/etc/caddy/Caddyfile` | outside the repo |
| Plaintext credentials | none exist in the repo; the one generated today lives outside it, mode 600 |

The middle row is the one that matters. The other three are properties of git; that one is a
property of the pathspec, which is why the guard exists — a pathspec is easy to widen by
accident and the guard fails closed when someone does.

## 6. Timing

- **Archives wait until after commit: yes.** `git archive` cannot see uncommitted work, so an
  archive taken now would silently contain none of it.
- **The live archive waits until after deploy: yes.** Stage 5 asserts things about a running
  system; taken earlier it documents a state that does not exist.
- Tag stage 1 *before* the first commit or it becomes indistinguishable from stage 2.
- Preferred single archive point if only one is wanted: **stage 3**, `dispatchos-preview-tested`
  — the last state that is fully verified and still entirely reversible.
