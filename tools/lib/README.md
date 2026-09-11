# tools/lib/ — shared helpers for the tools

Imported by the generators, benchmarks and audits. Nothing here runs in production.

```
model_inventory.py       the measured model inventory -- what is on disk vs the manifest
dependency_inventory.py  what this box has installed, by layer
app_health.py            is each surface answering
archive_tasks.py         move a finished task to the closed list, verbatim
index_references.py      the reference index
smoke.py                 run each surface on the port PORTS.tsv gives it
failure_modes.py         the catalogue of how things have broken here
sabotage_matrix.py       break a thing on purpose, confirm the right test goes red
gpu_lease_proof.py       prove the lease actually serialises
lease_proof_2p.py        the same, two processes
surface_pilot_proof.py   prove a delegated surface is really delegated
bootcamp_*.py            the training-bay scout and referee
```

`sabotage_matrix.py` is the tool for the standing rule: **a test that passes before and after
your change tested nothing.** It breaks a thing deliberately and asserts a specific test goes
red. Use it when you are not sure a check discriminates.

`model_inventory.py` reads `backend/core/config.py` for the active model, not `server.py` —
the constants moved on 2026-09-11, and a tool reading the wrong file reports an empty
inventory rather than an error.
