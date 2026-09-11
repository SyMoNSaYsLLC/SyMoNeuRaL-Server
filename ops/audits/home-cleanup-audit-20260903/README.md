# `home-cleanup-audit-20260903/` — what was in /home/google, and what it cost

The inventory behind that cleanup: totals, duplicates, largest files, what referenced what,
and `SHA256SUMS` so the claims are checkable rather than asserted.

`HOME-REFERENCES.tsv` is the one that mattered: it is what distinguished a file nothing
pointed at from a file that looked unused. Deleting on size alone is how a build breaks a
week later.

Point-in-time. The machine has changed since.
