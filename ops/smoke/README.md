# ops/smoke/ — proof something was actually run

A smoke record is written **by running the thing**, and it says what was observed, on what
date, on what revision.

## Why this is a directory and not a test

`exists`, `grep` and `ngrep` ask what is written on disk. None of them can ask whether the
thing works. Task #94 shipped a desktop client whose eighteen declared checks all went green
and whose chat surface was dead on arrival — a missing capability meant the page was never
permitted to hear the stream it had asked for, so it rendered one turn and then nothing, with
no error to read. The timer archived the task two minutes later.

A note explaining that the checks are insufficient does not help: the archiver reads checks,
not notes, and #94's note said exactly that and was ignored.

**The cheap fix is a stamped smoke record committed beside the code**, and a check that the
file exists — because that file cannot be written honestly without running the thing.

## Writing one

State, for each surface: what was run, what was observed, the date, and the revision. If it
failed, that is the record — a smoke file with a failure in it is worth more than no file,
and far more than a passing one that was written from the source.
