"""/identity.json keeps serving v2; /identity/v3.json is the new document."""

import asyncio
import json

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from auth.session import create_challenge
from auth.siwe import PURPOSE_BINDING
from core.gopher_server import GopherServer
from crypto.binding import create_binding, verify_identity_v3
from crypto.unlock import get_unlocked_key


@pytest.fixture
async def server(tmp_path, monkeypatch):
    monkeypatch.setattr("core.config.HOME_DIR", tmp_path / ".refinet")
    monkeypatch.setattr("core.config.DB_DIR", tmp_path / ".refinet" / "db")
    monkeypatch.setattr("core.config.PID_FILE", tmp_path / ".refinet" / "pid.json")
    monkeypatch.setattr("crypto.pid.PID_FILE", tmp_path / ".refinet" / "pid.json")
    monkeypatch.setattr("core.config.CONFIG_FILE", tmp_path / ".refinet" / "config.json")
    monkeypatch.setattr("core.config.GOPHER_ROOT", tmp_path / "gopherroot")
    (tmp_path / "gopherroot").mkdir()
    return GopherServer(host="127.0.0.1", port=0, hostname="localhost")


def _json(body: str) -> dict:
    return json.loads(body.split("\r\n.")[0])


def _make_binding(server):
    account = Account.create()
    challenge = create_challenge(account.address, chain_id=43113,
                                 purpose=PURPOSE_BINDING)
    sig = account.sign_message(
        encode_defunct(text=challenge["message"])).signature.hex()
    if not sig.startswith("0x"):
        sig = "0x" + sig
    return create_binding(
        pid_data=server.pid_data, evm_address=account.address,
        siwe_message=challenge["message"], siwe_signature=sig,
        private_key=get_unlocked_key(server.pid_data), binding_type="deployer")


class TestIdentityV2Unchanged:
    @pytest.mark.asyncio
    async def test_schema_version_is_still_2(self, server):
        doc = _json(await server._route("/identity.json"))
        assert doc["schema_version"] == 2
        assert set(["pid", "public_key", "key_store", "protocol"]) <= set(doc)

    @pytest.mark.asyncio
    async def test_deployer_binding_shape_is_unchanged(self, server):
        _make_binding(server)
        doc = _json(await server._route("/identity.json"))
        assert set(doc["deployer_binding"]) == {
            "binding_id", "evm_address", "chain_id", "pid_signature",
            "siwe_message", "siwe_signature", "binding_type", "created_at",
        }


class TestIdentityV3:
    @pytest.mark.asyncio
    async def test_v3_document_verifies(self, server):
        _make_binding(server)
        doc = _json(await server._route("/identity/v3.json"))
        assert doc["schema_version"] == 3
        assert doc["authority"].endswith(".pillar.refinet")
        assert len(doc["bindings"]) == 1
        ok, reason = verify_identity_v3(doc)
        assert ok, reason

    @pytest.mark.asyncio
    async def test_v3_is_served_with_no_bindings(self, server):
        doc = _json(await server._route("/identity/v3.json"))
        assert doc["bindings"] == []
        assert verify_identity_v3(doc)[0]

    @pytest.mark.asyncio
    async def test_v3_is_blocked_on_the_standard_gopher_port(self, server):
        server.is_refinet = False
        body = await server._route("/identity/v3.json")
        assert "REFInet feature" in body
