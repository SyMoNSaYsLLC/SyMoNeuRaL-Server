"""Read-only TRON node client. Stdlib `urllib` only, no wallet, no key, no signature.

## The one rule this file exists to hold

**A gateway that cannot verify says `offline`, and says which failure it was.** Unreachable
node, non-200, rate limit, DNS failure, timeout, truncated body, malformed JSON, empty
result -- every one of them is a failure, and `probe()` returns it as an `error` string. No
`except` anywhere in this package may return an affirmative reading. `docs/specs/
symon-ml-review.md` finding 1 is a licence check that fell back to `return True` when the
TRON lookup did not answer, so blocking the endpoint *granted* the licence. That is the exact
shape this file must never grow, and this is the file where someone would grow it.

## Why no wallet is involved

`wallet/getnowblock` and `wallet/getcontract` are unauthenticated reads. Despite the path
prefix they take no wallet, no key and no signature -- the prefix is TRON's naming, not an
authentication boundary. `triggerconstantsmartcontract` is likewise evaluated by the node and
never broadcast; it needs an `owner_address` only as the `msg.sender` the EVM should pretend
to, and a contract's own address serves for a read. So the whole of this file runs on public
data with nothing secret in the process.

## Structural safety

- **Endpoints come from `NODES`, keyed by an already-validated network name.** There is no
  `SYMONEURAL_GATEWAY_NODE_URL` and there must never be one: an env-supplied URL turns a
  public-facing web process into an arbitrary-URL fetcher pointed at whatever an operator --
  or anyone who can write that environment -- puts there.
- **HTTPS only, host checked against the map at call time**, so a mistake in a literal cannot
  quietly become a plaintext or off-host request.
- **Redirects are refused, not followed.** A 3xx from a node is a misconfiguration or an
  interception, and following it is how an allowlisted host becomes an unallowlisted one.
- **The body is read to a cap.** A contract ABI is legitimately large; unbounded is how a
  status refresher becomes a memory incident.
- **No caller-supplied host, path or method reaches this.** The router serves the cache and
  never triggers a fetch.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from . import abi, address

# Display name and endpoint, together, so the two cannot drift apart. Mainnet is present
# because pointing at it must be possible; it is never the default, and every detail line the
# rack prints names the network -- a gateway that does not say which chain it is on is one
# misconfiguration away from taking real USDT while everyone believes it is a test.
NODES = {
    "shasta": ("Shasta testnet", "https://api.shasta.trongrid.io"),
    "nile": ("Nile testnet", "https://nile.trongrid.io"),
    "mainnet": ("TRON mainnet", "https://api.trongrid.io"),
}

ALLOWED_HOSTS = frozenset(u.split("://", 1)[1] for _, u in NODES.values())

# The names an operator types, and the chain each one means. Deliberately NOT keys in `NODES`:
# that dict is iterated as the set of DISTINCT chains -- gateway/__main__.py:86 probes every
# entry and settlement/record.py:141 offers them as CLI choices -- so aliases in there would
# probe the same chain twice and offer six options for three networks. This maps one way only,
# and test_gateway.py pins its values to exactly `NODES`\' keys so the two cannot drift.
#
# TRON\'s own names (nile, shasta, mainnet) are not accepted from an operator. One vocabulary,
# so a value that reads as configured cannot mean a chain nobody chose. What this does NOT do
# is hide which chain is live: every rack detail line prints `NODES[net][0]` -- "TRON mainnet",
# "Nile testnet" -- for the reason argued above, and a house name in front of it changes
# nothing about that.
OPERATOR_NETWORKS = {
    "symoneural-live": "mainnet",        # real USDT, irreversible, real money
    "symoneural-test": "nile",           # Nile testnet -- fake money, the current one
    "symoneural-test-old": "shasta",     # Shasta testnet -- fake money, older
}

TIMEOUT = 8.0            # per request; the refresher runs off the status path either way
MAX_BYTES = 512 * 1024   # a real TRC-20 ABI is a few KB; this is a backstop, not a budget
USER_AGENT = "SyMoNeuRaL-Gateway/1 (+https://symoneural.com/gateway.html)"


class ChainError(Exception):
    """Every failure to read the chain. Callers turn it into an `offline` detail line."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ChainError(f"node redirected ({code}) to {newurl.split('?')[0]} — refused")


_OPENER = urllib.request.build_opener(_NoRedirect)


def http_post(url: str, body: bytes, timeout: float) -> tuple[int, bytes]:
    """The only outbound call in this package. Replaced wholesale by the tests.

    Injectable so that every branch above it -- timeout, non-200, truncation, bad JSON,
    absent contract, present contract -- is exercised deterministically and **offline**.
    `.claude/HANDOVER.md` §3.0d is a list of verification steps that failed on healthy input;
    a suite that needs egress to pass is the next one.
    """
    host = url.split("://", 1)[1].split("/", 1)[0]
    if not url.startswith("https://") or host not in ALLOWED_HOSTS:
        raise ChainError(f"refusing to call {host} — not a configured TRON node")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": USER_AGENT},
    )
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            raw = resp.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ChainError(f"response exceeded {MAX_BYTES} bytes")
            return resp.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read(MAX_BYTES)
    except ChainError:
        raise
    except Exception as e:                       # timeout, DNS, TLS, reset -- all failures
        raise ChainError(f"{e.__class__.__name__}: {e}") from e


def call(network: str, path: str, payload: dict, *, fetch=None, timeout: float = TIMEOUT) -> dict:
    """POST a node JSON endpoint and return the parsed object. Raises `ChainError` only."""
    if network not in NODES:
        raise ChainError(f"unknown network {network!r}")
    url = f"{NODES[network][1]}/{path.lstrip('/')}"
    # The transport's failures are normalised HERE, not only inside `http_post`, so that the
    # contract is the same whichever transport is in play: everything out of this function is
    # a ChainError. Without this an injected transport could raise a bare exception straight
    # into `/api/status` -- and the tests would be exercising a different failure shape from
    # the one production has, which is how a suite ends up proving the wrong thing.
    try:
        status, raw = (fetch or http_post)(url, json.dumps(payload).encode(), timeout)
    except ChainError:
        raise
    except Exception as e:
        raise ChainError(f"{e.__class__.__name__}: {e}") from e
    if status == 429:
        raise ChainError("node rate-limited this box (HTTP 429)")
    if status != 200:
        raise ChainError(f"node answered HTTP {status}")
    try:
        out = json.loads(raw.decode())
    except (ValueError, UnicodeDecodeError) as e:
        raise ChainError(f"node returned unparseable JSON: {e}") from e
    if not isinstance(out, dict):
        raise ChainError(f"node returned {type(out).__name__}, expected an object")
    # TronGrid reports application errors inside a 200. Treat them as failures, never as
    # an empty-but-fine reading.
    if out.get("Error"):
        raise ChainError(f"node reported: {str(out['Error'])[:120]}")
    return out


def head_block(network: str, *, fetch=None, timeout: float = TIMEOUT) -> tuple[int, int]:
    """(block number, block timestamp in ms). No wallet, no key.

    `getblock` with `detail: false`, **not** `getnowblock`. Measured 2026-08-17 from this
    box: the head block over `getnowblock` is 533,846 bytes on mainnet because it carries
    every transaction in the block, against 542 bytes for the header alone -- a thousandfold
    difference to read one integer, once a minute, forever. It was not noticed on a testnet
    (Nile 3,621 B, Shasta 541 B) and it was the size cap in `http_post` that surfaced it: the
    probe correctly reported "cannot verify", which is what a fail-closed design buys you.
    """
    out = call(network, "wallet/getblock", {"detail": False}, fetch=fetch, timeout=timeout)
    hdr = (out.get("block_header") or {}).get("raw_data") or {}
    num, ts = hdr.get("number"), hdr.get("timestamp")
    if not isinstance(num, int):
        raise ChainError("node answered without a block number")
    return num, ts if isinstance(ts, int) else 0


def contract_at(network: str, addr: str, *, fetch=None, timeout: float = TIMEOUT) -> dict | None:
    """The deployed contract at `addr`, or `None` when nothing is deployed there.

    The node answers `{}` for an address with no contract. That is the clean, keyless,
    fail-closed-by-nature probe this surface is built on: absent is `None`, unreachable
    raises, and neither can be mistaken for present.
    """
    out = call(network, "wallet/getcontract", {"value": addr, "visible": True},
               fetch=fetch, timeout=timeout)
    if not out or not out.get("contract_address"):
        return None
    return out


def constant_call(network: str, addr: str, signature: str, types: list[str] | None = None,
                  values: list | None = None, *, caller: str | None = None,
                  fetch=None, timeout: float = TIMEOUT) -> str:
    """Evaluate a view function on the node and return the raw result words.

    Nothing is broadcast and nothing is signed -- `owner_address` is only the `msg.sender`
    the EVM is told to assume, and defaults to the contract itself so that no wallet is
    needed or implied. Decode the return with `abi.decode_params`.
    """
    payload = {
        "owner_address": caller or addr,
        "contract_address": addr,
        "function_selector": signature,
        "parameter": abi.encode_params(types or [], values or []),
        "visible": True,
    }
    # `triggerconstantcontract`, NOT `triggersmartcontract`. The names are one word apart and
    # they are opposites: the constant one is evaluated by the node and thrown away, the other
    # BUILDS A TRANSACTION for signing and broadcast. Measured, 2026-08-17: the wrong-but-
    # plausible `triggerconstantsmartcontract` answers 405, and `triggersmartcontract` answers
    # 200 with an unsigned transaction -- so a typo here fails loudly, but a copy-paste from
    # the write side would quietly put this module on the transaction path. Nothing in this
    # package may build, sign or broadcast a transaction; `test_gateway.py` asserts it.
    out = call(network, "wallet/triggerconstantcontract", payload,
               fetch=fetch, timeout=timeout)
    result = out.get("result") or {}
    if result.get("result") is not True:
        msg = result.get("message") or out.get("message") or "call was not successful"
        try:
            msg = bytes.fromhex(msg).decode()
        except (ValueError, UnicodeDecodeError):
            pass
        raise ChainError(f"{signature} reverted: {str(msg)[:120]}")
    words = out.get("constant_result") or []
    if not words:
        raise ChainError(f"{signature} returned no data")
    return words[0]


def probe(network: str, addr: str, *, fetch=None, timeout: float = TIMEOUT) -> dict:
    """One reading of the chain, for the rack. **Never raises, and never fails open.**

    Every exit either carries a real measurement or an `error` naming what went wrong.
    There is no branch that returns a reading implying the contract is live without having
    read it, and no `except` that returns anything other than an error. If you are here to
    add a fallback: do not. See the module docstring and `symon-ml-review.md` finding 1.
    """
    started = time.monotonic()
    r = {
        "network": network, "endpoint": NODES.get(network, (None, None))[1],
        "contract": addr, "at": time.time(), "elapsed_ms": None, "error": None,
        "block": None, "block_ts_ms": None,
        "contract_present": None, "contract_name": None, "abi_functions": None,
    }

    def done(err: str | None = None) -> dict:
        r["error"] = err
        r["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        return r

    if network not in NODES:
        return done(f"unknown network {network!r}")
    if not address.valid(addr):
        return done(f"contract address {address.reason(addr)}")

    try:
        r["block"], r["block_ts_ms"] = head_block(network, fetch=fetch, timeout=timeout)
    except ChainError as e:
        return done(str(e))
    except Exception as e:               # a bug here is still a failure to verify
        return done(f"{e.__class__.__name__}: {e}")

    try:
        found = contract_at(network, addr, fetch=fetch, timeout=timeout)
    except ChainError as e:
        return done(str(e))
    except Exception as e:
        return done(f"{e.__class__.__name__}: {e}")

    if found is None:
        r["contract_present"] = False
        return done()
    r["contract_present"] = True
    r["contract_name"] = found.get("name") or None
    entries = (found.get("abi") or {}).get("entrys")
    if isinstance(entries, list):
        r["abi_functions"] = sum(1 for e in entries if e.get("type") == "Function")
    return done()
