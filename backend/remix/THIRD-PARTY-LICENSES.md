# Third-party licences — symoneural_dj

Versions and licences read from the installed distributions in
`~/.venvs/vllm` on 2026-08-09, not from memory. Regenerate with the command at
the bottom whenever dependencies change.

**Bottom line: every dependency is permissive (MIT / BSD / PSF) except
`certifi`, which is MPL-2.0 — file-level weak copyleft that is satisfied by not
modifying it.** Nothing here is GPL or AGPL. Nothing forces this project's own
source to be disclosed.

## Direct runtime dependencies

| Package | Version | Licence | Redistribution status |
|---|---|---|---|
| fastapi | 0.136.3 | MIT | ✅ Bundle freely; keep the MIT notice. |
| uvicorn | 0.51.0 | BSD-3-Clause | ✅ Bundle freely; keep notice + no endorsement claim. |
| httpx | 0.28.1 | BSD-3-Clause | ✅ Bundle freely; keep notice. |
| python-dotenv | 1.2.2 | BSD-3-Clause | ✅ Bundle freely; keep notice. |
| pillow | 12.3.0 | MIT-CMU | ✅ Bundle freely; keep the MIT-CMU notice. Used for procedural cover art only — no bundled fonts or images. |

## Transitive dependencies pulled in by the above

| Package | Version | Licence | Redistribution status |
|---|---|---|---|
| pydantic | 2.13.4 | MIT | ✅ |
| pydantic-core | 2.46.4 | MIT | ✅ |
| starlette | 1.3.1 | BSD-3-Clause | ✅ |
| anyio | 4.14.2 | MIT | ✅ |
| h11 | 0.16.0 | MIT | ✅ |
| httpcore | 1.0.9 | BSD-3-Clause | ✅ |
| idna | 3.18 | BSD-3-Clause | ✅ |
| sniffio | 1.3.1 | MIT OR Apache-2.0 | ✅ Dual — take MIT. |
| annotated-types | 0.7.0 | MIT | ✅ |
| click | 8.4.2 | BSD-3-Clause | ✅ |
| typing-extensions | 4.16.0 | PSF-2.0 | ✅ Python Software Foundation licence; permissive. |
| **certifi** | 2026.6.17 | **MPL-2.0** | ⚠️ **The only copyleft item.** See below. |

## Via `symoneural_accounts` (shared library, ours)

| Package | Version | Licence | Redistribution status |
|---|---|---|---|
| argon2-cffi | 25.1.0 | MIT | ✅ Password hashing. |
| argon2-cffi-bindings | 25.1.0 | MIT | ✅ |
| cffi | 2.1.0 | MIT-0 | ✅ MIT-0 waives even the attribution requirement. |
| pycparser | 3.0 | BSD-3-Clause | ✅ |

## Development only — not shipped

| Package | Version | Licence | Redistribution status |
|---|---|---|---|
| pytest | 9.1.1 | MIT | ✅ Test-time only; never in a runtime artifact. |

## The one that needs a sentence: certifi (MPL-2.0)

MPL-2.0 is **file-level** weak copyleft. It obliges you to publish the source of
*MPL-licensed files you modify*, and it explicitly permits combining unmodified
MPL files with proprietary code without affecting that code's licence.

We use `certifi` unmodified — it is a CA-bundle shipped as a Python package,
pulled in by `httpx`. So the obligation is discharged by (a) not patching it and
(b) keeping its licence text with any distribution. **It does not reach this
project's source.**

If that ever becomes uncomfortable, `httpx` can be pointed at the system trust
store instead, removing the dependency. Not necessary today.

## Attribution obligations, in practice

If you distribute a binary, container or VM containing these packages, ship
their licence texts. `pip install` already places each package's licence in
`site-packages/<dist>-<version>.dist-info/`, so the simplest compliant answer is:
**do not delete the `.dist-info` directories** from a built image. For a
source-distributed or server-side-only deployment (this app's normal shape,
where nothing is handed to a user), no further action is required — none of
these licences are triggered by *use over a network*, because none of them is
AGPL.

## What is NOT a dependency, and therefore not on this list

- **Spotify.** No Spotify SDK, no vendored code. This app is an HTTP client of
  a public API. That relationship is governed by Spotify's Developer Terms, not
  by a software licence — see `docs/LICENSING.md`.
- **The symon engine and its model weights.** A separate package this app calls
  over loopback HTTP. Weight provenance lives in `../models/PROVENANCE.md`.
- **Music and album art.** Fetched at runtime, never redistributed by this code.
  Cover art is generated procedurally by Pillow from shapes and colours; no
  third-party image assets are bundled.

## Regenerating this table

```bash
~/.venvs/vllm/bin/python - <<'PY'
from importlib.metadata import metadata, version
for p in ["fastapi","uvicorn","httpx","python-dotenv","pillow","pydantic",
          "starlette","anyio","h11","httpcore","certifi","idna","sniffio",
          "typing-extensions","annotated-types","pydantic-core","click",
          "argon2-cffi","argon2-cffi-bindings","cffi","pycparser","pytest"]:
    m = metadata(p)
    lic = m.get("License-Expression") or m.get("License") or ""
    if not lic or len(lic) > 40:
        cls = [c for c in m.get_all("Classifier") or [] if c.startswith("License ::")]
        lic = cls[0].split("::")[-1].strip() if cls else "see metadata"
    print(f"{p:<22} {version(p):<12} {lic}")
PY
```
