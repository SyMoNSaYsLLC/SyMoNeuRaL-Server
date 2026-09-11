#!/usr/bin/env python3
"""Operator-side tool for the SyMoNeuRaL Gateway: keys, deployment, quotes.

    ops/gateway/.venv/bin/python ops/gateway/gateway-cli.py <command> --help

## This program is the half that holds a private key, and it is deliberately over here

`backend/gateway/` — the half that runs inside the public-facing web process — cannot
build, sign or broadcast a transaction, has no wallet variable, and `test_gateway.py` asserts
all of that. This file is everything that was kept out of it. The separation is the design,
not an accident of layout, so:

- **Never import this from `backend/`.** The dependency runs one way. This module imports
  `gateway.address` so that an address this tool accepts is exactly an address the rack
  will validate — one implementation of base58check, not two that can drift.
- **It runs from its own venv** (`ops/gateway/.venv`, `tronpy`), never the serving interpreter.
  `.claude/CLAUDE.md` pins the serving path to OS packages and forbids `pip install` into it.
- **It never prints a private key**, and it refuses to read one from a world-readable file.

## Two refusals that come from things that actually happened here

**It will not write a key into `/tmp`.** `.claude/HANDOVER.md` §5 item 0: the contract signing
key's private half lived in `/tmp` and did not survive a reboot. The repo can currently verify
contracts nobody can sign. That is a cheap mistake to make once and this makes it hard to make
twice.

**It will not touch mainnet without `--yes-mainnet`.** Nile and Shasta cost nothing; mainnet
moves real USDT. The gateway module already forces the network name into every line the rack
prints, for the same reason.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import stat
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent                      # <repo>/ops/gateway -> <repo>

# ---------------------------------------------------------------- borrowing the leaf modules
#
# We want ONE implementation of base58check and one `NODES` map, so that an address this tool
# accepts is exactly an address the rack validates and both talk to the same endpoints. But a
# plain `import gateway.lib.address` executes the package `__init__`, which imports
# `routes.py`, which imports FastAPI — and this venv deliberately does not have FastAPI in it.
#
# That import error is the design working. The operator tool must not drag the public web
# surface in behind it. So the leaf modules are loaded directly, under a private package name
# whose `__path__` lets `chain.py`'s `from . import abi, address` resolve normally.
#
# The one-way rule stands: this file may read `backend/gateway`; nothing there may ever
# read this file.
import importlib.util                                                        # noqa: E402
import types                                                                 # noqa: E402

_GW = ROOT / "backend" / "apps" / "gateway"
_pkg = types.ModuleType("_symgw")
_pkg.__path__ = [str(_GW)]
sys.modules["_symgw"] = _pkg


def _leaf(name: str):
    spec = importlib.util.spec_from_file_location(f"_symgw.{name}", _GW / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"_symgw.{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


tron_address = _leaf("address")
_keccak = _leaf("keccak")
NODES = _leaf("chain").NODES

# The secp256k1 group order. Only used to check that a signature we are about to hand a buyer
# satisfies the same malleability bound `SymoneuralLicence._recover` enforces.
_SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141

try:
    from tronpy import Tron
    from tronpy.keys import PrivateKey
    from tronpy.providers import HTTPProvider
except ImportError:                            # pragma: no cover - operator-facing message
    sys.exit("tronpy is missing. Run:  ops/gateway/setup.sh\n"
             "It builds ops/gateway/.venv; this tool must never run from the serving "
             "interpreter (.claude/CLAUDE.md).")


def _client(network: str) -> Tron:
    """A tronpy client pinned to the same endpoints the rack reads from.

    `NODES` is imported rather than copied so that the tool and the surface can never be
    pointed at different nodes while reporting the same network name.
    """
    if network not in NODES:
        sys.exit(f"unknown network {network!r} — expected one of {', '.join(NODES)}")
    provider = HTTPProvider(NODES[network][1])
    return Tron(provider=provider, network="mainnet" if network == "mainnet" else network)


def _guard_mainnet(args) -> None:
    if args.network == "mainnet" and not getattr(args, "yes_mainnet", False):
        sys.exit("refusing: --network mainnet moves real money. Rehearse on nile first, then "
                 "pass --yes-mainnet if you genuinely mean it.")


def _load_key(path: Path) -> PrivateKey:
    if not path.exists():
        sys.exit(f"no key at {path}. Generate one with:  gateway-cli.py keygen --out {path}")
    mode = path.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        sys.exit(f"refusing: {path} is readable by group or other ({stat.filemode(mode)}). "
                 f"Run: chmod 600 {path}")
    raw = path.read_text().strip()
    try:
        return PrivateKey(bytes.fromhex(raw))
    except Exception as e:
        sys.exit(f"{path} is not a 64-character hex private key: {e}")


def _artifact(name: str) -> dict:
    p = HERE / "artifacts" / f"{name}.json"
    if not p.exists():
        sys.exit(f"no artefact for {name}. Build them first:  cd ops/gateway && node build.mjs")
    return json.loads(p.read_text())


# --------------------------------------------------------------------------------- keygen


def cmd_keygen(args) -> int:
    out = Path(args.out).expanduser()
    # The lesson from the lost signing key, enforced rather than written down again.
    if str(out).startswith("/tmp/") or str(out).startswith("/var/tmp/"):
        sys.exit("refusing to write a private key under /tmp — that is exactly how the "
                 "contract signing key was lost (.claude/HANDOVER.md §5 item 0).")
    if out.exists():
        sys.exit(f"refusing to overwrite {out}. A key file is not a thing to clobber.")

    key = PrivateKey.random()
    out.parent.mkdir(parents=True, exist_ok=True)
    # 0600 from the moment it exists: written through an fd opened with the right mode, not
    # written and then chmod'ed, which leaves a window where it is world-readable.
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(key.hex())
    pub = out.with_suffix(out.suffix + ".address") if out.suffix else Path(str(out) + ".address")
    pub.write_text(key.public_key.to_base58check_address() + "\n")

    print(f"private key   {out}   (0600, and it is the only copy — back it up now)")
    print(f"address       {key.public_key.to_base58check_address()}")
    print(f"              also written to {pub}")
    print()
    print("This address holds no funds and is not yet known to any chain. Next:")
    print("  1. fund it from a testnet faucet — https://nileex.io/join/getJoinPage")
    print("  2. gateway-cli.py balance --network nile --address <the address above>")
    print()
    print("The private key never goes into ops/units/symoneural-api.service, any systemd drop-in, "
          "or any file the web process can read.")
    return 0


# -------------------------------------------------------------------------------- balance


def cmd_balance(args) -> int:
    why = tron_address.reason(args.address)
    if why:
        sys.exit(f"{args.address} is not a valid TRON address: {why}")
    client = _client(args.network)
    try:
        trx = client.get_account_balance(args.address)
    except Exception as e:
        # An address the chain has never seen is not an error worth a stack trace; it is the
        # normal state of a freshly generated key, and saying so is more use than raising.
        print(f"{NODES[args.network][0]} · {args.address}")
        print(f"  balance   0 TRX — the chain has no record of this account ({e.__class__.__name__})")
        print("  A TRON account comes into existence when it first receives funds. Use the faucet.")
        return 1
    res = {}
    try:
        res = client.get_account_resource(args.address)
    except Exception:
        pass
    energy = res.get("EnergyLimit", 0) - res.get("EnergyUsed", 0)
    band = (res.get("freeNetLimit", 0) - res.get("freeNetUsed", 0)
            + res.get("NetLimit", 0) - res.get("NetUsed", 0))
    print(f"{NODES[args.network][0]} · {args.address}")
    print(f"  balance   {trx} TRX")
    print(f"  energy    {energy:,}")
    print(f"  bandwidth {band:,}")
    if trx < 1000:
        print("\n  A contract deployment burns TRX for Energy. Under ~1000 TRX on a testnet is "
              "likely to fail mid-deploy; top up from the faucet.")
    return 0


# --------------------------------------------------------------------------------- deploy


def cmd_deploy(args) -> int:
    _guard_mainnet(args)
    art = _artifact(args.contract)
    key = _load_key(Path(args.key).expanduser())
    owner = key.public_key.to_base58check_address()
    client = _client(args.network)

    params = []
    if args.contract == "SymoneuralLicence":
        for label, value in (("--quote-signer", args.quote_signer),
                             ("--beneficiary", args.beneficiary)):
            if not value:
                sys.exit(f"SymoneuralLicence needs {label}")
            why = tron_address.reason(value)
            if why:
                sys.exit(f"{label} {value} is not a valid TRON address: {why}")
        params = [args.quote_signer, args.beneficiary]

    print(f"network       {NODES[args.network][0]}  ({NODES[args.network][1]})")
    print(f"contract      {args.contract}  ({len(art['bytecode']) // 2:,} bytes, "
          f"{art['compiler']}, evm {art['evmVersion']})")
    print(f"deployer      {owner}")
    if params:
        print(f"constructor   quoteSigner={params[0]}  beneficiary={params[1]}")
    print(f"fee limit     {args.fee_limit:,} SUN ({args.fee_limit / 1_000_000:.0f} TRX)")
    if args.dry_run:
        print("\n--dry-run: nothing was broadcast.")
        return 0
    if args.network == "mainnet":
        if getpass.getuser() and input("\nType MAINNET to continue: ").strip() != "MAINNET":
            sys.exit("aborted.")

    txb = client.trx.deploy_contract(owner, {
        "abi": {"entrys": art["abi"]},
        "bytecode": art["bytecode"],
        "owner_address": owner,
        "name": args.contract,
        "parameters": params,
    })
    txb = txb.fee_limit(args.fee_limit)
    tx = txb.build().sign(key)
    result = tx.broadcast()
    print(f"\nbroadcast     {tx.txid}")
    receipt = result.wait(timeout=90)
    ok = receipt.get("receipt", {}).get("result") == "SUCCESS"
    addr = receipt.get("contract_address")
    if addr and not addr.startswith("T"):
        addr = tron_address.from_hex(addr)
    print(f"result        {'SUCCESS' if ok else receipt.get('receipt')}")
    print(f"block         {receipt.get('blockNumber')}")
    print(f"energy used   {receipt.get('receipt', {}).get('energy_usage_total', 0):,}")
    if not ok:
        print("\nThe deployment did not succeed. Nothing is deployed; nothing needs undoing.")
        return 1
    print(f"\ncontract      {addr}")
    print("\nVerify it independently — this tool saying SUCCESS is not the same as the chain "
          "agreeing:")
    print(f"  SYMONEURAL_GATEWAY_NETWORK={args.network} SYMONEURAL_GATEWAY_CONTRACT={addr} \\")
    print(f"    python3 -c \"from gateway.lib import chain; "
          f"print(chain.probe('{args.network}', '{addr}'))\"")
    return 0


# --------------------------------------------------------------------------------- inspect


def cmd_inspect(args) -> int:
    why = tron_address.reason(args.contract)
    if why:
        sys.exit(f"{args.contract} is not a valid TRON address: {why}")
    client = _client(args.network)
    art = _artifact("SymoneuralLicence")
    c = client.get_contract(args.contract)
    c.abi = art["abi"]
    print(f"{NODES[args.network][0]} · {args.contract}")
    for fn in ("owner", "quoteSigner", "beneficiary", "paused", "licenceCount"):
        try:
            print(f"  {fn:<14} {c.functions[fn]()}")
        except Exception as e:
            print(f"  {fn:<14} unreadable: {e.__class__.__name__}: {e}")
    return 0


# ----------------------------------------------------------------------------------- quote


def cmd_quote(args) -> int:
    """Sign one licence quote. This is where 'quoted, not published' actually happens.

    The digest is **read back out of the deployed contract** rather than recomputed here. It
    would be easy to reimplement `abi.encode(chainid, address(this), …)` in Python and it would
    be wrong in a way nothing catches until a real buyer's transaction reverts: TRON's CHAINID
    is not the number people assume. Asking the contract removes the guess — the same reason
    `test_contracts.mjs` calls `quoteDigest` instead of rebuilding the layout.
    """
    _guard_mainnet(args)
    key = _load_key(Path(args.key).expanduser())
    client = _client(args.network)
    for label, value in (("--contract", args.contract), ("--payer", args.payer),
                         ("--token", args.token)):
        why = tron_address.reason(value)
        if why:
            sys.exit(f"{label} {value} is not a valid TRON address: {why}")

    art = _artifact("SymoneuralLicence")
    c = client.get_contract(args.contract)
    c.abi = art["abi"]

    signer_on_chain = c.functions["quoteSigner"]()
    mine = key.public_key.to_base58check_address()
    if signer_on_chain != mine:
        sys.exit(f"refusing: the contract's quoteSigner is {signer_on_chain}, but this key is "
                 f"{mine}. A quote signed with the wrong key reverts at the buyer's expense.")

    workspace = args.workspace
    if not workspace.startswith("0x"):
        workspace = "0x" + _keccak.keccak256(workspace.encode()).hex()
    expiry = int(time.time()) + args.hours * 3600
    nonce = args.nonce if args.nonce is not None else int(time.time() * 1000)

    digest = c.functions["quoteDigest"](args.payer, nonce, args.token, args.amount,
                                        workspace, expiry)
    if isinstance(digest, str):
        digest = bytes.fromhex(digest.removeprefix("0x"))
    sig = key.sign_msg_hash(digest)

    # `_recover` rejects an s in the upper half of the curve order, so a high-s quote reverts —
    # and it reverts at the buyer's expense, reading like a contract bug rather than a signer
    # one. tronpy 0.6.2 hard-depends on coincurve (libsecp256k1), which normalises, and 500
    # signatures were measured low-s; but that is a transitive pin, and the pure-Python `ecdsa`
    # fallback does not normalise. Check the property rather than trusting the dependency —
    # test_contracts.mjs signs with @noble/curves, so the suite would never catch this.
    if sig.s > _SECP256K1_N // 2:
        sys.exit("refusing to emit this quote: the signature's s is in the upper half of the "
                 "curve order, which the contract rejects. The signing backend is not "
                 "normalising — check that coincurve is installed in this venv.")

    quote = {
        "network": args.network, "contract": args.contract, "payer": args.payer,
        "nonce": nonce, "token": args.token, "amount": args.amount,
        "workspace": workspace, "expiry": expiry,
        "signature": "0x" + bytes(sig).hex(),
    }
    print(json.dumps(quote, indent=2))
    print(f"\n# expires {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expiry))} "
          f"({args.hours}h). One nonce, one licence — this quote cannot be redeemed twice.",
          file=sys.stderr)
    print("# The amount is not published anywhere: it exists in this quote and, once redeemed, "
          "in one settled transaction.", file=sys.stderr)
    return 0


# ------------------------------------------------------------------------------------ main


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="gateway-cli.py", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def net(sp, mainnet_flag=True):
        sp.add_argument("--network", default="nile", choices=sorted(NODES))
        if mainnet_flag:
            sp.add_argument("--yes-mainnet", action="store_true",
                            help="required to touch mainnet, which moves real money")

    k = sub.add_parser("keygen", help="generate an operator keypair (never under /tmp)")
    k.add_argument("--out", required=True, help="path for the private key, e.g. ~/symoneural-gateway")
    k.set_defaults(fn=cmd_keygen)

    b = sub.add_parser("balance", help="TRX, Energy and Bandwidth for an address")
    net(b, mainnet_flag=False)
    b.add_argument("--address", required=True)
    b.set_defaults(fn=cmd_balance)

    d = sub.add_parser("deploy", help="deploy a compiled artefact")
    net(d)
    d.add_argument("--key", required=True)
    d.add_argument("--contract", required=True, choices=["MockTRC20", "SymoneuralLicence"])
    d.add_argument("--quote-signer", help="SymoneuralLicence: the address whose signature validates a quote")
    d.add_argument("--beneficiary", help="SymoneuralLicence: where fees land")
    d.add_argument("--fee-limit", type=int, default=1_000_000_000, help="SUN; 1000 TRX default")
    d.add_argument("--dry-run", action="store_true", help="print the plan and broadcast nothing")
    d.set_defaults(fn=cmd_deploy)

    i = sub.add_parser("inspect", help="read a deployed licence contract's public state")
    net(i, mainnet_flag=False)
    i.add_argument("--contract", required=True)
    i.set_defaults(fn=cmd_inspect)

    q = sub.add_parser("quote", help="sign one licence quote")
    net(q)
    q.add_argument("--key", required=True)
    q.add_argument("--contract", required=True)
    q.add_argument("--payer", required=True, help="the only address that may redeem this quote")
    q.add_argument("--token", required=True, help="the TRC-20 the fee is denominated in")
    q.add_argument("--amount", type=int, required=True, help="in the token's base units")
    q.add_argument("--workspace", required=True,
                   help="the build configuration this licence covers; hashed unless given as 0x…")
    q.add_argument("--hours", type=int, default=48)
    q.add_argument("--nonce", type=int, default=None)
    q.set_defaults(fn=cmd_quote)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
