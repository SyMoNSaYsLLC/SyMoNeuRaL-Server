# scripts/lib/ — what every script here shares

Sourced, never executed. Nothing in this directory has a `main`; each file defines functions
and constants and returns.

```
repo.sh      find the repository. Sourced FIRST, by everything.
say.sh       one voice: head_ say dim ok note bad step warn die
require.sh   preconditions: need_root need_cmd need_file need_dir confirm run
fetch.sh     download to .part, verify, promote. Never the other way round.
archive-guard.sh   the guard that refuses to archive a task whose checks are not real
```

## How to use it

```bash
#!/usr/bin/env bash
set -euo pipefail
. "$(dirname -- "${BASH_SOURCE[0]}")/lib/repo.sh"     # sets ROOT, or exits
. "$ROOT/scripts/lib/say.sh"
. "$ROOT/scripts/lib/require.sh"

need_root "$@"
need_cmd jq
head_ "doing the thing"
run install -m 644 "$ROOT/ops/Caddyfile" /etc/caddy/Caddyfile
ok "installed"
```

`repo.sh` is sourced with a path relative to `${BASH_SOURCE[0]}` because that is the only
thing known before `ROOT` exists. Everything after it spells its path from `$ROOT`.

A script one directory deeper — `model-staging/` — reaches back one more:
`. "$(dirname -- "${BASH_SOURCE[0]}")/../lib/repo.sh"`. That is the **only** place a
relative depth is written, and it is one line.

---

## Why each file exists

This directory was one file. It is five because the duplication was measured across the
25 scripts, not guessed at:

| idiom | scripts doing it | spellings |
|---|---|---|
| resolve the repository root | **16** | **8** |
| guard on a root marker | 14 | 2 different markers |
| `say` / `dim` / `warn` / `die` | 8 | 5 |
| check for root (`id -u`) | 8 | 3 |
| check a command exists | 8 | — |
| colour constants | 6 | — |
| download, verify, promote | 2 | 2, one missing the verify |

Where the count was low the code stayed where it was. `nvidia-smi` appears in five scripts
but only two of them query it, and `gpu-governor.sh` deliberately does **no arithmetic** on
the readings — that moved to Python because shell arithmetic on CSV was the cause of R-171.
Extracting a `lib/gpu.sh` would put the temptation back. Five unrelated call sites do not
need a framework between them.

### `repo.sh` — the one that mattered

Sixteen scripts resolved the root eight different ways, and **all but one counted parents**:

```bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"              # six scripts
ROOT="$(cd "$HERE/.." && pwd)"                        # five
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # five
ROOT="$(git rev-parse --show-toplevel)"               # one
ROOT="$(pwd)"                                         # one
```

Parent-counting is the failure this repository has paid for most. It broke on the `demo/`
flatten, on the `tools/` move, on the `backend/` move, and on 2026-09-11 it broke 63 Python
anchors at once when every tool moved one level deeper. It fails **silently**, because the
wrong parent is usually a directory that exists.

`$(pwd)` is worse, and it was in the most consequential script here.
`model-staging/symoneural-model-stage.sh` swaps the model a live surface loads; it worked
only if you happened to be standing in the repository root, and refused from anywhere else.
It had already moved a level deeper by then.

`git rev-parse` is wrong for a different reason: it answers about a *checkout*, and this tree
is also installed and run from places that are not one.

So `repo_root()` **walks up for `backend/server.py`** and stops at the first directory that
has it. It survives any move of the script, needs no git, and the one thing it depends on is
the thing whose absence means this is not the repository.

The refusal names the **file**, not a conclusion about the root. Commissioning once moved
`gpu-governor.sh` aside to see what an operator would read, and got *"repo root not found at
/home/google/Symoneural"* — which was the one thing that was not wrong.

### `say.sh`

Colour is TTY-gated and honours `NO_COLOR`. These run under systemd, in CI and through
`tee`; an escape sequence in a journal entry is noise that survives forever.

`warn` and `die` go to stderr with the program name on them, because an operator reading a
journal needs to know which of nine scripts produced the line.

### `require.sh`

`confirm` takes a **typed word**, not `y/n`, and refuses outright when there is no terminal.
Every caller is about to do something that costs money, evicts a surface, or overwrites
weights. A single keystroke is too cheap for that, a default answer is how a `--dry-run`
habit becomes an accident, and an unattended run must never be able to answer its own
question.

`run` respects `DRY_RUN=1` by describing instead of executing. Two scripts grew this
separately and named the variable identically, which is the signal it belonged here.

### `fetch.sh`

Three rules, and each one is a test in `tests/models/test_weight_names.py`:

1. the download lands at `<dest>.part`, never at `<dest>` — an interrupted run leaves no
   file that looks complete
2. it is verified **before** the rename; a corrupt `.part` is removed, not promoted
3. an existing `<dest>` is re-verified rather than trusted — "already there" is a claim
   about bytes, and the manifest exists so such claims are checkable

`test_same_size_corrupt_download_is_not_promoted` is named after the case that motivates all
three: a truncated download matching the expected byte count will load, and produce noise.

`fetch_licence` is separate and deliberately softer. Licence texts are small and unpinned,
and their absence must not stop a build — but it must be **said**. Apache-2.0 §4(a) obliges
the text to travel with the work, and a table row claiming Apache-2.0 while no text ships is
the obligation restated, not met.

### `archive-guard.sh`

The odd one out: it is a guard, not a helper, and it predates the rest. It refuses to archive
a task whose declared checks cannot distinguish done from not-done — `exists`, `grep` and
`ngrep` ask what is written on disk, and none of them can ask whether the thing works. #94
shipped a desktop client whose eighteen checks all went green and whose chat surface was dead
on arrival.

---

## Adding to this directory

Only when the duplication is **measured**. The count above was produced by pattern-matching
across every `.sh` here; re-run that before adding a sixth file. A helper with two callers is
usually two callers, and this repository's standing correction is that a fifth answer to a
question four registries already answer is a fifth thing that can disagree.

Every file must:

- be safe to source twice — no side effects but definitions, and `repo.sh`'s single
  `require_repo` call at the end is the deliberate exception
- pass `bash -n`
- name, in its header, the specific duplication or outage that justifies it
