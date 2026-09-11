# D-11 CUSTODY PRINCIPAL DECIDED — dedicated non-login release-custody UID

> **REDACTED.** Service names, credential filenames, internal ports, hostnames and web-root
> paths are masked or referred to by role. **No key material exists; none was created.** No
> account name is recorded. Unredacted detail is on the box in `Sept1.md` §22.3b.

**Date:** 2026-09-02 · **HEAD:** `4108bef4` · **Previous HEAD:** `1f6b3ca9`
**Repo:** `/home/google/Symoneural` · **Nature:** architecture/decision recording only.

## Continues from

Previous handoff: `d11-key-ceremony-blocked-custody-preconditions.md` (2026-09-02), which
stopped the ceremony at the gate with two blockers. This window resolves **Blocker 1 only**.
**Blocker 2 (offline media topology) remains open and was deliberately not decided.**

| Control point | At `1f6b3ca9` (prev) | Now at `4108bef4` |
|---|---|---|
| HEAD | `1f6b3ca9` | `4108bef4` |
| Blocker 1 — custody principal | **OPEN** | **DECIDED** |
| Blocker 2 — offline media | OPEN | **still OPEN** (untouched) |
| D-11 release authority | NOT ESTABLISHED | **NOT ESTABLISHED** |
| Secret signing keys | 0 | **0** |
| System accounts created | — | **0** |
| Tracked mods | `ops/registry/EXPORTS.md` | `ops/registry/EXPORTS.md` — untouched |

## The ruling

| | |
|---|---|
| **Custody principal** | **DEDICATED NON-LOGIN RELEASE-CUSTODY UID** |
| **Service-readability** | **literal byte non-readability required** |
| **Operator access** | **explicit identity/elevation transition, per operation** |
| **Passphrase** | **defense in depth only** — same-UID byte readability is insufficient |

Distinct from: operator UID, API/service UID, web-service UID, gateway/runtime identities,
build-service identities, customer/application identities. Its sole purpose is owning protected
D-11 release-signing custody — **not** a general application account, **not** an interactive
login identity.

**Recorded explicitly:** *passphrase-protected but same-UID-readable **DOES NOT** satisfy D-11
custody separation.* A passphrase makes material cryptographically *unusable*; the requirement
is that service processes cannot *read the bytes at all*.

## Synthetic DAC separation proof

No secret material. The final custody directory was **not** created.

| Case | Posture | uid-1000 read | Verdict |
|---|---|---|---|
| A | dir owned by **uid 1000**, mode `700` — *today* | **YES** | **fails** — the API runs as uid 1000 |
| B | dir owned by a **different uid**, mode `700` | **DENIED** | **satisfies the invariant** |
| C | dir owned by a different uid, mode `755` | **YES** | ownership alone is insufficient |

Case C is why the mode is part of the ruling rather than an implementation detail — a
differently-owned but world-readable directory provides no separation at all.

**Measured identities:** API service `User=google`/`Group=google`, `ProtectHome=no`,
`InaccessiblePaths=` empty, `PrivateUsers=no`. Operator `uid=1000(google)`.

## Minimum safe principal characteristics

| Property | Ruling | Why |
|---|---|---|
| Account class | **system account, UID < 1000** | `UID_MIN=1000` here, so a system UID is outside the regular-user range; 43 such accounts already exist |
| Login shell | **`nologin`** | matches existing service-account convention |
| Password state | **locked, no password login** | never authenticated *to*, only transitioned *into* |
| Custody root | **outside the operator home and outside the repository** | the operator home is precisely what `ProtectHome=no` exposes to the service |
| Primary group | **own dedicated group** | no shared group surface |
| Supplementary groups | **none** | no application/service group membership |
| Service memberships | **none — no service may run under this UID** | it owns custody; it does not run software |
| Interactive login | **no** | |
| sudo capability | **none granted to it** | the transition flows operator → custody, never outward |
| Ownership | custody dirs and all private material owned by **the custody principal only** | |
| Directory mode | **`0700`**; private key files **`0600`** | see Case C |
| umask | **set explicitly at creation — do NOT inherit** | operator umask measured **`0002`** (group-writable); inheriting it would create group-writable custody |
| GnuPG home | **`0700`, custody-owned, and a FRESH home** | **not** the default GnuPG home, which is currently mode **755** and not custody-grade |

**No extra privilege invented. No account name recorded as final** — naming belongs to the
account-creation authorization.

## Operator access model

| Option | Assessment |
|---|---|
| **`sudo -u <custody-principal> …`** | **RECOMMENDED** — smallest viable mechanism: explicit, per-operation, auditable, and needs **no policy expansion**, since the operator is already in the `sudo` group |
| `su`-style transition | Same effect, worse ergonomics and weaker logging |
| Dedicated wrapper | Reasonable later convenience; adds a component to review, so not the minimum |
| **Group-readable custody** | **REJECTED** |

**Why ordinary same-UID access is rejected:** any arrangement making the material directly
readable by the operator's UID also makes it readable by the API, **because they are the same
UID**. At the DAC layer, operator convenience is indistinguishable from service exposure. So the
architecture favours **explicit elevation per custody operation** over broadening key-file
permissions.

## Privilege bridges — identified, NOT repaired under this authorization

| Bridge | Finding | Consequence |
|---|---|---|
| **`gpg-agent` socket** | a `gpg-agent` is **already running as uid 1000**, sockets under the uid-1000 runtime dir, owned by the operator | **REAL BRIDGE.** If custody ever used the operator's agent, a same-UID service process could reach the socket and **request signing operations without reading key bytes** — defeating the invariant by a route other than file reads. The custody principal must run its **own** agent under its own runtime dir; the operator's agent must never hold the release subkey |
| **ACLs** | `getfacl` present; the filesystem is ext4 **without `noacl`**, so ACLs are honoured | An ACL could silently re-grant uid 1000 access to a correctly-owned `0700` directory. Custody must be verified **ACL-free**, not merely mode-checked |
| **Operator `sudo`** | operator is in the `sudo` group | **By design** — this *is* the §4 transition. Stated so the guarantee is not overclaimed: **custody separation protects against SERVICES, not against the operator** |
| **umask** | operator umask `0002` | group-writable by default; custody mode must be explicit |
| **Service delegation** | API unit `SupplementaryGroups=` and `ReadWritePaths=` both empty | no delegation bridge from the unit itself |
| **setuid helpers** | 15 setuid binaries in the standard bin dir | not custody-specific; noted for completeness, not audited system-wide |

The `gpg-agent` finding is the one that changes future implementation: it is a **use**-path
bridge rather than a **read**-path bridge, and a correct `0700` custody directory alone would
not have closed it.

## GnuPG operational boundary (future state — nothing created)

```
offline PRIMARY secret         -> removable/offline custody, NOT resident in routine signing
                                  custody                        (Blocker 2, still open)
release SIGNING-SUBKEY secret  -> owned by the DEDICATED CUSTODY PRINCIPAL, 0700/0600, in a
                                  custody-owned GnuPG home outside the repo and outside the
                                  operator home
custody principal's gpg-agent  -> its OWN agent and runtime dir; never the operator's agent
operator                       -> may invoke an explicitly authorized signing operation via
                                  `sudo -u <custody-principal>`, per operation
application/runtime services   -> CANNOT read signing-subkey bytes (different UID, mode 0700,
                                  no ACL, no shared group, no agent-socket access)
```

## §10 return

| Item | Value |
|---|---|
| HEAD | `4108bef4` |
| Previous HEAD | `1f6b3ca9` |
| Commit subject | `[D-11] Sept1.md: custody principal decided - dedicated non-login release-custody UID` |
| Files changed | **`Sept1.md` only** — `+112`, pure insertion (new §22.3b) |
| `git status --short` | ` M ops/registry/EXPORTS.md` |
| `git diff --cached --name-only` | `Sept1.md` (at commit time); EXPORTS.md staged **0** |
| Custody-principal ruling | **DEDICATED NON-LOGIN RELEASE-CUSTODY UID** |
| Recommended account class | **system account, UID < 1000** |
| Login-shell policy | **`nologin`** |
| Password/login policy | **locked; no password login; no interactive login** |
| Group-membership policy | **own dedicated group; no supplementary groups; no service memberships** |
| Custody-dir ownership | **custody principal only** |
| Custody-dir mode | **`0700`** (key files `0600`), set **explicitly** at creation |
| GnuPG-home ownership/mode | **custody principal, `0700`**, fresh home (not the default) |
| Operator transition | **`sudo -u <custody-principal>`**, per operation |
| Why same-UID access rejected | operator UID **==** API service UID, so operator-readable **is** service-readable |
| Synthetic DAC result | **A YES (fails) · B DENIED (satisfies) · C YES (mode matters)** |
| Service UID | **`google`, uid 1000** |
| Operator UID | **`google`, uid 1000** — *identical, which is the whole problem* |
| Privilege bridges | **gpg-agent socket (real)**, ACLs honoured, operator sudo (by design), umask `0002` |
| `ops/registry/EXPORTS.md` | **untouched and unstaged** |
| System account created | **NO** |
| Custody directory created | **NO** |
| sudo policy changed | **NO** |
| Service changed / restarted | **NO / NO** (no `daemon-reload`) |
| GnuPG material created | **NO** |
| Key generated | **NO** |
| Fingerprint created | **NO** |
| Public key published | **NO** |
| Artifact signed | **NO** |
| Release tag signed | **NO** |
| External release | **NOT AUTHORIZED** |

**Exporter suite:** 43 passed (7 A-2 + 15 P1 + 21 P2) — unaffected by a documentation-only
change. **Staged-diff secret scan:** 0 private-key blocks, 0 secret-export artifacts.

## Current state

```
P1                        COMPLETE
P2                        COMPLETE
P3                        CHANNEL CONFIRMED (key not published)
D-11 CUSTODY PRINCIPAL    DECIDED - dedicated non-login release-custody UID
D-11 RELEASE AUTHORITY    NOT ESTABLISHED

Blocker 1  service UID co-tenancy   RESOLVED (architecture)
Blocker 2  offline custody media    OPEN - not decided in this task

secret signing keys 0 · public signing keys 0 · fingerprints 0
release key published NO · signed release tags 0 · signed artifacts 0
customer archives 0 · external release NOT AUTHORIZED
```

## To resume — each its own authorization

1. **Blocker 2** — provision offline custody media, plus an owner ruling on **copy count and
   media topology**. Minimum safe: 2 separated copies, revocation certificate held apart.
2. **Custody-principal implementation** — create the system account, custody root and GnuPG
   home per §22.3b, including the **custody-owned `gpg-agent`** and an **ACL-free verification**
   step. This is where the account naming decision gets made.
3. **Re-run the ceremony gate**, then the ceremony itself.
4. **Post-ceremony §9 verification** — prove the real custody path cannot enter the
   customer-export path. P1's location patterns already refuse `ops/keys/` and `ops/signing/`,
   so once the custody class is fixed this is a short follow-on.

Still separately gated after that: public-key publication (P3-1, never hand-placed in the web
root), signed release tags (P2 mechanism), release-record signing, external release.

```
repo   /home/google/Symoneural
HEAD   4108bef4   [D-11] custody principal decided
prev   1f6b3ca9   [P2] non-forgeable release identity
git status --short:
 M ops/registry/EXPORTS.md
```

# D-11 CUSTODY PRINCIPAL DECIDED — DEDICATED NON-LOGIN RELEASE-CUSTODY UID
