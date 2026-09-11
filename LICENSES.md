# What this project is made of, and what each piece obliges

**720 components**, measured at `6aaa84d 2026-09-11`. This file is generated from `ops/LICENSES.tsv` by `tools/build/build_licenses.py`; the TSV is generated from the disk by `tools/audit/license_inventory.py`. **Do not hand-edit either** — re-run them.

The reason it is generated: a licence inventory typed by hand is wrong within a week, and every figure here has to be something a person can re-measure rather than trust.

## The short answer

| Class | Components | What it obliges |
|---|---:|---|
| copyleft | 1 | can oblige us to publish source of whatever it is combined with, **if we distribute that combination** |
| weak-copyleft | 6 | oblige us to publish changes *to that component*, not to our own code beside it |
| UNKNOWN | 107 | not yet measured. Unknown is not the same as absent, and it is not the same as safe |
| proprietary | 43 | read the terms; some forbid redistribution outright |
| permissive | 563 | attribution, and nothing else |

**One copyleft component in 720** — the ComfyUI fork, and it is not distributed. Everything else that ships is permissive or ours. The 107 unmeasured rows are the open work, and they are listed in full below rather than summarised away.

## By party

**"Party" here means provenance — who wrote the code — which is the sense `docs/DOCTRINE-NAMING-AND-CREDIT.md` already uses.** In contract language "second party" usually means the counterparty you signed with, which is a different question: *who could sue us, under what instrument*. That question is answered by the **Who could enforce** column rather than by the party label, so both readings come off the same table. If the contract sense is the one wanted for the label, say so and the generator can carry both.

### First party — 4 components

**First party** — we wrote it. Ours to licence as we choose.

| Component | Licence | Class | Carried | Who could enforce | Where |
|---|---|---|---|---|---|
| `SyMoNeuRaL API + surfaces` | LicenseRef-SyMoNeuRaL-Proprietary | proprietary | **shipped** | upstream authors, on distribution | `backend/` |
| `SyMoNeuRaL site` | LicenseRef-SyMoNeuRaL-Proprietary | proprietary | **shipped** | upstream authors, on distribution | `frontend/site/` |
| `symoneural-gateway` | LicenseRef-SyMoNeuRaL-Proprietary | proprietary | **shipped** | upstream authors, on distribution | `backend/gateway/Cargo.lock` |
| `symoneural_cleanroom + symoneural_gguf` | LicenseRef-SyMoNeuRaL-Proprietary | proprietary | **shipped** | upstream authors, on distribution | `backend/studio/custom_nodes/` |

### Second party — 3 components

**Second party** — someone else's work we forked and modified. Their licence still governs; our changes sit on top of it.

| Component | Licence | Class | Carried | Who could enforce | Where |
|---|---|---|---|---|---|
| `symoneural-diffuse` | MIT | permissive | **shipped** | upstream authors, on distribution | `not in this tree; see restore/` |
| `symoneural-llm` | MIT | permissive | **shipped** | upstream authors, on distribution | `not in this tree; see restore/` |
| `symoneural-ui` | GPL-3.0 | copyleft | **host-only** | upstream authors, on distribution | `/home/google/Symoneural/symoneural-ui` |

### Third party — 713 components

**Third party** — someone else's work, used unmodified.

Too many to list individually here; they are every row of `ops/LICENSES.tsv` with `party=third`. By ecosystem:

| Ecosystem | Components | Classes present |
|---|---:|---|
| model | 12 | UNKNOWN×12 |
| npm | 9 | UNKNOWN×9 |
| python | 331 | permissive×268, proprietary×39, UNKNOWN×18, weak-copyleft×6 |
| rust | 361 | permissive×293, UNKNOWN×68 |

## The one item that is a real decision

`symoneural-ui` is a fork of **ComfyUI, which is GPL-3.0** — confirmed 2026-09-11
against the GitHub API, not assumed. It is the only copyleft component in the
720, and it is the only row on this page that needs a person rather than a
generator.

**What is true, measured, not inferred:**

- The fork lives at `/home/google/Symoneural/symoneural-ui`. It is **not
  tracked by git**, and `scripts/build-deb.sh` builds its payload from
  `git ls-files`, so the GPL-3.0 code *cannot* enter the package. That is a
  structural guarantee, not a promise — and `carried` in the table is computed
  by running the packager's own exclusion rules, so it fails rather than lies if
  this ever changes.
- `backend/studio/` talks to it **over HTTP**, on `127.0.0.1:8188`, through
  `SYMONEURAL_COMFY_URL`. A socket between two processes is an arm's-length
  boundary and is the weakest possible coupling.
- **But** `backend/studio/custom_nodes/symoneural_cleanroom/` and
  `symoneural_gguf/` are ours, are tracked, and both export
  `NODE_CLASS_MAPPINGS` — ComfyUI's plugin ABI. They are *loaded into the
  GPL-3.0 process*. Neither imports a `comfy` module (hence "cleanroom"), but
  dynamic loading into a GPL host is exactly the linkage question that has no
  settled answer.
- **And they ship.** Measured against the packager's manifest on 2026-09-11:
  both files are in the 1,142-file `.deb` payload. An earlier version of this
  page called them `host-only`; that was asserted rather than measured, and it
  was wrong.

**What this page will not do is decide that.** Whether a plugin loaded into a
GPL-3.0 host forms a derivative work is genuinely contested, and per the naming
doctrine — *"that is not your call to make — record what was borrowed and from
where"* — it is recorded here and left to the owner and counsel.

**What makes it safe today:** the GPL-3.0 work is never distributed. The `.deb`
carries our two plugins but not the host they plug into, and the GPL obligation
attaches to distributing *the combination*. Shipping a plugin written against an
ABI, with no copy of the program that defines it, is the weak end of this
question rather than the sharp end.

**What would change that**, and it is one specific event: any build that puts
the fork and the plugins in the same artefact — a `.deb` that vendors ComfyUI,
an image, a VM, a customer install. The table's `carried` column is computed
from `scripts/build-deb.sh` every time this file is regenerated, so such a build
turns the `symoneural-ui` row to `shipped` and fails
`test_nothing_shipped_is_copyleft`. **That test is the tripwire.** It must be
answered before the build ships, not after.

The previous version of this file said ComfyUI was *"present on the build host;
not built, not incorporated, not packaged, not deployed."* Three of those four
are still right. **"Not incorporated" was wrong**: two first-party packages are
written against its plugin ABI and are loaded into its process.


## Weak copyleft — attribution plus changes to the component itself

None of these is modified here, so nothing beyond attribution is owed. Listed because that would stop being true the moment one is patched.

| Component | Licence | Where |
|---|---|---|
| `certifi` | Mozilla Public License 2.0 (MPL 2.0) | venv:vllm |
| `certifi` | Mozilla Public License 2.0 (MPL 2.0) | venv:coreml |
| `pycountry` | LGPL-2.1-only | venv:vllm-0271-cu130 |
| `tqdm` | MPL-2.0 AND MIT | venv:vllm |
| `tqdm` | MPL-2.0 AND MIT | venv:coreml |
| `tqdm` | MPL-2.0 AND MIT | venv:symoneural-hybrid |


## Unmeasured — 107 rows that still need an answer

Unknown is not absent and is not safe. Each of these is a component whose licence this generator could not read, and every one must be resolved before anything containing it is distributed.

**model** (12): `FLUX.1-schnell.MODEL-CARD`, `Qwen2.5-0.5B-Instruct.LICENSE`, `Qwen2.5-14B-Instruct.LICENSE`, `Qwen2.5-7B-Instruct.LICENSE`, `Qwen3-30B-A3B-Instruct.LICENSE`, `README`, `onnxruntime.LICENSE`, `openai-gpt-oss-20b-LICENSE`, `openai-whisper.LICENSE`, `rembg.LICENSE`, `u2net.LICENSE`, `whisper.cpp.LICENSE`

**npm** (9): `@types/node`, `@types/react`, `@types/react-dom`, `eslint`, `eslint-config-next`, `next`, `react`, `react-dom`, `typescript`

**python** (12): `cuda-toolkit`, `detect-installer`, `humming-kernels`, `openai-harmony`, `prometheus-fastapi-instrumentator`, `pyaml`, `pyelftools`, `quack-kernels`, `tiktoken`, `tokenspeed-mla`, `torchao`, `torchcodec`

**rust** (65): `android_system_properties`, `ar_archive_writer`, `core-foundation-sys`, `fd-lock`, `iana-time-zone-haiku`, `icu_collections`, `icu_locale_core`, `icu_normalizer`, `icu_normalizer_data`, `icu_properties`, `icu_properties_data`, `icu_provider`, `js-sys`, `libredox`, `litemap`, `mach2`, `potential_utf`, `psm`, `r-efi`, `redox_users`, `rustversion`, `tinystr`, `valuable`, `wasi`, `wasip2`, `wasm-bindgen`, `wasm-bindgen-futures`, `wasm-bindgen-macro`, `wasm-bindgen-macro-support`, `wasm-bindgen-shared`, `wasm-streams`, `web-sys`, `web-time`, `webpki-roots`, `winapi`, `winapi-i686-pc-windows-gnu`, `winapi-util`, `winapi-x86_64-pc-windows-gnu`, `windows-core`, `windows-implement`, `windows-interface`, `windows-link`, `windows-result`, `windows-strings`, `windows-sys`, `windows-targets`, `windows_aarch64_gnullvm`, `windows_aarch64_msvc`, `windows_i686_gnu`, `windows_i686_gnullvm`, `windows_i686_msvc`, `windows_x86_64_gnu`, `windows_x86_64_gnullvm`, `windows_x86_64_msvc`, `winx`, `wit-bindgen`, `writeable`, `yoke`, `yoke-derive`, `zerocopy-derive`, `zerofrom`, `zerofrom-derive`, `zerotrie`, `zerovec`, `zerovec-derive`


## Two gaps this file names rather than hides

- **The gateway ships 362 crates and has no notices file.** Their licences are now measured (permissive throughout; the two GPL crates, `ittapi` and `ittapi-sys`, are `GPL-2.0-only OR BSD-3-Clause`, so BSD applies). What does not exist is the attribution file those permissive licences require on distribution. `backend/remix/THIRD-PARTY-LICENSES.md` is the only notices file in the repository.
- **npm is declared but never installed.** `frontend/app` has had no `npm ci` run, so its dependency tree is unmeasured beyond the nine names in `package.json`. Those nine are listed as UNKNOWN above, which is honest, and they will resolve the first time the tree is installed.

## How to re-measure

```bash
tools/audit/license_inventory.py            # rewrite ops/LICENSES.tsv
tools/audit/license_inventory.py --findings # only the rows needing a decision
tools/build/build_licenses.py               # rewrite this file
```

Python is read with `importlib.metadata` inside **each venv**, not the system interpreter — reading the system one reports torch, transformers and cupy as absent while five venvs hold them. PEP 639 `License-Expression` is read before classifiers: reading classifiers alone reported 207 packages as unlicensed when the true figure was 13. System-python rows are included only when this repository actually imports something they provide, so the operating system's own packages (`nala`, `mpv`, `iotop`, PyQt) are not reported as our dependencies.
