# SyMoNeuRaL export policy — what may leave this box, and how

Written 2026-08-22 (R-180, Phase 0.6b), from the #75 finding the same day: every whole-repo
zip shared for review carried `training/corpus.jsonl` (the 327 hand-authored examples) and
`training/build_dataset.py`, because both are tracked and the zips were built from tracked
files. Trade secret exists only while reasonable measures keep it in.

## The rules

1. **No whole-repo zip exports, ever.** Not for review, not for backup, not "just this once".
   History never leaves this box; there is no git remote, and that is a protection, not a gap.
2. **The protected artefacts** (full reasoning in `docs/ENGINEERING.md`, trade-secret
   section): `training/corpus.jsonl`, `training/build_dataset.py`, `training/adapter/`
   weights. Never in an export, never served, never quoted into a page or commit message.
3. **Also excluded from any export:** the mode-600 ledgers (`GARRETT-REQUESTS.md`,
   `INTAKE.md`), anything under `review/`, `.env` files, tokens, `run/`, session transcripts.
4. **The only sanctioned path** is `tools/export_snapshot.sh`, and it is **allow-list
   construction, never repository-minus-deny-list**. The distinction is the whole security
   argument, because the two architectures give OPPOSITE answers for a path nobody
   classified:

       deny-list   unclassified path -> SHIPPED   (fails open; one missed pattern leaks)
       allow-list  unclassified path -> ABSENT    (fails closed; must be named to ship)

   So the exporter starts from the empty set and adds only what an explicit manifest names
   (stage 1), then independently re-scans the constructed set for the protected classes in
   rules 2 and 3 and aborts on any (stage 2). Stage 2 is not redundant: it catches an
   over-broad manifest entry, such as a directory that later gains a protected file.

   It writes an EXPORT-MANIFEST naming the source SHA and a per-file SHA256, and it REFUSES
   — non-zero, with **no archive emitted** — on a protected path, a missing manifest, a
   manifest naming a path that no longer exists, or path traversal. The archive is assembled
   in staging and only sealed after stage 2 passes, because a tool that detects a violation
   after writing the archive has already produced the artefact that must not exist.

   Earlier wording here said the script "excludes the above", which described a deny-list.
   That was the stale text: the architecture is allow-list, and the shipped script implements
   it. Corrected 2026-09-01.

## The acceptance check

The sanctioned exporter now exists and enforces this itself; the grep below remains a
cheap independent confirmation on any archive you are handed.

```bash
unzip -l export.zip | grep -E 'corpus\.jsonl|build_dataset\.py|GARRETT-REQUESTS|INTAKE\.md|\.env' \
  && echo "UNSAFE — do not send" || echo "safe export"
```
