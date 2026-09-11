# ops/history/ — what was decided, and by whom

```
decisions/   the record of a decision and its reasoning
handoffs/    one coder to the next: what was done, what is left, what will bite you
archive/     superseded state documents, kept so the supersession is visible
```

**Nothing here is current.** That is the point. A decision record edited to match what
happened later stops being a record.

## Why archive/ is not deleted

Three files once all claimed to describe current state, and agents kept acting on the stale
one. The fix was one canonical current-state source — not deleting the others, because a
document that vanishes and one that was never written read identically. They live here behind
a README that says so.

## Handoffs

Each names its recipient, the response it came from, the task IDs, the objective, scope,
prerequisites, files and services, acceptance checks, constraints, rollback, and completion
evidence. **It must stand alone without chat history.**

A generated plan and an old report cannot override a newer owner instruction. The receiving
coder checks the handoff against current source and runtime state before executing.
