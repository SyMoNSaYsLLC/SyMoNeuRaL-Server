#!/usr/bin/env python3
"""Verify every unit this repo carries, and diff it against what is actually installed.

Two failures this repo has already had, both invisible to reading the unit file:

  * **A directive in the wrong section.** `ops/units/symoneural-api.service` documents `StartLimit*`
    sitting under `[Service]`, where systemd silently ignores it -- for months. `systemd-analyze
    verify` reports exactly that class of mistake as an "Unknown key" warning, so it is worth
    running over every unit rather than trusting that the file says what it means.
  * **Drift between the repo template and the installed copy.** The repo is not authoritative
    about the running system; `/etc/systemd/system/` is. A template that has diverged from the
    installed unit means a reinstall would silently change behaviour, and a drop-in can
    override the file entirely without touching it.

So this reports three things per unit: verifier warnings, template-vs-installed drift, and
the drop-ins that override both. `systemctl show` is used for effective values, because that
is the only source that accounts for drop-ins and for directives systemd chose to ignore.
"""

from __future__ import annotations

import argparse
import difflib
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    """Find the root by its marker, not by counting parents.

    `backend/test_path_fragility.py` enforces this and explains why: a `parents[N]`
    root is silent when it is wrong, because the wrong parent usually exists too.
    """
    here = Path(__file__).resolve()
    for cand in (here, *here.parents):
        if (cand / "backend" / "server.py").is_file():
            return cand
    raise SystemExit(f"repo root not found above {here}: no backend/server.py marker")


ROOT = _repo_root()
OPS = ROOT / "ops"

SYSTEM_DIRS = ("/etc/systemd/system", "/run/systemd/system", "/usr/lib/systemd/system")
USER_DIRS = (Path.home() / ".config/systemd/user", Path("/usr/lib/systemd/user"))

# Read effective values rather than the file: these are the ones that had already silently
# failed to apply once. Restart limits only work when systemd actually parsed them.
EFFECTIVE_KEYS = (
    "FragmentPath", "UnitFileState", "ActiveState", "SubState",
    "Restart", "RestartUSec", "StartLimitIntervalUSec", "StartLimitBurst",
    "ExecMainPID", "MemoryMax", "TasksMax", "After", "Wants", "Requires",
)


def run(cmd: list[str]) -> tuple[int, str, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout, p.stderr


def installed_path(name: str) -> tuple[Path | None, str]:
    for d in SYSTEM_DIRS:
        p = Path(d) / name
        if p.is_file():
            return p, "system"
    for d in USER_DIRS:
        p = Path(d) / name
        if p.is_file():
            return p, "user"
    return None, "absent"


def dropins(name: str, scope: str) -> list[Path]:
    out: list[Path] = []
    roots = [Path(d) / f"{name}.d" for d in SYSTEM_DIRS] if scope != "user" \
        else [Path(d) / f"{name}.d" for d in USER_DIRS]
    for r in roots:
        if r.is_dir():
            out.extend(sorted(r.glob("*.conf")))
    return out


def verify(path: Path) -> list[str]:
    """systemd-analyze verify warnings. Exit status alone hides them, so parse the text."""
    rc, out, err = run(["systemd-analyze", "verify", str(path)])
    lines = [l.rstrip() for l in (out + err).splitlines() if l.strip()]
    # Missing-dependency noise is expected when verifying a file out of tree; keep it but
    # let the caller see it labelled rather than dropped.
    return lines


def show(unit: str, scope: str) -> dict[str, str]:
    cmd = ["systemctl"] + (["--user"] if scope == "user" else []) + \
          ["show", unit, "--no-pager", "--property=" + ",".join(EFFECTIVE_KEYS)]
    rc, out, _ = run(cmd)
    d: dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            d[k] = v
    return d


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--diff", action="store_true", help="print full unified diffs")
    args = ap.parse_args(argv)

    units = sorted(p for p in OPS.iterdir()
                   if p.suffix in (".service", ".timer", ".socket"))
    problems = 0

    for tpl in units:
        name = tpl.name
        inst, scope = installed_path(name)
        print(f"\n{'=' * 78}\n{name}")
        print(f"  repo template : {tpl.relative_to(ROOT)}")
        print(f"  installed     : {inst if inst else 'NOT INSTALLED'}"
              + (f"  ({scope} scope)" if inst else ""))

        # -- verifier ------------------------------------------------------------------
        warnings = verify(tpl)
        interesting = [w for w in warnings if "Unknown key" in w or "Unknown section" in w
                       or "ignoring" in w.lower() or "invalid" in w.lower()]
        if interesting:
            problems += len(interesting)
            print("  verify: PROBLEMS")
            for w in interesting:
                print(f"     ! {w}")
        else:
            print(f"  verify: no unknown-key/invalid warnings ({len(warnings)} line(s) total)")
        for w in warnings:
            if w not in interesting:
                print(f"       . {w}")

        # -- drift ---------------------------------------------------------------------
        if inst:
            a = tpl.read_text().splitlines(keepends=True)
            b = inst.read_text().splitlines(keepends=True)
            if a == b:
                print("  drift : none -- installed copy is byte-identical to the template")
            else:
                problems += 1
                d = list(difflib.unified_diff(
                    a, b, fromfile=f"repo/{tpl.relative_to(ROOT)}", tofile=str(inst), n=2))
                adds = sum(1 for l in d if l.startswith("+") and not l.startswith("+++"))
                dels = sum(1 for l in d if l.startswith("-") and not l.startswith("---"))
                print(f"  drift : DIVERGED -- installed has {adds} added / {dels} removed line(s)")
                for line in (d if args.diff else d[:40]):
                    print("     " + line.rstrip("\n"))
                if not args.diff and len(d) > 40:
                    print(f"     ... {len(d) - 40} more diff line(s); --diff for all")

            dd = dropins(name, scope)
            if dd:
                print(f"  drop-ins: {len(dd)} -- these override the file above")
                for f in dd:
                    print(f"     + {f}")
                    for line in f.read_text().splitlines():
                        if line.strip() and not line.startswith("#"):
                            print(f"         {line}")

            eff = show(name, scope)
            if eff:
                print("  effective (systemctl show -- accounts for drop-ins):")
                for k in EFFECTIVE_KEYS:
                    if k in eff and eff[k] not in ("", "0", "[not set]"):
                        print(f"     {k}={eff[k]}")
        else:
            print("  drift : n/a -- nothing installed to compare against")

    print(f"\n{'=' * 78}\n  {len(units)} unit(s) audited; {problems} problem(s) flagged")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
