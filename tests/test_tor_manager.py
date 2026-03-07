"""Tests for the Tor hidden service manager."""

import shutil
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path

from core.tor_manager import TorManager


class TestTorManagerInit:
    """Test TorManager construction and configuration."""

    def test_disabled_by_default(self):
        tm = TorManager({})
        assert tm.enabled is False
        assert tm.port_7070 == 7070
        assert tm.port_70 == 70

    def test_reads_config(self):
        cfg = {
            "tor_enabled": True,
            "port": 8080,
            "standard_port": 80,
            "tor_expose_port_70": False,
            "tor_socks_port": 9150,
            "tor_control_port": 9151,
        }
        tm = TorManager(cfg)
        assert tm.enabled is True
        assert tm.port_7070 == 8080
        assert tm.port_70 == 80
        assert tm.expose_70 is False
        assert tm.socks_port == 9150
        assert tm.control_port == 9151

    def test_initial_state_is_inactive(self):
        tm = TorManager({"tor_enabled": True})
        assert tm.is_active() is False
        assert tm.get_onion_address() is None


class TestTorManagerStart:
    """Test the start() method."""

    @pytest.mark.asyncio
    async def test_disabled_returns_false(self):
        tm = TorManager({"tor_enabled": False})
        assert await tm.start() is False

    @pytest.mark.asyncio
    async def test_no_tor_binary_returns_false(self):
        with patch.object(shutil, "which", return_value=None):
            tm = TorManager({"tor_enabled": True})
            assert await tm.start() is False

    @pytest.mark.asyncio
    async def test_start_success_with_mocked_stem(self, tmp_path):
        mock_process = MagicMock()
        mock_controller = MagicMock()
        mock_controller.authenticate = MagicMock()

        with patch.object(shutil, "which", return_value="/usr/bin/tor"), \
             patch("core.tor_manager.TOR_DATA_DIR", tmp_path / "tor_data"), \
             patch("core.tor_manager.stem.process.launch_tor_with_config", return_value=mock_process), \
             patch("core.tor_manager.stem.control.Controller.from_port", return_value=mock_controller):
            tm = TorManager({"tor_enabled": True})
            result = await tm.start()
            assert result is True
            assert tm._tor_process is mock_process
            assert tm._controller is mock_controller


class TestTorManagerHiddenService:
    """Test hidden service creation."""

    @pytest.mark.asyncio
    async def test_create_without_controller_returns_none(self):
        tm = TorManager({"tor_enabled": True})
        assert await tm.create_hidden_services() is None

    @pytest.mark.asyncio
    async def test_create_returns_onion_address(self, tmp_path):
        mock_controller = MagicMock()
        mock_hs_result = MagicMock()
        mock_hs_result.service_id = "abcdef1234567890abcdef1234567890abcdef1234567890abcdefgh"
        mock_hs_result.private_key = "test_private_key_data"
        mock_controller.create_ephemeral_hidden_service = MagicMock(return_value=mock_hs_result)

        with patch("core.tor_manager.TOR_DATA_DIR", tmp_path / "tor_data"):
            (tmp_path / "tor_data").mkdir()
            tm = TorManager({"tor_enabled": True})
            tm._controller = mock_controller
            onion = await tm.create_hidden_services()

            assert onion is not None
            assert onion.endswith(".onion")
            assert tm.is_active() is True
            assert tm.get_onion_address() == onion

    @pytest.mark.asyncio
    async def test_privkey_persistence(self, tmp_path):
        """Private key is saved on first run and reused on second."""
        tor_data = tmp_path / "tor_data"
        tor_data.mkdir()

        mock_controller = MagicMock()
        mock_hs_result = MagicMock()
        mock_hs_result.service_id = "testserviceid1234567890"
        mock_hs_result.private_key = "ED25519_PRIVKEY_DATA"
        mock_controller.create_ephemeral_hidden_service = MagicMock(return_value=mock_hs_result)

        with patch("core.tor_manager.TOR_DATA_DIR", tor_data):
            # First instantiation — generates and persists key
            tm1 = TorManager({"tor_enabled": True})
            tm1._controller = mock_controller
            await tm1.create_hidden_services()

            privkey_path = tor_data / "hs_privkey"
            assert privkey_path.exists()
            assert privkey_path.read_text().strip() == "ED25519_PRIVKEY_DATA"

            # Second instantiation — loads persisted key
            tm2 = TorManager({"tor_enabled": True})
            tm2._controller = mock_controller
            await tm2.create_hidden_services()

            # Verify create_ephemeral_hidden_service was called with the persisted key
            last_call = mock_controller.create_ephemeral_hidden_service.call_args
            assert last_call.kwargs.get("key_type") == "ED25519-V3"
            assert last_call.kwargs.get("key_content") == "ED25519_PRIVKEY_DATA"


class TestTorManagerStop:
    """Test the stop() method."""

    @pytest.mark.asyncio
    async def test_stop_closes_controller(self):
        mock_controller = MagicMock()
        mock_process = MagicMock()

        tm = TorManager({"tor_enabled": True})
        tm._controller = mock_controller
        tm._tor_process = mock_process
        tm._onion_address = "test.onion"

        await tm.stop()

        mock_controller.close.assert_called_once()
        mock_process.kill.assert_called_once()
        assert tm.is_active() is False
        assert tm.get_onion_address() is None

    @pytest.mark.asyncio
    async def test_stop_with_no_state_is_safe(self):
        tm = TorManager({})
        await tm.stop()  # Should not raise


class TestTorManagerAccessors:
    """Test get_onion_address() and is_active()."""

    def test_inactive_by_default(self):
        tm = TorManager({})
        assert tm.is_active() is False
        assert tm.get_onion_address() is None

    def test_active_after_address_set(self):
        tm = TorManager({})
        tm._onion_address = "abc123.onion"
        assert tm.is_active() is True
        assert tm.get_onion_address() == "abc123.onion"


class TestInstallHint:
    """Test platform-specific install hints."""

    def test_darwin_hint(self):
        with patch("core.tor_manager.platform.system", return_value="Darwin"):
            hint = TorManager._install_hint()
            assert "brew" in hint

    def test_linux_hint(self):
        with patch("core.tor_manager.platform.system", return_value="Linux"):
            hint = TorManager._install_hint()
            assert "apt" in hint
