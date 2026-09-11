# P3 CHANNEL CONFIRMED — public-key distribution (P3-1 + P3-4)

> **REDACTED.** Customer names, credential filenames, security tooling names, internal ports,
> public hostnames and web-root paths are masked or referred to by role. **No key material, no
> fingerprint, and no key exists** — nothing was generated or published. Unredacted detail is on
> the box.

**Date:** 2026-09-02 · **HEAD:** `d73b74af` · **Repo:** `/home/google/Symoneural`
**Nature:** evidence-and-decision task. Documentation only.

## Continues from

Previous handoff: `p1-exporter-signing-material-exclusions.md` (2026-09-02), HEAD `bb9230f4`,
which implemented P1. This window confirms the **P3 channel only** — no P2, no key ceremony.

| Control point | At `bb9230f4` | Now at `d73b74af` |
|---|---|---|
| HEAD | `bb9230f4` | `d73b74af` |
| P3 | recommendation | **CHANNEL CONFIRMED — P3-1 + P3-4** |
| P1 exporter + tests | committed | **byte-identical**, 22 tests green |
| Signing keys | 0 | **0** |
| Fingerprints | 0 | **0** |
| Keys published | 0 | **0** |
| Tracked mods | `docs/ops/EXPORTS.md` | `docs/ops/EXPORTS.md` — untouched |

## What CHANNEL CONFIRMED means, and what it does not

Four separate states. Confirming the channel reaches **none** of the other three:

| State | Now |
|---|---|
| **CHANNEL CONFIRMED** | **YES** — this window |
| KEY PUBLISHED | **NO** |
| KEY GENERATED | **NO** |
| KEY CEREMONY PERFORMED | **NO** |
| RELEASE AUTHORIZED | **NO** |

## 1. Web publication path — re-measured with file:line evidence

Measured from the current tree, not carried over from the prior report.

| Question | Answer | Evidence |
|---|---|---|
| Which script publishes `site/`? | **`scripts/deploy.sh`** — sole authority | `deploy.sh:39` `SRC="$ROOT/site"` |
| Destination class | **local filesystem web root**, `install`ed `www-data:www-data` mode `644` | `deploy.sh:40`, `deploy.sh:76` |
| `txt` permitted? | **YES** | `deploy.sh:61` allow-list contains `txt`; verified by matching the candidate path against the live regex, not by reading it |
| `asc` permitted? | **NO** | same line — `asc` absent. A `.asc` in `site/` is reported `skipped: not a web asset` (`deploy.sh:62,65-67`) |
| Depth-limited? | **YES — `-maxdepth 1`** | `deploy.sh:75`, the only install action |
| Nested `.well-known/` publish? | **NO** | no recursive copy anywhere in the script; exactly one install action, which flattens into the destination |
| Unlinked top-level `.txt` retained? | **YES** | `deploy.sh:104` — retention is `[ -f "$SRC/$f" ]` **plus** extension match; **zero** link references in the orphan block |
| Source-page link required? | **NO** | the reference check (`deploy.sh:135,244`) iterates `src=`/`href=` **found in HTML** and asserts each resolves on disk. It never asserts that a published file *is* referenced — so an unreferenced key file is never examined and cannot fail a deploy |

### New finding — a second publication trigger, and an operational precondition

`scripts/build-deb.sh` postinst **republishes the web root on `apt upgrade`**. My prior report
named only `deploy.sh`, so this is genuinely new. It resolves safely: build-deb implements **no
publication logic of its own** — it **delegates to `deploy.sh --prune`** (`build-deb.sh:181` +
postinst). One allow-list therefore governs both paths.

But the consequence is load-bearing. Because line 104's retention test keys on presence in the
**source** tree, a key file **hand-placed directly into the web root** and absent from `site/` is
an **orphan** — and `--prune` **deletes it on the next `apt upgrade`**. A file tracked at
`site/release-key.txt` survives both triggers.

**Precondition recorded: the key must live in `site/` and must never be hand-placed in the web
root.** Doing so would produce a key that silently disappears at the next package upgrade — the
worst failure mode for a verification channel, because the release chain would break long after
anyone connected it to an upgrade.

## 2. `site/release-key.txt` viability

**CONFIRMED VIABLE with zero deployment-script change.** `.txt` is in the allow-list, the file
sits at depth 1, retention does not require a linking page, and the reference check runs in the
opposite direction. Both publication triggers honour the same rules.

**The file was NOT created.** Confirmed **viable, not present** — no file, no sample, no
fabricated key.

**P1/P3 collision check** (P1 landed *after* the P3 section was first written, so this needed
testing rather than assuming): against the live committed patterns, `site/release-key.txt`
matches **none** of the 22 P1-a path patterns, and `-----BEGIN PGP PUBLIC KEY BLOCK-----` matches
**none** of the 3 P1-b content patterns. **No collision** — the public key remains both
exportable and publishable, which is exactly what P1-c was written to protect.

## 3. Alternatives re-evaluated against the current tree

| Option | Works unchanged? | Needs impl? | External trust service? | Distributes key? | Authenticates fingerprint? | Role |
|---|---|---|---|---|---|---|
| **P3-1** `site/release-key.txt` | **YES** | no | **no** | **yes** | **no** | **PRIMARY key channel** |
| **P3-2** add `asc` to allow-list | no | **yes** (`deploy.sh`) | no | yes | no | deferred cleanup, own authorization |
| **P3-3** public keyserver | no | yes | **YES** | yes | no | **rejected as primary** |
| **P3-4** out-of-band fingerprint | **YES** (business process) | no | no | no (fingerprint only) | **YES** | **PRIMARY fingerprint channel** |

No new architecture introduced — the measured evidence did not invalidate any recorded option.

**Neither confirmed path is sufficient alone.** P3-1 distributes a key but authenticates nothing;
P3-4 authenticates a fingerprint but distributes no key. **Possession of a public key downloaded
from the project site is NOT authentication by itself.**

## 4. Two-channel trust model — confirmed

```
offline certify-only PRIMARY            (C-2 custody, never on the serving host)
        | certifies
        v
release-signing SUBKEY
        | signs
        v
release artifacts / signed release record
        | verified using
        v
public key from project-controlled HTTPS publication   (P3-1)
        +
40-hex PRIMARY fingerprint obtained independently      (P3-4, MANDATORY comparison)
```

**P3-1 + P3-4 still satisfies the D-11 requirement.**

**The guarantee, stated no more strongly than the evidence supports.** Compromise of the web host
permits **replacement of the downloadable public-key file**. It does **not**, absent compromise
of the **offline primary**, permit creation of a new subkey certification that chains to the
primary fingerprint a recipient already holds independently.

**That protection is conditional on the recipient actually performing the fingerprint check.** A
recipient who downloads the key and skips the comparison is defeated by web-host compromise
alone, because nothing else in the chain would object. **The fingerprint comparison is therefore
MANDATORY in the eventual recipient verification procedure, not advisory** — it is the step that
makes the two-channel model load-bearing rather than decorative. This is the honest limit of the
claim, and it is now recorded as a requirement on the procedure rather than an assumption about
recipient diligence.

## 5. Repository boundary

One file changed: **`Sept1.md` §22.3** — the P3 block, which previously read as a
*recommendation*, now records the confirmed ruling plus the build-deb finding and the
`--prune` precondition. `+76 / -10`.

**Verified untouched and byte-identical:** `tools/data/export_snapshot.sh`,
`backend/apps/test_export_snapshot.py` (**P1 byte-identical**; 22 tests re-run, all pass),
`docs/ops/EXPORTS.md` (unstaged, `EXPORTS.md staged: 0`), `site/`, `scripts/deploy.sh`, git
signing configuration, service and runtime configuration, release feeds, customer manifests.

## Errors / notes from this window

1. **My prior P3 report named only one publisher.** Five scripts referenced `site/`; I checked
   each rather than stopping at `deploy.sh`, which surfaced the `build-deb.sh` upgrade trigger.
   It resolved safely (delegation, not duplication) — but had build-deb implemented its own copy
   logic with different rules, the recorded recommendation would have been wrong.
2. **I tested allow-list membership and orphan retention programmatically** against the live
   regex and the real line-104 condition, rather than reading the pattern and concluding. The
   earlier `-maxdepth 4` `/yocto` mis-measurement is why.

## Still open from earlier

- **P2 — NOT implemented.** Two fail-closed cases remain, including the live one: the exporter
  copies from the **working tree** but labels with `git rev-parse HEAD`, so a modified manifested
  file ships content not matching its stated `source-sha`. This tree has carried
  ` M docs/ops/EXPORTS.md` throughout; the 7-entry manifest happens not to overlap it.
- **Key ceremony — NOT performed.** P1 and P3 are now both settled, which clears two of the three
  recorded pre-key prerequisites; **P2 remains**.
- **External release NOT authorized.** D-12 separate and unimplemented.
- **`docs/ops/EXPORTS.md`** still modified-and-unstaged; prerequisite item 9 will eventually add
  a signing rule there, on its own authorization.

## Verification — measured

```
HEAD                        d73b74af
git status --short           M docs/ops/EXPORTS.md   (pre-existing, untouched, unstaged)
staged at commit            Sept1.md only        EXPORTS.md staged: 0
P1 exporter / tests         byte-identical vs bb9230f4; 22 passed
site/ and deploy.sh         unchanged
secret keys on box          0        public signing keys on box   0
fingerprints created        0        keys published               0
site/release-key.txt        absent   *.asc in site/               0
signed tags                 0        signed artifacts             0
git signing config          0 entries
external release            NOT authorized
```

## To resume

```
repo   /home/google/Symoneural
HEAD   d73b74af   [P3] confirm public-key distribution channel (P3-1 + P3-4)
prev   bb9230f4   [P1] refuse signing material by path and by content
git status --short:
 M docs/ops/EXPORTS.md
```

Next authorization: **P2** — exporter refuses `source-sha: UNKNOWN` **and** refuses working-tree
drift; adopt signed release tags (`tag.gpgsign`, not `commit.gpgsign`). After P2, the **key
ceremony** becomes the next gate, separately authorized.

# P3 CHANNEL CONFIRMED — P3-1 + P3-4
