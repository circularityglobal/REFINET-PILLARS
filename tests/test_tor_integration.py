"""
TOR-25: Integration test for Tor hidden service round-trip.

Requires the 'tor' binary to be installed AND the --integration flag.
Tests are skipped automatically if either condition is not met.
"""

import shutil
import pytest


class TestTorIntegration:
    """End-to-end test: start Pillar with Tor, connect via .onion, verify."""

    @pytest.mark.asyncio
    async def test_hidden_service_creation(self, tmp_path, monkeypatch, request):
        """Start TorManager and verify .onion address is generated."""
        if not request.config.getoption("--integration", default=False):
            pytest.skip("Tor integration tests require --integration flag")
        if not shutil.which("tor"):
            pytest.skip("Tor binary not found")
        monkeypatch.setattr("core.tor_manager.TOR_DATA_DIR", tmp_path / "tor_data")
        from core.tor_manager import TorManager

        config = {
            "tor_enabled": True,
            "port": 7070,
            "standard_port": 70,
            "tor_expose_port_70": True,
            "tor_socks_port": 19050,  # Use non-standard to avoid conflicts
            "tor_control_port": 19051,
        }
        tor = TorManager(config)
        try:
            started = await tor.start()
            if not started:
                pytest.skip("Tor failed to start (network/config issue)")

            onion = await tor.create_hidden_services()
            assert onion is not None
            assert onion.endswith(".onion")
            assert len(onion) > 10  # v3 onion addresses are 56 chars + .onion
            assert tor.is_active()
        finally:
            await tor.stop()

    @pytest.mark.asyncio
    async def test_onion_address_persistence(self, tmp_path, monkeypatch, request):
        """Verify .onion address is consistent across two TorManager lifecycles."""
        if not request.config.getoption("--integration", default=False):
            pytest.skip("Tor integration tests require --integration flag")
        if not shutil.which("tor"):
            pytest.skip("Tor binary not found")
        tor_data = tmp_path / "tor_data"
        monkeypatch.setattr("core.tor_manager.TOR_DATA_DIR", tor_data)
        from core.tor_manager import TorManager

        config = {
            "tor_enabled": True,
            "port": 7070,
            "tor_socks_port": 19052,
            "tor_control_port": 19053,
        }

        # First lifecycle
        tor1 = TorManager(config)
        try:
            if not await tor1.start():
                pytest.skip("Tor failed to start")
            addr1 = await tor1.create_hidden_services()
            assert addr1 is not None
        finally:
            await tor1.stop()

        # Second lifecycle — should reuse private key
        tor2 = TorManager(config)
        try:
            if not await tor2.start():
                pytest.skip("Tor failed to restart")
            addr2 = await tor2.create_hidden_services()
            assert addr2 == addr1, "Onion address should persist across restarts"
        finally:
            await tor2.stop()
