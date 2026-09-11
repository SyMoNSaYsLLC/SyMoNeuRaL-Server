#!/usr/bin/env python3
"""Tests for the discovery guards. System interpreter, no network, no venv.

    python3 backend/asicminer/test_scan.py

`scan.py` imports pyasic lazily -- inside the identify path -- specifically so this file can
exercise `allowed_network` without the venv. The guard is the part worth testing hardest:
this code runs on a host with a public IP, and a scanner that accepts an arbitrary CIDR is
one someone can aim at the internet from our address.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

from asicminer.lib import scan  # noqa: E402


class TestRefusesPublicRanges(unittest.TestCase):
    """Every one of these must be refused before a packet is sent."""

    PUBLIC = [
        "8.8.8.0/24",            # Google DNS
        "1.1.1.1/32",            # single public host
        "0.0.0.0/0",             # the whole internet
        "172.217.0.0/24",        # public, and adjacent to RFC1918 172.16/12
        "192.169.0.0/24",        # public, one octet off 192.168/16
        "11.0.0.0/24",           # public, one octet off 10/8
        "2606:4700::/48",        # public IPv6
    ]

    def test_public_ranges_refused(self):
        for cidr in self.PUBLIC:
            net, why = scan.allowed_network(cidr)
            self.assertIsNone(net, f"{cidr} was ACCEPTED — it is publicly routable")
            self.assertTrue(why)

    def test_near_misses_are_not_treated_as_private(self):
        # 172.16/12 is private but 172.32/12 is not; the boundary is where a naive
        # string check ("starts with 172.") goes wrong.
        for cidr in ("172.32.0.0/24", "172.15.0.0/24"):
            self.assertIsNone(scan.allowed_network(cidr)[0], cidr)

    def test_alternate_spellings_cannot_slip_through(self):
        # The check is on the parsed network, not the text, so padded or odd spellings
        # of a public address are still recognised as public.
        for cidr in ("8.8.8.8", "8.8.8.8/32"):
            self.assertIsNone(scan.allowed_network(cidr)[0], cidr)


class TestAcceptsPrivateRanges(unittest.TestCase):
    def test_rfc1918_accepted(self):
        for cidr in ("10.0.0.0/24", "192.168.1.0/24", "172.16.5.0/24", "127.0.0.0/30"):
            net, why = scan.allowed_network(cidr)
            self.assertIsNotNone(net, f"{cidr} was refused: {why}")

    def test_link_local_accepted(self):
        self.assertIsNotNone(scan.allowed_network("169.254.1.0/24")[0])


class TestBounds(unittest.TestCase):
    def test_broad_private_ranges_refused(self):
        # Private, but 16.7M addresses. "Scan my network" is usually a typo for a /24 and
        # the cost of the typo should not be an hour of SYN traffic.
        for cidr in ("10.0.0.0/8", "172.16.0.0/12", "10.0.0.0/19"):
            net, why = scan.allowed_network(cidr)
            self.assertIsNone(net, f"{cidr} was accepted")
            self.assertIn("too broad", why)

    def test_the_widest_accepted_prefix_is_exactly_the_documented_one(self):
        self.assertIsNotNone(scan.allowed_network(f"10.0.0.0/{scan.MIN_PREFIX_V4}")[0])
        self.assertIsNone(scan.allowed_network(f"10.0.0.0/{scan.MIN_PREFIX_V4 - 1}")[0])


class TestMalformed(unittest.TestCase):
    def test_garbage_is_refused_not_raised(self):
        for junk in ("", "   ", "not-a-cidr", "10.0.0.0/33", "999.1.1.1/24",
                     "10.0.0.0/-1", "; rm -rf /", "10.0.0.0/24 10.0.1.0/24"):
            net, why = scan.allowed_network(junk)
            self.assertIsNone(net, f"{junk!r} was accepted")
            self.assertTrue(why, f"{junk!r} refused with no reason given")


if __name__ == "__main__":
    unittest.main(verbosity=1)
