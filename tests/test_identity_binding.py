"""Identity: a binding is not a login, and a challenge is not portable.

Covers F1 (binding statement is its own statement), F2 (the chain id comes
from the message), F3 (per-Pillar domain, nonce registry, URI check) and
F4 (contract wallets via EIP-1271), plus the §3.2 identity document.
"""

import json

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from auth import siwe
from auth.session import create_challenge, establish_session
from auth.siwe import (
    PURPOSE_BINDING, PURPOSE_LOGIN, generate_binding_challenge,
    generate_challenge, is_binding_message, parse_binding_statement,
    pillar_authority, parse_chain_id,
)
from crypto.binding import (
    create_binding, verify_binding, get_deployer_binding, get_v1_bindings,
    compute_binding_id, build_identity_v3, verify_identity_v3,
    is_legacy_binding,
)
from crypto.pid import generate_pid, get_private_key, save_pid
from crypto.signing import sign_content
from db.live_db import _connect, init_live_db, record_siwe_nonce


@pytest.fixture(autouse=True)
def _db():
    init_live_db()


@pytest.fixture
def pillar():
    pid_data = generate_pid()
    save_pid(pid_data)
    return pid_data, get_private_key(pid_data)


def _sign(account, message):
    sig = account.sign_message(encode_defunct(text=message)).signature.hex()
    return sig if sig.startswith("0x") else "0x" + sig


class TestMessageShape:
    def test_binding_statement_is_exact(self, pillar):
        pid_data, _ = pillar
        account = Account.create()
        msg, _ = generate_binding_challenge(account.address, pid_data["pid"],
                                            chain_id=43113)
        assert (f"I bind this wallet to REFINET Pillar {pid_data['pid']} as its deployer"
                in msg)
        assert f"URI: refinet://pillar/{pid_data['pid']}" in msg
        assert parse_binding_statement(msg) == (pid_data["pid"], "deployer")
        assert is_binding_message(msg)

    def test_login_statement_is_not_a_binding(self, pillar):
        pid_data, _ = pillar
        msg, _ = generate_challenge("0x" + "1" * 40, pid_data["pid"])
        assert not is_binding_message(msg)
        assert f"Sign in to REFInet Pillar {pid_data['pid']}" in msg

    def test_statement_carries_the_full_pid_not_a_prefix(self, pillar):
        pid_data, _ = pillar
        msg, _ = generate_challenge("0x" + "1" * 40, pid_data["pid"])
        assert pid_data["pid"][:16] + "..." not in msg
        assert pid_data["pid"] in msg

    def test_authority_is_per_pillar_not_one_literal(self, pillar):
        pid_data, _ = pillar
        other = generate_pid()
        assert pillar_authority(pid_data["pid"]) != pillar_authority(other["pid"])
        assert pillar_authority(pid_data["pid"], "pillar.example.org", 7070) == \
            "pillar.example.org:7070"

    def test_company_url_appears_in_resources(self, pillar):
        pid_data, _ = pillar
        msg, _ = generate_binding_challenge(
            "0x" + "1" * 40, pid_data["pid"], chain_id=43113,
            company_url="https://tradesphere.example/company/7")
        assert "- https://tradesphere.example/company/7" in msg


class TestPurposeSeparation:
    def test_login_message_cannot_create_a_binding(self, pillar):
        """F1: the bug — a sign-in signature was accepted as a binding."""
        pid_data, key = pillar
        account = Account.create()
        challenge = create_challenge(account.address, chain_id=1)
        with pytest.raises(ValueError, match="Not a binding message"):
            create_binding(
                pid_data=pid_data, evm_address=account.address,
                siwe_message=challenge["message"],
                siwe_signature=_sign(account, challenge["message"]),
                private_key=key, binding_type="deployer")

    def test_binding_message_cannot_open_a_session(self, pillar):
        """F3: the binding is published, so it must not be spendable as a login."""
        pid_data, _ = pillar
        account = Account.create()
        challenge = create_challenge(account.address, chain_id=1,
                                     purpose=PURPOSE_BINDING)
        with pytest.raises(ValueError, match="cannot open a session"):
            establish_session(account.address, challenge["message"],
                              _sign(account, challenge["message"]))

    def test_binding_nonce_cannot_be_spent_as_a_login_nonce(self, pillar):
        pid_data, _ = pillar
        account = Account.create()
        msg, nonce = generate_binding_challenge(account.address, pid_data["pid"],
                                                chain_id=1)
        record_siwe_nonce(nonce, PURPOSE_BINDING, pid_data["pid"])
        # Strip the binding statement so only the nonce's purpose can catch it
        forged = msg.replace(
            f"I bind this wallet to REFINET Pillar {pid_data['pid']} as its deployer",
            f"Sign in to REFInet Pillar {pid_data['pid']}")
        with pytest.raises(ValueError, match="issued for 'binding'"):
            establish_session(account.address, forged, _sign(account, forged))

    def test_role_must_match_the_statement(self, pillar):
        pid_data, key = pillar
        account = Account.create()
        challenge = create_challenge(account.address, chain_id=1,
                                     purpose=PURPOSE_BINDING,
                                     binding_type="operator")
        with pytest.raises(ValueError, match="says 'operator'"):
            create_binding(
                pid_data=pid_data, evm_address=account.address,
                siwe_message=challenge["message"],
                siwe_signature=_sign(account, challenge["message"]),
                private_key=key, binding_type="deployer")


class TestNonceRegistry:
    def test_unissued_nonce_is_refused(self, pillar):
        pid_data, _ = pillar
        account = Account.create()
        msg, _ = generate_challenge(account.address, pid_data["pid"])  # never registered
        with pytest.raises(ValueError, match="not issued by this Pillar"):
            establish_session(account.address, msg, _sign(account, msg))

    def test_nonce_is_spent_on_first_use(self, pillar):
        pid_data, _ = pillar
        account = Account.create()
        challenge = create_challenge(account.address, chain_id=1)
        sig = _sign(account, challenge["message"])
        assert establish_session(account.address, challenge["message"], sig)["session_id"]
        with pytest.raises(ValueError, match="already used"):
            establish_session(account.address, challenge["message"], sig)

    def test_nonce_is_spent_even_when_the_signature_is_wrong(self, pillar):
        pid_data, _ = pillar
        account, impostor = Account.create(), Account.create()
        challenge = create_challenge(account.address, chain_id=1)
        with pytest.raises(ValueError, match="Signature verification failed"):
            establish_session(account.address, challenge["message"],
                              _sign(impostor, challenge["message"]))
        # The challenge is burned: no second attempt with the right signature
        with pytest.raises(ValueError, match="already used"):
            establish_session(account.address, challenge["message"],
                              _sign(account, challenge["message"]))

    def test_message_from_another_pillar_is_refused(self, pillar, monkeypatch):
        """F3: publishing a message at /identity.json must not be a login elsewhere."""
        pid_a, _ = pillar
        account = Account.create()
        challenge = create_challenge(account.address, chain_id=1)   # issued by A
        sig = _sign(account, challenge["message"])

        # Pillar B: same database, different identity
        pid_b = generate_pid()
        save_pid(pid_b)
        monkeypatch.setattr("auth.session.get_or_create_pid", lambda: pid_b)
        with pytest.raises(ValueError, match="not issued by this Pillar"):
            establish_session(account.address, challenge["message"], sig)


class TestChainId:
    def test_binding_records_the_chain_the_wallet_signed_on(self, pillar):
        """F2: the wizard used to hard-code chain 1 for every binding."""
        pid_data, key = pillar
        account = Account.create()
        challenge = create_challenge(account.address, chain_id=43113,
                                     purpose=PURPOSE_BINDING)
        assert parse_chain_id(challenge["message"]) == 43113
        binding = create_binding(
            pid_data=pid_data, evm_address=account.address,
            siwe_message=challenge["message"],
            siwe_signature=_sign(account, challenge["message"]),
            private_key=key, binding_type="deployer")
        assert binding["chain_id"] == 43113


class TestContractWallets:
    def test_eip1271_accepted_when_the_account_contract_says_yes(self, pillar, monkeypatch):
        """F4: a Safe produces no recoverable signature."""
        from auth import wallet_sig
        pid_data, key = pillar
        safe_address = "0x" + "5" * 40
        challenge = create_challenge(safe_address, chain_id=43113,
                                     purpose=PURPOSE_BINDING)
        # The Pillar states which chains it will believe a contract wallet on.
        monkeypatch.setattr(wallet_sig, "_accepted_contract_chains", lambda: {43113})
        monkeypatch.setattr(wallet_sig, "verify_eip1271",
                            lambda *a, **k: (True, "valid (EIP-1271)"))
        binding = create_binding(
            pid_data=pid_data, evm_address=safe_address,
            siwe_message=challenge["message"],
            siwe_signature="0x" + "ab" * 65,
            private_key=key, binding_type="deployer")
        assert binding["evm_address"] == safe_address

    def test_a_contract_wallet_on_an_unaccepted_chain_is_refused(self, pillar, monkeypatch):
        """Whoever picks the chain picks where the wallet contract lives. A
        signer who could name it would deploy at the same address on a chain
        nobody watches and be believed here, so the Pillar picks."""
        from auth import wallet_sig
        pid_data, key = pillar
        safe_address = "0x" + "5" * 40
        challenge = create_challenge(safe_address, chain_id=43113,
                                     purpose=PURPOSE_BINDING)
        monkeypatch.setattr(wallet_sig, "_accepted_contract_chains", lambda: {50})
        # Even with the contract answering yes, the chain is not one we accept.
        monkeypatch.setattr(wallet_sig, "verify_eip1271",
                            lambda *a, **k: (True, "valid (EIP-1271)"))
        with pytest.raises(ValueError, match="not accepted on chain 43113"):
            create_binding(
                pid_data=pid_data, evm_address=safe_address,
                siwe_message=challenge["message"],
                siwe_signature="0x" + "ab" * 65,
                private_key=key, binding_type="deployer")

    def test_eip1271_rejection_is_a_rejection(self, pillar, monkeypatch):
        from auth import wallet_sig
        pid_data, key = pillar
        safe_address = "0x" + "5" * 40
        challenge = create_challenge(safe_address, chain_id=43113,
                                     purpose=PURPOSE_BINDING)
        monkeypatch.setattr(wallet_sig, "_accepted_contract_chains", lambda: {43113})
        monkeypatch.setattr(wallet_sig, "verify_eip1271",
                            lambda *a, **k: (False, "contract rejected the signature"))
        with pytest.raises(ValueError, match="does not match"):
            create_binding(
                pid_data=pid_data, evm_address=safe_address,
                siwe_message=challenge["message"],
                siwe_signature="0x" + "ab" * 65,
                private_key=key, binding_type="deployer")

    def test_stored_binding_verification_makes_no_network_call(self, pillar, monkeypatch):
        from auth import wallet_sig
        pid_data, key = pillar
        account = Account.create()
        challenge = create_challenge(account.address, chain_id=43113,
                                     purpose=PURPOSE_BINDING)
        binding = create_binding(
            pid_data=pid_data, evm_address=account.address,
            siwe_message=challenge["message"],
            siwe_signature=_sign(account, challenge["message"]),
            private_key=key, binding_type="deployer")

        def _boom(*a, **k):
            raise AssertionError("verify_binding must not hit the network")

        monkeypatch.setattr(wallet_sig, "verify_eip1271", _boom)
        assert verify_binding(binding)[0]


def _insert_legacy_binding(pid_data, private_key, account):
    """A pre-0.5.0 row: made from a sign-in message, signing the bare id."""
    message, nonce = generate_challenge(account.address, pid_data["pid"])
    signature = _sign(account, message)
    binding_id = compute_binding_id(pid_data["pid"], account.address, nonce)
    row = (binding_id, pid_data["pid"], pid_data["public_key"], account.address, 1,
           message, signature, sign_content(binding_id.encode(), private_key),
           "deployer")
    with _connect() as conn:
        conn.execute(
            """INSERT INTO pid_bindings
               (binding_id, pid, public_key, evm_address, chain_id, siwe_message,
                siwe_signature, pid_signature, binding_type)
               VALUES (?,?,?,?,?,?,?,?,?)""", row)
        conn.commit()
        return dict(conn.execute(
            "SELECT * FROM pid_bindings WHERE binding_id=?", (binding_id,)).fetchone())


class TestLegacyBindings:
    def test_existing_legacy_binding_still_verifies(self, pillar):
        pid_data, key = pillar
        legacy = _insert_legacy_binding(pid_data, key, Account.create())
        assert is_legacy_binding(legacy)
        ok, reason = verify_binding(legacy)
        assert ok and reason == "valid (legacy)"

    def test_legacy_binding_stays_canonical_until_a_rebind(self, pillar):
        pid_data, key = pillar
        legacy = _insert_legacy_binding(pid_data, key, Account.create())
        assert get_deployer_binding(pid_data["pid"])["binding_id"] == legacy["binding_id"]
        assert get_v1_bindings(pid_data["pid"]) == []

    def test_a_v1_binding_becomes_canonical(self, pillar):
        pid_data, key = pillar
        _insert_legacy_binding(pid_data, key, Account.create())
        account = Account.create()
        challenge = create_challenge(account.address, chain_id=43113,
                                     purpose=PURPOSE_BINDING)
        new = create_binding(
            pid_data=pid_data, evm_address=account.address,
            siwe_message=challenge["message"],
            siwe_signature=_sign(account, challenge["message"]),
            private_key=key, binding_type="deployer")
        assert get_deployer_binding(pid_data["pid"])["binding_id"] == new["binding_id"]
        assert [b["binding_id"] for b in get_v1_bindings(pid_data["pid"])] == \
            [new["binding_id"]]


class TestIdentityDocument:
    def test_v3_document_verifies_and_lists_only_v1_bindings(self, pillar):
        pid_data, key = pillar
        _insert_legacy_binding(pid_data, key, Account.create())
        account = Account.create()
        challenge = create_challenge(account.address, chain_id=43113,
                                     purpose=PURPOSE_BINDING)
        create_binding(
            pid_data=pid_data, evm_address=account.address,
            siwe_message=challenge["message"],
            siwe_signature=_sign(account, challenge["message"]),
            private_key=key, binding_type="deployer")

        doc = build_identity_v3(
            pid=pid_data["pid"], public_key=pid_data["public_key"],
            authority=pillar_authority(pid_data["pid"]),
            bindings=get_v1_bindings(pid_data["pid"]), private_key=key)
        assert doc["schema_version"] == 3
        assert len(doc["bindings"]) == 1
        assert verify_identity_v3(doc)[0]

    def test_tampered_v3_document_fails(self, pillar):
        pid_data, key = pillar
        doc = build_identity_v3(
            pid=pid_data["pid"], public_key=pid_data["public_key"],
            authority="x.pillar.refinet", bindings=[], private_key=key)
        doc["authority"] = "evil.example"
        assert not verify_identity_v3(doc)[0]
