"""Tests for on-chain settlement. Run: cd backend && python3 -m pytest apps/gateway -q

The important ones here are not the happy paths. `docs/specs/symon-ml-review.md` finding 1 is
a licence check that returned True when the chain was unreachable, and its second half is a
positive result cached for the process lifetime. Both are regression-tested below by name,
because both are the kind of bug a green test suite happily coexists with.

Each of those was verified to go RED by putting the bug back — a fail-closed test that has
never been seen to fail is not evidence of anything.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

_APPS = Path(__file__).resolve().parent.parent
if str(_APPS) not in sys.path:
    sys.path.insert(0, str(_APPS))

from gateway import abi, chain                                      # noqa: E402
from gateway import entitlement, store, verify                   # noqa: E402
from gateway.verify import Granted, Refused, verify_payment      # noqa: E402

# The canonical chain key -- what readings, `verify` and the clearance store are keyed by.
NET = "nile"
# The name an operator types, which is a different vocabulary on purpose (gateway/chain.py
# argues why). Resolved from the map rather than typed, so the two cannot drift.
NET_ENV = next(k for k, v in chain.OPERATOR_NETWORKS.items() if v == NET)
CONTRACT = "TNPeeaaFB7K9cmo4uQpcU32zGK8G1NYqeL"
PAYER = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
OTHER = "TLa2f6VPqDgRE67v1736s7bJ8Ray5wYjU7"
TOKEN = "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj"
WS = "0x" + "ab" * 32
OTHER_WS = "0x" + "cd" * 32
FIXTURE = Path(__file__).resolve().parents[2] / "ops/gateway/artifacts/licence-record.json"


# ------------------------------------------------------------------ a fake node, not a mock

def encode_licence(payer=PAYER, token=TOKEN, amount=1_000_000, workspace=WS,
                   at_block=70_000_000, at_time=1_786_000_000) -> str:
    """Build the exact 6-word return `licenceByNonce` produces, using our own encoder."""
    from gateway import address as A
    return b"".join([
        A.evm(payer).rjust(32, b"\x00"),
        A.evm(token).rjust(32, b"\x00"),
        amount.to_bytes(32, "big"),
        bytes.fromhex(workspace.removeprefix("0x")),
        at_block.to_bytes(32, "big"),
        at_time.to_bytes(32, "big"),
    ]).hex()


def node(result_hex: str | None = None, *, ok=True, status=200, message=""):
    """A `fetch` that answers like a TRON node, so no test touches the network."""
    def _fetch(url, body, timeout):
        payload = {"result": {"result": ok}}
        if message:
            payload["result"]["message"] = message.encode().hex()
        if result_hex is not None:
            payload["constant_result"] = [result_hex]
        return status, json.dumps(payload).encode()
    return _fetch


def exploding(exc=OSError("network is unreachable")):
    def _fetch(url, body, timeout):
        raise exc
    return _fetch


def probe_reading(**over):
    """A `chain.probe` reading shaped the way `unit_state` actually demands.

    The keys are load-bearing and were got wrong first time: `unit_state` discards any reading
    whose `network`/`contract` do not match the configured pair, and reads `age_s`,
    `contract_present`, `contract_name` and `abi_functions` -- not `age`, `present`, `name` or
    `functions`. A reading with the wrong keys is thrown away and the state is `offline` for a
    reason that has nothing to do with what the test is asserting, so a test built on one
    passes while proving nothing.
    """
    r = {"network": NET, "contract": CONTRACT, "contract_present": True,
         "contract_name": "SymoneuralLicence", "abi_functions": 9,
         "block": 70_000_000, "age_s": 1.0}
    r.update(over)
    return r


def ok_args(**over):
    args = dict(expect_payer=PAYER, expect_token=TOKEN, expect_workspace=WS,
                min_amount=1_000_000)
    args.update(over)
    return args


# ---------------------------------------------------------------------- finding 1, by name

class TestFailsClosed:
    """`_check_local_sandbox_state()` returned True unconditionally. Never again."""

    def test_an_unreachable_node_refuses_rather_than_granting(self):
        r = verify_payment(NET, CONTRACT, 1, fetch=exploding(), **ok_args())
        assert isinstance(r, Refused)
        assert not r, "a failed chain read must be falsy -- this is the reviewed bug"

    def test_blocking_the_node_cannot_grant_a_licence(self):
        """The literal firewall scenario from the review: one iptables rule granted it."""
        for exc in (OSError("connection refused"), TimeoutError("timed out"),
                    ValueError("garbage"), RuntimeError("boom")):
            r = verify_payment(NET, CONTRACT, 1, fetch=exploding(exc), **ok_args())
            assert not r, f"{type(exc).__name__} produced a grant"

    def test_a_reverting_call_refuses(self):
        assert not verify_payment(NET, CONTRACT, 1, fetch=node(ok=False, message="REVERT"),
                                  **ok_args())

    def test_an_http_error_refuses(self):
        assert not verify_payment(NET, CONTRACT, 1, fetch=node("00" * 192, status=500),
                                  **ok_args())

    def test_undecodable_data_refuses(self):
        assert not verify_payment(NET, CONTRACT, 1, fetch=node("beef"), **ok_args())

    def test_refused_is_falsy_and_granted_is_truthy(self):
        assert not Refused("x")
        assert Granted(nonce=1, payer=PAYER, token=TOKEN, amount=1, workspace=WS,
                       at_block=1, at_time=1)

    def test_no_exception_escapes_to_the_caller(self):
        """A caller must never need try/except -- that is where `except: pass` is born."""
        try:
            verify_payment(NET, CONTRACT, 1, fetch=exploding(), **ok_args())
        except Exception as e:                                  # noqa: BLE001
            pytest.fail(f"verify_payment raised {type(e).__name__}: {e}")


class TestNoCachedYes:
    """The review's second half: `is_licensed` set once, never re-checked, never expired."""

    def test_every_call_reads_the_chain_again(self):
        calls = []

        def counting(url, body, timeout):
            calls.append(1)
            return 200, json.dumps({"result": {"result": True},
                                    "constant_result": [encode_licence()]}).encode()

        for _ in range(3):
            assert verify_payment(NET, CONTRACT, 1, fetch=counting, **ok_args())
        assert len(calls) == 3, "a positive result was cached across calls"

    def test_a_grant_then_a_revocation_is_seen_immediately(self):
        assert verify_payment(NET, CONTRACT, 1, fetch=node(encode_licence()), **ok_args())
        empty = encode_licence(payer=OTHER, amount=0, at_time=0, at_block=0)
        assert not verify_payment(NET, CONTRACT, 1, fetch=node(empty), **ok_args())

    def test_the_module_holds_no_state(self):
        assert not [n for n, v in vars(verify).items()
                    if isinstance(v, (dict, list, set)) and n.islower()
                    and not n.startswith("_")], "module-level mutable state is a cache"


# ------------------------------------------------------------- the four unchecked fields

class TestChecksEveryField:
    """The PoC checked recipient and `confirmed` only. Each of these was a way in."""

    def test_a_matching_licence_is_granted(self):
        g = verify_payment(NET, CONTRACT, 7, fetch=node(encode_licence()), **ok_args())
        assert g, g
        assert g.nonce == 7 and g.payer == PAYER and g.amount == 1_000_000

    def test_a_different_payer_is_refused(self):
        r = verify_payment(NET, CONTRACT, 1, fetch=node(encode_licence(payer=OTHER)),
                           **ok_args())
        assert not r and "different address" in r.reason

    def test_a_different_token_is_refused(self):
        """Otherwise a token the buyer minted themselves buys a licence."""
        r = verify_payment(NET, CONTRACT, 1, fetch=node(encode_licence(token=OTHER)),
                           **ok_args())
        assert not r and "different token" in r.reason

    def test_a_different_workspace_is_refused(self):
        r = verify_payment(NET, CONTRACT, 1, fetch=node(encode_licence(workspace=OTHER_WS)),
                           **ok_args())
        assert not r and "different workspace" in r.reason

    def test_paying_less_than_required_is_refused(self):
        r = verify_payment(NET, CONTRACT, 1, fetch=node(encode_licence(amount=999_999)),
                           **ok_args())
        assert not r and "less than" in r.reason

    def test_paying_more_than_required_is_fine(self):
        assert verify_payment(NET, CONTRACT, 1, fetch=node(encode_licence(amount=2_000_000)),
                              **ok_args())

    def test_an_unissued_nonce_is_refused(self):
        """An unset mapping decodes to all zeros, not to an error. It must not grant."""
        r = verify_payment(NET, CONTRACT, 999, fetch=node("00" * 192), **ok_args())
        assert not r and "no licence" in r.reason

    def test_a_zero_minimum_cannot_be_used_to_grant_on_an_empty_record(self):
        assert not verify_payment(NET, CONTRACT, 1, fetch=node("00" * 192),
                                  **ok_args(min_amount=0))

    def test_a_malformed_address_is_refused_before_any_read(self):
        called = []

        def spy(url, body, timeout):
            called.append(1)
            raise AssertionError("should not have been reached")

        assert not verify_payment(NET, CONTRACT, 1, fetch=spy, **ok_args(expect_payer="nope"))
        assert not called, "a malformed argument still hit the network"


# --------------------------------------------------------------------------- the bytes32 trap

class TestAbiExtensions:
    def test_bytes32_round_trips_left_aligned(self):
        enc = abi.encode_params(["bytes32"], [WS])
        assert enc == "ab" * 32
        assert abi.decode_params(["bytes32"], enc)[0].hex() == "ab" * 32

    def test_a_workspace_hash_is_not_treated_as_a_number(self):
        """Right-aligning it would silently produce a different, plausible-looking hash."""
        ws = "0x" + "01" + "00" * 31
        out = abi.decode_params(["bytes32"], abi.encode_params(["bytes32"], [ws]))[0]
        assert out.hex() == "01" + "00" * 31, "bytes32 was right-aligned like a uint"

    def test_uint64_decodes_and_rejects_oversize(self):
        assert abi.decode_params(["uint64"], (2 ** 63).to_bytes(32, "big").hex())[0] == 2 ** 63
        with pytest.raises(abi.AbiError):
            abi.decode_params(["uint64"], (1 << 200).to_bytes(32, "big").hex())

    def test_the_return_shape_matches_the_compiled_artifact(self):
        """Pin the tuple order against the ABI, not against a comment that can drift."""
        art = Path(__file__).resolve().parents[2] / "ops/gateway/artifacts/SymoneuralLicence.json"
        if not art.exists():
            pytest.skip("artifacts not built")
        fn = [f for f in json.loads(art.read_text())["abi"]
              if f.get("name") == "licenceByNonce"][0]
        assert [o["type"] for o in fn["outputs"]] == verify.LICENCE_RETURNS

    def test_decodes_a_record_the_real_evm_produced(self):
        """The one test here that is not self-consistent, and the reason it exists.

        Every other licence test builds the node's answer with `encode_licence`, which uses
        our own encoder — so a wrong belief about the word layout would agree with itself and
        pass. `ops/gateway/test_contracts.mjs` redeems a licence in a real EVM and writes out
        exactly what `licenceByNonce` returned. Decoding *that* is what proves the layout, and
        it is what would have caught bytes32 being right-aligned like a uint.
        """
        if not FIXTURE.exists():
            pytest.skip("run: node ops/gateway/test_contracts.mjs")
        f = json.loads(FIXTURE.read_text())
        from gateway import address as A

        got = verify.read_licence(NET, CONTRACT, f["nonce"], fetch=node(f["raw"]))
        assert not isinstance(got, Refused), got
        assert got["payer"] == A.from_hex(f["expect"]["payer_hex"])
        assert got["token"] == A.from_hex(f["expect"]["token_hex"])
        assert got["amount"] == int(f["expect"]["amount"])
        assert got["workspace"] == "0x" + f["expect"]["workspace_hex"]
        assert got["at_block"] > 0 and got["at_time"] > 0

    def test_a_real_record_grants_only_for_the_right_expectations(self):
        """End to end: EVM settlement -> node shape -> decode -> grant, each field biting."""
        if not FIXTURE.exists():
            pytest.skip("run: node ops/gateway/test_contracts.mjs")
        f = json.loads(FIXTURE.read_text())
        from gateway import address as A
        payer, token = A.from_hex(f["expect"]["payer_hex"]), A.from_hex(f["expect"]["token_hex"])
        ws, amt = "0x" + f["expect"]["workspace_hex"], int(f["expect"]["amount"])
        real = dict(expect_payer=payer, expect_token=token, expect_workspace=ws, min_amount=amt)

        assert verify_payment(NET, CONTRACT, f["nonce"], fetch=node(f["raw"]), **real)
        for wrong in (dict(expect_payer=OTHER), dict(expect_token=OTHER),
                      dict(expect_workspace=OTHER_WS), dict(min_amount=amt + 1)):
            assert not verify_payment(NET, CONTRACT, f["nonce"], fetch=node(f["raw"]),
                                      **{**real, **wrong}), f"{wrong} still granted"


# ------------------------------------------------------------------------------ entitlements

class TestEntitlement:
    def setup_method(self):
        self.key, self.pem = entitlement.generate()
        self.pub = self.key.public_key()

    def mint(self, **over):
        args = dict(workspace=WS, payer=PAYER, nonce=1, network=NET, contract=CONTRACT)
        args.update(over)
        return entitlement.mint(self.key, **args)

    def test_a_freshly_minted_entitlement_verifies(self):
        ent = entitlement.verify(self.mint(), self.pub)
        assert ent is not None and ent.payer == PAYER and ent.nonce == 1

    def test_a_tampered_payload_does_not_verify(self):
        import base64
        body, sig = self.mint().split(".")
        data = json.loads(base64.urlsafe_b64decode(body + "==="))
        data["payer"] = OTHER
        forged = base64.urlsafe_b64encode(
            json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        ).rstrip(b"=").decode()
        assert entitlement.verify(f"{forged}.{sig}", self.pub) is None

    def test_another_authoritys_signature_does_not_verify(self):
        other, _ = entitlement.generate()
        assert entitlement.verify(self.mint(), other.public_key()) is None

    def test_an_expired_entitlement_is_refused(self):
        assert entitlement.verify(self.mint(ttl_s=60, now=int(time.time()) - 3600),
                                  self.pub) is None

    def test_an_entitlement_from_the_future_is_refused(self):
        assert entitlement.verify(self.mint(now=int(time.time()) + 3600), self.pub) is None

    def test_garbage_returns_none_and_never_raises(self):
        for bad in ["", ".", "a.b", "....", "x" * 200, "a.b.c", None, 12]:
            assert entitlement.verify(bad, self.pub) is None    # type: ignore

    def test_verify_accepts_a_raw_public_key(self):
        from cryptography.hazmat.primitives import serialization as s
        raw = self.pub.public_bytes(s.Encoding.Raw, s.PublicFormat.Raw)
        assert entitlement.verify(self.mint(), raw) is not None

    def test_the_public_key_cannot_mint(self):
        assert not hasattr(self.pub, "sign"), "the public key can sign -- asymmetry is gone"

    def test_the_signed_payload_is_canonical(self):
        a = entitlement.Entitlement(1, WS, PAYER, 1, NET, CONTRACT, 100, 200).payload()
        b = entitlement.Entitlement(1, WS, PAYER, 1, NET, CONTRACT, 100, 200).payload()
        assert a == b and b" " not in a

    def test_it_is_not_a_jwt_and_has_no_algorithm_field(self):
        """No `alg` means no `alg: none`, the canonical JWT foot-gun."""
        import base64
        body = json.loads(base64.urlsafe_b64decode(self.mint().split(".")[0] + "==="))
        assert "alg" not in body and "typ" not in body


# --------------------------------------------------------------------------------- the store

class TestClearanceStore:
    def make(self, **over):
        args = dict(nonce=1, payer=PAYER, token=TOKEN, amount=1_000_000, workspace=WS,
                    network=NET, contract=CONTRACT, at_block=70_000_000, at_time=1_786_000_000)
        args.update(over)
        return store.Clearance(**args)

    def test_a_missing_store_is_zero_clearances_not_an_error(self, tmp_path):
        s = store.ClearanceStore(tmp_path / "nope.jsonl")
        assert s.all() == [] and s.count() == 0 and not s.has_cleared(NET, CONTRACT)

    def test_an_appended_clearance_survives_a_reopen(self, tmp_path):
        p = tmp_path / "c.jsonl"
        store.ClearanceStore(p).append(self.make())
        assert store.ClearanceStore(p).has_cleared(NET, CONTRACT)

    def test_a_truncated_final_line_does_not_lose_the_rest(self, tmp_path):
        p = tmp_path / "c.jsonl"
        s = store.ClearanceStore(p)
        s.append(self.make(nonce=1))
        s.append(self.make(nonce=2))
        with open(p, "a") as fh:
            fh.write('{"nonce": 3, "payer"')          # power cut mid-write
        s2 = store.ClearanceStore(p)
        assert len(s2.all()) == 2 and s2.bad_lines == 1

    def test_a_clearance_on_another_network_does_not_count(self, tmp_path):
        p = tmp_path / "c.jsonl"
        store.ClearanceStore(p).append(self.make(network="shasta"))
        s = store.ClearanceStore(p)
        assert not s.has_cleared("mainnet", CONTRACT)
        assert not s.has_cleared(NET, CONTRACT)
        assert s.has_cleared("shasta", CONTRACT)

    def test_a_clearance_against_another_contract_does_not_count(self, tmp_path):
        p = tmp_path / "c.jsonl"
        store.ClearanceStore(p).append(self.make(contract=OTHER))
        assert not store.ClearanceStore(p).has_cleared(NET, CONTRACT)

    def test_latest_picks_the_newest_settlement(self, tmp_path):
        p = tmp_path / "c.jsonl"
        s = store.ClearanceStore(p)
        for n, t in ((1, 100), (2, 300), (3, 200)):
            s.append(self.make(nonce=n, at_time=t))
        assert store.ClearanceStore(p).latest(NET, CONTRACT).nonce == 2


# ------------------------------------------------------- the serving process holds no key

class TestServingSideHasNoPrivateKey:
    def test_this_package_never_imports_the_operator_toolchain(self):
        src = "\n".join((Path(__file__).parent / f).read_text()
                        for f in ("__init__.py", "verify.py", "entitlement.py", "store.py"))
        for banned in ("tronpy", "coincurve", "ops.gateway", "from ops", "import ops"):
            assert banned not in src, f"{banned} reached the serving side"

    def test_nothing_here_can_sign_a_tron_transaction(self):
        """Scan identifiers, not source text.

        The text version of this test failed on its own documentation: verify.py's docstring
        says the module cannot "sign or broadcast", and a substring search cannot tell a
        promise from a call. Parse instead, and look only at names the code actually uses.
        """
        import ast
        tree = ast.parse((Path(__file__).parent / "verify.py").read_text())
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names |= {n.value for n in ast.walk(tree)
                  if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        for banned in ("broadcast", "sign_msg_hash", "PrivateKey", "triggersmartcontract",
                       "sign", "sendrawtransaction"):
            assert banned not in names, f"verify.py uses {banned}"

    def test_verify_only_ever_makes_constant_calls(self):
        seen = []

        def spy(url, body, timeout):
            seen.append(url)
            return 200, json.dumps({"result": {"result": True},
                                    "constant_result": [encode_licence()]}).encode()

        verify_payment(NET, CONTRACT, 1, fetch=spy, **ok_args())
        assert seen, "no call was made at all -- this test would pass vacuously"
        for url in seen:
            assert "triggerconstantcontract" in url, url
            assert "triggersmartcontract" not in url


# -------------------------------------------------- the two packages must not be confused

class TestNotTheOtherLicensingPackage:
    """`apps/licensing/` is the mining dev fee. This work once overwrote it. Never again."""

    def test_the_dev_fee_package_is_still_intact_and_separate(self):
        lic = Path(__file__).resolve().parent.parent / "licensing"
        for f in ("__init__.py", "issue.py", "test_licensing.py", "contract-signing.pub"):
            assert (lic / f).exists(), f"licensing/{f} is missing"
        assert "dev fee" in (lic / "__init__.py").read_text()[:400].lower()

    def test_this_package_does_not_import_the_dev_fee_model(self):
        src = "\n".join((Path(__file__).parent / f).read_text()
                        for f in ("verify.py", "entitlement.py", "store.py"))
        assert "import licensing" not in src and "from licensing" not in src


# ------------------------------------------ the writer: the only path from a payment to the LED

class TestRecorder:
    """`record_settlement` is the only thing in the serving tree that writes a clearance.

    Until it existed nothing did, so a real customer could have paid on a real chain and the
    rack would have stayed dark. These tests are mostly about what it must *not* write.
    """

    def _store(self, tmp_path):
        return store.ClearanceStore(tmp_path / "clearances.jsonl")

    def test_a_verified_settlement_is_recorded_once(self, tmp_path):
        from gateway.record import record_settlement
        s = self._store(tmp_path)
        r = record_settlement(NET, CONTRACT, 7, store=s, fetch=node(encode_licence()),
                              **ok_args())
        assert r, str(r)
        assert s.count() == 1
        c = s.all()[0]
        assert (c.nonce, c.payer, c.token, c.amount) == (7, PAYER, TOKEN, 1_000_000)
        assert (c.network, c.contract) == (NET, CONTRACT)

    def test_an_unreachable_chain_records_nothing(self, tmp_path):
        from gateway.record import record_settlement
        s = self._store(tmp_path)
        r = record_settlement(NET, CONTRACT, 7, store=s, fetch=exploding(), **ok_args())
        assert not r
        assert s.count() == 0, "an outage left a clearance behind"

    def test_a_refused_settlement_records_nothing(self, tmp_path):
        """One case per field, because a single 'it refuses' test hides three live bugs."""
        from gateway.record import record_settlement
        for label, over in (("payer", dict(expect_payer=OTHER)),
                            ("token", dict(expect_token=OTHER)),
                            ("workspace", dict(expect_workspace=OTHER_WS)),
                            ("amount", dict(min_amount=2_000_000))):
            s = self._store(tmp_path / label)
            r = record_settlement(NET, CONTRACT, 7, store=s, fetch=node(encode_licence()),
                                  **ok_args(**over))
            assert not r, f"wrong {label} was granted"
            assert s.count() == 0, f"wrong {label} was recorded anyway"

    def test_recording_the_same_nonce_twice_appends_once(self, tmp_path):
        from gateway.record import record_settlement, AlreadyRecorded
        s = self._store(tmp_path)
        first = record_settlement(NET, CONTRACT, 7, store=s, fetch=node(encode_licence()),
                                  **ok_args())
        second = record_settlement(NET, CONTRACT, 7, store=s, fetch=node(encode_licence()),
                                   **ok_args())
        assert first and isinstance(second, AlreadyRecorded)
        assert not second, "AlreadyRecorded must stay falsy"
        assert s.count() == 1

    def test_the_same_nonce_on_another_contract_is_a_different_licence(self, tmp_path):
        from gateway.record import record_settlement
        s = self._store(tmp_path)
        record_settlement(NET, CONTRACT, 7, store=s, fetch=node(encode_licence()), **ok_args())
        r = record_settlement("shasta", CONTRACT, 7, store=s, fetch=node(encode_licence()),
                              **ok_args())
        assert r, "a nonce is only unique within one deployment"
        assert s.count() == 2

    def test_the_readable_workspace_and_its_word_mean_the_same_thing(self):
        """`quote` takes a readable string; the chain stores keccak256 of it.

        An operator who passes the same `--workspace` to both commands must not be told the
        licence covers a different workspace. This is the one place the two CLIs could
        disagree while both looking right.
        """
        from gateway.record import workspace_key
        human = "debian-13 · cuda-12.8 · sm_120"
        word = workspace_key(human)
        assert word.startswith("0x") and len(word) == 66
        assert workspace_key(word) == word, "hashing an already-hashed word"

        # The same rule ops/gateway/gateway-cli.py applies, checked against its source rather
        # than trusted: nothing may import from ops/, so the two implementations are separate.
        cli = (Path(__file__).resolve().parents[2]
               / "ops/gateway/gateway-cli.py").read_text()
        assert 'workspace.startswith("0x")' in cli
        assert "keccak256(workspace.encode())" in cli

    def test_recording_by_readable_workspace_matches_the_quoted_licence(self, tmp_path):
        from gateway.record import record_settlement, workspace_key
        human = "debian-13 · cuda-12.8 · sm_120"
        onchain = workspace_key(human)
        s = self._store(tmp_path)
        r = record_settlement(NET, CONTRACT, 7, store=s,
                              fetch=node(encode_licence(workspace=onchain)),
                              **ok_args(expect_workspace=workspace_key(human)))
        assert r, str(r)
        assert s.count() == 1

    def test_the_operator_cli_runs_and_reports_by_exit_code(self, tmp_path, monkeypatch):
        """`main()` is what DEPLOY.md tells an operator to type, and it had never been run.

        Exit codes matter here because the command is meant to be usable from a shell script:
        0 for a fresh recording and for a repeat, non-zero for any refusal.
        """
        from gateway import record as rec_mod
        monkeypatch.setattr(store, "DEFAULT_PATH", tmp_path / "clearances.jsonl")
        monkeypatch.setattr(rec_mod, "verify_payment",
                            lambda *a, **k: verify.verify_payment(*a, **{**k, "fetch": node(
                                encode_licence())}))
        argv = ["--network", NET_ENV, "--contract", CONTRACT, "--nonce", "7",
                "--payer", PAYER, "--token", TOKEN, "--workspace", WS,
                "--min-amount", "1000000"]

        assert rec_mod.main(argv) == 0, "a good settlement did not exit 0"
        assert rec_mod.main(argv) == 0, "re-running must not be an error"
        assert store.ClearanceStore(tmp_path / "clearances.jsonl").count() == 1

        # A fresh nonce, or the already-recorded check short-circuits before verification and
        # this asserts nothing. That precedence is deliberate — a nonce already on file was
        # verified when it was written, and re-reading the chain for it is wasted work — but
        # it means a wrong-payer re-run of a *recorded* nonce reports "already recorded"
        # rather than the mismatch. Pinned just below so the ordering cannot change silently.
        bad = list(argv)
        bad[bad.index("--nonce") + 1] = "8"
        bad[bad.index("--payer") + 1] = OTHER
        assert rec_mod.main(bad) == 1, "a refusal must exit non-zero"
        assert store.ClearanceStore(tmp_path / "clearances.jsonl").count() == 1

        repeat_with_nonsense = list(argv)
        repeat_with_nonsense[repeat_with_nonsense.index("--payer") + 1] = OTHER
        assert rec_mod.main(repeat_with_nonsense) == 0, \
            "an already-recorded nonce is reported as such before anything is re-verified"

    def test_there_is_no_way_to_record_without_a_chain_read(self):
        """No bypass flag, no caller-supplied record: every write follows a chain read.

        Scanned through the AST rather than as text. A substring scan reads this module's own
        prose -- the docstring says the words it is looking for -- and fails on the sentence
        promising the thing it is checking. That already happened once here, and once before
        in `test_nothing_here_can_sign_a_tron_transaction`.
        """
        import ast
        src = (Path(__file__).parent / "record.py").read_text()
        tree = ast.parse(src)

        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        names |= {a.arg for n in ast.walk(tree)
                  if isinstance(n, ast.arguments) for a in n.args + n.kwonlyargs}
        names |= {k.arg for n in ast.walk(tree)
                  if isinstance(n, ast.keyword) for k in [n] if k.arg}
        flags = {s.value for s in ast.walk(tree)
                 if isinstance(s, ast.Constant) and isinstance(s.value, str)
                 and s.value.startswith("--")}

        for escape in ("force", "assume", "skip_verify", "no_verify", "trust"):
            bad = {i for i in names | flags if escape in i.lower()}
            assert not bad, f"record.py grew a bypass: {bad}"

        called = {n.func.id for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        assert "verify_payment" in called, "recording no longer reads the chain"


class TestRecordingIsWhatLightsTheLed:
    """End to end: the rack is dark until a settlement is recorded, and green after.

    This is the assertion the whole surface exists to earn. It runs `unit_state` for real
    against a temporary clearance file rather than asserting on a mocked return value.
    """

    def test_unit_state_goes_from_offline_to_ready_when_a_settlement_is_recorded(
            self, tmp_path, monkeypatch):
        import gateway
        from gateway.record import record_settlement

        monkeypatch.setenv("SYMONEURAL_GATEWAY_ENABLED", "1")
        monkeypatch.setenv("SYMONEURAL_GATEWAY_NETWORK", NET_ENV)
        monkeypatch.setenv("SYMONEURAL_GATEWAY_CONTRACT", CONTRACT)
        monkeypatch.setattr(store, "DEFAULT_PATH", tmp_path / "clearances.jsonl")

        reading = probe_reading()

        state, _ = gateway.unit_state(reading)
        assert state == "offline", "dark before anything settled"

        r = record_settlement(NET, CONTRACT, 7, fetch=node(encode_licence()), **ok_args())
        assert r, str(r)

        state, detail = gateway.unit_state(reading)
        assert state == "ready", f"a settlement did not light the LED: {detail}"

    def test_an_unreadable_store_says_so_instead_of_claiming_nothing_settled(
            self, tmp_path, monkeypatch):
        """Fail-closed is the right state and can still be the wrong sentence.

        `ClearanceStore.all` turns an unreadable file into zero clearances, so the surface
        used to report "no licence has ever cleared against this contract" when the truth was
        that nobody could tell. Same LED, different claim — and this site's whole argument is
        that what it prints is real.
        """
        import gateway
        monkeypatch.setenv("SYMONEURAL_GATEWAY_ENABLED", "1")
        monkeypatch.setenv("SYMONEURAL_GATEWAY_NETWORK", NET_ENV)
        monkeypatch.setenv("SYMONEURAL_GATEWAY_CONTRACT", CONTRACT)

        p = tmp_path / "clearances.jsonl"
        p.write_text("{}\n")
        p.chmod(0o000)
        monkeypatch.setattr(store, "DEFAULT_PATH", p)
        try:
            state, detail = gateway.unit_state(probe_reading())
        finally:
            p.chmod(0o600)

        assert state == "offline"
        assert "could not be read" in detail, detail
        assert "no licence has ever cleared" not in detail, \
            "claimed nothing settled when the store was unreadable"

    def test_a_corrupt_line_is_disclosed_rather_than_silently_skipped(
            self, tmp_path, monkeypatch):
        import gateway
        from gateway.record import record_settlement
        monkeypatch.setenv("SYMONEURAL_GATEWAY_ENABLED", "1")
        monkeypatch.setenv("SYMONEURAL_GATEWAY_NETWORK", NET_ENV)
        monkeypatch.setenv("SYMONEURAL_GATEWAY_CONTRACT", CONTRACT)
        p = tmp_path / "clearances.jsonl"
        monkeypatch.setattr(store, "DEFAULT_PATH", p)

        record_settlement(NET, CONTRACT, 7, fetch=node(encode_licence()), **ok_args())
        with open(p, "a", encoding="utf-8") as fh:
            fh.write("{not json at all\n")

        state, detail = gateway.unit_state(probe_reading())
        assert state == "ready", detail
        assert "could not be parsed" in detail, detail

    def test_a_settlement_on_a_different_contract_does_not_light_it(
            self, tmp_path, monkeypatch):
        import gateway
        from gateway.record import record_settlement

        monkeypatch.setenv("SYMONEURAL_GATEWAY_ENABLED", "1")
        monkeypatch.setenv("SYMONEURAL_GATEWAY_NETWORK", NET_ENV)
        monkeypatch.setenv("SYMONEURAL_GATEWAY_CONTRACT", CONTRACT)
        monkeypatch.setattr(store, "DEFAULT_PATH", tmp_path / "clearances.jsonl")

        record_settlement("shasta", OTHER, 7, fetch=node(encode_licence()), **ok_args())
        state, detail = gateway.unit_state(probe_reading())
        assert state == "offline", "somebody else's deployment lit our lamp"
        # It must be dark for the RIGHT reason. With a malformed reading this assertion
        # passes no matter what the store holds, which is how it first passed.
        assert "no licence has ever cleared" in detail, detail
