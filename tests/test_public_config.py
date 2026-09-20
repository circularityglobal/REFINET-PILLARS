"""0.6.0 settings: off by default, env-overridable, never written back."""

import json

import pytest

from core import config as cfg


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / ".refinet" / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_FILE", path)
    for var in cfg._ENV_OVERRIDES:
        monkeypatch.delenv(var, raising=False)
    return path


def test_everything_new_is_off_by_default(config_file):
    c = cfg.load_config()
    assert c["http_gateway_enabled"] is False
    assert c["http_gateway_host"] == "127.0.0.1"
    assert c["websocket_host"] == "127.0.0.1"
    assert c["staking_contracts"] == []
    assert c["mesh_require_stake"] is False
    assert c["public_domain"] == ""


def test_a_050_config_file_loads_with_defaults(config_file):
    config_file.parent.mkdir(parents=True, exist_ok=True)
    old = {"hostname": "node.lan", "port": 7070, "pillar_name": "Old",
           "tor_enabled": False, "websocket_extension_ids": ["abc"]}
    config_file.write_text(json.dumps(old))
    c = cfg.load_config()
    assert c["hostname"] == "node.lan" and c["websocket_extension_ids"] == ["abc"]
    assert c["mesh_require_stake"] is False and c["http_gateway_enabled"] is False
    # Loading does not rewrite the operator's file
    assert json.loads(config_file.read_text()) == old


def test_fresh_file_has_no_public_or_staking_keys(config_file):
    cfg.load_config()
    written = json.loads(config_file.read_text())
    for key in list(cfg.PUBLIC_DEFAULTS) + list(cfg.STAKING_DEFAULTS):
        assert key not in written


def test_env_overrides_apply_but_are_not_persisted(config_file, monkeypatch):
    cfg.load_config()
    monkeypatch.setenv("REFINET_PUBLIC_DOMAIN", "pillars.google.com")
    monkeypatch.setenv("REFINET_HTTP_GATEWAY", "1")
    monkeypatch.setenv("REFINET_HTTP_GATEWAY_PORT", "8080")
    monkeypatch.setenv("REFINET_STAKING_CONTRACTS", "0xabc, 0xdef")
    monkeypatch.setenv("REFINET_MESH_REQUIRE_STAKE", "true")
    c = cfg.load_config()
    assert c["public_domain"] == "pillars.google.com"
    assert c["http_gateway_enabled"] is True
    assert c["http_gateway_port"] == 8080
    assert c["staking_contracts"] == ["0xabc", "0xdef"]
    assert c["mesh_require_stake"] is True
    assert "public_domain" not in json.loads(config_file.read_text())


def test_apply_env_overrides_types():
    c = cfg.apply_env_overrides({}, environ={
        "REFINET_HTTP_GATEWAY": "no",
        "REFINET_HTTP_GATEWAY_PORT": "not-a-number",
        "REFINET_CORS_ORIGINS": "https://a.com,,https://b.com ",
        "REFINET_STAKING_CHAIN_ID": "51",
    })
    assert c == {"http_gateway_enabled": False,
                 "http_gateway_cors_origins": ["https://a.com", "https://b.com"],
                 "staking_chain_id": 51}


def test_websocket_bridge_admits_configured_app_origin(config_file, monkeypatch):
    from integration.websocket_bridge import WebSocketBridge, _match_origin
    monkeypatch.setenv("REFINET_WEBSOCKET_ORIGINS", "https://app.example.com")
    bridge = WebSocketBridge(gopher_server=None)
    assert _match_origin("https://app.example.com", bridge.allowed_origins)
    assert _match_origin("chrome-extension://anything", bridge.allowed_origins)
    assert not _match_origin("https://evil.example.com", bridge.allowed_origins)


def test_websocket_bridge_defaults_unchanged(config_file):
    from integration.websocket_bridge import WebSocketBridge
    from core.config import WEBSOCKET_ALLOWED_ORIGINS
    assert WebSocketBridge(gopher_server=None).allowed_origins == WEBSOCKET_ALLOWED_ORIGINS
