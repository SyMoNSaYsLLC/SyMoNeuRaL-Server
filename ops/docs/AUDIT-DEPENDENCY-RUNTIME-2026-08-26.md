# Dependency, runtime, and shipping audit — 2026-08-26

Inputs: `backend/DEPENDENCIES.md`, `ops/docs/RUNTIME-PROFILES.md`, every first-party
requirements/pyproject/Cargo/package manifest in the tracked tree, a Python AST import
inventory, runtime path references, Git's tracked-file list, and the Debian package builder.

This audit distinguishes three things that are easy to blur together:

- a **host reading** says what was installed or built on one machine at one time;
- a **declaration/lock** says what a clean environment can reproduce;
- a **portable artifact** says what this repository or package actually carries.

## Findings

### 1. The dependency ledger is a dated host snapshot, not a current install contract

The ledger says its versions were read on 2026-08-21 at `f3ed5ab`. Current declarations
have since moved:

| Area | Ledger | Current declaration |
|---|---|---|
| Remix FastAPI | 0.115.11 serving snapshot | `fastapi>=0.136` |
| Remix Uvicorn | 0.32.0 serving snapshot | `uvicorn>=0.51` |
| Remix python-dotenv | 1.0.1 | `python-dotenv>=1.2` (pyproject says measured 1.2.2) |
| Reinforce NumPy | 2.2.4 | `numpy>=2.3.2` |
| Crypto miner psutil | ledger says 7.0.0 | requirement pins `psutil==5.9.8` |

None of these differences proves which wheel is installed on the live host. They prove the
ledger cannot be used as the install source of truth. The declarations and their actual
environment must be reconciled deliberately.

### 2. Training has imports and measured versions, but no tracked declaration or lock

Production training code imports `torch`, `transformers`, `peft`, `datasets`,
`bitsandbytes`, and `safetensors`. The ledger names a measured training environment, but
`training/` has no `requirements.txt`, `pyproject.toml`, `uv.lock`, or `poetry.lock`.

Do not synthesize a lock from this scratch archive and do not touch the protected corpus or
dataset builder. Capture the actual training environment on the authorized host, review the
CUDA/PyTorch index and platform markers, then commit the resulting declaration separately.

### 3. Several toolchains are real but absent from the dependency ledger

The tracked repository has reproducible locks for:

- the Rust gateway (`backend/apps/gateway/Cargo.lock`);
- the Tauri desktop client (`desktop-client/src-tauri/Cargo.lock`);
- browser verification (`tests/package-lock.json`, Playwright 1.56.1).

It also has the dependency-free `yocto/oematch` Python project and 15,209 tracked files of
adopted SDK/reference source under `backend/vendor/`. Those are separate toolchains or
reference inputs; treating the Python ledger as a complete bill of materials misses them.

### 4. The documented engine maturity is a host claim, not portable repo state

In this uploaded HEAD archive all four sanctioned runtime homes are absent:

```text
engines/symoneural-llm
engines/symoneural-diffuse
engines/symoneural-ui
engines/symoneural-listen
```

The `references/` build inputs are absent too. Existing fork scripts explain how the first
three host trees are derived, but they cannot reproduce anything from this archive alone.
Therefore “built” in `RUNTIME-PROFILES.md` must remain labelled as a dated host reading;
it is not evidence that a clone or `.deb` contains those runtimes.

### 5. ASR still points at the path its own runtime contract bans

The runtime contract reserves `engines/symoneural-listen/`, but all current executable
paths still target `contrib/whisper.cpp`:

- `backend/apps/voice/asr.py`;
- `backend/apps/sigils/listen.py`;
- `scripts/fetch-whisper.sh`.

The source/binary is absent here, so changing only the paths would not make ASR work. The
complete fix is a reproducible `symoneural-listen` fork/build with provenance, renamed
artifacts, licences, hashes, and tests, followed by the three path changes. Until that
exists, the honest runtime level is `absent`.

### 6. The main Debian payload was including non-production source

`scripts/build-deb.sh` previously selected every tracked path except secrets and a few
repository mechanics. `backend/vendor/` alone contributes 15,209 tracked SDK/reference
files, and the payload also admitted tests, the non-live Bento experiment, separate
desktop/Yocto source packages, and review/import staging.

The builder now excludes those paths from the main runtime `.deb` without deleting them
from Git. `scripts/build-deb.sh --list` previews the exact payload without building; the
current tracked HEAD produces 775 paths and retains the API, CLI, deploy script, and site.
Seven package/leak mutation tests pass against the new boundary.

## Repeatable audit commands

```bash
# Read-only manifest, AST import, lock, engine-home and ASR-path inventory.
python3 tools/audit/audit_runtime_dependencies.py
python3 tools/audit/audit_runtime_dependencies.py --json

# Exact production payload; does not build or write a .deb.
scripts/build-deb.sh --list

# Existing engine helpers. These require host-only reference inputs and should fail loudly
# in this portable archive rather than inventing binaries.
tools/sh/fork_engines.sh all
tools/sh/fork_render_ui.sh --verify
```

## Recommended order for the next runtime pass

1. Capture and review a real training declaration/lock from the authorized training venv.
2. Decide whether the crypto miner requirement or its measured 7.0.0 environment is the
   intended baseline; make the file and ledger agree.
3. Add a machine-readable runtime artifact manifest: runtime id, source revision, licence,
   build command, output path, SHA-256, architecture, and maturity reading.
4. Implement `symoneural-listen` as one complete fork/build/path/test change. Do not revive
   `contrib/whisper.cpp` and do not copy a quarantined reference binary into production.
5. Build the `.deb` only after `--list` review; package engine binaries separately because
   they are architecture/driver-specific and intentionally absent from the `Architecture:
   all` source package.

The audit helper is intentionally non-mutating. “Clean shipping” here means controlling
the produced artifact, not deleting useful tests, SDK references, or source projects from
the development repository.
