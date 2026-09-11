# The `/yocto` boundary: build there, never depend on it at runtime

**Written 2026-08-26.** Garrett stated the rule in one sentence and it is the whole of this
document:

> **The rule is not "never touch `/yocto`." The rule is: build from `/yocto` when
> appropriate, but never require `/yocto` at runtime.**

An earlier reading of "do not use `/yocto`" would have thrown away a working extensible SDK,
a BitBake workspace, 21 GB of sstate and 18 GB of downloads. That is not what was asked.

---

## Two directories, and only one of them is deleted

| path | status |
|---|---|
| `/home/google/yocto` | **PERMANENTLY DELETED.** Never recreate it, never reference it. `ops/deploy/verify-runtime.sh` fails if it reappears, because `mkdir -p` in a careless script is exactly how it would. |
| `/yocto` (top-level mount) | **Authorized build environment.** A different thing entirely. |

## What `/yocto` may be used for — ALLOWED

- Sourcing the extensible SDK environment.
- Its compiler, linker, sysroot, headers, libraries, `devtool`, BitBake, recipes, build
  caches, downloads and sstate.
- Compiling and packaging native software.
- **Reading** existing source and model artifacts as migration inputs.
- Temporary build and staging output.
- Build logs and CMake/BitBake metadata that contain build-time `/yocto` paths. **These are
  fine.** A `CMakeCache.txt` naming the directory it was configured in is a record, not a
  dependency.

Existing `/yocto` artifacts are **not** modified, moved or deleted without separate
authorization. The chat model was *copied out* as a read-only source; the original is
untouched.

## What may never depend on `/yocto` — FORBIDDEN AT RUNTIME

After installation, no live component may reach `/yocto` through:

- systemd `WorkingDirectory`, `ExecStart`, `ExecStartPre`, `ExecStartPost`, or environment;
- shebangs, wrapper scripts, config files, Python imports, `PYTHONPATH`, module search paths;
- executable, model, plugin, library, asset, database, log or state paths;
- symlinks, hardlinks, bind mounts, overlay mounts, working-tree indirection;
- ELF interpreter, `RPATH`, `RUNPATH`, an unresolved dependency, loader config, plugin search;
- process cwd, argv, environment, open file descriptors, mapped files;
- Caddy configuration or boot-time deployment behaviour.

## Why the check inspects the system and not the repository

`ops/deploy/verify-runtime.sh` deliberately does **not** grep this repository for `/yocto`. The
`yocto/` layer directory, the BitBake recipes and the build docs all contain that string
legitimately, and a check that goes red on them is a check people learn to skip. It inspects
the running system and the installable artifacts instead — units, processes, ELF headers,
Python paths, mounts, boot behaviour.

`backend/apps/test_runtime_boundary.py` covers the half that needs no root: the **unit
templates**, because a template with `/yocto` baked in is a live dependency on the next
install, on this box or any other.

---

## Component classification, decided from evidence

The three layers are kept distinct, because conflating them is how a GGUF ends up described
as "compiled for the GPU":

| layer | what it is | how it is validated |
|---|---|---|
| Python modules (`backend/`, `guide_ask_model`, the DispatchOS adapters) | application and orchestration code | Python 3.13 test suites. **Not** compiled hardware drivers. |
| `symon-1.0-7b-q4_k_m.gguf` | **weight data** | manifest: size, SHA-256, GGUF version, architecture, identity, file type. Never compiled, never renamed from another model. |
| `symoneural-llm` | the **native inference engine** — the component that must be built and linked for this host and GPU | ELF/ABI/CUDA-target inspection |

### The SDK targets aarch64, so it cannot build the Debian host artifacts

Read from the SDK's own `…toolchain-0.1.0.testdata.json`, not assumed:

    SDK_SYS                    x86_64-oesdk-linux      the machine that RUNS the compiler
    TARGET_SYS                 aarch64-oe-linux        what it COMPILES FOR
    TARGET_ARCH                aarch64
    MACHINE                    symoneural-arm64
    TCLIBC                     glibc
    SDKPATH                    /usr/local/oe-sdk-hardcoded-buildpath

The live host is `x86_64-linux-gnu`, Debian 13.6. **"Both are x86-64" is the trap**: the SDK
is x86-64 on the *host* side and aarch64 on the *target* side, and the target side is what
lands in a binary. So this is case 2 of the component decision — the SDK builds artifacts for
a separate SyMoNeuRaL image, and every Debian-host artifact comes from a separate reproducible
native build of the same canonical source.

No SDK is currently installed on this box: `OECORE_NATIVE_SYSROOT` and `SDKTARGETSYSROOT` are
both unset, and nothing exists under `/opt/poky*`.

### Native Debian toolchain, verified present

    cargo   1.97.1        rustc  1.97.1 (host x86_64-unknown-linux-gnu)
    cc/c++  Debian 14.2.0 nvcc   13.3 (V13.3.73)      cmake 3.31.6

---

## Machine baseline — audited 2026-08-26, and this supersedes earlier figures

| item | value |
|---|---|
| OS | Debian 13.6 Trixie |
| Architecture | AMD64 / x86-64 |
| Kernel | 6.12.105+deb13-amd64 |
| Python | 3.13.5 (`cpython-313-x86_64-linux-gnu`) |
| GPU | NVIDIA GeForce RTX 5070 Ti, 16303 MiB |
| Compute capability | 12.0 |
| NVIDIA driver | **610.57.04** |
| CUDA toolkit | **13.3** |
| Engine CUDA target | `sm_120a` (`CMAKE_CUDA_ARCHITECTURES=120`) |
| Execution | **GPU only. No CPU fallback.** |

Two figures were previously carried as 590.48.01 and CUDA 13.1. Both were wrong; the values
above were read off the box. This project's standing rule applies — re-measure rather than
re-date.

---

## Canonical runtime paths

| what | path |
|---|---|
| Repository / runtime root | `/home/google/Symoneural` |
| Models | `/home/google/Symoneural/backend/models` |
| Chat model | `/home/google/Symoneural/backend/models/llm/symon-1.0-7b-q4_k_m.gguf` |
| **Inference engine** | `/home/google/Symoneural/engines/symoneural-llm/build/bin/symoneural-llm` |
| Gateway | `/home/google/Symoneural/backend/apps/gateway/target/release/symon-gateway` |
| Deploy script | `/home/google/Symoneural/scripts/deploy.sh` |
| Webroot (published to) | `/var/www/symoneural` |

**The engine is at `engines/`, NOT `backend/engines/`.** `backend/server.py:183` computes
`LLM_ENGINE = ROOT / "engines" / …`. An instruction naming `backend/engines/` for the native
engine is wrong and is corrected wherever it appears.

Note the collision: `.claude/HANDOVER.md` discusses a *planned Python adapter package* also
called `backend/engines/` (`llamacpp.py`, `sdcpp.py`, "behind ONE interface"). That is a
different thing from the native engine binary and those references are correct as written.
When reading either, check whether the subject is a Python module or an ELF executable.

---

## The coded path — no step here is a manual command

| script | what it does |
|---|---|
| `ops/deploy/build-gateway.sh` | native Debian build of the gateway from canonical source; writes `ops/manifests/gateway-build.json` |
| `ops/deploy/install-runtime.sh` | idempotent install/migration: preflight, backup, atomic install, `daemon-reload`, controlled restart, health checks, **automatic rollback on failure**, then runs the verifier. `--dry-run`, `--no-restart`. |
| `ops/deploy/rollback-runtime.sh` | restore a backup by hand later. `--list`, `--dry-run`. |
| `ops/deploy/verify-runtime.sh` | proves the runtime boundary against the live system. Exit 1 on any violation. |
| `ops/manifests/llm-chat-model.json` | model identity, so an uncommitted weight file is verifiable |
| `backend/apps/test_runtime_boundary.py` | fails if a template or installed unit reintroduces `/yocto` |

Nothing in production depends on a command that exists only in somebody's shell history.
