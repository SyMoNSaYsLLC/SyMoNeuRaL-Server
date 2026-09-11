# `archive/buildv2` — what is retained, what is offloaded, and how to get it back

Required before any removal by the spec's buildv2 section: *"Classify/offload reacquirable
third-party bulk such as Apple SDK/OSXCross/toolchain/vendor source after recording name,
version, upstream, revision, license, SHA256, Drive path, reacquire method."*

`archive/buildv2` is 5.0G. **4.99G of that is two directories**, and the first-party build
authority the spec says to keep locally is about 23M. So this is not a wholesale removal —
it is a split, and the split is lopsided.

## Retained locally (~23M) — first-party and restore authority

| Path | Size | Why it stays |
|---|---:|---|
| `native-project/` | 20M | First-party. Named explicitly for retention. |
| `evidence/` | 2.0M | Provenance and build evidence, including the protected `symoneural-toolchain-evidence.zip` (mode 0600, sha256 `8bf3e74f…40ab9` — **do not chmod 644**). |
| `scripts/` | 208K | Build recipes required for restore. |
| `src/`, `build/`, `tests/`, `fixtures/`, `fuzz/` | 672K | Source, build glue and the fixtures needed to verify. |
| `toolchains/` | 312K | Toolchain *configuration*, not toolchain binaries — 49 small files. |
| `MANIFEST.sha256` | 16K | 141 recorded hashes; the verification authority for the tree. |
| `tools/`, `docs/`, `reference/`, `CMakeLists.txt`, `Makefile`, `config.mk`, `CHANGELOG.md`, `README.md`, dotfiles | ~100K | Build definition and documentation. |
| `.local/project-native/` | 5.8M | Dependency analysis, inventory and test baselines for the retained `native-project`. Evidence about a kept thing is kept. |
| `vendor/checksums/` | 24K | **The reacquisition authority itself.** Four `.sha256` files recording every offloaded wheel and archive by exact version and hash. Offloading these would destroy the ability to verify what comes back. |

## Offloaded (4.99G) — reacquirable third-party bulk

Nothing in the repository reads these. Measured: the only references to
`buildv2/.local` or `buildv2/vendor` anywhere in the tree are two prose mentions in
`docs/history/handoffs/TOTAL-SYMONEURAL-HISTORY*.md`. No code, no recipe, no script.

| Collection | Size | Identity recorded | Reacquire |
|---|---:|---|---|
| `.local/apple/downloads` | 2.8G | `Xcode_26.6_Universal.xip`, `MacOSX26.sdk.tar.xz`, `MacOSX26.5.sdk.tar.xz` | Apple Developer downloads (account required). Versions are exact. |
| `.local/apple/target` | 860M | OSXCross build output | Rebuild from `osxcross-src` + the SDK archives. |
| `.local/apple/osxcross-src` | 636M | OSXCross source tree | Public upstream: `tpoechtrager/osxcross`. |
| `.local/apple/sdk-archives` | 110M | macOS SDK archives, versioned filenames | Extracted from the Xcode xip above. |
| `.local/ai-sdk` | 289M | Vendored AI SDK build inputs | Re-fetch per `vendor/checksums/{anthropic,openai,antigravity}.sha256`. |
| `.local/jvm` | 151M | JVM build inputs | Re-fetch per `vendor/checksums/jvm.sha256`. |
| `.local/cuda` | 1.1M | CUDA build inputs | NVIDIA public archives. |
| `vendor/jvm/gradle-9.5.1-bin.zip` | 134M | **gradle 9.5.1**, sha256 `bafc141b619ad6350fd975fc903156dd5c151998cc8b058e8c1044ab5f7b031f` | `services.gradle.org` — version and hash both recorded, so the returned file is verifiable. |
| `vendor/python/antigravity` | 53M | Wheels, each version+sha256 in `antigravity.sha256` | PyPI. |
| `vendor/python/openai` | 5.0M | Wheels, each version+sha256 in `openai.sha256` | PyPI. |
| `vendor/python/anthropic` | 4.6M | Wheels, each version+sha256 in `anthropic.sha256` | PyPI, e.g. `anthropic-1.3.0-py3-none-any.whl` sha256 `e7e7dbebf9f3c84a23954ab989378af6ae10a4d1804c81e9fea4b5ced695ce75`. |
| `vendor/{rust,go}` | 8K | Placeholder/config only | n/a |

## On licences

These are third-party artefacts under their own upstream licences. Storing them on Drive
changes nothing about that, and none of them becomes first-party by being adjacent to
first-party code. Gradle is Apache-2.0; the Python wheels carry their individual upstream
licences; the Apple SDK and Xcode remain under Apple's licence terms and are **not
redistributable** — which is a further reason they are held as a private archive and
reacquired from Apple rather than treated as project material.

## Why the checksums stay and the payload goes

The pattern throughout this reorganisation is *reacquisition, not custody*: keep the
identity, drop the bytes, and prove the identity is sufficient to get the bytes back. Here
the identity already exists in a form somebody else wrote down — four `.sha256` files with
exact versions. Keeping 24K to release 4.99G, with verification preserved, is the whole
trade.
