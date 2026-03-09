"""Tests for core/vpn_manager.py — VPN Integration."""

import pytest
from core.vpn_manager import VPNManager, generate_wireguard_config, MAX_RESTART_ATTEMPTS


class TestVPNManagerInit:
    """VPNManager constructor and defaults."""

    def test_default_vpn_type(self):
        vpn = VPNManager({})
        assert vpn._vpn_type == "wireguard"

    def test_custom_vpn_type(self):
        vpn = VPNManager({"vpn_type": "openvpn"})
        assert vpn._vpn_type == "openvpn"

    def test_inactive_by_default(self):
        vpn = VPNManager({})
        assert vpn.is_active() is False

    def test_restart_count_starts_zero(self):
        vpn = VPNManager({})
        assert vpn._restart_count == 0


class TestVPNStart:
    """VPN start behavior."""

    @pytest.mark.asyncio
    async def test_disabled_config_returns_false(self):
        vpn = VPNManager({"vpn_enabled": False})
        result = await vpn.start()
        assert result is False

    @pytest.mark.asyncio
    async def test_disabled_by_default(self):
        vpn = VPNManager({})
        result = await vpn.start()
        assert result is False


class TestVPNStop:
    """VPN stop behavior."""

    @pytest.mark.asyncio
    async def test_stop_inactive_is_noop(self):
        vpn = VPNManager({})
        await vpn.stop()  # Should not raise
        assert vpn.is_active() is False


class TestGenerateWireguardConfig:
    """WireGuard config template generation."""

    def test_config_contains_peer_key(self):
        pid = {"pid": "a" * 64}
        config = generate_wireguard_config(
            pid, "vpn.example.com:51820", "PEER_PUB_KEY_HERE"
        )
        assert "PEER_PUB_KEY_HERE" in config
        assert "vpn.example.com:51820" in config

    def test_config_contains_pid_prefix(self):
        pid = {"pid": "abcdef1234567890" + "0" * 48}
        config = generate_wireguard_config(pid, "host:1234", "key")
        assert "abcdef1234567890" in config

    def test_config_default_allowed_ips(self):
        pid = {"pid": "a" * 64}
        config = generate_wireguard_config(pid, "h:1", "k")
        assert "0.0.0.0/0" in config

    def test_config_custom_port(self):
        pid = {"pid": "a" * 64}
        config = generate_wireguard_config(pid, "h:1", "k", listen_port=12345)
        assert "12345" in config


class TestMaxRestartAttempts:
    """Restart limit constant."""

    def test_max_restart_attempts_is_three(self):
        assert MAX_RESTART_ATTEMPTS == 3
