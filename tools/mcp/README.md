# tools/mcp — shims that sit between an MCP client and a third-party MCP server

An MCP server we did not write is sometimes wrong on the wire in a way that costs
us the whole server. Nothing here adds features. Each file repairs one specific,
measured protocol defect in one upstream, and each is written to become a no-op
the day that upstream is fixed, so removing it is never urgent and never risky.

| File | Repairs | Retire when |
|---|---|---|
| `fill_result_type.py` | github-mcp-server 1.6.0 omits `resultType`, which protocol revision 2026-07-28 requires, while echoing that revision back — so the client will not apply its bridge and drops all 26 tools | `--verbose` reports `repaired 0 result(s)` |

## How they are wired

Never into the MCP client config directly. The launcher in `bin/` owns the
server, and the shim goes inside it, so the config names one command and the
reason for the shim lives next to the code that needs it:

```bash
exec tools/mcp/fill_result_type.py -- "$BIN" stdio --read-only
```

`bin/symoneural-github-mcp` is the working example, and also the place the
GitHub credential is read from the `gh` keyring rather than from a config file.

## Verifying one

Health alone proves nothing — a broken server still reports `Connected`. Take the
shim out and watch the failure come back:

```bash
claude mcp list | grep symoneural-github      # ✔ Connected
# edit bin/symoneural-github-mcp, drop the shim from the exec line
claude mcp list | grep symoneural-github      # tools fetch failed
```

Measured 2026-09-11 on github-mcp-server 1.6.0, Claude Code 2.1.236: with the
shim, 26 tools; without it, zero and an `Invalid result for tools/list` error.

## Writing another

Three rules, all of them learned from the first one costing a rewrite:

1. **Make the server do more, not claim less.** The first attempt rewrote the
   echoed `protocolVersion` downward to re-arm the client's compatibility
   bridge. The client kept enforcing the newer rule and it did not work. Supply
   the missing thing instead; the wire result then matches a conforming server.
2. **Forward anything you cannot parse, byte for byte.** A shim must never be
   the reason a message fails to arrive.
3. **Leave a correct field alone.** That is what makes the shim safe to keep
   after upstream is fixed, and what makes `--verbose` a retirement signal.
