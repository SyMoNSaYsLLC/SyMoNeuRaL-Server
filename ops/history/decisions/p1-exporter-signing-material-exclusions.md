# P1 COMPLETE — exporter refuses signing material by path and by content

> **REDACTED.** Customer names, credential filenames, security tooling names, internal ports
> and infrastructure-posture details are masked or referred to by role. **No key material
> appears in this file or in the repository** — all fixtures are synthetic armor headers.
> Unredacted detail is on the box.

**Date:** 2026-09-02 · **HEAD:** `bb9230f4` · **Repo:** `/home/google/Symoneural`
**Nature:** implementation + tests. **P1 only.**

## Continues from

Previous handoff: `d11-decided-pre-key-prerequisites.md` (2026-09-02), HEAD `5063b480`, which
recorded the D-11 ruling and characterized P1/P2/P3. This window implements **P1 only**.

| Control point | At `5063b480` | Now at `bb9230f4` |
|---|---|---|
| HEAD | `5063b480` | `bb9230f4` |
| Exporter path patterns | **17** | **22** (+5 P1-a) |
| Content inspection | **none** | **stage 2b, 3 patterns** |
| Exporter test count | 7 | **22** (7 A-2 + 15 P1) |
| Signing keys on box | 0 | **0 — none generated** |
| Signed artifacts | 0 | **0** |
| A-4 | COMPLETE 19/19 | **unchanged** |
| Tracked mods | `ops/registry/EXPORTS.md` | `ops/registry/EXPORTS.md` — untouched |

## Why this had to land before the key ceremony

Measured 2026-09-02 against the then-live 17 patterns — every one of these **passed stage 2**:

```
ops/keys/release.asc              .gnupg/pubring.kbx        ops/release.gpg
ops/release.minisig               ops/signing/release_ed25519 (+ .pub)
```

Harmless only because zero keys existed. Generating a key first would have opened a window in
which the private half was exportable. P1 is therefore a **prerequisite of** the key ceremony,
not a follow-up to it.

## What was implemented

### P1-a — five path/name patterns (17 → 22), with five index-parallel labels

| Pattern | Class |
|---|---|
| `\.kbx$` | GPG keybox |
| `(^\|/)private-keys-v1\.d/` | GPG private key store |
| `(^\|/)\.gnupg/` | GPG home directory |
| `\.minisig$` | minisign material |
| `(^\|/)ops/(keys\|signing)/` | release custody directory — **refuses by LOCATION** |

The last one means an innocuously-named file in a custody directory is still refused; the test
uses `notes.txt` with innocuous contents to prove location alone is sufficient.

**Added a startup array-parity check.** Stage 2 indexes `PROTECTED_LABELS[$i]` under `set -u`,
so a pattern without a matching label is an "unbound variable" crash **at the exact moment the
script must work — while refusing**. Measured: 22 patterns / 22 labels, 3 content patterns /
3 labels.

### P1-b — new stage 2b: content inspection

**An addition in kind, not another pattern.** Everything else in stage 2 matches a *path*;
this matches *bytes*.

Why content and not name: `gpg --export-secret-keys --armor` writes `.asc` (must never leave),
and `scripts/build-apt-repo.sh:105` writes a **publishable** keyring to `.asc` as well. A
blanket `.asc` suffix rule would refuse the public key a recipient needs to verify anything.
Content is also the **only** rule that reaches an **extensionless** private key.

Patterns: `BEGIN <any> PRIVATE KEY BLOCK` · `BEGIN OPENSSH PRIVATE KEY` ·
`BEGIN <any> PRIVATE KEY`.

**Three grep outcomes, all handled — this is the part that fails silently if built the obvious
way:**

```
rc 0  matched      -> refuse, naming the class and path (never the bytes)
rc 1  clean miss   -> continue
rc >=2 ERROR       -> refuse as "uninspectable candidate"
```

`if grep -q ...; then refuse; fi` treats an unreadable file as a clean miss and **exports it
uninspected**. An inspection that could not run has **not** passed — the same rule already
written into `authz.py` for entitlement. Verified on this host, where **`grep` is `ugrep 7.8.4`,
not GNU grep**: unreadable → `rc 2`, clean miss → `rc 1`, match → `rc 0`. Assumed nothing.

`LC_ALL=C grep -qaE`, byte-oriented so a **leading NUL** cannot turn a private key into
"binary file, skipped". **No byte cap:** a cap is not an optimisation, it is the bypass — pad
past it and the key ships. `grep -q` short-circuits on first match, so an uncapped scan is
cheap. The large-file test puts the header **~4 MB in, after the padding**, so it fails if
anyone later adds `head -c`.

### P1-c — no exporter change needed; the test is the guard

Public armor is `BEGIN PGP PUBLIC KEY BLOCK`, which none of the private patterns match — so
the carve-out works without a special case. That makes the positive test's entire job to
**fail loudly if someone later adds a blanket `.asc` prohibition**, which is why it asserts
archive contents rather than being a comment asking people not to.

## Verification — all 16 required rows

| Required demonstration | Test | Result |
|---|---|---|
| existing exporter tests | `ExportSnapshotTests` (7) | **PASS** |
| existing private-material exclusions | `test_protected_path_is_refused` | **PASS** |
| `.kbx` refusal | `test_p1a_kbx_keybox_refused` | **PASS** |
| `private-keys-v1.d` refusal | `test_p1a_private_keys_v1d_refused` | **PASS** |
| `.gnupg` refusal | `test_p1a_gnupg_home_refused` | **PASS** |
| `.minisig` refusal | `test_p1a_minisig_refused` | **PASS** |
| `ops/keys` refusal | `test_p1a_ops_keys_dir_refused` | **PASS** |
| `ops/signing` refusal | `test_p1a_ops_signing_dir_refused` | **PASS** |
| armored private-key content refusal | `test_p1b_armored_pgp_private_key_content_refused` | **PASS** |
| OpenSSH private-key content refusal | `test_p1b_openssh_private_key_content_refused` | **PASS** |
| generic private-key content refusal | `test_p1b_generic_pem_private_key_content_refused` | **PASS** |
| extension-independent detection | `test_p1b_detection_is_extension_independent` (5 names) | **PASS** |
| binary/leading-NUL resistance | `test_p1b_leading_nul_does_not_bypass` | **PASS** |
| large-file case | `test_p1b_large_file_does_not_bypass` (~4 MB) | **PASS** |
| public armored `.asc` export | `test_p1c_public_armored_keyring_is_exportable` | **PASS** |
| refusal creates no archive | asserted in **every** refusal via `_refused()` | **PASS** |

Plus two beyond the required set: `test_p1b_uninspectable_candidate_is_refused` (the grep-error
branch) and `test_p1_inspects_only_manifested_candidates` (scope).

**Commands:**
```
python3 -m pytest backend/apps/test_export_snapshot.py -q                 -> 22 passed
python3 -m pytest ...::ExportSnapshotTests -q                             ->  7 passed
python3 -m pytest ...::P1SigningMaterialExclusionTests -v                 -> 15 passed
```

### Proven by sabotage, not by a green run

Reverting the exporter to `5063b480` and re-running: **13 of 15 P1 tests FAIL.** The 2 that
pass either way are `test_p1c` (asserts behaviour P1 must **preserve**) and the positive half
of the scope test. A test that passes before the implementation proves nothing — this is the
`models-finetune.sh` lesson, where any non-zero exit satisfied the assertion.

### Scope — a refusal control, not a repository scanner

Stage 2b iterates the **same `CANDIDATES` array stage 1 built**, so a file no manifest names is
**never opened**. This is a property of the loop, not a claim.
`test_p1_inspects_only_manifested_candidates` plants a private key at an **unmanifested** path
and asserts export succeeds — then names it and asserts refusal, proving the pass was scope
rather than a blind spot.

### Regression on the real customer manifest

The real 7-entry manifest still passes **both** stages under `--dry-run`, no archive written.
The new content inspection does not reject legitimate application source.

## Errors / notes from this window

1. **Subclassing inflated the count.** My P1 class initially extended `ExportSnapshotTests` to
   reuse `setUp`, which re-ran all 7 A-2 tests under the subclass and reported **29** while
   meaning **22**. Fixed by splitting the fixture into a `_ExporterFixture` mixin. A pass count
   that overstates coverage is a reporting defect, not a cosmetic one.
2. **My first array-parity check was wrong** — an `awk` range over the file counted the P1-b
   label block too, reporting 22 vs 23. Re-measured by sourcing the actual declarations: 22/22.
   Same shape as earlier mis-measurements: parse the artifact, don't eyeball a range.
3. One `SyntaxWarning` from `\.` inside a docstring; fixed, now compiles clean under
   `-W error::SyntaxWarning`.

**Consequence worth carrying forward:** because detection is content-based, any manifested file
that merely **quotes** a private-key header now refuses. That is correct fail-closed behaviour,
and it means documentation containing those strings must never be manifested. The new test file
contains them and is not in any manifest.

## Still open from earlier

- **P2 — non-forgeable release identity: NOT implemented.** Two fail-closed cases remain,
  including the live one: the exporter copies from the **working tree** but labels with
  `git rev-parse HEAD`, so a modified manifested file ships content not matching its stated
  `source-sha`. This tree has carried ` M ops/registry/EXPORTS.md` throughout; the 7-entry manifest
  happens not to overlap it — luck, not a guarantee.
- **P3 — public-key distribution: NOT implemented, nothing published.** Recommendation stands:
  `site/release-key.txt` + fingerprint out-of-band.
- **Key ceremony: NOT performed.** Separately authorized; P1 landing is what unblocks it.
- **External release: NOT authorized.** D-12 separate and unimplemented.
- **`ops/registry/EXPORTS.md`** remains modified-and-unstaged; verified unstaged at this commit.
  Note prerequisite item 9 will eventually add a signing rule there — on its own authorization.

## Verification — measured

```
HEAD                     bb9230f4
git status --short        M ops/registry/EXPORTS.md   (pre-existing, untouched, never staged)
git diff --cached         tools/data/export_snapshot.sh, backend/apps/test_export_snapshot.py
EXPORTS.md staged        0        Sept1.md staged   0
tests                    22 passed (7 A-2 + 15 P1)
sabotage check           13/15 P1 tests fail against pre-P1 exporter
path patterns            17 -> 22   labels 22   (parity asserted at startup)
content patterns         3          labels  3
secret keys on box       0        public keys        0
archives produced        0        artifacts signed   0
tags created/signed      0        custody records    none
real key material in repo  none   base64 key bodies  0
A-4                      COMPLETE, 19/19 (untouched)
```

## To resume

```
repo   /home/google/Symoneural
HEAD   bb9230f4   [P1] export_snapshot.sh: refuse signing material by path and by content
prev   5063b480   [D-11] record owner ruling as controlling signing architecture
git status --short:
 M ops/registry/EXPORTS.md
```

Next authorization, in the recorded order: **P3 channel confirmation**, then **P2**
(refuse `UNKNOWN` + refuse working-tree drift, signed release tags), then the **key ceremony**.
Each requires its own authorization; none is started.

# P1 COMPLETE — COMMITTED CHECKPOINT bb9230f4
