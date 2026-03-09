"""Tests for crypto/recovery.py — Shamir's Secret Sharing over GF(256)."""

import pytest
from crypto.recovery import split_key, recover_key, generate_recovery_shares
from crypto.pid import generate_pid


class TestSplitAndRecover:
    """Round-trip split/recover tests."""

    def test_split_and_recover_exact_threshold(self):
        key_hex = "ab" * 32  # 32-byte key
        shares = split_key(key_hex, threshold=3, num_shares=5)
        recovered = recover_key(shares[:3])
        assert recovered == key_hex

    def test_split_and_recover_all_shares(self):
        key_hex = "cd" * 32
        shares = split_key(key_hex, threshold=3, num_shares=5)
        recovered = recover_key(shares)
        assert recovered == key_hex

    def test_split_and_recover_different_subsets(self):
        key_hex = "ef" * 32
        shares = split_key(key_hex, threshold=3, num_shares=5)
        # Try different 3-share subsets
        assert recover_key([shares[0], shares[2], shares[4]]) == key_hex
        assert recover_key([shares[1], shares[3], shares[4]]) == key_hex

    def test_recover_with_real_pid_key(self, test_pid):
        priv_hex = test_pid["private_key"]
        shares = split_key(priv_hex, threshold=2, num_shares=3)
        recovered = recover_key(shares[:2])
        assert recovered == priv_hex


class TestSplitValidation:
    """Input validation for split_key."""

    def test_threshold_below_two_rejected(self):
        with pytest.raises(ValueError, match="at least 2"):
            split_key("ab" * 32, threshold=1, num_shares=3)

    def test_num_shares_below_threshold_rejected(self):
        with pytest.raises(ValueError, match="num_shares must be >= threshold"):
            split_key("ab" * 32, threshold=5, num_shares=3)

    def test_max_shares_limit(self):
        with pytest.raises(ValueError, match="Maximum 255"):
            split_key("ab" * 32, threshold=2, num_shares=256)

    def test_empty_key_rejected(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            split_key("", threshold=2, num_shares=3)


class TestShareFormat:
    """Share encoding and format tests."""

    def test_shares_have_prefix(self):
        shares = split_key("ab" * 32, threshold=2, num_shares=3)
        for share in shares:
            assert share.startswith("REFINET-SHARE-")

    def test_share_count_matches_num_shares(self):
        shares = split_key("ab" * 32, threshold=2, num_shares=7)
        assert len(shares) == 7

    def test_shares_are_unique(self):
        shares = split_key("ab" * 32, threshold=2, num_shares=5)
        assert len(set(shares)) == 5


class TestRecoverValidation:
    """Edge cases and error paths for recover_key."""

    def test_insufficient_shares(self):
        shares = split_key("ab" * 32, threshold=3, num_shares=5)
        with pytest.raises(ValueError, match="Need at least 3"):
            recover_key(shares[:2])

    def test_duplicate_share_detection(self):
        shares = split_key("ab" * 32, threshold=2, num_shares=3)
        with pytest.raises(ValueError, match="Duplicate"):
            recover_key([shares[0], shares[0]])

    def test_fingerprint_mismatch(self):
        key_a = "aa" * 32
        key_b = "bb" * 32
        shares_a = split_key(key_a, threshold=2, num_shares=3)
        shares_b = split_key(key_b, threshold=2, num_shares=3)
        with pytest.raises(ValueError, match="fingerprint"):
            recover_key([shares_a[0], shares_b[1]])

    def test_no_shares_provided(self):
        with pytest.raises(ValueError, match="No shares"):
            recover_key([])

    def test_invalid_prefix_rejected(self):
        with pytest.raises(ValueError, match="REFINET-SHARE-"):
            recover_key(["NOT-A-SHARE-abc123"])


class TestGenerateRecoveryShares:
    """High-level generate_recovery_shares with PID."""

    def test_generate_from_unencrypted_pid(self, test_pid):
        shares = generate_recovery_shares(test_pid, threshold=2, num_shares=3)
        assert len(shares) == 3
        recovered = recover_key(shares[:2])
        assert recovered == test_pid["private_key"]

    def test_encrypted_pid_without_password_raises(self):
        pid = generate_pid(password="test-pass")
        with pytest.raises(ValueError, match="password required"):
            generate_recovery_shares(pid)
