#!/usr/bin/env python3
"""Mint and inspect SyMoNeuRaL contract keys.

**This is an operator tool. It needs the private signing key, which must never exist on a
rig, in a customer image, or in the environment of a public-facing web process.** The rig
side ships only `contract-signing.pub` and verifies offline.

    # once, on a machine that is not this one if you can help it
    python3 issue.py keygen --out ./contract-signing

    # a standard contract -- 2.5%, the agreed rate, applied without retyping it
    python3 issue.py sign --key ./contract-signing.key \\
        --contract "Warehouse A" --days 365

    # a negotiated one. --fee-bps is REQUIRED here: an unstated custom rate is a
    # contradiction, and inheriting the standard rate silently is how a "custom" deal
    # quietly becomes the list price.
    python3 issue.py sign --key ./contract-signing.key \\
        --contract "Fleet — 4,000 rigs" --type custom --fee-bps 150 --days 365

    # what a key actually says, using only the public half
    python3 issue.py show "SYMN1.eyJ...."

The standard rate lives in this file and nowhere else. `licensing/__init__.py` — the half
that runs on a rig — still has no rate in it at all, so a machine reads its fee from a
signed contract or has no fee. That separation is the point: a default in the verifier
would be a number a tampered or missing contract could silently fall back to.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import licensing  # noqa: E402

# The standard rate: 2.5%, chosen by Garrett on 2026-08-17 to match Braiins' headline.
#
# It lives HERE, in the issuing tool, and deliberately not in `licensing/__init__.py`. The
# verifier must never carry a rate: a rig reads its fee from the signed contract or it has
# no fee at all, so a tampered or absent contract can never quietly fall back to a number.
# This constant only saves retyping when minting a standard contract.
#
# Sourced, because it is a competitive claim and this project labels those. From
# braiins.com/os-firmware: the headline is "2.5% dev fee", but the FAQ on the same page says
# "we collect a 2-2.5% dev fee (depending on the hardware model)". So 2.5% matches their
# CEILING, not a flat rate they charge everywhere -- on some hardware Braiins is cheaper than
# this. Worth knowing before "same as Braiins" is used in any customer-facing copy, because
# it is true of the headline and not of every rig.
#
# And the comparison is against Braiins, not against Bitmain. Stock Antminer firmware has no
# dev fee: bmminer extracted from the S17 Pro rootfs carries no hardcoded pool (only the bare
# "stratum+tcp://" scheme string it uses to parse the operator's own URL) and no devfee or
# donation strings at all. So this is not "replacing Bitmain's fee" -- stock takes 0%, and a
# dev fee is something custom firmware adds. The honest pitch is 2.5% against Braiins' 2-2.5%.
STANDARD_FEE_BPS = 250


def keygen(out: pathlib.Path) -> int:
    priv, pub = out.with_suffix(".key"), out.with_suffix(".pub")
    if priv.exists():
        print(f"refusing to overwrite an existing private key at {priv}", file=sys.stderr)
        return 1
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(priv)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    priv.chmod(0o600)
    subprocess.run(["openssl", "pkey", "-in", str(priv), "-pubout", "-out", str(pub)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"private key  {priv}   (0600 — keep it off every rig and out of git)")
    print(f"public key   {pub}    (ship this; copy to backend/licensing/)")
    return 0


def sign(key: pathlib.Path, contract: str, ctype: str, fee_bps: int, days: int) -> int:
    if not (0 <= fee_bps <= licensing.BPS_MAX):
        print(f"--fee-bps must be 0..{licensing.BPS_MAX}", file=sys.stderr)
        return 1
    now = int(time.time())
    body = {
        "v": 1,
        "contract": contract,
        "type": ctype,
        "dev_fee_bps": fee_bps,
        "issued_at": now,
        "expires_at": now + days * 86400,
    }
    # separators and sort_keys so the bytes that get signed are reproducible; the verifier
    # checks the signature against these exact bytes, not against a re-serialisation.
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="symlic-sign-"))
    try:
        (tmp / "p").write_bytes(raw)
        subprocess.run(
            ["openssl", "pkeyutl", "-sign", "-inkey", str(key), "-rawin",
             "-in", str(tmp / "p"), "-out", str(tmp / "s")],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        sig = (tmp / "s").read_bytes()
    except subprocess.CalledProcessError:
        print(f"signing failed — is {key} an ed25519 private key?", file=sys.stderr)
        return 1
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    token = f"{licensing.KEY_PREFIX}.{licensing._b64e(raw)}.{licensing._b64e(sig)}"
    print(token)
    print(f"\n  {contract} · {ctype} · {fee_bps} bps = {fee_bps / 100}% · "
          f"expires {time.strftime('%Y-%m-%d', time.gmtime(body['expires_at']))}",
          file=sys.stderr)
    return 0


def show(token: str, pub: pathlib.Path | None) -> int:
    print(json.dumps(licensing.parse(token, pubkey=pub), indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("keygen", help="create an ed25519 signing keypair")
    g.add_argument("--out", type=pathlib.Path, default=pathlib.Path("./contract-signing"))

    s = sub.add_parser("sign", help="mint a contract key")
    s.add_argument("--key", type=pathlib.Path, required=True)
    s.add_argument("--contract", required=True, help="human-readable contract name")
    s.add_argument("--type", dest="ctype", default="standard",
                   choices=["standard", "custom"])
    s.add_argument("--fee-bps", type=int, default=None,
                   help=f"dev fee in basis points (1 bps = 0.01%%). Omit ONLY with "
                        f"--type standard, which uses {STANDARD_FEE_BPS} bps "
                        f"({STANDARD_FEE_BPS / 100}%%). A custom contract must state its "
                        f"rate explicitly -- that is what makes it custom.")
    s.add_argument("--days", type=int, required=True)

    w = sub.add_parser("show", help="verify and print a contract key")
    w.add_argument("token")
    w.add_argument("--pub", type=pathlib.Path, default=None)

    a = ap.parse_args()
    if a.cmd == "keygen":
        return keygen(a.out)
    if a.cmd == "sign":
        fee = a.fee_bps
        if fee is None:
            if a.ctype != "standard":
                print("--fee-bps is required for a custom contract: a negotiated rate has "
                      "to be stated, not inherited.", file=sys.stderr)
                return 1
            fee = STANDARD_FEE_BPS
        return sign(a.key, a.contract, a.ctype, fee, a.days)
    return show(a.token, a.pub)


if __name__ == "__main__":
    raise SystemExit(main())
