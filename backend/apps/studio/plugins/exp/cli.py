"""Mount a manifest, print what happened, exit. No FastAPI, no gate, no HTTP.

    python3 -m apps.studio.plugins.exp.cli                       # the dev preset, as a table
    python3 -m apps.studio.plugins.exp.cli --preset sessions      # two isolated sessions
    python3 -m apps.studio.plugins.exp.cli --preset failures      # every failure mode at once
    python3 -m apps.studio.plugins.exp.cli path/to/manifest.yaml   # your own
    python3 -m apps.studio.plugins.exp.cli --json                 # `Loader.state()`, verbatim
    python3 -m apps.studio.plugins.exp.cli --trace 40             # and the last 40 trace events

Run from `backend/`, which is where `apps` is importable from.

This exists for two reasons. The first is that the page and the API are behind
`SYMONEURAL_EXP_ENABLED` and `SYMONEURAL_EXP_TOKEN`, and a manifest you are still writing should not need a
live process and a secret to check -- `--json` here and `GET /api/exp/state` there return the
same structure from the same `Loader.state()`. The second is that it is the standing proof that
everything under `routes.py` is standard-library only: if an import creeps into `context.py`,
`fiber.py`, `registry.py`, `loader.py` or `trace.py` that Debian's interpreter does not have,
this command stops working before the API does.

Mount, print, dispose. It is deliberately not a REPL: a runtime whose whole argument is
reversible mounting should demonstrate teardown on every run, and the exit code says whether
anything failed, which is what makes it usable from a shell.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys

from .context import ContextError
from .loader import Loader, preset_path, presets

#: A failed *plugin* is not a failed *run* by default -- `failures.yaml` mounts four of them on
#: purpose and exits 0, because that preset working means the failures appeared. `--strict`
#: inverts it, which is what a manifest of your own wants from a shell.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_BAD_MANIFEST = 2


def _source(arg: str):
    """A preset name if it is one, otherwise a path. Presets win: `dev` is the preset, and
    `./dev` is the file, which is the same rule `POST /api/exp/preset` follows."""
    if arg in presets():
        return preset_path(arg), arg
    path = pathlib.Path(arg)
    if not path.exists():
        raise ContextError(f"no preset or file {arg!r}; presets: {', '.join(presets())}")
    return path, str(path)


def _table(state: dict) -> str:
    rows = [("STATE", "ID", "PLUGIN", "PROVIDES", "MISSING", "NOTE")]
    fibers = {f["id"]: f for f in state["fibers"]}
    for entry in state["entries"]:
        fiber = fibers.get(entry["fiber"] or "")
        note = (entry["error"] or "").splitlines()
        rows.append((
            entry["state"],
            entry["id"],
            entry["use"] or "(group)",
            ",".join(fiber["provides"]) if fiber else "",
            ",".join(fiber["missing"]) if fiber else "",
            note[-1][:60] if note else "",
        ))
    width = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(cell.ljust(width[i]) for i, cell in enumerate(row)).rstrip()
                     for row in rows)


def _services(loader: Loader) -> str:
    live = sorted(loader.runtime.services.values(), key=lambda s: s.key)
    if not live:
        return "  (none)"
    # Realm ids carry the isolating group's label and are long; padding to a guessed width puts
    # the columns of `sessions.yaml` -- the one preset where realms are the point -- out of line.
    realms = {s.key: (s.key.split(":", 1)[0] or "root") for s in live}
    wide = max(len(r) for r in realms.values())
    return "\n".join(
        f"  {s.name:<12} realm={realms[s.key]:<{wide}}  epoch={s.epoch:<3} "
        f"{type(s.value).__name__} <- {s.owner.label if s.owner else '-'}" for s in live)


async def _run(args) -> int:
    try:
        source, label = _source(args.manifest)
    except ContextError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_BAD_MANIFEST

    loader = Loader(trace_path=args.trace_file)
    try:
        try:
            await loader.apply(source, label=label)
        except ContextError as exc:
            print(f"manifest rejected: {exc}", file=sys.stderr)
            return EXIT_BAD_MANIFEST

        state = loader.state(with_config=args.config)
        if args.json:
            print(json.dumps(state, indent=2, default=str))
        else:
            print(f"source: {state['source']}    "
                  + "  ".join(f"{k}={v}" for k, v in sorted(state["states"].items())))
            print()
            print(_table(state))
            print("\nservices:")
            print(_services(loader))
        if args.trace:
            print("\ntrace:")
            for event in loader.runtime.trace.tail(args.trace):
                fields = "  ".join(f"{k}={v}" for k, v in event.items()
                                   if k not in ("seq", "event", "t"))
                print(f"  {event['seq']:>4}  {event['event']:<22} {fields}")
        # Entries, not fibers. `no-such-module` in `failures.yaml` fails while *resolving*, so
        # it never gets a fiber -- counting fibers reports three failures where the table shows
        # four, and the one it drops is the one you most need told about.
        failed = [e for e in state["entries"] if e["state"] == "failed"]
        if failed and not args.json:
            print(f"\n{len(failed)} failed: " + ", ".join(e["id"] for e in failed))
        return EXIT_FAILED if (failed and args.strict) else EXIT_OK
    finally:
        # Always. The teardown path is the half of this runtime that is easy to leave untested,
        # and running it on every invocation is free coverage of the reverse unwind.
        await loader.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m apps.studio.plugins.exp.cli",
        description="Mount a manifest in-process, print the plugin table, tear it down again.")
    # Two spellings, two dests, resolved below. Sharing one `dest` does not work: a positional
    # with `nargs="?"` is always "parsed", consuming zero arguments, and argparse applies its
    # default *after* the optionals -- so `--preset sessions` would be silently overwritten with
    # "dev" and the command would mount the wrong manifest while reporting success.
    parser.add_argument("manifest", nargs="?", default=None,
                        help="preset name (default: dev) or path to a YAML manifest")
    parser.add_argument("--preset", dest="preset", default=None,
                        help="same thing, spelled as a flag")
    parser.add_argument("--json", action="store_true", help="print Loader.state() as JSON")
    parser.add_argument("--config", action="store_true",
                        help="include each entry's config (the API needs a token for this)")
    parser.add_argument("--trace", type=int, metavar="N", default=0,
                        help="also print the last N trace events")
    parser.add_argument("--trace-file", metavar="PATH", default=None,
                        help="append the trace to a JSONL file as well")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 if any plugin failed to mount")
    args = parser.parse_args(argv)
    args.manifest = args.preset or args.manifest or "dev"
    return asyncio.run(_run(args))


if __name__ == "__main__":       # pragma: no cover -- exercised as a subprocess, not imported
    raise SystemExit(main())
