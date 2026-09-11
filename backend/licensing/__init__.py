"""SyMoNeuRaL licensing — a dev fee that the operator can always read.

Modelled on the shape Braiins uses in `bos-plus-api` (`proto/bos/v1/license.proto`), because
the shape is good: the fee lives in the licence rather than the binary, licences are named
contracts, types split standard from negotiated, and an expired licence degrades on a timer
instead of stopping the machine. None of their code is used — this is our own
implementation, and it talks to nothing of theirs.

## The one rule this module exists to enforce

**A dev fee that the operator can read is a business model. A dev fee they cannot is
malware.** Mining firmware that quietly redirects a slice of hashrate is the single most
common way this feature is abused, and it is indistinguishable from theft at the wire level.

So disclosure is not a UI decision here, it is structural:

- The rate is **only** ever what a signed contract says. There is no default, no fallback and
  no constant in this file that could become a rate.
- `disclosure()` returns the full terms in one call and is wired to the public status
  endpoint, so a rig cannot be running a fee that the panel is not showing.
- The signed payload is returned verbatim alongside the parsed view, so an operator can
  verify our arithmetic rather than trust it.

That matches the rest of this project: publish the numbers, keep the methods.

## Contract keys are verified offline

    SYMN1.<base64url(payload json)>.<base64url(ed25519 signature)>

Ed25519 over the exact payload bytes, checked against a public key that ships with the
software. Signing needs the private key, which lives only where contracts are issued and
must never be on a rig or in the environment of a web process.

Offline verification is the point: a rig in a warehouse with no route to us still knows
whether its licence is valid, and we learn nothing about when or where it runs. A
licence server that has to be reachable is a licence server that fails closed in a power cut.

`openssl` does the crypto by exec, exactly as `backend/asicminer/fwcheck.py` does and as
Bitmain's own `runme.sh` does. The serving interpreter carries seven packages and none of
them do asymmetric crypto; adding one for this would break a deliberate constraint.

## What this module does NOT do

**It does not collect anything.** There is no hashrate diversion, no pool substitution and no
share redirection here, and none is implied by the presence of a rate. Collection has to
happen inside whatever mining engine actually runs, which this box does not have. Reporting a
fee as *collected* when nothing collects it would be exactly the kind of unearned claim the
rest of this site exists to argue against.

What is implemented is the licence model and its accounting: issue, verify, expire, degrade,
and disclose.
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import subprocess
import time

HERE = pathlib.Path(__file__).resolve().parent
PUBKEY = HERE / "contract-signing.pub"

KEY_PREFIX = "SYMN1"

# A basis point is one hundredth of one percentage point: 1 bps = 0.01%, 250 bps = 2.5%.
# Same unit Braiins uses, chosen for the same reason -- it makes a fraction of a percent
# expressible without floating point, so a rate can never drift in serialisation.
BPS_MAX = 10_000                     # 100%. A contract above this is malformed, not greedy.

# How long an expired contract keeps running before it is restricted. Degrading beats
# stopping: a fleet that halts at midnight on expiry costs an operator more than the licence
# is worth, and makes the vendor the cause of the outage.
GRACE_SECONDS = 14 * 24 * 3600

STATE_NONE = "none"          # no contract present
STATE_VALID = "valid"        # signed, in date
STATE_EXPIRED = "expired"    # signed, past expiry, still inside the grace window
STATE_RESTRICTED = "restricted"   # past expiry and past grace
STATE_INVALID = "invalid"    # present but failed verification -- never treated as valid


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _verify(payload: bytes, sig: bytes, pubkey: pathlib.Path) -> bool:
    """Ed25519 verify by exec. Returns False on any failure, never raises."""
    if not pubkey.is_file():
        return False
    import tempfile
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="symlic-"))
    try:
        (tmp / "p").write_bytes(payload)
        (tmp / "s").write_bytes(sig)
        r = subprocess.run(
            ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(pubkey),
             "-rawin", "-in", str(tmp / "p"), "-sigfile", str(tmp / "s")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return r.returncode == 0
    except Exception:
        return False
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def parse(contract_key: str, pubkey: pathlib.Path | None = None,
          now: float | None = None) -> dict:
    """Verify a contract key and return its state. Never raises, never guesses.

    An unverifiable key is `invalid`, which is deliberately NOT the same as `none`: silently
    treating a tampered contract as "no licence" would hide the tampering, and treating it as
    valid would make the signature decorative.
    """
    now = time.time() if now is None else now
    pubkey = PUBKEY if pubkey is None else pubkey
    out = {
        "state": STATE_NONE, "contract": None, "type": None,
        "dev_fee_bps": None, "dev_fee_percent": None,
        "issued_at": None, "expires_at": None,
        "seconds_to_expiry": None, "seconds_to_restricted": None,
        "payload": None, "error": None,
    }
    if not contract_key or not contract_key.strip():
        return out

    parts = contract_key.strip().split(".")
    if len(parts) != 3 or parts[0] != KEY_PREFIX:
        return {**out, "state": STATE_INVALID,
                "error": f"not a {KEY_PREFIX} contract key"}
    try:
        raw = _b64d(parts[1])
        sig = _b64d(parts[2])
        body = json.loads(raw)
    except Exception as e:
        return {**out, "state": STATE_INVALID,
                "error": f"malformed contract key: {e.__class__.__name__}"}

    if not _verify(raw, sig, pubkey):
        return {**out, "state": STATE_INVALID,
                "error": "signature does not verify against the shipped public key"}

    bps = body.get("dev_fee_bps")
    if not isinstance(bps, int) or not (0 <= bps <= BPS_MAX):
        return {**out, "state": STATE_INVALID,
                "error": f"dev_fee_bps must be an integer 0..{BPS_MAX}, got {bps!r}"}

    issued, expires = body.get("issued_at"), body.get("expires_at")
    if not isinstance(expires, (int, float)):
        return {**out, "state": STATE_INVALID, "error": "contract has no expiry"}

    to_expiry = expires - now
    restricted_at = expires + GRACE_SECONDS
    state = (STATE_VALID if to_expiry > 0
             else STATE_EXPIRED if now < restricted_at
             else STATE_RESTRICTED)

    return {
        "state": state,
        "contract": body.get("contract"),
        "type": body.get("type"),
        "dev_fee_bps": bps,
        # Printed as well as stored. bps/100 is exact for every integer bps, so this is a
        # rendering of the same number rather than a second, drifting source of truth.
        "dev_fee_percent": round(bps / 100, 2),
        "issued_at": issued,
        "expires_at": expires,
        "seconds_to_expiry": int(to_expiry),
        "seconds_to_restricted": int(restricted_at - now),
        "payload": body,          # verbatim, so the operator can check our arithmetic
        "error": None,
    }


def current(now: float | None = None) -> dict:
    """The licence this installation is running under, from SYMONEURAL_CONTRACT_KEY."""
    return parse(os.environ.get("SYMONEURAL_CONTRACT_KEY", ""), now=now)


def disclosure(lic: dict | None = None) -> dict:
    """Everything an operator is entitled to know, in one call.

    Wired to the public status endpoint on purpose. If the fee is running, this is showing
    it; there is no code path where a rate applies and this returns nothing.
    """
    lic = current() if lic is None else lic
    st = lic["state"]
    return {
        "state": st,
        "contract": lic["contract"],
        "type": lic["type"],
        "dev_fee_bps": lic["dev_fee_bps"],
        "dev_fee_percent": lic["dev_fee_percent"],
        "expires_at": lic["expires_at"],
        "seconds_to_restricted": lic["seconds_to_restricted"],
        "collected": False,
        "collection_note": (
            "This build implements the licence model only. No hashrate is diverted, no pool "
            "is substituted and no shares are redirected by this software — collection would "
            "have to happen inside the mining engine, and this installation has none."
        ),
        "terms": _terms(lic),
        "error": lic["error"],
    }


def _terms(lic: dict) -> str:
    st = lic["state"]
    if st == STATE_NONE:
        return ("No contract key is installed, so no dev fee applies and none is being "
                "charged. Set SYMONEURAL_CONTRACT_KEY to apply one.")
    if st == STATE_INVALID:
        return (f"A contract key is present but did not verify ({lic['error']}). It is being "
                "ignored — an unverifiable contract is never treated as valid, and never "
                "silently treated as absent either.")
    pct = lic["dev_fee_percent"]
    who = f"contract “{lic['contract']}”" if lic["contract"] else "this contract"
    if st == STATE_VALID:
        return (f"{who} sets a dev fee of {pct}% ({lic['dev_fee_bps']} bps). "
                f"It is signed, in date, and readable here at any time.")
    if st == STATE_EXPIRED:
        d = max(0, lic["seconds_to_restricted"]) // 86400
        return (f"{who} expired. The {pct}% rate still stands and the machine keeps running "
                f"for about {d} more day(s) before it is restricted, rather than stopping "
                f"at the moment of expiry.")
    return (f"{who} expired and the grace period is over, so this installation is "
            f"restricted. The rate on the contract was {pct}%.")
