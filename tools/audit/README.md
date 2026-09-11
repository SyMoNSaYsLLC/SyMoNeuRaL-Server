# tools/audit/ — report, never fix

These print findings and change nothing. An auditor that repaired what it found would destroy
the evidence it was ever wrong, and its next count would mean nothing.

```
import_audit.py          what imports what, and what imports out of the tree
route_audit.py           every mounted route against what the registry expects
cross_root_audit.py      this tree against the old one
probe_apps.py            does each surface answer
probe_engines.py         are the engine binaries where the registry says
serving_config_audit.py  what the running service was actually configured with
runtime_probe.py         what is executing right now
prove_*.py               narrow proofs: ravencalc steps, the vendor facade
access_log_audit.py      what reached this box
check_links.py           every link in the docs resolves
```

A finding is not a bug report until somebody reads it. Put what you act on in
`ops/audits/` with the date and the commit.
