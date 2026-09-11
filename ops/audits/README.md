# ops/audits/ — what was true on the day it was taken

A point-in-time finding. **Nothing here is maintained**, and that is the point: an audit
corrected after the fact stops being evidence and becomes an opinion.

```
AUDIT-*-2026-08-26.md              account security, dependency runtime, frontend
APPLICATION-VERIFICATION-20260908  what answered, and what did not
BOX-REALITY-AUDIT.md               what is on this machine vs what the repo claims
CONSOLIDATION-20260908.md          the restructure, as it was executed
RECONCILIATION-20260908.md         where four records disagreed, and which won
LICENSE-AUDIT.md                   every artefact, its licence, and what is unclassified
SECURITY-AUDIT.md
css-audit.md  online-apps-audit.md
diagnostics/                       host dumps: cgroups, kernel, /proc, /sys, EFI vars
home-cleanup-audit-20260903/       the inventory, hashes and totals behind that cleanup
lora-restoration-20260903/         payload list and SHA256SUMS
reference/                         upstream pins, vendor classification, storage records
```

## When to read one

To answer *"was this already broken, or did I break it?"* — which is the question a dated
audit answers and a current record cannot. `BOX-REALITY-AUDIT.md` and
`RECONCILIATION-20260908.md` are the two worth reading before believing any claim about what
is installed here.

## When to write one

When you measured something across the whole tree and the result is worth being able to
compare against later. Name it `<SUBJECT>-<YYYYMMDD>.md`, state the command that produced
each figure, and carry the commit SHA.

## What does not belong here

Anything you intend to keep correct. That is `ops/registry/`. If you find yourself editing a
file in this directory to make it right again, it was in the wrong directory.
