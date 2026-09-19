"""`pillar identity` — the migration path for a pre-0.5.0 binding.

Before this command existed, re-signing a legacy binding was only possible
by hand-crafting a WebSocket message, which made the documented upgrade
path unusable in practice.
"""

import json

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from auth.session import create_challenge
from auth.siwe import PURPOSE_BINDING, generate_challenge
from cli import identity as cli_identity
from crypto.binding import (
    compute_binding_id, get_all_bindings, get_deployer_binding,
    is_legacy_binding, verify_binding,
)
from crypto.pid import generate_pid, get_private_key, save_pid
from crypto.signing import sign_content
from db.live_db import _connect, init_live_db


@pytest.fixture(autouse=True)
def _db():
    init_live_db()


@pytest.fixture
def pillar():
    pid_data = generate_pid()
    save_pid(pid_data)
    return pid_data


class _Args:
    def __init__(self, **kw):
        self.address = None
        self.chain = 1
        self.type = "deployer"
        self.company_url = None
        self.signature = None
        self.quiet = False
        self.__dict__.update(kw)


def _sign(account, message):
    sig = account.sign_message(encode_defunct(text=message)).signature.hex()
    return sig if sig.startswith("0x") else "0x" + sig


def _insert_legacy_binding(pid_data, account):
    """A pre-0.5.0 row: made from a sign-in message, signing the bare id."""
    message, nonce = generate_challenge(account.address, pid_data["pid"])
    binding_id = compute_binding_id(pid_data["pid"], account.address, nonce)
    with _connect() as conn:
        conn.execute(
            """INSERT INTO pid_bindings
               (binding_id, pid, public_key, evm_address, chain_id, siwe_message,
                siwe_signature, pid_signature, binding_type)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (binding_id, pid_data["pid"], pid_data["public_key"], account.address,
             1, message, _sign(account, message),
             sign_content(binding_id.encode(), get_private_key(pid_data)),
             "deployer"))
        conn.commit()
    return binding_id


class TestChallengeThenRebind:
    def test_scripted_two_step_writes_a_v1_binding(self, pillar):
        account = Account.create()
        cli_identity.cmd_identity_challenge(
            _Args(address=account.address, chain=43113, quiet=True))

        pending = json.loads(cli_identity._pending_path().read_text())
        assert pending["address"] == account.address
        assert "I bind this wallet to REFINET Pillar" in pending["message"]

        cli_identity.cmd_identity_rebind(
            _Args(address=account.address, chain=43113,
                  signature=_sign(account, pending["message"])))

        bindings = get_all_bindings(pillar["pid"])
        assert len(bindings) == 1
        assert bindings[0]["chain_id"] == 43113
        assert not is_legacy_binding(bindings[0])
        assert verify_binding(bindings[0])[0]

    def test_pending_challenge_is_cleared_after_use(self, pillar):
        account = Account.create()
        cli_identity.cmd_identity_challenge(_Args(address=account.address, quiet=True))
        pending = json.loads(cli_identity._pending_path().read_text())
        cli_identity.cmd_identity_rebind(
            _Args(address=account.address,
                  signature=_sign(account, pending["message"])))
        assert not cli_identity._pending_path().exists()

    def test_pending_file_is_owner_only(self, pillar):
        import stat
        account = Account.create()
        cli_identity.cmd_identity_challenge(_Args(address=account.address, quiet=True))
        mode = stat.S_IMODE(cli_identity._pending_path().stat().st_mode)
        assert mode == 0o600

    def test_signature_without_a_pending_challenge_is_refused(self, pillar):
        account = Account.create()
        with pytest.raises(SystemExit):
            cli_identity.cmd_identity_rebind(
                _Args(address=account.address, signature="0x" + "ab" * 65))
        assert get_all_bindings(pillar["pid"]) == []

    def test_a_wrong_signature_fails_and_burns_the_challenge(self, pillar):
        account, impostor = Account.create(), Account.create()
        cli_identity.cmd_identity_challenge(_Args(address=account.address, quiet=True))
        pending = json.loads(cli_identity._pending_path().read_text())
        with pytest.raises(SystemExit):
            cli_identity.cmd_identity_rebind(
                _Args(address=account.address,
                      signature=_sign(impostor, pending["message"])))
        assert get_all_bindings(pillar["pid"]) == []
        assert not cli_identity._pending_path().exists()

    def test_bad_address_is_refused(self, pillar):
        with pytest.raises(SystemExit):
            cli_identity.cmd_identity_rebind(_Args(address="nope"))

    def test_operator_binding_records_its_role(self, pillar):
        account = Account.create()
        cli_identity.cmd_identity_challenge(
            _Args(address=account.address, type="operator", quiet=True))
        pending = json.loads(cli_identity._pending_path().read_text())
        cli_identity.cmd_identity_rebind(
            _Args(address=account.address, type="operator",
                  signature=_sign(account, pending["message"])))
        assert get_all_bindings(pillar["pid"])[0]["binding_type"] == "operator"


class TestLegacyMigration:
    def test_rebind_supersedes_a_legacy_binding_without_deleting_it(self, pillar):
        """The whole point: the old row stays, the new one becomes canonical."""
        account = Account.create()
        legacy_id = _insert_legacy_binding(pillar, account)
        assert get_deployer_binding(pillar["pid"])["binding_id"] == legacy_id

        cli_identity.cmd_identity_challenge(
            _Args(address=account.address, chain=43113, quiet=True))
        pending = json.loads(cli_identity._pending_path().read_text())
        cli_identity.cmd_identity_rebind(
            _Args(address=account.address, chain=43113,
                  signature=_sign(account, pending["message"])))

        bindings = get_all_bindings(pillar["pid"])
        assert len(bindings) == 2
        assert any(b["binding_id"] == legacy_id for b in bindings)
        canonical = get_deployer_binding(pillar["pid"])
        assert canonical["binding_id"] != legacy_id
        assert all(verify_binding(b)[0] for b in bindings)


class TestIdentityShow:
    def test_show_flags_a_legacy_binding_and_names_the_fix(self, pillar, capsys):
        account = Account.create()
        _insert_legacy_binding(pillar, account)
        cli_identity.cmd_identity_show(_Args())
        out = capsys.readouterr().out
        assert "pre-0.5.0" in out and "canonical" in out
        assert "identity rebind" in out
        assert account.address in out

    def test_show_reports_no_bindings(self, pillar, capsys):
        cli_identity.cmd_identity_show(_Args())
        assert "No wallet bindings" in capsys.readouterr().out

    def test_show_exits_without_a_pid(self, monkeypatch):
        monkeypatch.setattr(cli_identity, "load_pid", lambda: None)
        with pytest.raises(SystemExit):
            cli_identity.cmd_identity_show(_Args())
