"""
REFInet Pillar — VPN Manager (WireGuard / OpenVPN)

Manages VPN tunnel lifecycle alongside or as an alternative to Tor.
Mirrors the TorManager pattern: start(), stop(), is_active(), check_health().

Supports:
  - WireGuard: config generation, wg-quick subprocess management
  - OpenVPN: .ovpn config, openvpn subprocess management

VPN and Tor can run independently or together.
"""

import asyncio
import logging
import shutil
import subprocess
from pathlib import Path

from core.config import VPN_DIR, HOME_DIR, ensure_dirs

logger = logging.getLogger("refinet.vpn")

MAX_RESTART_ATTEMPTS = 3


class VPNManager:
    """
    Manages VPN tunnel lifecycle for outbound traffic anonymization.

    Usage:
        vpn = VPNManager(config)
        active = await vpn.start()
        if active:
            # VPN tunnel is running
            pass
        await vpn.stop()
    """

    def __init__(self, config: dict):
        self._config = config
        self._process = None
        self._active = False
        self._restart_count = 0
        self._vpn_type = config.get("vpn_type", "wireguard")

    async def start(self) -> bool:
        """
        Start the VPN tunnel.

        Returns True if the tunnel was established successfully.
        """
        if not self._config.get("vpn_enabled", False):
            logger.info("[VPN] VPN not enabled in config")
            return False

        ensure_dirs()
        VPN_DIR.mkdir(parents=True, exist_ok=True)

        if self._vpn_type == "wireguard":
            return await self._start_wireguard()
        elif self._vpn_type == "openvpn":
            return await self._start_openvpn()
        else:
            logger.error(f"[VPN] Unknown VPN type: {self._vpn_type}")
            return False

    async def _start_wireguard(self) -> bool:
        """Start WireGuard tunnel via wg-quick."""
        wg_quick = shutil.which("wg-quick")
        if not wg_quick:
            logger.warning("[VPN] wg-quick not found. Install WireGuard first.")
            return False

        config_path = VPN_DIR / "wg0.conf"
        if not config_path.exists():
            logger.warning(f"[VPN] WireGuard config not found: {config_path}")
            logger.info("[VPN] Generate one with: pillar.py vpn generate-config")
            return False

        try:
            self._process = await asyncio.create_subprocess_exec(
                wg_quick, "up", str(config_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                self._process.communicate(), timeout=30
            )
            if self._process.returncode == 0:
                self._active = True
                logger.info("[VPN] WireGuard tunnel established")
                return True
            else:
                logger.error(f"[VPN] WireGuard failed: {stderr.decode()}")
                return False
        except asyncio.TimeoutError:
            logger.error("[VPN] WireGuard startup timeout")
            return False
        except Exception as e:
            logger.error(f"[VPN] WireGuard error: {e}")
            return False

    async def _start_openvpn(self) -> bool:
        """Start OpenVPN tunnel."""
        openvpn = shutil.which("openvpn")
        if not openvpn:
            logger.warning("[VPN] openvpn not found. Install OpenVPN first.")
            return False

        config_path = VPN_DIR / "client.ovpn"
        if not config_path.exists():
            logger.warning(f"[VPN] OpenVPN config not found: {config_path}")
            return False

        try:
            self._process = await asyncio.create_subprocess_exec(
                openvpn, "--config", str(config_path),
                "--daemon", "refinet-vpn",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.sleep(5)  # Give OpenVPN time to establish
            self._active = True
            logger.info("[VPN] OpenVPN tunnel established")
            return True
        except Exception as e:
            logger.error(f"[VPN] OpenVPN error: {e}")
            return False

    async def stop(self):
        """Stop the VPN tunnel."""
        if not self._active:
            return

        if self._vpn_type == "wireguard":
            config_path = VPN_DIR / "wg0.conf"
            wg_quick = shutil.which("wg-quick")
            if wg_quick and config_path.exists():
                try:
                    proc = await asyncio.create_subprocess_exec(
                        wg_quick, "down", str(config_path),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    await asyncio.wait_for(proc.communicate(), timeout=10)
                except Exception as e:
                    logger.warning(f"[VPN] Error stopping WireGuard: {e}")
        elif self._vpn_type == "openvpn":
            if self._process and self._process.returncode is None:
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=10)
                except asyncio.TimeoutError:
                    self._process.kill()

        self._active = False
        logger.info("[VPN] Tunnel stopped")

    def is_active(self) -> bool:
        """Check if the VPN tunnel is currently active."""
        return self._active

    async def check_vpn_health(self):
        """
        Background task: periodically check VPN health and auto-restart.
        Runs every 60 seconds.
        """
        while True:
            await asyncio.sleep(60)
            if not self._active:
                continue

            try:
                healthy = await self._is_healthy()
                if not healthy:
                    logger.warning("[VPN] Health check failed — attempting restart")
                    await self._attempt_restart()
            except Exception as e:
                logger.error(f"[VPN] Health check error: {e}")

    async def _is_healthy(self) -> bool:
        """Check if the VPN tunnel is healthy."""
        if self._vpn_type == "wireguard":
            wg = shutil.which("wg")
            if not wg:
                return False
            try:
                proc = await asyncio.create_subprocess_exec(
                    wg, "show", "wg0",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
                return proc.returncode == 0 and b"latest handshake" in stdout
            except Exception:
                return False
        return self._active

    async def _attempt_restart(self):
        """Attempt to restart the VPN tunnel."""
        if self._restart_count >= MAX_RESTART_ATTEMPTS:
            logger.error("[VPN] Max restart attempts reached. VPN will remain inactive.")
            self._active = False
            return

        self._restart_count += 1
        backoff = 10 * (2 ** (self._restart_count - 1))
        logger.info(f"[VPN] Restart attempt {self._restart_count}/{MAX_RESTART_ATTEMPTS} "
                     f"(backoff: {backoff}s)")

        await self.stop()
        await asyncio.sleep(backoff)
        success = await self.start()

        if success:
            self._restart_count = 0
            logger.info("[VPN] Restart successful")


def generate_wireguard_config(pid_data: dict, peer_endpoint: str,
                               peer_public_key: str,
                               allowed_ips: str = "0.0.0.0/0",
                               listen_port: int = 51820) -> str:
    """
    Generate a WireGuard configuration file.

    Args:
        pid_data: PID data dict
        peer_endpoint: VPN server endpoint (host:port)
        peer_public_key: Server's WireGuard public key
        allowed_ips: Allowed IP ranges to route through VPN
        listen_port: Local WireGuard listen port

    Returns:
        WireGuard config file content as string
    """
    # Note: WireGuard uses Curve25519 keys, not Ed25519.
    # In production, generate a separate WireGuard keypair.
    return f"""[Interface]
# REFInet Pillar VPN — PID: {pid_data['pid'][:16]}...
# Generate keys with: wg genkey | tee privatekey | wg pubkey > publickey
PrivateKey = <YOUR_WIREGUARD_PRIVATE_KEY>
ListenPort = {listen_port}
DNS = 1.1.1.1, 9.9.9.9

[Peer]
PublicKey = {peer_public_key}
Endpoint = {peer_endpoint}
AllowedIPs = {allowed_ips}
PersistentKeepalive = 25
"""
