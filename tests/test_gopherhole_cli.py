"""Tests for gopherhole business logic and CLI module."""

import pytest
from core.gopherhole import validate_selector, verify_gopherhole_signature
from crypto.pid import get_private_key
from crypto.signing import sign_content


class TestSelectorValidation:
    """Test gopherhole selector format validation."""

    def test_valid_selectors(self):
        validate_selector("/holes/mysite")
        validate_selector("/holes/a")
        validate_selector("/holes/my-site")
        validate_selector("/holes/my_site")
        validate_selector("/holes/Site123")

    def test_invalid_no_prefix(self):
        with pytest.raises(ValueError, match="Invalid selector"):
            validate_selector("/mysite")

    def test_invalid_empty_slug(self):
        with pytest.raises(ValueError, match="Invalid selector"):
            validate_selector("/holes/")

    def test_invalid_too_long(self):
        with pytest.raises(ValueError, match="Invalid selector"):
            validate_selector("/holes/" + "a" * 65)

    def test_invalid_special_chars(self):
        with pytest.raises(ValueError, match="Invalid selector"):
            validate_selector("/holes/my site")
        with pytest.raises(ValueError, match="Invalid selector"):
            validate_selector("/holes/my.site")

    def test_max_length_valid(self):
        validate_selector("/holes/" + "a" * 64)


class TestGopherholeSignature:
    """Test gopherhole signature creation and verification."""

    def test_verify_valid_signature(self, test_pid, test_private_key):
        pid = test_pid["pid"]
        selector = "/holes/test"
        name = "Test Site"
        registered_at = "2026-03-01"

        payload = f"{pid}:{selector}:{name}:{registered_at}"
        signature = sign_content(payload.encode(), test_private_key)

        record = {
            "pid": pid,
            "selector": selector,
            "name": name,
            "registered_at": registered_at,
            "signature": signature,
            "pubkey_hex": test_pid["public_key"],
        }

        assert verify_gopherhole_signature(record) is True

    def test_verify_tampered_name(self, test_pid, test_private_key):
        pid = test_pid["pid"]
        selector = "/holes/test"
        name = "Test Site"
        registered_at = "2026-03-01"

        payload = f"{pid}:{selector}:{name}:{registered_at}"
        signature = sign_content(payload.encode(), test_private_key)

        record = {
            "pid": pid,
            "selector": selector,
            "name": "Tampered Name",  # Changed
            "registered_at": registered_at,
            "signature": signature,
            "pubkey_hex": test_pid["public_key"],
        }

        assert verify_gopherhole_signature(record) is False

    def test_verify_wrong_key(self, test_pid):
        """Signature from one PID should not verify with another PID's key."""
        from crypto.pid import generate_pid, get_private_key as gpk

        other_pid = generate_pid()
        other_key = gpk(other_pid)

        pid = test_pid["pid"]
        payload = f"{pid}:/holes/test:Name:2026-01-01"
        signature = sign_content(payload.encode(), other_key)

        record = {
            "pid": pid,
            "selector": "/holes/test",
            "name": "Name",
            "registered_at": "2026-01-01",
            "signature": signature,
            "pubkey_hex": test_pid["public_key"],  # Wrong key for this sig
        }

        assert verify_gopherhole_signature(record) is False
