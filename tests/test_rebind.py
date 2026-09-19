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


class TestExtensionContract:
    """The bundled extension speaks this protocol; keep them in step.

    The extension cannot be driven from the Python suite, so the least we
    can do is fail when the message names drift apart.
    """

    def _background_js(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        return (root / "browser-extension" / "background.js").read_text(encoding="utf-8")

    def test_extension_sends_the_message_type_the_bridge_handles(self):
        js = self._background_js()
        assert '"rebind-start"' in js, "popup action missing from background.js"
        assert 'type: "rebind"' in js, "extension must send the bridge's 'rebind' type"

    def test_extension_awaits_the_reply_types_the_bridge_sends(self):
        js = self._background_js()
        assert '"rebind_challenge"' in js
        assert '"rebind_complete"' in js

    @pytest.mark.asyncio
    async def test_bridge_really_answers_with_those_types(self, bridge):
        ws, _ = bridge
        account = Account.create()
        challenge = await ws._handle_rebind({
            "type": "rebind", "address": account.address, "chain_id": 43113})
        assert challenge["type"] == "rebind_challenge"
        sig = account.sign_message(
            encode_defunct(text=challenge["message"])).signature.hex()
        done = await ws._handle_rebind({
            "type": "rebind", "address": account.address,
            "message": challenge["message"],
            "signature": sig if sig.startswith("0x") else "0x" + sig})
        assert done["type"] == "rebind_complete"
        assert "binding_id" in done

    def test_extension_handles_a_locked_pillar_key(self):
        """The bridge answers {locked: true} when the key needs a password."""
        js = self._background_js()
        assert "locked" in js

    def test_extension_version_tracks_the_protocol(self):
        import json
        from pathlib import Path
        from core.version import __version__
        root = Path(__file__).resolve().parent.parent
        manifest = json.loads(
            (root / "browser-extension" / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["version"] == __version__
