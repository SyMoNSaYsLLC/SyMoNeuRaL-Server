# P2 COMPLETE — non-forgeable release identity

> **REDACTED.** Customer names, credential filenames, security tooling names, internal ports,
> public hostnames and web-root paths are masked or referred to by role. **No key material, no
> fingerprint, no signed tag, and no key exists.** Unredacted detail is on the box.

**Date:** 2026-09-02 · **HEAD:** `1f6b3ca9` · **Previous HEAD:** `d73b74af`
**Repo:** `/home/google/Symoneural`

## Continues from

Previous handoff: `p3-channel-confirmed-public-key-distribution.md` (2026-09-02), HEAD
`d73b74af`. P2 was the **last recorded prerequisite** before a separately authorized key
ceremony.

| Control point | At `d73b74af` | Now at `1f6b3ca9` |
|---|---|---|
| HEAD | `d73b74af` | `1f6b3ca9` |
| P1 | COMPLETE | **COMPLETE**, 15 tests green |
| P3 | CHANNEL CONFIRMED | **unchanged**, key not published |
| **P2** | not implemented | **COMPLETE** |
| Exporter stages | 1, 2, 2b | **1, 2, 2b, 3** |
| Exporter test count | 22 | **43** (7 A-2 + 15 P1 + 21 P2) |
| Signing keys / fingerprints | 0 / 0 | **0 / 0** |
| Tracked mods | `ops/docs/EXPORTS.md` | `ops/docs/EXPORTS.md` — untouched |

## The two forgeries P2 closes

An archive states a `source-sha`. Before P2, **that statement could be false in two ways**, and
neither was checked.

**1. The SHA might not resolve.** `git rev-parse HEAD 2>/dev/null || echo UNKNOWN` wrote the
literal `UNKNOWN` and carried on. Signing that yields a *valid signature over an unidentifiable
release* — worse than an unsigned archive, because it looks authoritative.

**2. The bytes might not match the SHA.** The exporter copies from the **working tree** but
labels with **HEAD**. A modified candidate ships content the stated commit never contained —
and a recipient **cannot detect it**: the per-file checksums match the manifest, and the
manifest names a real commit.

## What was implemented

### P2-a — refuse unresolved release identity (exporter stage 3)

`git rev-parse --verify HEAD`, refuse on failure. No substitute accepted: not a branch name,
timestamp, tree hash, or "dirty". It resolves to a commit or the export stops. `UNKNOWN` now
appears **only in explanatory comments** — asserted by a test that scans the script for the
string outside comment lines.

Also refuses when `--root` is **not the repository top level**: `HEAD:<path>` and `diff-index`
resolve against the repo root, not `--root`, so a subdirectory root would silently compare the
**wrong paths**. Refused rather than compared incorrectly.

### P2-b — refuse manifested working-tree drift

**Authority: git object identity**, via `git diff-index HEAD -- <path>`. Not mtime, not size,
not timestamps. Verified against a throwaway repository **before** choosing the primitive:

| Drift class | `diff-index` |
|---|---|
| content changed | **detected** |
| **mode only** (`100644`↔`100755`), content identical | **detected** |
| deletion | **detected** |
| **type** drift (regular ↔ symlink, mode `120000`) | **detected** |
| **untracked path** | **NOT detected — reads as clean** |

`git hash-object` was **rejected as the primitive**: without `--path` it does not apply clean
filters (this tree has `.gitattributes` under `backend/vendor/`), and on a symlink it **follows
the link** and hashes the target, while git stores the link *target string* as the blob.

**The untracked hole, and why it mattered.** Stage 1 expands a manifested *directory* into its
files, so an uncommitted file inside a named directory becomes a candidate — and would ship
under a `source-sha` that never contained it. That is exactly the forgery P2-b exists to stop.
Each candidate is therefore **also** probed with `git cat-file -e "HEAD:$path"`, with all three
exit branches handled: present → compare, absent → refuse, **error → refuse**. A check that
could not run has not passed.

**Invariant proved, stated no more strongly:** *candidate content, file mode and object type
match HEAD as git records them.* **Not** a claim of post-filter byte-identity on disk. Without
`git update-index --refresh`, a stat-only change can be reported as modified — that direction
is conservative (refuses a possibly-identical file), so it is accepted rather than worked
around.

**Explicitly NOT a clean-working-tree requirement.** Only manifested candidates are checked.
The repository intentionally carries an unrelated modified file the customer manifest does not
name; a dedicated test asserts an unmanifested dirty file does **not** refuse, and the real
manifest was confirmed passing with the tree dirty.

### P2-c — signed release-tag binding, deliberately outside the exporter

New tool: `tools/audit/verify_release_identity.sh`.

**Why separate.** The exporter must stay runnable with **zero keys** — its allow-list,
protected-class, P1 and P2 refusals are controls that must work *today*, on this box. Folding
tag verification in would **invert the dependency**, so that a missing key began *disabling*
protections rather than blocking a release. This matches §22.4 item 6 ("a separate signer
invoked after the exporter, never inside it").

**Two mandatory conditions, checked independently:**

```
signed release tag
      | signature verifies against the authorized release key     <- condition 1
      v
tag resolves to a commit SHA
      | that SHA == the archive manifest's source-sha             <- condition 2
      v
release identity verified
```

"The tag verified" is **never** allowed to imply "the tag points at this release" — reusing a
genuinely signed tag to bless an archive built from another commit is a real attack shape, and
it is refused even when the signature check passes.

**No key exists**, so the verifier is **injected** via `SYMONEURAL_TAG_VERIFY_CMD` (default
`git verify-tag`). The future key ceremony supplies the real authority by making that default
usable — **no redesign of P2 required**.

> Named `SYM_TAG_VERIFY_CMD` when this ruling was written, before the `SYMONEURAL_` rename.
> Both spellings are kept here on purpose: the original so the record still matches what was
> decided, the current one because that is the name a reader should actually set today. The
> `SYM_` spelling is deprecated and will stop being read.

## Sabotage — three prongs, each measured

Green tests alone prove nothing. Each prong was run against the pre-P2 implementation.

**Prong 1 — unresolved identity reached the old acceptance path.**
```
PRE-P2, non-git root :  exit 0, ARCHIVE WRITTEN, "source-sha: UNKNOWN"
POST-P2, same root   :  REFUSED "release identity unresolved", no archive
```

**Prong 2 — drift evaded release identity. This is the clearest one.**
```
PRE-P2 :  archive CLAIMS   source-sha e4e1809f...  (a real commit)
          archive CONTAINS "FORGED CONTENT NEVER COMMITTED"
          that commit HAS  "committed content"
          -> archive labelled with a commit that never held those bytes; exit 0
POST-P2:  DRIFT [differs from HEAD] deliverable/a.txt -> REFUSED, no archive
```

**Prong 3 — tag/source identity was not cryptographically bound.**
```
PRE-P2 :  no verification path existed at all; tag and source-sha unrelated
POST-P2:  authentic signature + WRONG commit -> REFUSED on SHA mismatch
          bad signature      + right commit -> REFUSED on signature
          both conditions hold              -> VERIFIED
```

## Tests — 43 total

```
python3 -m pytest backend/apps/test_export_snapshot.py -q                      -> 43 passed
  ::ExportSnapshotTests            (A-2)                                       ->  7 passed
  ::P1SigningMaterialExclusionTests                                            -> 15 passed
  ::P2ReleaseIdentityTests                                                     -> 21 passed
```

Every required demonstration row is covered, plus: repo-with-no-commits, subdirectory root,
untracked candidate, deletion, mode-only drift, symlink type drift, dry-run coverage,
refusal-precedes-staging, both-conditions-independent, and exporter-runs-with-no-key.

**P1 was not weakened.** 14 of 15 P1 tests still refuse on **P1 grounds**, because stages 2 and
2b run *before* stage 3. Private material still refused, public armored material still
exportable, inspection still manifest-scoped.

### Fixture rework, and three test corrections

The fixture had to become a **real throwaway git repo** (`git init` inside `mktemp`, never
inside this repository, committed with explicit identity and `gpgsign=false`). Required twice
over: drift is defined against HEAD, and unresolved identity is now a hard refusal — the old
plain-`mktemp` root would have broken 4 existing tests. **I re-baselined at 22 immediately
after the fixture change, before touching the exporter,** to separate fixture breakage from P2
breakage.

Three tests then failed. **None was fixed by relaxing the exporter:**

1. **`test_p1c_public_armored_keyring_is_exportable`** — its fixture was written but never
   committed, so P2-b correctly refused it as untracked. Leaving it uncommitted would have
   turned a P1-c test into an accidental P2-b test. Fixed by committing the fixture.
2. **Deletion test** — named the parent *directory*, so stage 1 expanded it, the deleted file
   simply wasn't among the results, and the rest exported cleanly. The deletion never became a
   candidate. Fixed by naming the file directly.
3. **Symlink test** — same shape, plus it pointed outside the fixture. Fixed by naming the file
   and targeting a path inside the fixture.

## Real customer-manifest regression

```
stage 1 : 7 file(s) selected by manifest
stage 2 : 0 protected paths -- passed
stage 2b: 7 candidate(s) content-inspected -- no private key material
stage 3 : release identity d73b74af...; 7 candidate(s) correspond to HEAD
dry run -- no archive written                                   exit 0
```

**No drift in the real manifest.** The unrelated dirty unmanifested file did **not** cause
refusal — it is not among the 7 candidates. P2 checks run **before** the dry-run exit, so
`--dry-run` genuinely exercises them (asserted by its own test).

## Still open

- **Key ceremony — NOT performed.** P1, P3 and P2 now settle **all three** recorded pre-key
  prerequisites. The ceremony is the next gate and requires its own explicit authorization.
- **External release NOT authorized.** D-11 architecture is decided; permission to ship is a
  separate decision, along with per-archive production authorization, export-scope
  re-confirmation, licence/provenance terms, and a recipient verification procedure.
- **D-12** separate and unimplemented.
- **`ops/docs/EXPORTS.md`** still modified-and-unstaged; the eventual signing-rule addition is
  its own authorization.

## Verification — measured

```
HEAD                       1f6b3ca9      previous HEAD  d73b74af
git status --short          M ops/docs/EXPORTS.md   (pre-existing, untouched, unstaged)
git diff --cached           Sept1.md, backend/apps/test_export_snapshot.py,
                           tools/data/export_snapshot.sh, tools/audit/verify_release_identity.sh
EXPORTS.md staged          0
tests                      43 passed (7 + 15 + 21)
sabotage                   3 of 3 prongs demonstrated against the pre-P2 implementation
secret keys on box         0      public signing keys on box   0
fingerprints created       0      site/release-key.txt         absent
signed tags created        0      signed artifacts created     0
archives created           0      git signing config           0 entries
site/ deploy.sh build-deb  unchanged
external release           NOT AUTHORIZED
```

## To resume

```
repo   /home/google/Symoneural
HEAD   1f6b3ca9   [P2] non-forgeable release identity
prev   d73b74af   [P3] confirm public-key distribution channel
git status --short:
 M ops/docs/EXPORTS.md
```

State: **P1 COMPLETE · P3 CHANNEL CONFIRMED · P2 COMPLETE.** All three pre-key prerequisites
are settled. The **key ceremony** is next and needs a new explicit authorization: primary
offline, signing subkey, revocation certificate, 40-hex fingerprint recorded, expiry set,
custody media provisioned — reporting only *that* it succeeded plus fingerprint, location
class, ownership and mode, never key material.

# P2 COMPLETE — NON-FORGEABLE RELEASE IDENTITY
