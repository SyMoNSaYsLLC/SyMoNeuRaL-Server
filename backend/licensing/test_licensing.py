#!/usr/bin/env python3
"""Tests for the contract-key licence model. Runs on the system interpreter, no network.

    python3 backend/licensing/test_licensing.py

The tamper cases are the point. A signature that cannot catch someone editing the fee down
to zero is decorative, and a licence model whose failure mode is "silently valid" is worse
than none at all.
"""
from __future__ import annotations

import base64
import json
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

import licensing  # noqa: E402


def _mint(key: pathlib.Path, **body) -> str:
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="t-"))
    (tmp / "p").write_bytes(raw)
    subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", str(key), "-rawin",
                    "-in", str(tmp / "p"), "-out", str(tmp / "s")], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sig = (tmp / "s").read_bytes()
    return f"{licensing.KEY_PREFIX}.{licensing._b64e(raw)}.{licensing._b64e(sig)}"


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = pathlib.Path(tempfile.mkdtemp(prefix="symlic-test-"))
        cls.key = cls.dir / "s.key"
        cls.pub = cls.dir / "s.pub"
        subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(cls.key)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["openssl", "pkey", "-in", str(cls.key), "-pubout", "-out", str(cls.pub)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # a second, unrelated key -- for "signed, but not by us"
        cls.other = cls.dir / "o.key"
        cls.otherpub = cls.dir / "o.pub"
        subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(cls.other)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["openssl", "pkey", "-in", str(cls.other), "-pubout",
                        "-out", str(cls.otherpub)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.now = time.time()

    def good(self, **over):
        b = dict(v=1, contract="Test", type="standard", dev_fee_bps=250,
                 issued_at=int(self.now), expires_at=int(self.now) + 86400)
        b.update(over)
        return _mint(self.key, **b)


class TestValid(Base):
    def test_valid_contract_parses(self):
        r = licensing.parse(self.good(), pubkey=self.pub, now=self.now)
        self.assertEqual(r["state"], licensing.STATE_VALID)
        self.assertEqual(r["dev_fee_bps"], 250)
        self.assertEqual(r["dev_fee_percent"], 2.5)
        self.assertEqual(r["contract"], "Test")

    def test_percent_is_a_rendering_not_a_second_source(self):
        for bps in (0, 1, 7, 99, 250, 1234, 10000):
            r = licensing.parse(self.good(dev_fee_bps=bps), pubkey=self.pub, now=self.now)
            self.assertEqual(r["dev_fee_percent"], round(bps / 100, 2), f"bps={bps}")

    def test_payload_is_returned_verbatim_for_audit(self):
        r = licensing.parse(self.good(), pubkey=self.pub, now=self.now)
        self.assertEqual(r["payload"]["dev_fee_bps"], r["dev_fee_bps"])


class TestTamper(Base):
    """If any of these pass, the signature is decorative."""

    def _edit(self, token: str, **changes) -> str:
        pre, pay, sig = token.split(".")
        body = json.loads(licensing._b64d(pay))
        body.update(changes)
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        return f"{pre}.{licensing._b64e(raw)}.{sig}"      # original signature kept

    def test_editing_the_fee_down_is_caught(self):
        t = self._edit(self.good(), dev_fee_bps=0)
        r = licensing.parse(t, pubkey=self.pub, now=self.now)
        self.assertEqual(r["state"], licensing.STATE_INVALID)
        self.assertIsNone(r["dev_fee_bps"])

    def test_extending_the_expiry_is_caught(self):
        t = self._edit(self.good(), expires_at=int(self.now) + 10 * 365 * 86400)
        self.assertEqual(licensing.parse(t, pubkey=self.pub, now=self.now)["state"],
                         licensing.STATE_INVALID)

    def test_signed_by_someone_else_is_caught(self):
        t = _mint(self.other, v=1, contract="Forged", type="custom", dev_fee_bps=0,
                  issued_at=int(self.now), expires_at=int(self.now) + 86400)
        self.assertEqual(licensing.parse(t, pubkey=self.pub, now=self.now)["state"],
                         licensing.STATE_INVALID)

    def test_invalid_is_not_silently_treated_as_absent(self):
        # The dangerous failure: a tampered key quietly becoming "no licence", which hides
        # the tampering, or quietly becoming valid, which defeats the point.
        r = licensing.parse(self.good().replace("SYMN1", "SYMN9"), pubkey=self.pub)
        self.assertEqual(r["state"], licensing.STATE_INVALID)
        self.assertNotEqual(r["state"], licensing.STATE_NONE)

    def test_garbage_does_not_raise(self):
        for junk in ("", "  ", "nonsense", "SYMN1.notbase64!.x", "SYMN1.a.b.c", "a.b.c"):
            licensing.parse(junk, pubkey=self.pub)      # must not raise


class TestLifecycle(Base):
    def test_expired_still_runs_inside_grace(self):
        t = self.good(expires_at=int(self.now) - 3600)
        r = licensing.parse(t, pubkey=self.pub, now=self.now)
        self.assertEqual(r["state"], licensing.STATE_EXPIRED)
        self.assertGreater(r["seconds_to_restricted"], 0)
        self.assertEqual(r["dev_fee_bps"], 250, "the rate survives expiry")

    def test_restricted_after_grace(self):
        t = self.good(expires_at=int(self.now) - licensing.GRACE_SECONDS - 10)
        self.assertEqual(licensing.parse(t, pubkey=self.pub, now=self.now)["state"],
                         licensing.STATE_RESTRICTED)

    def test_no_key_is_none_and_charges_nothing(self):
        r = licensing.parse("", pubkey=self.pub)
        self.assertEqual(r["state"], licensing.STATE_NONE)
        self.assertIsNone(r["dev_fee_bps"])

    def test_out_of_range_fee_rejected(self):
        for bad in (-1, licensing.BPS_MAX + 1, "250", 2.5, None):
            r = licensing.parse(self.good(dev_fee_bps=bad), pubkey=self.pub, now=self.now)
            self.assertEqual(r["state"], licensing.STATE_INVALID, f"bps={bad!r}")

    def test_missing_expiry_rejected(self):
        b = dict(v=1, contract="T", type="standard", dev_fee_bps=250, issued_at=int(self.now))
        self.assertEqual(licensing.parse(_mint(self.key, **b), pubkey=self.pub)["state"],
                         licensing.STATE_INVALID)


class TestDisclosure(Base):
    def test_every_state_discloses_and_says_it_collects_nothing(self):
        cases = [
            licensing.parse("", pubkey=self.pub),
            licensing.parse(self.good(), pubkey=self.pub, now=self.now),
            licensing.parse(self.good(expires_at=int(self.now) - 3600),
                            pubkey=self.pub, now=self.now),
            licensing.parse("SYMN1.x.y", pubkey=self.pub),
        ]
        for lic in cases:
            d = licensing.disclosure(lic)
            self.assertTrue(d["terms"], f"no terms for state {lic['state']}")
            self.assertIs(d["collected"], False)
            self.assertIn("No hashrate is diverted", d["collection_note"])

    def test_a_rate_can_never_apply_without_being_disclosed(self):
        # The structural guarantee: if dev_fee_bps is set, disclosure carries it too.
        lic = licensing.parse(self.good(dev_fee_bps=137), pubkey=self.pub, now=self.now)
        d = licensing.disclosure(lic)
        self.assertEqual(d["dev_fee_bps"], 137)
        self.assertEqual(d["dev_fee_percent"], 1.37)
        self.assertIn("1.37%", d["terms"])

    def test_no_default_rate_exists_anywhere_in_the_module(self):
        # "Never invent pricing." With no contract there is no number to show.
        d = licensing.disclosure(licensing.parse("", pubkey=self.pub))
        self.assertIsNone(d["dev_fee_bps"])
        self.assertIsNone(d["dev_fee_percent"])
        self.assertIn("no dev fee applies", d["terms"])




class TestIssuerRates(Base):
    """The standard rate is a business decision; where it lives is a safety decision."""

    def test_verifier_never_assigns_a_rate_literal(self):
        """No integer literal in the verifier can ever become a dev fee.

        Checks the precise property rather than a proxy for it. Two earlier attempts were
        wrong in instructive ways: grepping the source for "250" fired on the comment that
        explains the unit, and allow-listing "safe" integers fired on 86400 (seconds in a
        day). Both would have been deleted the first time they cried wolf. What actually
        matters is narrow -- `dev_fee_bps` must only ever be read from a verified payload,
        never assigned a constant.
        """
        import ast
        tree = ast.parse(pathlib.Path(licensing.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if (isinstance(k, ast.Constant) and k.value in
                            ("dev_fee_bps", "dev_fee_percent")):
                        self.assertNotIsInstance(
                            v, ast.Constant if not (isinstance(v, ast.Constant)
                                                    and v.value is None) else type(None),
                            f"{k.value} is assigned the literal "
                            f"{getattr(v, 'value', v)!r} in the verifier")
        for name in dir(licensing):
            if "FEE" in name.upper() and "BPS" in name.upper():
                self.fail(f"licensing.{name} is a rate constant in the verifier")

    def test_no_contract_means_no_rate_at_runtime(self):
        # The behavioural half of the same guarantee.
        self.assertIsNone(licensing.parse("", pubkey=self.pub)["dev_fee_bps"])
        self.assertIsNone(licensing.disclosure(
            licensing.parse("", pubkey=self.pub))["dev_fee_percent"])

    def test_issuer_standard_rate_is_250_bps(self):
        sys.path.insert(0, str(pathlib.Path(licensing.__file__).resolve().parent))
        import issue
        self.assertEqual(issue.STANDARD_FEE_BPS, 250)
        self.assertEqual(issue.STANDARD_FEE_BPS / 100, 2.5)

    def test_a_standard_contract_verifies_at_two_and_a_half_percent(self):
        t = self.good(type="standard", dev_fee_bps=250)
        r = licensing.parse(t, pubkey=self.pub, now=self.now)
        self.assertEqual(r["state"], licensing.STATE_VALID)
        self.assertEqual(r["dev_fee_percent"], 2.5)
        self.assertIn("2.5%", licensing.disclosure(r)["terms"])

    def test_a_custom_rate_is_carried_verbatim(self):
        # A negotiated contract must not be quietly normalised to the standard rate.
        for bps in (0, 100, 150, 249, 251, 500):
            r = licensing.parse(self.good(type="custom", dev_fee_bps=bps),
                                pubkey=self.pub, now=self.now)
            self.assertEqual(r["dev_fee_bps"], bps)
            self.assertEqual(r["type"], "custom")


if __name__ == "__main__":
    unittest.main(verbosity=1)
