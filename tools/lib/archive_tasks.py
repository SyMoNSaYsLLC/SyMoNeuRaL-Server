#!/usr/bin/env python3
"""Move finished tasks out of PROJECT-TASKS.md and into review/CLOSED-TASKS.md.

Garrett, 2026-08-20: *"done should automatically leave the list"*, after *"cancelled and done
task need to be removed from the list and placed into a folder that makes sense"*. The first
move was done by hand, which means it was accurate exactly once. This is the same operation
run by the same systemd timer that rebuilds the progress page, so the canonical list stays a
reading of remaining work without anybody remembering to prune it.

It runs BEFORE `build_progress.py` in the unit, so the page is always rendered from the file
as it will be left, never from a list that still contains rows about to be archived.

Three properties this has to have, because it edits a file a human also edits:

  * **Verbatim.** A block is moved, never rewritten or summarised. The only thing added is
    one `ARCHIVED` line recording the date and how the task was judged finished.
  * **Idempotent.** With nothing to move it writes nothing at all -- not even a rewritten
    identical file -- so it cannot fight an editor over mtime, and `git status` stays quiet.
  * **Atomic.** Write to a temporary file in the same directory and rename over the target.
    A crash midway leaves the original, not half a task list.

What counts as finished is deliberately WIDER than the marker in the file. A task whose
`check:` predicates all pass is finished whether or not anybody flipped its marker -- that is
the whole point of the percentage. The `ARCHIVED` line says which of the two it was, so a
task archived on checks alone can be found and argued with.
"""
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_progress import TASK_ROW, parse_tasks   # noqa: E402  (path set above)

CLOSED_HEADER = """# CLOSED-TASKS.md — every task that is done or cancelled

Moved out of `PROJECT-TASKS.md` automatically by `tools/lib/archive_tasks.py`, on the same timer
that rebuilds the progress page. The canonical list holds only open work, so its length is a
reading of what is left rather than of everything that ever happened.

Nothing here is deleted or summarised — each entry is the block that was in the task list,
verbatim, SHA and all, plus one `ARCHIVED` line saying when it left and what judged it
finished. `review/` is uncommitted, the same standing rule that covers every other review
artefact.

Closed here does not mean closed everywhere: audit items, the request ledger and `git log`
still carry their own records, and those are the ones to trust for what actually landed.

---

## Done
"""

FINISHED = ("done", "cancelled")


def split_blocks(text: str) -> list[dict]:
    """Every task block plus the lines between blocks, in order, losing nothing."""
    parts, cur = [], {"row": None, "lines": []}
    parts.append(cur)
    for line in text.split("\n"):
        m = TASK_ROW.match(line)
        if m:
            cur = {"row": m.group(2), "lines": [line]}
            parts.append(cur)
        elif cur["row"] is not None and not (line.startswith((" ", "\t"))
                                             or line.strip() == ""):
            # Prose resumed at column zero: the block ended here, and this line belongs to
            # the file rather than to the task. Without this a section heading following a
            # finished task would be archived along with it.
            cur = {"row": None, "lines": [line]}
            parts.append(cur)
        else:
            cur["lines"].append(line)
    return parts


def trailing_blank_count(lines: list[str]) -> int:
    n = 0
    for line in reversed(lines):
        if line.strip():
            break
        n += 1
    return n


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    tasks_file = root / "PROJECT-TASKS.md"
    closed_file = root / "review" / "CLOSED-TASKS.md"
    if not tasks_file.exists():
        print("PROJECT-TASKS.md not found; nothing to archive")
        return 0

    text = tasks_file.read_text()
    state = {t["id"]: t for t in parse_tasks(text, root)}
    blocks = split_blocks(text)

    moving = [b for b in blocks
              if b["row"] and state.get(b["row"], {}).get("state") in FINISHED]
    if not moving:
        return 0

    stamp = time.strftime("%Y-%m-%d")
    done_out, cancelled_out = [], []
    for b in moving:
        t = state[b["row"]]
        if t["from_disk"]:
            how = "resolved against the filesystem"
        elif t["checks"] and all(ok for _, ok in t["checks"]):
            how = ("every declared check passes — "
                   + "; ".join(label for label, _ in t["checks"]))
        else:
            how = "marked in PROJECT-TASKS.md"
        # Drop trailing blanks so the archive does not accumulate a growing gap per entry.
        lines = b["lines"][:len(b["lines"]) - trailing_blank_count(b["lines"])]
        entry = "\n".join(lines) + f"\n        ARCHIVED {stamp} — {how}.\n"
        (cancelled_out if t["state"] == "cancelled" else done_out).append(entry)

    if not closed_file.exists():
        closed_file.parent.mkdir(parents=True, exist_ok=True)
        closed_file.write_text(CLOSED_HEADER)
    closed = closed_file.read_text()
    if "\n## Cancelled\n" not in closed:
        closed = closed.rstrip("\n") + "\n\n## Cancelled\n"
    # Each entry is inserted under its own heading rather than appended to the end of the
    # file, so Done and Cancelled do not interleave as entries arrive in mixed batches.
    head, sep, tail = closed.partition("\n## Cancelled\n")
    if done_out:
        head = head.rstrip("\n") + "\n\n" + "\n".join(done_out)
    if cancelled_out:
        tail = tail.rstrip("\n") + "\n\n" + "\n".join(cancelled_out)
    write_atomic(closed_file, head.rstrip("\n") + "\n" + sep + tail.rstrip("\n") + "\n")

    keep = [b for b in blocks if b not in moving]
    remaining = "\n".join("\n".join(b["lines"]) for b in keep)
    # Collapse the gap a removed block leaves behind: three or more blank lines become two.
    while "\n\n\n\n" in remaining:
        remaining = remaining.replace("\n\n\n\n", "\n\n\n")
    write_atomic(tasks_file, remaining.rstrip("\n") + "\n")

    for b in moving:
        print(f"archived {b['row']} ({state[b['row']]['state']})")
    return 0


def write_atomic(path: Path, text: str) -> None:
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False,
                                     prefix=path.name + ".", suffix=".tmp") as fh:
        fh.write(text)
        tmp = Path(fh.name)
    shutil.copymode(path, tmp) if path.exists() else None
    tmp.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
