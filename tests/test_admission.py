"""Stake-gated admission: off by default; on, stake + binding must agree."""

import copy
import json

import pytest

from mesh import admission
from mesh.staking import StakeStatus
from tests import vectors


@pytest.fixture(autouse=True)
def _fresh_cache():
    admission.clear_cache()
    yield
    admission.clear_cache()


def _vector():
    data = json.loads(vectors.FIXTURE_PATH.read_text())["binding_identity_v3"]
    return data["identity_v3"], data["wallet_address"].lower()


class FakeReader:
    def __init__(self, active=True, operator=None):
        self.active = active
        self.operator = operator
        self.calls = 0

    async def status(self, pid):
        self.calls += 1
        return StakeStatus(pid=pid, active=self.active, operator=self.operator)


REQUIRED = {"mesh_require_stake": True, "staking_contracts": ["0x" + "11" * 20]}


async def test_everyone_admitted_when_not_required():
    reader = FakeReader(active=False)
    assert await admission.peer_admitted("a" * 64, "h", 7070, config={}, reader=reader)
    assert reader.calls == 0


async def test_required_without_contracts_admits_nobody():
    assert not await admission.peer_admitted(
        "a" * 64, "h", 7070, config={"mesh_require_stake": True})


async def test_staked_and_bound_is_admitted():
    pytest.importorskip("eth_account")
    doc, wallet = _vector()

    async def fetch(host, port):
        return doc

    ok = await admission.peer_admitted(doc["pid"], "h", 7070, config=REQUIRED,
                                       reader=FakeReader(operator=wallet), fetch_identity=fetch)
    assert ok


async def test_inactive_stake_is_refused():
    doc, wallet = _vector()

    async def fetch(host, port):
        raise AssertionError("identity is not fetched for an inactive stake")

    ok, why = await admission.check_peer(doc["pid"], "h", 7070,
                                         FakeReader(active=False, operator=wallet), fetch)
    assert not ok and "not active on-chain" in why


async def test_stake_from_an_unbound_wallet_is_refused():
    doc, _ = _vector()

    async def fetch(host, port):
        return doc

    ok, why = await admission.check_peer(doc["pid"], "h", 7070,
                                         FakeReader(operator="0x" + "99" * 20), fetch)
    assert not ok and "not bound" in why


async def test_identity_for_another_pid_is_refused():
    doc, wallet = _vector()

    async def fetch(host, port):
        return doc

    ok, why = await admission.check_peer("f" * 64, "h", 7070, FakeReader(operator=wallet), fetch)
    assert not ok and "different PID" in why


async def test_tampered_identity_is_refused():
    doc, wallet = _vector()
    forged = copy.deepcopy(doc)
    forged["authority"] = "evil.example"

    async def fetch(host, port):
        return forged

    ok, why = await admission.check_peer(doc["pid"], "h", 7070, FakeReader(operator=wallet), fetch)
    assert not ok and "identity v3" in why


async def test_unreachable_peer_is_refused_not_raised():
    doc, wallet = _vector()

    async def fetch(host, port):
        raise ConnectionRefusedError()

    ok, why = await admission.check_peer(doc["pid"], "h", 7070, FakeReader(operator=wallet), fetch)
    assert not ok and "admission check failed" in why


async def test_decisions_are_cached():
    reader = FakeReader(active=False)
    for _ in range(3):
        assert not await admission.peer_admitted("a" * 64, "h", 7070, config=REQUIRED,
                                                 reader=reader)
    assert reader.calls == 1


def test_parse_signed_json_strips_terminator_and_trailer():
    text = ('{"a": 1}\r\n.\r\n'
            "\r\n---BEGIN REFINET SIGNATURE---\r\npid:x\r\n---END REFINET SIGNATURE---\r\n")
    assert admission.parse_signed_json(text) == {"a": 1}
    assert admission.parse_signed_json('{"a": 2}') == {"a": 2}


async def test_replication_skips_peers_that_are_not_admitted(monkeypatch):
    from mesh import replication

    async def refuse(pid, host, port, config=None, **kw):
        return False

    async def fetch(*a, **kw):
        raise AssertionError("an unadmitted peer is never fetched")

    monkeypatch.setattr(admission, "peer_admitted", refuse)
    monkeypatch.setattr(replication, "fetch", fetch)
    assert await replication.sync_peer_registry("h", 7070, "a" * 64) == 0


# ---------------------------------------------------------------------------
# A pre-0.5.0 ("legacy") binding names no PID and its counter-signature is not
# domain-separated, and the peer decides which of its records look legacy. So
# a peer could take any sign-in message a wallet ever signed anywhere, counter
# sign it with its own key, and publish it as "this wallet runs my Pillar".
# ---------------------------------------------------------------------------
def _forged_legacy_doc(victim_wallet: str):
    from crypto.binding import compute_binding_id, sign_binding_id, build_identity_v3
    from crypto.pid import generate_pid, get_private_key

    attacker = generate_pid()
    key = get_private_key(attacker)
    nonce = "0123456789abcdef"
    # An ordinary EIP-4361 sign-in message: it never names a PID
    message = ("example.com wants you to sign in with your Ethereum account:\n"
               f"{victim_wallet}\n\nSign in\n\nURI: https://example.com\nVersion: 1\n"
               f"Chain ID: 1\nNonce: {nonce}\nIssued At: 2026-01-01T00:00:00Z")
    binding_id = compute_binding_id(attacker["pid"], victim_wallet, nonce)
    binding = {
        "binding_id": binding_id,
        "type": "deployer",
        "evm_address": victim_wallet,
        "chain_id": 1,
        "siwe_message": message,
        "siwe_signature": "0x" + "11" * 65,
        # Bare signature over the binding_id — what a legacy record carries
        "pid_signature": sign_binding_id(binding_id, key),
        "created_at": "2026-01-01T00:00:00Z",
    }
    doc = build_identity_v3(pid=attacker["pid"], public_key=attacker["public_key"],
                            authority=f"{attacker['pid']}.pillar.refinet",
                            bindings=[binding], private_key=key)
    return doc


def test_a_legacy_binding_cannot_claim_a_wallet():
    victim = "0x" + "ab" * 20
    doc = _forged_legacy_doc(victim)
    from crypto.binding import verify_identity_v3
    # The document itself is genuinely signed by the attacker's own key…
    assert verify_identity_v3(doc)[0]
    # …but the wallet it names never agreed to anything
    ok, why = admission.operator_is_bound(doc, victim)
    assert not ok and "predates 0.5.0" in why


async def test_forged_legacy_binding_is_not_admitted():
    victim = "0x" + "ab" * 20
    doc = _forged_legacy_doc(victim)

    async def fetch(host, port):
        return doc

    ok, why = await admission.check_peer(doc["pid"], "h", 7070,
                                         FakeReader(operator=victim), fetch)
    assert not ok and "predates 0.5.0" in why


async def test_a_verdict_is_not_reused_at_another_address():
    """An approval at one address says nothing about the same PID elsewhere."""
    pytest.importorskip("eth_account")
    doc, wallet = _vector()
    fetched = []

    async def fetch(host, port):
        fetched.append((host, port))
        return doc

    reader = FakeReader(operator=wallet)
    assert await admission.peer_admitted(doc["pid"], "real.example.com", 7070,
                                         config=REQUIRED, reader=reader, fetch_identity=fetch)
    # Same PID, attacker's address: it must be checked there too
    await admission.peer_admitted(doc["pid"], "attacker.example.com", 7070,
                                  config=REQUIRED, reader=reader, fetch_identity=fetch)
    assert fetched == [("real.example.com", 7070), ("attacker.example.com", 7070)]
