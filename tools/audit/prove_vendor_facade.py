"""Break each facade on purpose, one break at a time, and record what goes red.

Task #74 item 5. Run it after touching anything under `FACADES` in
`backend/test_vendor_facade.py`:

    python3 tools/audit/prove_vendor_facade.py     # exit 0 iff every break goes red and nothing is left behind

`archive/vendor-sdks/SMOKE-vendor-facade.md` is its output pasted, and that file cannot be written
honestly by anybody who did not run this.

`.claude/CLAUDE.md`: *"When behaviour changes, prove it changed: break it on purpose and
watch a test fail, then fix it. A test that passes before and after your change tested
nothing."* Doing that by hand for six breaks is six chances to forget to restore a file,
so it is a script: every edit is applied to a copy of the original text and unconditionally
rolled back in a `finally`, and the run ends by asserting the tree is byte-identical to
where it started.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

REPO = pathlib.Path("/home/google/Symoneural")
BACKEND = REPO / "backend"
TEST = "apps/test_vendor_facade.py"

#: (label, file, find, replace) -- each is the single edit that reintroduces one defect.
BREAKS = [
    ("a shipped module imports the vendor directly",
     "backend/studio/inference.py",
     "from . import httpclient", "import httpx"),

    ("...and the alias form an ngrep cannot see",
     "backend/studio/inference.py",
     "from . import httpclient", "import httpx as httpclient"),

    ("the remix connector reaches past its facade",
     "backend/remix/symoneural_dj/connectors/spotify.py",
     "from .. import httpclient", "import httpx as httpclient"),

    ("an incomplete re-export -- the `convert_xor` shape",
     "backend/studio/httpclient.py",
     "HTTPStatusError = httpx.HTTPStatusError", "# HTTPStatusError = httpx.HTTPStatusError"),

    ("the remix facade drops a name its connectors annotate with",
     "backend/remix/symoneural_dj/httpclient.py",
     "Response = httpx.Response", "# Response = httpx.Response"),

    ("the facade stops importing its vendor (rule passes, nothing works)",
     "backend/studio/mcpframework.py",
     "import fastmcp\n", "\n"),

    ("an exemption that no longer applies is left in EXEMPT",
     "backend/ravencalc/ravencalc.py",
     "from sympy.parsing.sympy_parser import", "from symbolic_parser_stub import"),
]


def run() -> tuple[int, str]:
    p = subprocess.run([sys.executable, "-m", "pytest", TEST, "-q", "--no-header", "-p",
                        "no:cacheprovider"],
                       cwd=BACKEND, capture_output=True, text=True)
    tail = [ln for ln in (p.stdout + p.stderr).splitlines() if ln.strip()]
    return p.returncode, tail[-1] if tail else "(no output)"


def main() -> int:
    code, line = run()
    print(f"{'BASELINE':<8} {'green' if code == 0 else 'RED':<5}  {line}")
    if code != 0:
        print("baseline is not green; refusing to measure breaks against a red tree")
        return 1

    # Read every target once, up front. Every break is applied to this text and rolled
    # back to it, and the final comparison is against it -- so "clean" means "the script
    # left nothing behind", not "the working tree matches HEAD", which it never did.
    snapshot = {rel: (REPO / rel).read_text() for _, rel, _, _ in BREAKS}

    failures = 0
    for label, relpath, find, repl in BREAKS:
        path = REPO / relpath
        original = snapshot[relpath]
        if find not in original:
            print(f"{'SKIP':<8} {'-':<5}  anchor missing in {relpath}: {find!r}")
            failures += 1
            continue
        try:
            path.write_text(original.replace(find, repl, 1))
            code, line = run()
        finally:
            path.write_text(original)
        verdict = "RED" if code != 0 else "green"
        if code == 0:
            failures += 1
        print(f"{'BREAK':<8} {verdict:<5}  {label}\n{'':8} {'':5}  {relpath}: {line}")

    code, line = run()
    print(f"{'RESTORED':<8} {'green' if code == 0 else 'RED':<5}  {line}")
    if code != 0:
        failures += 1

    residue = [rel for rel, text in snapshot.items()
               if (REPO / rel).read_text() != text]
    print(f"{'TREE':<8} {'clean' if not residue else 'DIRTY':<5}  "
          f"{residue or 'every file byte-identical to where it started'}")
    return 1 if failures or residue else 0


if __name__ == "__main__":
    raise SystemExit(main())
