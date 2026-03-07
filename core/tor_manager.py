"""
REFInet Pillar — Tor Hidden Service Manager

Manages a Tor subprocess and exposes REFInet Pillar ports as hidden services.
Lifecycle: start() -> create_hidden_services() -> get_onion_address() -> stop()

The Pillar gets two identities:
  - REFInet PID: SHA-256(Ed25519 pubkey) for content signing and TOFU trust
  - .onion address: SHA3-256(Tor Ed25519 pubkey) for network routing

Both are self-generated. Neither requires external registration.
"""

import asyncio
import logging
import platform
import shutil
from pathlib import Path
from typing import Optional

import stem
import stem.process
import stem.control

from core.config import TOR_DATA_DIR

logger = logging.getLogger("refinet.tor")
TOR_TIMEOUT = 120  # seconds to wait for bootstrap
MAX_RESTART_ATTEMPTS = 3


class TorManager:
    """
    Manages a Tor subprocess and exposes REFInet Pillar ports as hidden services.

    All public methods are safe to call from asyncio context.
    """

    def __init__(self, config: dict):
        self.enabled = config.get("tor_enabled", False)
        self.port_7070 = config.get("port", 7070)
        self.port_70 = config.get("standard_port", 70)
        self.expose_70 = config.get("tor_expose_port_70", True)
        self.socks_port = config.get("tor_socks_port", 9050)
        self.control_port = config.get("tor_control_port", 9051)
        self._tor_process = None
        self._controller: Optional[stem.control.Controller] = None
        self._onion_address: Optional[str] = None
        self._hs_privkey: Optional[str] = None
        self._restart_count = 0

    # -- PUBLIC API -----------------------------------------------------------

    async def start(self) -> bool:
        """
        Launch Tor subprocess, wait for bootstrap, authenticate to control port.
        Returns True on success, False if Tor is unavailable or disabled.
        Should be called before starting TCP servers.
        """
        if not self.enabled:
            logger.info("[TOR] Tor mode disabled in config. Running direct TCP.")
            return False

        if not shutil.which("tor"):
            hint = self._install_hint()
            logger.error(f"[TOR] 'tor' binary not found in PATH. {hint}")
            return False

        try:
            TOR_DATA_DIR.mkdir(parents=True, exist_ok=True)

            tor_config = {
                "SocksPort": str(self.socks_port),
                "ControlPort": str(self.control_port),
                "DataDirectory": str(TOR_DATA_DIR.resolve()),
                "Log": "notice stdout",
                "ExitPolicy": "reject *:*",
                "HiddenServiceStatistics": "0",
            }

            logger.info("[TOR] Launching Tor subprocess...")
            loop = asyncio.get_event_loop()
            self._tor_process = await loop.run_in_executor(
                None,
                lambda: stem.process.launch_tor_with_config(
                    config=tor_config,
                    init_msg_handler=self._bootstrap_handler,
                    timeout=TOR_TIMEOUT,
                    take_ownership=True,
                ),
            )
            logger.info("[TOR] Bootstrap complete. Connecting to control port...")

            self._controller = await loop.run_in_executor(
                None,
                lambda: stem.control.Controller.from_port(port=self.control_port),
            )
            await loop.run_in_executor(None, self._controller.authenticate)
            logger.info("[TOR] Control port authenticated.")
            return True

        except Exception as e:
            logger.error(
                f"[TOR] Failed to start Tor: {e}. "
                "Continuing in direct TCP mode."
            )
            return False

    async def create_hidden_services(self) -> Optional[str]:
        """
        Create ephemeral hidden service mappings for Pillar ports.
        Returns the .onion address (without port suffix), or None on failure.

        If a persisted private key exists in tor_data/hs_privkey, reuses it
        so the .onion address is consistent across restarts.
        """
        if not self._controller:
            return None

        try:
            privkey = self._load_persisted_privkey()
            key_type = "ED25519-V3" if privkey else "NEW"
            key_content = privkey if privkey else "ED25519-V3"

            # Build port mappings: virtual_port -> target (localhost:port)
            port_mappings = {self.port_7070: self.port_7070}
            if self.expose_70:
                port_mappings[self.port_70] = self.port_70

            loop = asyncio.get_event_loop()
            hs_result = await loop.run_in_executor(
                None,
                lambda: self._controller.create_ephemeral_hidden_service(
                    ports=port_mappings,
                    key_type=key_type,
                    key_content=key_content,
                    await_publication=True,
                ),
            )

            # stem returns the full .onion hostname (without trailing dot)
            self._onion_address = hs_result.service_id + ".onion"

            # Persist private key so address survives restart
            if not privkey and hs_result.private_key:
                self._persist_privkey(hs_result.private_key)
                self._hs_privkey = hs_result.private_key

            logger.info(f"[TOR] Hidden service active: {self._onion_address}")
            logger.info(
                f"[TOR] Mapping: {self._onion_address}:{self.port_7070} "
                f"-> 127.0.0.1:{self.port_7070}"
            )
            if self.expose_70:
                logger.info(
                    f"[TOR] Mapping: {self._onion_address}:{self.port_70} "
                    f"-> 127.0.0.1:{self.port_70}"
                )

            return self._onion_address

        except Exception as e:
            logger.error(f"[TOR] Failed to create hidden service: {e}")
            return None

    def get_onion_address(self) -> Optional[str]:
        """Return the .onion address if Tor hidden service is active."""
        return self._onion_address

    def is_active(self) -> bool:
        """Return True if a hidden service is running and has an address."""
        return self._onion_address is not None

    async def stop(self):
        """
        Remove hidden service and terminate Tor process.
        Called from pillar.py shutdown sequence.
        """
        try:
            if self._controller:
                if self._onion_address:
                    service_id = self._onion_address.replace(".onion", "")
                    try:
                        self._controller.remove_ephemeral_hidden_service(service_id)
                    except Exception:
                        pass
                self._controller.close()
        except Exception:
            pass
        if self._tor_process:
            self._tor_process.kill()
        self._onion_address = None
        self._controller = None
        self._tor_process = None
        logger.info("[TOR] Tor process terminated.")

    async def check_tor_health(self):
        """
        Background task: monitor Tor process health every 60 seconds.
        If Tor dies, attempt restart up to MAX_RESTART_ATTEMPTS times.
        """
        await asyncio.sleep(30)  # Initial delay after startup
        while True:
            try:
                if self._controller and self.is_active():
                    loop = asyncio.get_event_loop()
                    try:
                        status = await loop.run_in_executor(
                            None,
                            lambda: self._controller.get_info(
                                "status/circuit-established"
                            ),
                        )
                        if status == "1":
                            logger.debug("[TOR] Health check: circuits established")
                        else:
                            logger.warning(
                                "[TOR] Health check: no circuits established"
                            )
                    except Exception as e:
                        logger.warning(f"[TOR] Health check failed: {e}")
                        await self._attempt_restart()
                elif self.enabled and not self.is_active():
                    await self._attempt_restart()
            except Exception as e:
                logger.warning(f"[TOR] Health monitor error: {e}")
            await asyncio.sleep(60)

    # -- PRIVATE HELPERS ------------------------------------------------------

    async def _attempt_restart(self):
        """Attempt to restart Tor if it has died, up to MAX_RESTART_ATTEMPTS."""
        if self._restart_count >= MAX_RESTART_ATTEMPTS:
            logger.error(
                f"[TOR] Max restart attempts ({MAX_RESTART_ATTEMPTS}) reached. "
                "Tor will remain inactive. Manual intervention required."
            )
            return

        self._restart_count += 1
        logger.warning(
            f"[TOR] Attempting restart ({self._restart_count}/{MAX_RESTART_ATTEMPTS})..."
        )

        await self.stop()
        success = await self.start()
        if success:
            onion = await self.create_hidden_services()
            if onion:
                logger.info(f"[TOR] Restart successful. Address: {onion}")
                self._restart_count = 0
            else:
                logger.error("[TOR] Restart: bootstrap OK but hidden service failed.")
        else:
            backoff = 10 * (2 ** (self._restart_count - 1))
            logger.error(f"[TOR] Restart failed. Next attempt in {backoff}s.")
            await asyncio.sleep(backoff)

    def _bootstrap_handler(self, line: str):
        """Log Tor bootstrap progress lines."""
        if "Bootstrapped" in line:
            logger.info(f"[TOR] {line.strip()}")

    def _privkey_path(self) -> Path:
        return TOR_DATA_DIR / "hs_privkey"

    def _load_persisted_privkey(self) -> Optional[str]:
        """Load persisted hidden service private key if it exists."""
        path = self._privkey_path()
        if path.exists():
            return path.read_text().strip()
        return None

    def _persist_privkey(self, privkey: str):
        """Save hidden service private key with restrictive permissions."""
        path = self._privkey_path()
        path.write_text(privkey)
        path.chmod(0o600)  # owner read/write only
        logger.info("[TOR] Hidden service private key persisted to tor_data/hs_privkey")

    @staticmethod
    def _install_hint() -> str:
        """Return platform-specific Tor install instructions."""
        system = platform.system().lower()
        if system == "darwin":
            return "Install: brew install tor"
        elif system == "linux":
            return (
                "Install: sudo apt install tor (Debian/Ubuntu) or "
                "sudo dnf install tor (Fedora). "
                "Guide: https://torproject.org/install"
            )
        return "Install Tor from https://torproject.org/install"
