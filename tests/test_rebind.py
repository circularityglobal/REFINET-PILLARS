"""The rebind flow: an onboarded Pillar adds a §3.1 binding (needs the wallet)."""

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from crypto.binding import get_v1_bindings, verify_binding
from crypto.pid import generate_pid, save_pid
from crypto.unlock import lock_all
from db.live_db import init_live_db
from integration.websocket_bridge import WebSocketBridge


class _Server:
    def __init__(self, pid_data):
        self.pid_data = pid_data
        from crypto.pid import get_private_key
        self.private_key = get_private_key(pid_data)


@pytest.fixture
def bridge():
    init_live_db()
    pid_data = generate_pid()
    save_pid(pid_data)
    return WebSocketBridge(gopher_server=_Server(pid_data)), pid_data


@pytest.mark.asyncio
async def test_rebind_issues_a_binding_challenge_then_writes_it(bridge):
    ws, pid_data = bridge
    account = Account.create()

    challenge = await ws._handle_rebind({
        "type": "rebind", "address": account.address,
        "chain_id": 43113, "company_url": "https://tradesphere.example/company/9",
    })
    assert challenge["type"] == "rebind_challenge"
    message = challenge["message"]
    assert f"I bind this wallet to REFINET Pillar {pid_data['pid']} as its deployer" in message
    assert "- https://tradesphere.example/company/9" in message

    sig = account.sign_message(encode_defunct(text=message)).signature.hex()
    done = await ws._handle_rebind({
        "type": "rebind", "address": account.address,
        "message": message, "signature": sig if sig.startswith("0x") else "0x" + sig,
    })
    assert done["type"] == "rebind_complete"
    assert done["chain_id"] == 43113
    bindings = get_v1_bindings(pid_data["pid"])
    assert len(bindings) == 1 and verify_binding(bindings[0])[0]


@pytest.mark.asyncio
async def test_rebind_rejects_a_bad_address(bridge):
    ws, _ = bridge
    result = await ws._handle_rebind({"type": "rebind", "address": "nope"})
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_rebind_reports_a_locked_key(bridge, monkeypatch):
    ws, pid_data = bridge
    encrypted = generate_pid(password="pw")
    save_pid(encrypted)
    ws.gopher_server.pid_data = encrypted
    lock_all()
    account = Account.create()
    result = await ws._handle_rebind({
        "type": "rebind", "address": account.address,
        "message": "x", "signature": "0x" + "ab" * 65,
    })
    assert result["status"] == "error" and result.get("locked") is True
