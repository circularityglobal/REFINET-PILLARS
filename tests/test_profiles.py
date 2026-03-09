"""Tests for crypto/profiles.py — Multi-Identity Profile Management."""

import pytest
from pathlib import Path


def _patch_dirs(tmp_path, monkeypatch):
    """Redirect all profile paths to tmp_path."""
    import crypto.profiles as mod
    monkeypatch.setattr(mod, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(mod, "ACTIVE_PROFILE_FILE", tmp_path / "active_profile")
    monkeypatch.setattr(mod, "PID_FILE", tmp_path / "pid.json")
    monkeypatch.setattr(mod, "HOME_DIR", tmp_path)


class TestProfilesCRUD:
    """Create, list, switch, delete profiles."""

    def test_create_profile(self, tmp_path, monkeypatch):
        _patch_dirs(tmp_path, monkeypatch)
        from crypto.profiles import create_profile, list_profiles

        pid = create_profile("alice")
        assert "pid" in pid
        assert "public_key" in pid
        assert "alice" in list_profiles()

    def test_list_profiles_empty(self, tmp_path, monkeypatch):
        _patch_dirs(tmp_path, monkeypatch)
        from crypto.profiles import list_profiles
        assert list_profiles() == []

    def test_list_profiles_multiple(self, tmp_path, monkeypatch):
        _patch_dirs(tmp_path, monkeypatch)
        from crypto.profiles import create_profile, list_profiles

        create_profile("alice")
        create_profile("bob")
        profiles = list_profiles()
        assert "alice" in profiles
        assert "bob" in profiles

    def test_switch_profile(self, tmp_path, monkeypatch):
        _patch_dirs(tmp_path, monkeypatch)
        from crypto.profiles import create_profile, switch_profile, get_active_profile

        create_profile("alice")
        create_profile("bob")
        switch_profile("bob")
        assert get_active_profile() == "bob"

    def test_delete_profile(self, tmp_path, monkeypatch):
        _patch_dirs(tmp_path, monkeypatch)
        from crypto.profiles import create_profile, switch_profile, delete_profile, list_profiles

        create_profile("alice")
        create_profile("bob")
        switch_profile("bob")
        delete_profile("alice")
        assert "alice" not in list_profiles()

    def test_delete_active_profile_blocked(self, tmp_path, monkeypatch):
        _patch_dirs(tmp_path, monkeypatch)
        from crypto.profiles import create_profile, switch_profile, delete_profile

        create_profile("alice")
        switch_profile("alice")
        with pytest.raises(ValueError, match="Cannot delete the active profile"):
            delete_profile("alice")

    def test_create_duplicate_profile_rejected(self, tmp_path, monkeypatch):
        _patch_dirs(tmp_path, monkeypatch)
        from crypto.profiles import create_profile

        create_profile("alice")
        with pytest.raises(ValueError, match="already exists"):
            create_profile("alice")

    def test_switch_nonexistent_profile_rejected(self, tmp_path, monkeypatch):
        _patch_dirs(tmp_path, monkeypatch)
        from crypto.profiles import switch_profile

        with pytest.raises(ValueError, match="does not exist"):
            switch_profile("ghost")


class TestPathTraversal:
    """Path traversal protection."""

    def test_dots_and_slashes_stripped(self, tmp_path, monkeypatch):
        _patch_dirs(tmp_path, monkeypatch)
        from crypto.profiles import _profile_dir

        d = _profile_dir("../etc/passwd")
        # Dots and slashes are stripped, only alnum chars remain
        assert ".." not in d.name
        assert "/" not in d.name

    def test_empty_name_after_sanitize_rejected(self, tmp_path, monkeypatch):
        _patch_dirs(tmp_path, monkeypatch)
        from crypto.profiles import _profile_dir

        with pytest.raises(ValueError, match="alphanumeric"):
            _profile_dir("../../../")

    def test_hyphens_and_underscores_allowed(self, tmp_path, monkeypatch):
        _patch_dirs(tmp_path, monkeypatch)
        from crypto.profiles import _profile_dir

        d = _profile_dir("my-profile_01")
        assert d.name == "my-profile_01"


class TestGetActivePid:
    """get_active_pid fallback logic."""

    def test_creates_default_profile_if_none(self, tmp_path, monkeypatch):
        _patch_dirs(tmp_path, monkeypatch)
        from crypto.profiles import get_active_pid

        pid = get_active_pid()
        assert "pid" in pid
        assert "public_key" in pid

    def test_get_profile_db_dir(self, tmp_path, monkeypatch):
        _patch_dirs(tmp_path, monkeypatch)
        from crypto.profiles import create_profile, get_profile_db_dir

        create_profile("alice")
        db_dir = get_profile_db_dir("alice")
        assert db_dir.exists()
        assert "alice" in str(db_dir)
