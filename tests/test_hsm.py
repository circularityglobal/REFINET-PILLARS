"""Tests for crypto/hsm.py — HSM/PKCS#11 integration (graceful fallback)."""

import pytest
from crypto.hsm import HSMKeyStore, HSMSigner, _PKCS11_AVAILABLE


class TestHSMAvailability:
    """HSM availability and graceful fallback."""

    def test_pkcs11_available_is_bool(self):
        assert isinstance(_PKCS11_AVAILABLE, bool)

    def test_hsm_init_without_hardware(self):
        """HSMKeyStore should not crash even without real hardware."""
        hsm = HSMKeyStore("/nonexistent/lib.so", "test-token", "1234")
        assert not hsm.is_available()

    def test_is_available_returns_false_without_hardware(self):
        hsm = HSMKeyStore("/nonexistent/lib.so", "test", "pin")
        assert hsm.is_available() is False

    def test_generate_keypair_raises_without_hardware(self):
        hsm = HSMKeyStore("/nonexistent/lib.so", "test", "pin")
        with pytest.raises(RuntimeError, match="HSM not available"):
            hsm.generate_keypair("test-key")

    def test_sign_raises_without_hardware(self):
        hsm = HSMKeyStore("/nonexistent/lib.so", "test", "pin")
        with pytest.raises(RuntimeError, match="HSM not available"):
            hsm.sign(b"data", "test-key")

    def test_get_public_key_raises_without_hardware(self):
        hsm = HSMKeyStore("/nonexistent/lib.so", "test", "pin")
        with pytest.raises(RuntimeError, match="HSM not available"):
            hsm.get_public_key("test-key")

    def test_delete_key_raises_without_hardware(self):
        hsm = HSMKeyStore("/nonexistent/lib.so", "test", "pin")
        with pytest.raises(RuntimeError, match="HSM not available"):
            hsm.delete_key("test-key")

    def test_list_keys_returns_empty_without_hardware(self):
        hsm = HSMKeyStore("/nonexistent/lib.so", "test", "pin")
        assert hsm.list_keys() == []


class TestHSMSigner:
    """HSMSigner duck-type interface."""

    def test_signer_has_sign_method(self):
        hsm = HSMKeyStore("/nonexistent/lib.so", "test", "pin")
        signer = HSMSigner(hsm, "test-key")
        assert callable(signer.sign)

    def test_signer_delegates_to_hsm(self):
        hsm = HSMKeyStore("/nonexistent/lib.so", "test", "pin")
        signer = HSMSigner(hsm, "test-key")
        with pytest.raises(RuntimeError, match="HSM not available"):
            signer.sign(b"data")
