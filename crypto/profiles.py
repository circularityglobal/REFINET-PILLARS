"""
REFInet Pillar — Multi-Identity Profile Management

Each profile is an isolated identity with its own:
  - Ed25519 keypair (PID)
  - Database directory
  - Configuration

Profiles are stored under ~/.refinet/profiles/<name>/
The active profile name is persisted in ~/.refinet/active_profile
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from core.config import (
    HOME_DIR, PROFILES_DIR, ACTIVE_PROFILE_FILE, PID_FILE,
    DB_DIR, ensure_dirs,
)
from crypto.pid import generate_pid, save_pid, load_pid, is_encrypted


def _profile_dir(name: str) -> Path:
    """Return the directory for a named profile."""
    # Sanitize name to prevent path traversal
    safe_name = "".join(c for c in name if c.isalnum() or c in ("-", "_"))
    if not safe_name:
        raise ValueError("Profile name must contain alphanumeric characters")
    return PROFILES_DIR / safe_name


def list_profiles() -> list[str]:
    """List all available profile names."""
    ensure_dirs()
    profiles = []
    if PROFILES_DIR.exists():
        for d in sorted(PROFILES_DIR.iterdir()):
            if d.is_dir() and (d / "pid.json").exists():
                profiles.append(d.name)
    return profiles


def create_profile(name: str, password: str = None) -> dict:
    """
    Create a new identity profile.

    Args:
        name: Profile name (alphanumeric, hyphens, underscores)
        password: Optional password for encrypting the private key

    Returns:
        The generated PID data dict.
    """
    profile_dir = _profile_dir(name)
    if profile_dir.exists() and (profile_dir / "pid.json").exists():
        raise ValueError(f"Profile '{name}' already exists")

    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "db").mkdir(parents=True, exist_ok=True)

    pid_data = generate_pid(password=password)
    save_pid(pid_data, profile_dir / "pid.json")

    return pid_data


def delete_profile(name: str):
    """
    Delete a profile and all its data.
    Cannot delete the active profile.
    """
    if name == get_active_profile():
        raise ValueError("Cannot delete the active profile. Switch to another first.")

    profile_dir = _profile_dir(name)
    if not profile_dir.exists():
        raise ValueError(f"Profile '{name}' does not exist")

    shutil.rmtree(profile_dir)


def switch_profile(name: str) -> dict:
    """
    Switch to a different profile.

    Returns the PID data for the newly active profile.
    """
    profile_dir = _profile_dir(name)
    pid_path = profile_dir / "pid.json"
    if not pid_path.exists():
        raise ValueError(f"Profile '{name}' does not exist")

    pid_data = load_pid(pid_path)
    if pid_data is None:
        raise ValueError(f"Profile '{name}' has corrupted PID data")

    # Persist the active profile selection
    ensure_dirs()
    ACTIVE_PROFILE_FILE.write_text(name, encoding="utf-8")

    return pid_data


def get_active_profile() -> str:
    """Get the name of the active profile. Defaults to 'default'."""
    if ACTIVE_PROFILE_FILE.exists():
        try:
            name = ACTIVE_PROFILE_FILE.read_text(encoding="utf-8").strip()
            if name:
                return name
        except OSError:
            pass
    return "default"


def get_active_pid(password: str = None) -> dict:
    """
    Load the PID for the active profile.

    Falls back to:
      1. Active profile's pid.json
      2. Legacy ~/.refinet/pid.json (auto-migrated to profiles/default/)
      3. Generate new default profile
    """
    profile_name = get_active_profile()
    profile_dir = _profile_dir(profile_name)
    pid_path = profile_dir / "pid.json"

    # Try loading from active profile
    if pid_path.exists():
        return load_pid(pid_path)

    # Auto-migrate legacy single pid.json → profiles/default/
    if profile_name == "default" and PID_FILE.exists():
        legacy_pid = load_pid(PID_FILE)
        if legacy_pid:
            profile_dir.mkdir(parents=True, exist_ok=True)
            (profile_dir / "db").mkdir(parents=True, exist_ok=True)
            save_pid(legacy_pid, pid_path)
            return legacy_pid

    # Generate new default profile
    pid_data = create_profile(profile_name, password=password)

    # Set as active
    ACTIVE_PROFILE_FILE.write_text(profile_name, encoding="utf-8")

    return pid_data


def get_profile_db_dir(profile_name: str = None) -> Path:
    """Get the database directory for a profile."""
    if profile_name is None:
        profile_name = get_active_profile()
    profile_dir = _profile_dir(profile_name)
    db_dir = profile_dir / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir


def get_profile_info(name: str) -> dict:
    """Get summary information about a profile."""
    profile_dir = _profile_dir(name)
    pid_path = profile_dir / "pid.json"
    pid_data = load_pid(pid_path)
    if pid_data is None:
        return {"name": name, "error": "corrupted"}

    return {
        "name": name,
        "pid": pid_data["pid"],
        "public_key": pid_data["public_key"],
        "created_at": pid_data.get("created_at"),
        "encrypted": is_encrypted(pid_data),
        "key_store": pid_data.get("key_store", "software"),
        "active": name == get_active_profile(),
    }
