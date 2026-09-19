"""Key-at-rest protection and in-memory unlock (F5)."""

import json
import stat
import sys

import pytest

from crypto import unlock as unlock_mod
from crypto.pid import generate_pid, save_pid, load_pid


@pytest.fixture(autouse=True)
def _clean_unlock_cache():
    unlock_mod.lock_all()
    yield
    unlock_mod.lock_all()


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


class TestFileModes:
    def test_pid_json_is_owner_only(self, tmp_path):
        path = tmp_path / "pid.json"
        save_pid(generate_pid(), path=path)
        assert _mode(path) == 0o600

    def test_existing_world_readable_pid_json_is_tightened(self, tmp_path):
        path = tmp_path / "pid.json"
        path.write_text("{}")
        path.chmod(0o644)
        save_pid(generate_pid(), path=path)
        assert _mode(path) == 0o600

    def test_home_dir_is_owner_only(self):
        from core import config
        config.ensure_dirs()
        assert _mode(config.HOME_DIR) == 0o700


class TestUnlockCache:
    def test_plaintext_pid_needs_no_unlock(self):
        pid = generate_pid()
        assert unlock_mod.is_unlocked(pid)
        assert unlock_mod.get_unlocked_key(pid) is not None

    def test_encrypted_pid_requires_unlock(self):
        pid = generate_pid(password="pw")
        assert not unlock_mod.is_unlocked(pid)
        with pytest.raises(ValueError, match="password required"):
            unlock_mod.get_unlocked_key(pid)
        unlock_mod.unlock(pid, "pw")
        assert unlock_mod.get_unlocked_key(pid) is not None

    def test_wrong_password_rejected(self):
        pid = generate_pid(password="pw")
        with pytest.raises(ValueError):
            unlock_mod.unlock(pid, "nope")
        assert not unlock_mod.is_unlocked(pid)


class TestPasswordNeverOnDisk:
    def test_save_state_drops_password(self):
        from onboarding.wizard import (
            ONBOARDING_STATE_FILE, save_onboarding_state,
        )
        import onboarding.wizard as wiz
        save_onboarding_state({"step": "STEP_CONNECT_WALLET", "password": "secret"})
        assert "password" not in json.loads(wiz.ONBOARDING_STATE_FILE.read_text())

    def test_legacy_state_password_is_migrated_and_unlocks(self):
        import onboarding.wizard as wiz
        from core import config
        pid = generate_pid(password="legacy-pw")
        save_pid(pid)
        # A pre-0.5.0 state file with the password in the clear
        config.ensure_dirs()
        wiz.ONBOARDING_STATE_FILE.write_text(json.dumps({
            "step": "STEP_SIWE_CHALLENGE", "pid": pid["pid"], "password": "legacy-pw",
        }))
        state = wiz.get_onboarding_state()
        assert "password" not in state
        assert "password" not in json.loads(wiz.ONBOARDING_STATE_FILE.read_text())
        assert unlock_mod.is_unlocked(load_pid())

    @pytest.mark.asyncio
    async def test_wizard_generate_pid_does_not_persist_password(self):
        import onboarding.wizard as wiz
        await wiz.handle_wizard_step("/onboarding/generate-pid", "pw123", "localhost", 7070)
        assert "password" not in json.loads(wiz.ONBOARDING_STATE_FILE.read_text())
        assert unlock_mod.is_unlocked(load_pid())

    @pytest.mark.asyncio
    async def test_cold_process_wizard_asks_to_unlock(self):
        import onboarding.wizard as wiz
        await wiz.handle_wizard_step("/onboarding/generate-pid", "pw123", "localhost", 7070)
        unlock_mod.lock_all()  # simulate a restart
        state = wiz.get_onboarding_state()
        state.update(step="STEP_SIWE_CHALLENGE", evm_address="0x" + "1" * 40,
                     siwe_message="x")
        wiz.save_onboarding_state(state)
        resp = await wiz.handle_wizard_step("/onboarding/siwe-verify", "0xsig", "localhost", 7070)
        assert "Unlock Pillar Key" in resp
        bad = await wiz.handle_wizard_step("/onboarding/unlock", "wrong", "localhost", 7070)
        assert "Unlock Pillar Key" in bad and "Error" in bad
        assert not unlock_mod.is_unlocked(load_pid())


class TestStartupUnlock:
    def test_env_password_unlocks(self, monkeypatch):
        import pillar
        pid = generate_pid(password="envpw")
        monkeypatch.setenv("REFINET_PID_PASSWORD", "envpw")
        pillar.unlock_pid_or_exit(pid)
        assert unlock_mod.is_unlocked(pid)

    def test_missing_password_exits(self, monkeypatch):
        import pillar
        pid = generate_pid(password="envpw")
        monkeypatch.delenv("REFINET_PID_PASSWORD", raising=False)
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
        with pytest.raises(SystemExit):
            pillar.unlock_pid_or_exit(pid)

    def test_encrypted_pid_serves_after_unlock(self):
        from core.gopher_server import GopherServer
        pid = generate_pid(password="srvpw")
        save_pid(pid)
        with pytest.raises(ValueError):
            GopherServer(host="127.0.0.1", port=0)
        unlock_mod.unlock(pid, "srvpw")
        server = GopherServer(host="127.0.0.1", port=0)
        assert server.private_key is not None
