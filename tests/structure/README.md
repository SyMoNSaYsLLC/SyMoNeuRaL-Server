# tests/structure/ — rules about the tree itself

These do not test a feature. They test that the repository still has a property it decided
to have, and **each one exists after a specific failure**.

| test | the rule, and what it cost |
|---|---|
| `test_no_tokens.py` | no inbound gate anywhere. It passed for days while walking `backend/apps/` — a directory that had stopped existing — and reported success over a tree where studio, exp, reinforce and both miners were still refusing callers |
| `test_path_fragility.py` | no parent-counting root anchors. Its first version opened with `parents[2]`, the exact construct it was written to count, and the ratchet caught its own author on the next run |
| `test_one_route_to_each_module.py` | every route reachable, each module mounted once |
| `test_credential_header.py` | our own client never sends a credential header |
| `test_no_external_source_dependency.py` | nothing imports out of the tree |
| `test_no_claude_dependency.py` | the repository does not require one vendor's tooling |
| `test_repository_map.py` | the README describes every folder that exists |
| `test_vendor_facade.py`, `test_vendor_sdks.py` | vendored SDKs stay out |
| `test_surface_split.py` | a delegated surface is really delegated |
| `test_tool_policy.py` | `ops/authority/TOOL-POLICY.json` matches what is refused |

## The property that makes these worth having

A guard must be able to **fail**. Before trusting a green one, check it looked at something:
`test_no_tokens.py` now asserts its walk found source files before believing an empty gate
list, because an empty result over an empty walk is not evidence.

A guard that exempts itself is the first step to a guard that exempts everything.
