#!/usr/bin/env python3
"""Tests for the Gateway. Stdlib `unittest`, and they run with the network unplugged.

    python3 backend/apps/gateway/test_gateway.py

Two things this suite is built to do, beyond checking the code works:

**It must pass offline.** `.claude/HANDOVER.md` §3.0d lists five verification steps that
printed FAILED on healthy input, and the damage is cumulative -- a check that cries wolf
trains the reader to skip the whole block. Every chain test drives an injected `fetch`, so
none of them depends on egress, on TronGrid's rate limit, or on a testnet being up.

**It is a tripwire against a fail-open.** `test_no_configuration_can_produce_a_green_light`
asserts that across every environment and every reading -- including a perfectly successful
one showing a deployed contract -- the state is `offline`. It is phrased against behaviour
rather than today's signature, so the commit that would break it is the one it exists to
catch. `docs/specs/symon-ml-review.md` finding 1 is the bug it is watching for.
"""
from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
import os
import pathlib
import re
import sys
import types
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import gateway  # noqa: E402
from gateway import abi, address, chain, routes  # noqa: E402
from gateway.keccak import _sponge, keccak256  # noqa: E402

# The live USDT TRC-20 contract on mainnet. Used only as a known-good *address*; nothing in
# this file contacts a node.
USDT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
# The same address with two characters transposed. It passes the base58 alphabet-and-length
# regex the module used to validate with, and it is not a real address.
USDT_TRANSPOSED = "TR7NHqjeKQGxTCi8q8ZY4pL8otSzgjLj6t"

ENV = ("SYMONEURAL_GATEWAY_ENABLED", "SYMONEURAL_GATEWAY_NETWORK", "SYMONEURAL_GATEWAY_CONTRACT")


def env(**kw):
    """Patch only the gateway switches, clearing any the caller did not set."""
    base = {k: "" for k in ENV}
    base.update(kw)
    return mock.patch.dict(os.environ, base, clear=False)


def fake(*responses):
    """A `fetch` that returns queued `(status, body)` pairs, or raises what it is given."""
    queue = list(responses)
    calls = []

    def _fetch(url, body, timeout):
        calls.append((url, json.loads(body.decode()), timeout))
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, BaseException):
            raise item
        status, payload = item
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return status, raw

    _fetch.calls = calls
    return _fetch


def block_ok(number=70_152_715):
    return (200, {"block_header": {"raw_data": {"number": number, "timestamp": 1_755_000_000_000}}})


CONTRACT_OK = (200, {
    "contract_address": USDT, "origin_address": USDT, "name": "TetherToken",
    "abi": {"entrys": [{"type": "Function", "name": "transfer"},
                       {"type": "Function", "name": "balanceOf"},
                       {"type": "Event", "name": "Transfer"}]},
})
CONTRACT_ABSENT = (200, {})


def reading_for(net="nile", addr=USDT, **kw):
    r = {"network": net, "contract": addr, "at": 0.0, "elapsed_ms": 12, "error": None,
         "block": 70_152_715, "block_ts_ms": 1_755_000_000_000, "age_s": 3.0,
         "contract_present": True, "contract_name": "TetherToken", "abi_functions": 2}
    r.update(kw)
    return r


# --------------------------------------------------------------------------- keccak


class TestKeccak(unittest.TestCase):
    def test_published_vectors(self):
        self.assertEqual(keccak256(b"").hex(),
                         "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470")
        self.assertEqual(keccak256(b"abc").hex(),
                         "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45")

    def test_it_is_not_sha3(self):
        """The bug this file exists to prevent: hashlib.sha3_256 is a different hash."""
        self.assertNotEqual(keccak256(b""), hashlib.sha3_256(b"").digest())

    def test_permutation_matches_hashlib_across_every_length(self):
        """There is no second Keccak on this box, so validate the sponge against SHA-3.

        Same permutation, same padding rule, same absorb and squeeze -- only the domain byte
        differs. Four published vectors do not reach the multi-block path; this does, at
        every length either side of the 136-byte rate.
        """
        for n in list(range(0, 280)) + [512, 1000, 4096]:
            data = bytes((i * 31 + n) % 256 for i in range(n))
            with self.subTest(n=n):
                self.assertEqual(_sponge(data, 0x06), hashlib.sha3_256(data).digest())


# --------------------------------------------------------------------------- addresses


class TestAddress(unittest.TestCase):
    def test_known_good(self):
        self.assertTrue(address.valid(USDT))
        self.assertIsNone(address.reason(USDT))
        self.assertEqual(address.to_hex(USDT), "41a614f803b6fd780986a42c78ec9c7f77e6ded13c")
        self.assertEqual(address.evm(USDT).hex(), "a614f803b6fd780986a42c78ec9c7f77e6ded13c")

    def test_roundtrip(self):
        self.assertEqual(address.from_hex(address.to_hex(USDT)), USDT)
        self.assertEqual(address.from_hex(address.evm(USDT).hex()), USDT)

    def test_transposed_characters_are_caught(self):
        """The whole reason base58check exists here. The old regex accepted this string."""
        old_regex = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")
        self.assertIsNotNone(old_regex.match(USDT_TRANSPOSED),
                             "the shape-only check must accept it, or this test proves nothing")
        self.assertFalse(address.valid(USDT_TRANSPOSED))
        self.assertIn("checksum", address.reason(USDT_TRANSPOSED))

    def test_each_fault_is_named(self):
        for bad, expect in [
            ("", "empty"),
            ("X" + USDT[1:], "does not start with T"),
            (USDT[:-1], "33 characters"),
            (USDT + "x", "35 characters"),
            ("T" + "0" * 33, "not a base58 character"),
        ]:
            with self.subTest(bad=bad[:10]):
                self.assertIn(expect, address.reason(bad) or "")

    def test_wrong_prefix_byte_is_rejected(self):
        payload = b"\x42" + address.evm(USDT)
        wrong = address._b58_encode(payload + address.checksum(payload))
        self.assertIn("prefix byte", address.reason(wrong) or "")

    def test_short_keeps_head_and_tail(self):
        self.assertEqual(address.short(USDT), "TR7NHq…Lj6t")


# --------------------------------------------------------------------------- ABI codec


class TestAbi(unittest.TestCase):
    def test_selectors(self):
        self.assertEqual(abi.selector("transfer(address,uint256)"), "a9059cbb")
        self.assertEqual(abi.selector("balanceOf(address)"), "70a08231")
        # Cross-checked against TRON itself: asked for `symbol()` on mainnet USDT on
        # 2026-08-17, the node built the call data `95d89b41`. Our keccak agrees.
        self.assertEqual(abi.selector("symbol()"), "95d89b41")
        with self.assertRaises(abi.AbiError):
            abi.selector("not a signature")

    def test_static_roundtrip(self):
        data = abi.encode_params(["address", "uint256", "bool"], [USDT, 1234567890, True])
        self.assertEqual(len(data), 64 * 3)
        self.assertEqual(abi.decode_params(["address", "uint256", "bool"], data),
                         [USDT, 1234567890, True])

    def test_address_is_left_padded_to_a_word(self):
        word = abi.encode_params(["address"], [USDT])
        self.assertEqual(word[:24], "0" * 24)
        self.assertTrue(word.endswith(address.evm(USDT).hex()))

    def test_string_roundtrip_including_multiword(self):
        for s in ["", "USDT", "a" * 31, "a" * 32, "a" * 33, "naïve — em dash"]:
            with self.subTest(s=s[:12]):
                data = abi.encode_params(["string"], [s])
                self.assertEqual(abi.decode_params(["string"], data), [s])

    def test_mixed_head_and_tail(self):
        data = abi.encode_params(["uint256", "string"], [7, "SyMoNeuRaL"])
        self.assertEqual(abi.decode_params(["uint256", "string"], data), [7, "SyMoNeuRaL"])

    def test_refusals(self):
        # `bytes32` and `uint64` used to be refused here and are now supported: the licence
        # record returns both, so `licensing/verify.py` needs them. The refusal that matters
        # is still that an UNKNOWN type raises rather than being guessed at.
        with self.assertRaises(abi.AbiError):
            abi.encode_params(["uint128"], [1])
        with self.assertRaises(abi.AbiError):
            abi.decode_params(["bytes16"], "00" * 32)
        with self.assertRaises(abi.AbiError):
            abi.encode_params(["bytes32"], [b"\x00" * 31])       # wrong length, not 32
        with self.assertRaises(abi.AbiError):
            abi.encode_params(["uint64"], [1 << 64])             # out of range
        with self.assertRaises(abi.AbiError):
            abi.encode_params(["uint256"], [-1])
        with self.assertRaises(abi.AbiError):
            abi.encode_params(["uint256", "bool"], [1])
        with self.assertRaises(abi.AbiError):
            abi.decode_params(["uint256"], "00")                 # short
        with self.assertRaises(abi.AbiError):
            abi.decode_params(["bool"], "%064x" % 2)             # not 0 or 1
        with self.assertRaises(abi.AbiError):
            abi.decode_params(["string"], "%064x" % 4096)        # offset past the end


# --------------------------------------------------------------------------- chain client


class TestChainClient(unittest.TestCase):
    def test_head_block(self):
        f = fake(block_ok())
        self.assertEqual(chain.head_block("nile", fetch=f), (70_152_715, 1_755_000_000_000))
        url, payload, _ = f.calls[0]
        # `getblock` with detail:false, not `getnowblock` -- see the docstring there. Asserted
        # because the difference is invisible on a testnet and 533 KB per read on mainnet.
        self.assertEqual(url, "https://nile.trongrid.io/wallet/getblock")
        self.assertIs(payload["detail"], False)

    def test_contract_present_and_absent(self):
        self.assertIsNotNone(chain.contract_at("nile", USDT, fetch=fake(CONTRACT_OK)))
        self.assertIsNone(chain.contract_at("nile", USDT, fetch=fake(CONTRACT_ABSENT)))

    def test_every_transport_failure_raises_rather_than_returning_something(self):
        for label, response in [
            ("rate limit", (429, {})),
            ("server error", (500, {"x": 1})),
            ("gateway error", (502, b"<html>")),
            ("not json", (200, b"<html>not json</html>")),
            ("json but not an object", (200, b"[1,2,3]")),
            ("application error in a 200", (200, {"Error": "class java.lang.NullPointer"})),
            ("timeout", TimeoutError("timed out")),
            ("dns", OSError("Name or service not known")),
        ]:
            with self.subTest(label=label):
                # ChainError specifically, not "some exception": everything that leaves this
                # client must already be the type the rack knows how to render.
                with self.assertRaises(chain.ChainError):
                    chain.head_block("nile", fetch=fake(response))

    def test_a_failed_contract_query_never_reads_as_absent(self):
        """The dangerous near-miss. `{}` means "nothing deployed there"; a rate limit or a
        500 means "we could not look". Collapsing the second into the first would print
        `no contract is deployed at that address` on the rack when nothing was measured at
        all -- a fabricated on-chain reading, which is the one thing this surface must not
        produce. Found by mutating `call` to return `{}` on a 429: every other test still
        passed.
        """
        for label, response in [("rate limit", (429, {})), ("server error", (500, {})),
                                ("app error", (200, {"Error": "boom"})),
                                ("timeout", TimeoutError("timed out"))]:
            with self.subTest(label=label):
                with self.assertRaises(chain.ChainError):
                    chain.contract_at("nile", USDT, fetch=fake(response))
                r = chain.probe("nile", USDT, fetch=fake(block_ok(), response))
                self.assertTrue(r["error"])
                self.assertIsNone(r["contract_present"],
                                  "unverified must not be reported as absent or present")

    def test_the_rate_limit_message_names_the_rate_limit(self):
        with self.assertRaises(chain.ChainError) as cm:
            chain.call("nile", "wallet/getnowblock", {}, fetch=fake((429, {})))
        self.assertIn("429", str(cm.exception))

    def test_block_without_a_number_is_a_failure(self):
        with self.assertRaises(chain.ChainError):
            chain.head_block("nile", fetch=fake((200, {"block_header": {}})))

    def test_unknown_network_never_builds_a_url(self):
        with self.assertRaises(chain.ChainError):
            chain.call("evilnet", "wallet/getnowblock", {}, fetch=fake(block_ok()))

    def test_the_real_transport_refuses_a_host_outside_the_map(self):
        with self.assertRaises(chain.ChainError):
            chain.http_post("https://example.com/wallet/getnowblock", b"{}", 1.0)
        with self.assertRaises(chain.ChainError):
            chain.http_post("http://nile.trongrid.io/wallet/getnowblock", b"{}", 1.0)

    def test_redirects_are_refused(self):
        handler = chain._NoRedirect()
        with self.assertRaises(chain.ChainError):
            handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example/x")

    def test_every_endpoint_is_https_and_no_url_comes_from_the_environment(self):
        for name, (_, url) in chain.NODES.items():
            with self.subTest(net=name):
                self.assertTrue(url.startswith("https://"))
        # Read the *code*, not the prose: the docstrings deliberately name
        # SYMONEURAL_GATEWAY_NODE_URL in order to forbid it. What matters is which variables are
        # actually looked up, and that no lookup is built from a non-literal.
        src = "\n".join(p.read_text() for p in HERE.glob("*.py")
                        if p.name != "test_gateway.py")
        lookups = re.findall(r"os\.environ(?:\.get)?[\(\[]\s*(.{0,40}?)[,)\]]", src)
        literals = {m.strip("\"' ") for m in lookups}
        self.assertTrue(all(m.strip().startswith(("'", '"')) for m in lookups),
                        f"an environment lookup is not a literal: {lookups}")
        self.assertEqual(literals, set(ENV),
                         f"the surface reads {sorted(literals)}, expected exactly {sorted(ENV)}")

    def test_no_key_material_is_ever_read_or_sent(self):
        """No wallet, no private key. Reading the chain needs neither, and a public-facing
        web process must never hold one -- see the package docstring."""
        src = "\n".join(p.read_text() for p in HERE.glob("*.py")
                        if p.name != "test_gateway.py")
        for forbidden in ("PRIVATE_KEY", "private_key", "SYMONEURAL_GATEWAY_WALLET",
                          "SYMONEURAL_GATEWAY_KEY", "sign_transaction", "broadcasttransaction",
                          "broadcasthex", "createtransaction"):
            self.assertNotIn(forbidden, src)
        # `triggersmartcontract` builds a transaction for signing; `triggerconstantcontract`
        # is evaluated and thrown away. One word apart, opposite consequences. The only
        # mention of the write path in this package is the warning comment next to the read.
        self.assertEqual(src.count("wallet/triggersmartcontract"), 0)
        self.assertEqual(src.count('call(network, "wallet/triggerconstantcontract"'), 1)

    def test_constant_call_encodes_and_decodes(self):
        word = "%064x" % (6 * 10 ** 6)
        f = fake((200, {"result": {"result": True}, "constant_result": [word]}))
        raw = chain.constant_call("nile", USDT, "balanceOf(address)", ["address"], [USDT],
                                  fetch=f)
        self.assertEqual(abi.decode_params(["uint256"], raw), [6_000_000])
        url, payload, _ = f.calls[0]
        self.assertTrue(url.endswith("/wallet/triggerconstantcontract"), url)
        self.assertEqual(payload["function_selector"], "balanceOf(address)")
        self.assertEqual(payload["parameter"], abi.encode_params(["address"], [USDT]))
        self.assertEqual(payload["owner_address"], USDT)   # no wallet is implied

    def test_constant_call_revert_is_an_error_not_a_value(self):
        f = fake((200, {"result": {"result": False, "message": b"nope".hex()}}))
        with self.assertRaises(chain.ChainError) as cm:
            chain.constant_call("nile", USDT, "symbol()", fetch=f)
        self.assertIn("nope", str(cm.exception))

    def test_constant_call_with_no_data_is_an_error(self):
        f = fake((200, {"result": {"result": True}, "constant_result": []}))
        with self.assertRaises(chain.ChainError):
            chain.constant_call("nile", USDT, "symbol()", fetch=f)


class TestProbe(unittest.TestCase):
    def test_probe_never_raises_and_always_says_why(self):
        for label, responses in [
            ("node down", (OSError("connection refused"),)),
            ("rate limited", ((429, {}),)),
            ("bad json", ((200, b"nope"),)),
            ("contract query fails", (block_ok(), (500, {}))),
        ]:
            with self.subTest(label=label):
                r = chain.probe("nile", USDT, fetch=fake(*responses))
                self.assertTrue(r["error"], "a failed probe must carry a reason")
                self.assertIsNot(r["contract_present"], True)

    def test_probe_reports_an_absent_contract_as_absent(self):
        r = chain.probe("nile", USDT, fetch=fake(block_ok(), CONTRACT_ABSENT))
        self.assertIsNone(r["error"])
        self.assertIs(r["contract_present"], False)
        self.assertEqual(r["block"], 70_152_715)

    def test_probe_reports_a_present_contract_with_what_it_read(self):
        r = chain.probe("nile", USDT, fetch=fake(block_ok(), CONTRACT_OK))
        self.assertIsNone(r["error"])
        self.assertIs(r["contract_present"], True)
        self.assertEqual(r["contract_name"], "TetherToken")
        self.assertEqual(r["abi_functions"], 2)          # the Event is not counted
        self.assertIsInstance(r["elapsed_ms"], int)

    def test_probe_validates_the_address_before_it_touches_the_network(self):
        f = fake(block_ok())
        r = chain.probe("nile", USDT_TRANSPOSED, fetch=f)
        self.assertIn("checksum", r["error"])
        self.assertEqual(f.calls, [], "a malformed address must not reach a node")

    def test_probe_rejects_an_unknown_network_before_it_touches_the_network(self):
        f = fake(block_ok())
        r = chain.probe("evilnet", USDT, fetch=f)
        self.assertIn("unknown network", r["error"])
        self.assertEqual(f.calls, [])


# --------------------------------------------------------------------------- rack state


class TestUnitState(unittest.TestCase):
    def test_offline_when_the_switch_is_unset_and_it_says_how_to_set_it(self):
        with env():
            state, detail = gateway.unit_state()
        self.assertEqual(state, "offline")
        for token in ("SYMONEURAL_GATEWAY_ENABLED=1", "SYMONEURAL_GATEWAY_NETWORK", "SYMONEURAL_GATEWAY_CONTRACT"):
            self.assertIn(token, detail)

    def test_bad_network_names_what_was_found_and_what_is_expected(self):
        """The message must echo what the operator actually typed and list what would work.

        It lists the OPERATOR vocabulary, not `chain.NODES`' keys: those are the canonical
        chain names, they are not accepted from the environment, and printing them as the
        remedy would send someone to set a value this code refuses.
        """
        with env(SYMONEURAL_GATEWAY_ENABLED="1", SYMONEURAL_GATEWAY_NETWORK="nilee"):
            _, detail = gateway.unit_state()
        self.assertIn("SYMONEURAL_GATEWAY_NETWORK=nilee", detail)
        for n in chain.OPERATOR_NETWORKS:
            self.assertIn(n, detail)
        # And the remedy never names a value that would be refused.
        for canonical in chain.NODES:
            self.assertNotIn(f"{canonical}," , detail)

    def test_the_operator_vocabulary_covers_every_chain_exactly_once(self):
        """`OPERATOR_NETWORKS` and `NODES` are two dicts that have to agree, and nothing but
        this test makes them. A chain with no operator name is unreachable; two names for one
        chain would make `settlement/__main__.py`'s NET_ENV lookup ambiguous."""
        self.assertEqual(sorted(chain.OPERATOR_NETWORKS.values()), sorted(chain.NODES))

    def test_trons_own_network_names_are_refused(self):
        """The rename is only worth anything if the old vocabulary actually stops working.

        `network()` resolves through `OPERATOR_NETWORKS`; if it fell back to returning the raw
        value, "nile" would be a valid `NODES` key and would configure a chain nobody named --
        silently, and with a detail line reading `ready`. That is the failure this pins.
        """
        for canonical in chain.NODES:
            with self.subTest(net=canonical):
                with env(SYMONEURAL_GATEWAY_ENABLED="1", SYMONEURAL_GATEWAY_NETWORK=canonical,
                         SYMONEURAL_GATEWAY_CONTRACT=USDT):
                    self.assertEqual(gateway.network(), "",
                                     f"{canonical} resolved instead of being refused")
                    ok, why = gateway.configured()
                    self.assertFalse(ok, f"{canonical} was accepted as configured")
                    self.assertIn(canonical, why)         # echoes what was typed
                    state, _ = gateway.unit_state(reading_for(net=canonical))
                    self.assertEqual(state, "offline")

    def test_missing_contract_names_the_variable_and_the_shape(self):
        with env(SYMONEURAL_GATEWAY_ENABLED="1", SYMONEURAL_GATEWAY_NETWORK="symoneural-test"):
            _, detail = gateway.unit_state()
        self.assertIn("SYMONEURAL_GATEWAY_CONTRACT unset", detail)
        self.assertIn("Nile testnet", detail)

    def test_malformed_contract_says_which_fault(self):
        with env(SYMONEURAL_GATEWAY_ENABLED="1", SYMONEURAL_GATEWAY_NETWORK="symoneural-test",
                 SYMONEURAL_GATEWAY_CONTRACT=USDT_TRANSPOSED):
            _, detail = gateway.unit_state()
        self.assertIn("malformed", detail)
        self.assertIn("checksum", detail)

    def test_configured_but_unprobed_says_so(self):
        with env(SYMONEURAL_GATEWAY_ENABLED="1", SYMONEURAL_GATEWAY_NETWORK="symoneural-test", SYMONEURAL_GATEWAY_CONTRACT=USDT):
            _, detail = gateway.unit_state(None)
        self.assertIn("has not been read yet", detail)

    def test_a_reading_for_a_different_configuration_is_discarded(self):
        with env(SYMONEURAL_GATEWAY_ENABLED="1", SYMONEURAL_GATEWAY_NETWORK="symoneural-test", SYMONEURAL_GATEWAY_CONTRACT=USDT):
            _, detail = gateway.unit_state(reading_for(net="shasta"))
            self.assertIn("has not been read yet", detail)
            _, detail = gateway.unit_state(reading_for(addr=address.from_hex("41" + "11" * 20)))
            self.assertIn("has not been read yet", detail)

    def test_a_failed_reading_surfaces_the_reason_verbatim(self):
        with env(SYMONEURAL_GATEWAY_ENABLED="1", SYMONEURAL_GATEWAY_NETWORK="symoneural-test", SYMONEURAL_GATEWAY_CONTRACT=USDT):
            _, detail = gateway.unit_state(reading_for(error="node rate-limited this box (HTTP 429)",
                                                       contract_present=None))
        self.assertIn("cannot verify", detail)
        self.assertIn("HTTP 429", detail)

    def test_absent_contract_is_stated_as_a_measurement(self):
        with env(SYMONEURAL_GATEWAY_ENABLED="1", SYMONEURAL_GATEWAY_NETWORK="symoneural-test", SYMONEURAL_GATEWAY_CONTRACT=USDT):
            _, detail = gateway.unit_state(reading_for(contract_present=False,
                                                       contract_name=None, abi_functions=None))
        self.assertIn("measured", detail)
        self.assertIn("no contract is deployed", detail)
        self.assertIn("70,152,715", detail)

    def test_present_contract_is_measured_and_still_says_why_it_is_offline(self):
        """A deployed contract is not a working licensing service. This is THE test.

        §4 of the completion spec names "the contract is there, so report ready" as the
        wrong commit that this surface invites. A present contract, a reachable node and a
        clean reading must still be `offline` while no licence has ever settled.
        """
        with env(SYMONEURAL_GATEWAY_ENABLED="1", SYMONEURAL_GATEWAY_NETWORK="symoneural-test", SYMONEURAL_GATEWAY_CONTRACT=USDT):
            state, detail = gateway.unit_state(reading_for())
        self.assertEqual(state, "offline")
        self.assertIn("measured", detail)
        self.assertIn("deployed", detail)
        self.assertIn("no licence has ever cleared", detail)

    def test_a_broken_clearance_store_can_never_light_the_led(self):
        """`_cleared` is the only route to `ready`, so every failure in it must mean offline."""
        for boom in (OSError("permission denied"), ValueError("corrupt"),
                     ImportError("no licensing package"), RuntimeError("boom")):
            with mock.patch.object(gateway, "_cleared", side_effect=boom):
                with env(SYMONEURAL_GATEWAY_ENABLED="1", SYMONEURAL_GATEWAY_NETWORK="symoneural-test",
                         SYMONEURAL_GATEWAY_CONTRACT=USDT):
                    try:
                        state, _ = gateway.unit_state(reading_for())
                    except Exception as e:                      # noqa: BLE001
                        self.fail(f"unit_state raised {type(e).__name__} instead of offline: {e}")
            self.assertEqual(state, "offline", f"{type(boom).__name__} produced {state}")

    def test_ready_requires_a_settlement_against_this_exact_contract(self):
        """A clearance recorded for another network or address is not evidence about this one."""
        rec = types.SimpleNamespace(nonce=42, at_block=70_152_800)

        # The store is asked for (network, contract) and answers None when they do not match;
        # that filtering is store.latest's job and is tested in apps/licensing. Here we only
        # assert unit_state honours a None as "not ready".
        with mock.patch.object(gateway, "_cleared", return_value=(None, None)):
            with env(SYMONEURAL_GATEWAY_ENABLED="1", SYMONEURAL_GATEWAY_NETWORK="symoneural-test",
                     SYMONEURAL_GATEWAY_CONTRACT=USDT):
                state, _ = gateway.unit_state(reading_for())
        self.assertEqual(state, "offline")

        with mock.patch.object(gateway, "_cleared", return_value=(rec, None)):
            with env(SYMONEURAL_GATEWAY_ENABLED="1", SYMONEURAL_GATEWAY_NETWORK="symoneural-test",
                     SYMONEURAL_GATEWAY_CONTRACT=USDT):
                state, detail = gateway.unit_state(reading_for())
        self.assertEqual(state, "ready")
        self.assertIn("Licence #42", detail)
        self.assertIn("70,152,800", detail)

    def test_ready_is_unreachable_without_a_present_contract(self):
        """Even with a settlement on record, a missing or unverified contract stays offline."""
        rec = types.SimpleNamespace(nonce=1, at_block=1)
        with mock.patch.object(gateway, "_cleared", return_value=(rec, None)):
            with env(SYMONEURAL_GATEWAY_ENABLED="1", SYMONEURAL_GATEWAY_NETWORK="symoneural-test",
                     SYMONEURAL_GATEWAY_CONTRACT=USDT):
                for reading in (None,
                                reading_for(contract_present=False, contract_name=None,
                                            abi_functions=None),
                                reading_for(contract_present=None),
                                reading_for(error="HTTP 429")):
                    state, _ = gateway.unit_state(reading)
                    self.assertEqual(state, "offline", f"{reading} produced {state}")

    def test_the_only_states_this_surface_can_emit_are_known_to_the_frontend(self):
        """`site/console.js:47` lights the LED for anything that is not literally `offline`."""
        seen = set()
        rec = types.SimpleNamespace(nonce=1, at_block=1)
        for cleared in (None, rec):
            with mock.patch.object(gateway, "_cleared", return_value=(cleared, None)):
                for kw in ({}, {"error": "boom"}, {"contract_present": False},
                           {"contract_present": None}):
                    with env(SYMONEURAL_GATEWAY_ENABLED="1", SYMONEURAL_GATEWAY_NETWORK="symoneural-test",
                             SYMONEURAL_GATEWAY_CONTRACT=USDT):
                        seen.add(gateway.unit_state(reading_for(**kw))[0])
                    with env():
                        seen.add(gateway.unit_state(None)[0])
        self.assertTrue(seen <= {"ready", "offline"}, f"unexpected state(s): {seen}")

    def test_every_detail_line_names_the_network_once_one_is_chosen(self):
        """A gateway that does not say which chain it is on is one misconfiguration away
        from taking real USDT while everyone believes it is a test."""
        for op, name in [(o, chain.NODES[c][0]) for o, c in
                         chain.OPERATOR_NETWORKS.items()]:
            net = chain.OPERATOR_NETWORKS[op]
            for reading in (None, reading_for(net=net), reading_for(net=net, error="boom"),
                            reading_for(net=net, contract_present=False)):
                with env(SYMONEURAL_GATEWAY_ENABLED="1", SYMONEURAL_GATEWAY_NETWORK=op,
                         SYMONEURAL_GATEWAY_CONTRACT=USDT):
                    _, detail = gateway.unit_state(reading)
                with self.subTest(net=net, reading=bool(reading)):
                    self.assertIn(name, detail)

    def test_no_detail_line_is_truncated(self):
        """`.claude/CLAUDE.md`: folding is allowed, trimming is data loss. asicminer slices
        its detail to 90 characters; this surface must not copy that."""
        with env(SYMONEURAL_GATEWAY_ENABLED="1", SYMONEURAL_GATEWAY_NETWORK="symoneural-test", SYMONEURAL_GATEWAY_CONTRACT=USDT):
            long = "x" * 400
            _, detail = gateway.unit_state(reading_for(error=long))
        self.assertIn(long, detail)
        self.assertNotIn("…", detail.replace(address.short(USDT), ""))

    def test_no_configuration_can_produce_a_green_light(self):
        """THE TRIPWIRE. Do not delete this to make a change pass.

        For every environment and every reading -- including a completely successful one
        showing a deployed contract on mainnet -- the state is `offline`. `ready` here means
        a visitor can obtain a licence, which needs the off-chain daemon, a payment path a
        real person can complete, an unlock, and one round trip actually completed. Until a
        human deletes this test on purpose, having read `docs/specs/symon-ml-review.md`
        findings 1 and 2, the answer is `offline`.

        Phrased against behaviour, not against today's signature: if `unit_state` grows a
        different argument, fix the call below -- do not weaken the assertion.
        """
        readings = [None, {}, {"error": "boom"}, reading_for(), reading_for(contract_present=False),
                    reading_for(error=None, contract_present=True, abi_functions=99),
                    reading_for(net="mainnet"), reading_for(contract_present=None),
                    {"network": "nile", "contract": USDT, "block": 1, "contract_present": True,
                     "error": None, "state": "ready", "ok": True, "licensed": True}]
        switches = itertools.product(["", "1", "true", "0"],
                                     ["", "nile", "shasta", "mainnet", "bogus",
                                      "symoneural-test", "symoneural-live"],
                                     ["", USDT, USDT_TRANSPOSED, "garbage"])
        checked = 0
        for on, net, addr in switches:
            for reading in readings:
                with env(SYMONEURAL_GATEWAY_ENABLED=on, SYMONEURAL_GATEWAY_NETWORK=net,
                         SYMONEURAL_GATEWAY_CONTRACT=addr):
                    for r in (reading, {**reading, "network": net, "contract": addr}
                              if isinstance(reading, dict) else reading):
                        state, detail = gateway.unit_state(r)
                        checked += 1
                        self.assertEqual(state, "offline",
                                         f"env=({on},{net},{addr}) reading={r} -> {state}")
                        self.assertTrue(detail.strip(), "offline must always say why")
        self.assertGreater(checked, 500)

    def test_status_dict_matches_the_rack_unit_model(self):
        with env():
            s = gateway.status()
        self.assertEqual(set(s), {"id", "label", "slot", "state", "bus", "href", "spec", "detail"})
        self.assertEqual(s["id"], "gateway")
        self.assertEqual(s["bus"], "net")
        self.assertEqual(s["state"], "offline")
        with env(SYMONEURAL_GATEWAY_ENABLED="1", SYMONEURAL_GATEWAY_NETWORK="symoneural-test", SYMONEURAL_GATEWAY_CONTRACT=USDT):
            self.assertEqual(gateway.status(reading_for())["detail"],
                             gateway.unit_state(reading_for())[1])

    def test_the_state_string_is_one_api_py_accepts(self):
        """A fifth state is a pydantic ValidationError on /api/status, which is polled and
        drives the websocket -- it would take the rack down for every visitor."""
        allowed = {"ready", "busy", "queued", "offline"}
        for on in ("", "1"):
            with env(SYMONEURAL_GATEWAY_ENABLED=on, SYMONEURAL_GATEWAY_NETWORK="symoneural-test",
                     SYMONEURAL_GATEWAY_CONTRACT=USDT):
                self.assertIn(gateway.unit_state(reading_for())[0], allowed)


# --------------------------------------------------------------------------- cache + route


class TestCacheAndRefresher(unittest.TestCase):
    def test_cache_starts_empty_and_carries_an_age(self):
        c = gateway.ChainCache()
        self.assertIsNone(c.get())
        self.assertTrue(c.stale())
        c.put({"block": 1})
        got = c.get()
        self.assertEqual(got["block"], 1)
        self.assertIn("age_s", got)
        self.assertFalse(c.stale())

    def test_refresh_does_nothing_when_the_surface_is_not_configured(self):
        with env():
            with mock.patch.object(chain, "probe", side_effect=AssertionError("probed!")):
                self.assertIsNone(asyncio.run(gateway.refresh_once()))

    def test_refresh_stores_what_the_probe_measured(self):
        want = reading_for()
        with env(SYMONEURAL_GATEWAY_ENABLED="1", SYMONEURAL_GATEWAY_NETWORK="symoneural-test", SYMONEURAL_GATEWAY_CONTRACT=USDT):
            with mock.patch.object(chain, "probe", return_value=want) as p:
                got = asyncio.run(gateway.refresh_once())
        self.assertEqual(got["block"], want["block"])
        self.assertEqual(p.call_args.args, ("nile", USDT))

    def test_a_bug_in_the_probe_is_stored_as_a_failure_not_swallowed(self):
        with env(SYMONEURAL_GATEWAY_ENABLED="1", SYMONEURAL_GATEWAY_NETWORK="symoneural-test", SYMONEURAL_GATEWAY_CONTRACT=USDT):
            with mock.patch.object(chain, "probe", side_effect=RuntimeError("kaboom")):
                got = asyncio.run(gateway.refresh_once())
        self.assertIn("kaboom", got["error"])
        self.assertIsNone(got["contract_present"])
        with env(SYMONEURAL_GATEWAY_ENABLED="1", SYMONEURAL_GATEWAY_NETWORK="symoneural-test", SYMONEURAL_GATEWAY_CONTRACT=USDT):
            self.assertEqual(gateway.unit_state(got)[0], "offline")


    def test_the_refresher_announces_itself_once(self):
        """An operator restarting the service must be able to tell from the journal whether
        this task is alive. A loop that runs forever, does nothing and says nothing is
        indistinguishable from a loop that was never started."""
        async def one_pass():
            task = asyncio.create_task(gateway.refresher())
            await asyncio.sleep(0.05)
            task.cancel()
        with env():
            with self.assertLogs("symoneural.gateway", level="INFO") as cm:
                asyncio.run(one_pass())
        self.assertTrue(any("idle" in line for line in cm.output), cm.output)


class TestDetailEncoding(unittest.TestCase):
    """The detail line is the delivery channel to the rack, and it carries —, · and ….

    `site/gateway.html` sets `d.textContent = u.detail`, so whatever survives the JSON
    round trip is what the operator reads. Checked here rather than assumed: a mangled
    character would be the difference between an answer he can read off the rack and one
    he cannot.
    """

    def test_the_punctuation_survives_a_json_round_trip(self):
        with env(SYMONEURAL_GATEWAY_ENABLED="1", SYMONEURAL_GATEWAY_NETWORK="symoneural-test", SYMONEURAL_GATEWAY_CONTRACT=USDT):
            details = [gateway.unit_state(r)[1] for r in
                       (None, reading_for(), reading_for(contract_present=False),
                        reading_for(error="node rate-limited this box (HTTP 429)"))]
        with env():
            details.append(gateway.unit_state()[1])
        for d in details:
            with self.subTest(d=d[:40]):
                self.assertEqual(json.loads(json.dumps({"detail": d}))["detail"], d)
                raw = json.dumps({"detail": d}, ensure_ascii=False).encode("utf-8")
                self.assertEqual(json.loads(raw.decode("utf-8"))["detail"], d)
        self.assertTrue(any("—" in d for d in details))
        self.assertTrue(any("·" in d for d in details))


class TestRoute(unittest.TestCase):
    def test_503_while_the_surface_is_off_and_it_says_what_to_set(self):
        from fastapi import HTTPException
        with env():
            with self.assertRaises(HTTPException) as cm:
                routes.state()
        self.assertEqual(cm.exception.status_code, 503)
        self.assertIn("SYMONEURAL_GATEWAY_ENABLED=1", cm.exception.detail)

    def test_it_serves_the_cache_and_never_fetches(self):
        with env(SYMONEURAL_GATEWAY_ENABLED="1", SYMONEURAL_GATEWAY_NETWORK="symoneural-test", SYMONEURAL_GATEWAY_CONTRACT=USDT):
            gateway.CACHE.put(reading_for())
            with mock.patch.object(chain, "http_post", side_effect=AssertionError("fetched!")):
                out = routes.state()
        self.assertTrue(out["configured"])
        self.assertEqual(out["endpoint"], "https://nile.trongrid.io")
        self.assertEqual(out["reading"]["block"], 70_152_715)
        self.assertEqual(out["unit"]["state"], "offline")

    def test_it_reports_a_misconfiguration_rather_than_hiding_it(self):
        with env(SYMONEURAL_GATEWAY_ENABLED="1", SYMONEURAL_GATEWAY_NETWORK="bogus"):
            out = routes.state()
        self.assertFalse(out["configured"])
        self.assertIn("SYMONEURAL_GATEWAY_NETWORK", out["problem"])
        self.assertIsNone(out["endpoint"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
