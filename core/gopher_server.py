"""
REFInet Pillar — Gopher Protocol Server

A fully functional Gopher server (RFC 1436 compatible) enhanced for REFInet:
  - Serves hierarchical menus and files on TCP port 7070
  - Dynamically generates menus from live database state
  - Logs every request as a transaction in the SQLite ledger
  - Signs content with the Pillar's PID
  - Compatible with standard Gopher clients (lynx, curl, Bombadillo, etc.)

Protocol flow:
  1. Client connects via TCP
  2. Client sends selector string + CRLF
  3. Server responds with menu or file content
  4. Connection closes

This IS Gopherspace. Running this makes you part of it.
"""

import asyncio
import base64
import collections
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.config import GOPHER_HOST, GOPHER_PORT, GOPHER_ROOT, PROTOCOL_VERSION, load_config
import json

from core.menu_builder import (
    build_root_menu,
    build_about_menu,
    build_network_menu,
    build_dapps_menu,
    build_directory_menu,
    build_releases_menu,
    build_pillar_setup_menu,
    build_welcome_menu,
    build_auth_menu,
    build_rpc_menu,
    build_pid_document,
    build_transactions_document,
    build_peers_document,
    build_ledger_document,
    info_line,
    menu_link,
    search_link,
    separator,
)
from crypto.pid import get_or_create_pid, get_private_key, get_short_pid
from crypto.signing import hash_content, sign_content
from db.live_db import (
    init_live_db,
    record_transaction,
    update_daily_metrics,
    get_tx_count_today,
    get_recent_transactions,
    get_peers,
    index_content,
    list_gopherholes,
    insert_service_proof,
    get_license_tier,
    get_replication_rejections_today,
    search_content,
)
from db.archive_db import init_archive_db


logger = logging.getLogger("refinet.gopher")


class RateLimiter:
    """Simple in-memory per-IP sliding window rate limiter."""

    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, collections.deque] = {}
        self.blocked_count = 0

    def is_allowed(self, ip: str) -> bool:
        now = time.time()
        cutoff = now - self.window_seconds

        if ip not in self._requests:
            self._requests[ip] = collections.deque()

        q = self._requests[ip]
        while q and q[0] < cutoff:
            q.popleft()

        if len(q) >= self.max_requests:
            self.blocked_count += 1
            return False

        q.append(now)
        return True

    def get_stats(self) -> dict:
        """Return rate limiter statistics for status display."""
        now = time.time()
        cutoff = now - self.window_seconds
        active_ips = sum(
            1 for q in self._requests.values()
            if q and q[-1] >= cutoff
        )
        return {
            "active_ips": active_ips,
            "blocked_last_minute": self.blocked_count,
        }


_db_initialized = False


def _safe_dapp_count() -> int:
    """Return DApp count without crashing if the module fails to import."""
    try:
        from core.dapp import get_dapp_count
        return get_dapp_count()
    except Exception:
        return 0


def _accounting_date_dict() -> dict:
    """Return the current accounting date as a dict for status.json."""
    from db.live_db import get_accounting_date
    day, month, year = get_accounting_date()
    return {"day": day, "month": month, "year": year}


# REFInet-exclusive routes — blocked on standard Gopher port
REFINET_ROUTES = (
    "/auth", "/rpc", "/pid", "/transactions", "/peers",
    "/ledger", "/network", "/directory.json", "/status.json", "/search",
    "/pillar/status",
)


def _extract_chain_id_from_tx(signed_tx_hex: str) -> int:
    """
    Extract chain_id from a signed EVM transaction.
    Supports EIP-2718 typed transactions (Type 1, Type 2) and legacy EIP-155.
    Returns chain_id or 1 as fallback.
    """
    try:
        raw = bytes.fromhex(signed_tx_hex.replace("0x", ""))
        if not raw:
            return 1
        import rlp
        # EIP-2718 typed transactions: first byte is tx type (1 or 2)
        if raw[0] in (1, 2):
            # Type 1 (EIP-2930) and Type 2 (EIP-1559): first RLP element is chain_id
            payload = rlp.decode(raw[1:])
            return int.from_bytes(payload[0], "big") if payload[0] else 1
        # Legacy tx (EIP-155): chain_id encoded in v value
        # v = chain_id * 2 + 35 or chain_id * 2 + 36
        decoded = rlp.decode(raw)
        v = int.from_bytes(decoded[6], "big") if decoded[6] else 27
        if v >= 35:
            return (v - 35) // 2
        return 1
    except Exception:
        return 1


class GopherServer:
    """
    Async TCP Gopher server for REFInet Pillars.

    Handles standard Gopher selectors + REFInet dynamic routes.
    Every request is logged as a transaction in the live ledger.

    When is_refinet=True (default, port 7070): all routes available.
    When is_refinet=False (port 70): only standard Gopher content served.
    """

    def __init__(self, host: str = None, port: int = None, hostname: str = None,
                 is_refinet: bool = True, tor_manager=None):
        self.config = load_config()
        self.host = host or GOPHER_HOST
        self.port = port or self.config.get("port", GOPHER_PORT)
        self.hostname = hostname or self.config.get("hostname", "localhost")
        self.is_refinet = is_refinet
        self.tor_manager = tor_manager
        self.pid_data = get_or_create_pid()
        self.private_key = get_private_key(self.pid_data)
        self.start_time = time.time()
        self.request_count = 0
        # Use a higher limit for Tor inbound (all traffic appears as 127.0.0.1)
        tor_active = tor_manager and tor_manager.is_active()
        self.rate_limiter = RateLimiter(
            max_requests=500 if tor_active else 100,
        )

        # Initialize databases (once across all instances)
        global _db_initialized
        if not _db_initialized:
            init_live_db()
            init_archive_db()
            _db_initialized = True

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle a single Gopher client connection."""
        addr = writer.get_extra_info("peername")
        try:
            # Rate limit check
            if not self.rate_limiter.is_allowed(addr[0]):
                logger.warning(f"[{addr[0]}:{addr[1]}] rate limited")
                writer.write(self._error_response("Rate limit exceeded. Try again later.").encode("utf-8"))
                await writer.drain()
                return

            # Read selector (Gopher: client sends selector + CRLF)
            raw = await asyncio.wait_for(reader.readline(), timeout=30.0)
            selector = raw.decode("utf-8", errors="replace").strip()

            # Normalize empty selector to root
            if not selector or selector == "/":
                selector = ""

            logger.info(f"[{addr[0]}:{addr[1]}] → selector: '{selector}'")
            self.request_count += 1

            # Route the request
            response = await self._route(selector)

            # Log as transaction in live DB
            content_hash = hash_content(response.encode("utf-8"))
            record_transaction(
                dapp_id="gopher.core",
                pid=self.pid_data["pid"],
                selector=selector or "/",
                content_hash=content_hash,
            )

            # Update daily metrics
            update_daily_metrics(
                self.pid_data["pid"],
                content_served=self.request_count,
                uptime_seconds=int(time.time() - self.start_time),
            )

            # Sign and index served content
            content_type = "menu" if response.startswith("i") or response.startswith("1") else "text"
            signature_hex = sign_content(response.encode("utf-8"), self.private_key)
            try:
                index_content(
                    selector=selector or "/",
                    content_type=content_type,
                    content_hash=content_hash,
                    signature=signature_hex,
                    pid=self.pid_data["pid"],
                    size_bytes=len(response.encode("utf-8")),
                )
            except Exception:
                pass  # Never break serving for indexing failures

            # Generate service proof for token economics (Phase 3).
            # Proof generation must never interrupt serving.
            try:
                proof_ts = int(time.time())
                proof_payload = f"{self.pid_data['pid']}:gopher.serve:{selector or '/'}:{content_hash}:{proof_ts}"
                proof_sig = sign_content(proof_payload.encode("utf-8"), self.private_key)
                proof_hash = hash_content(proof_payload.encode("utf-8"))
                insert_service_proof(
                    proof_id=str(uuid.uuid4()),
                    pid=self.pid_data["pid"],
                    service="gopher.serve",
                    proof_hash=proof_hash,
                    signature=proof_sig,
                )
            except Exception:
                pass  # Never break serving for proof failures

            # Append Ed25519 signature block after the response.
            # The block goes AFTER the Gopher "." terminator so legacy
            # clients that stop reading at "." are unaffected. Browsers
            # and peers that know REFInet can parse the trailing block.
            sig_block = (
                "\r\n---BEGIN REFINET SIGNATURE---\r\n"
                f"pid:{self.pid_data['pid']}\r\n"
                f"pubkey:{self.pid_data['public_key']}\r\n"
                f"sig:{signature_hex}\r\n"
                f"hash:{content_hash}\r\n"
                "---END REFINET SIGNATURE---\r\n"
            )

            # Send response + signature block
            writer.write((response + sig_block).encode("utf-8"))
            await writer.drain()

        except asyncio.TimeoutError:
            logger.warning(f"[{addr[0]}:{addr[1]}] timeout")
        except Exception as e:
            logger.error(f"[{addr[0]}:{addr[1]}] error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()

    async def _route(self, selector: str) -> str:
        """
        Route a Gopher selector to the appropriate handler.

        Dynamic routes (generated from DB/state):
          ""            → root menu
          /about        → about this pillar
          /network      → network status + peers
          /dapps        → DApp directory
          /directory    → gopherhole registry (human-readable)
          /directory.json → gopherhole registry (machine-readable, browser contract)
          /pid          → PID identity document
          /transactions → recent transaction log
          /peers        → peer list document
          /ledger       → ledger status

        Static routes:
          /news/*     → files from gopherroot/news/
          Any other   → try to serve from gopherroot/
        """
        h = self.hostname
        p = self.port

        # --- REFInet route gating (port 70 = standard Gopher only) ---
        if not self.is_refinet:
            if any(selector == r or selector.startswith(r + "/") or selector.startswith(r + "?")
                   for r in REFINET_ROUTES):
                return self._error_response(
                    "REFInet feature. Connect on port 7070 for full access."
                )

        # --- Dynamic routes ---
        if selector == "" or selector == "/":
            tx_today = get_tx_count_today(self.pid_data["pid"])
            peers = get_peers()
            tier = get_license_tier(self.pid_data["pid"])
            onion = self.tor_manager.get_onion_address() if self.tor_manager else None
            return build_root_menu(self.pid_data, h, p, tx_today, len(peers),
                                   is_refinet=self.is_refinet,
                                   license_tier=tier,
                                   onion_address=onion)

        elif selector == "/about":
            onion = self.tor_manager.get_onion_address() if self.tor_manager else None
            return build_about_menu(self.pid_data, h, p, onion_address=onion)

        elif selector == "/network":
            peers = get_peers()
            rejections = get_replication_rejections_today()
            return build_network_menu(peers, h, p, replication_rejections_today=rejections)

        elif selector == "/dapps":
            from core.dapp import load_all_dapps
            dapps = load_all_dapps()
            return build_dapps_menu(h, p, dapps=dapps)

        elif selector.startswith("/dapps/") and selector.endswith(".dapp"):
            slug = selector.replace("/dapps/", "").replace(".dapp", "")
            from core.dapp import parse_dapp_file, list_dapp_files
            for path in list_dapp_files():
                if path.stem == slug:
                    dapp = parse_dapp_file(path)
                    return self._render_dapp_detail(dapp, h, p)
            return self._error_response(f"DApp not found: {slug}")

        elif selector == "/directory":
            holes = list_gopherholes()
            return build_directory_menu(holes, h, p)

        elif selector == "/releases":
            return build_releases_menu(h, p)

        elif selector == "/pillar-setup":
            return build_pillar_setup_menu(h, p)

        elif selector == "/welcome":
            return build_welcome_menu(h, p)

        elif selector == "/directory.json":
            holes = list_gopherholes()
            # Versioned JSON schema — browser contract (v1)
            # The browser consumes this endpoint. Do NOT change field names
            # or remove fields without bumping schema_version.
            entries = [
                {
                    "pid": hole["pid"],
                    "selector": hole["selector"],
                    "name": hole["name"],
                    "description": hole["description"],
                    "owner_address": hole["owner_address"],
                    "pubkey_hex": hole["pubkey_hex"],
                    "signature": hole["signature"],
                    "registered_at": hole["registered_at"],
                    "tx_hash": hole["tx_hash"],
                    "source": hole["source"],
                }
                for hole in holes
            ]
            envelope = {
                "schema_version": 1,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "pillar_pid": self.pid_data["pid"],
                # Field name 'gopherholes' is canonical — do not rename.
                # Browser's pillarGetDirectory() accepts both 'gopherholes'
                # and 'pillars' for compatibility, but 'gopherholes' is correct.
                "gopherholes": entries,
            }
            return json.dumps(envelope, indent=2) + "\r\n.\r\n"

        elif selector == "/status.json":
            # Machine-readable status endpoint — browser contract.
            # Field names are part of the REFInet wire protocol — do NOT
            # rename without coordinating with Browser's status-aggregator.js.
            uptime = int(time.time() - self.start_time)
            peers = get_peers()
            tx_today = get_tx_count_today(self.pid_data["pid"])
            status = {
                "schema_version": 1,
                "pid": self.pid_data["pid"],
                "public_key": self.pid_data["public_key"],
                "pillar_name": self.config.get("pillar_name", "REFInet Pillar"),
                "protocol_version": PROTOCOL_VERSION,
                "uptime_seconds": uptime,
                "tx_count_today": tx_today,
                "peers_online": len(peers),
                "port": self.port,
                "timestamp": int(time.time()),
                "license_tier": get_license_tier(self.pid_data["pid"]),
                "dapp_count": _safe_dapp_count(),
                "accounting_date": _accounting_date_dict(),
                "rate_limiter": self.rate_limiter.get_stats(),
                "tor_active": self.tor_manager.is_active() if self.tor_manager else False,
                "onion_address": self.tor_manager.get_onion_address() if self.tor_manager else None,
            }
            return json.dumps(status, indent=2) + "\r\n.\r\n"

        elif selector == "/pillar/status":
            return self._build_pillar_status_response(h, p)

        elif selector == "/auth":
            return build_auth_menu(h, p)

        elif selector.startswith("/auth/challenge"):
            # Extract address from query: /auth/challenge?address=0x...
            # Gopher type 7 search sends query after tab
            # Browser sends address:chainId (colon-delimited)
            query = selector.split("\t", 1)[1] if "\t" in selector else ""
            if not query:
                # Try URL-style ?address=
                if "?address=" in selector:
                    query = selector.split("?address=", 1)[1]
            query = query.strip()

            # Parse address:chainId (Browser format) or plain address (legacy)
            chain_id = 1  # default to Ethereum mainnet
            if ":" in query:
                parts = query.split(":", 1)
                address = parts[0].strip()
                try:
                    chain_id = int(parts[1].strip())
                except (ValueError, IndexError):
                    chain_id = 1
            else:
                address = query

            if not address.startswith("0x") or len(address) != 42:
                return self._error_response(
                    "Invalid EVM address. Format: 0x followed by 40 hex chars"
                )
            try:
                from auth.session import create_challenge
                challenge = create_challenge(address, chain_id=chain_id)
                return challenge["message"] + "\r\n.\r\n"
            except ImportError:
                return self._error_response("Authentication requires: pip install eth-account")

        elif selector.startswith("/auth/verify"):
            # Browser Alignment: CONFIRMED — this handler correctly implements:
            # 1. Tab-split for Type 7 query extraction
            # 2. Pipe-split for 3 fields: address|signature|base64(message)
            # 3. Base64 decode with newline detection (SIWE messages contain newlines)
            # 4. Domain validation (rejects Browser-issued challenges)
            # Gopher type 7 search: query arrives after tab
            query = selector.split("\t", 1)[1] if "\t" in selector else ""
            if not query:
                if "?" in selector:
                    query = selector.split("?", 1)[1]

            # Expected format: address|signature|message_or_base64 (pipe-delimited)
            # The message field can be base64-encoded (from Browser clients,
            # since SIWE messages contain newlines that can't survive Gopher's
            # single-line query protocol) or plain text (from Gopher type-7
            # clients where the message has no newlines).
            parts = query.strip().split("|", 2)
            if len(parts) != 3:
                return self._error_response(
                    "Format: address|signature|base64(message_text)"
                )

            address, sig, msg_field = (
                parts[0].strip(), parts[1].strip(), parts[2].strip()
            )

            # Detect base64-encoded message: attempt strict decode and
            # check that result contains newlines (SIWE messages always do).
            # Fall back to raw text for plain Gopher type-7 queries.
            message_text = msg_field
            try:
                decoded = base64.b64decode(msg_field, validate=True).decode("utf-8")
                if "\n" in decoded:
                    message_text = decoded
            except Exception:
                pass

            # Domain validation: reject messages issued for Browser sessions
            if "URI: refinet://browser" in message_text or "URI:refinet://browser" in message_text:
                return self._error_response(
                    "Challenge was issued for Browser session, not Pillar session"
                )

            if not address.startswith("0x") or len(address) != 42:
                return self._error_response(
                    "Invalid EVM address. Format: 0x followed by 40 hex chars"
                )

            try:
                from auth.session import establish_session
                session = establish_session(address, message_text, sig)
                lines = []
                lines.append(info_line(""))
                lines.append(info_line("  AUTHENTICATION SUCCESSFUL"))
                lines.append(separator())
                lines.append(info_line(""))
                lines.append(info_line(f"  Session ID: {session['session_id']}"))
                lines.append(info_line(f"  Address:    {session['address']}"))
                lines.append(info_line(f"  Expires:    {session['expires_at']}"))
                lines.append(info_line(""))
                lines.append(info_line("  Use this session_id for authenticated operations."))
                lines.append(info_line(""))
                lines.append(separator())
                lines.append(menu_link("  ← Back to Auth", "/auth", h, p))
                lines.append(menu_link("  ← Back to Root", "/", h, p))
                lines.append(info_line(""))
                lines.append(".\r\n")
                return "".join(lines)
            except ValueError as e:
                return self._error_response(f"Authentication failed: {e}")
            except ImportError:
                return self._error_response("Authentication requires: pip install eth-account")

        elif selector == "/rpc":
            return await self._route_rpc_status(h, p)

        elif selector.startswith("/rpc/balance"):
            query = selector.split("\t", 1)[1] if "\t" in selector else ""
            if not query and "?" in selector:
                query = selector.split("?", 1)[1]
            if not query:
                return self._error_response("Usage: chain_id|0xAddress or address:chainName")
            # Support both formats:
            # Legacy:  chain_id|0xAddress (pipe, 2 fields)
            # Browser: address:chainName (colon, 2 fields)
            try:
                if "|" in query:
                    parts = query.strip().split("|")
                    if len(parts) != 2:
                        return self._error_response("Pipe format: chain_id|0xAddress")
                    chain_id = int(parts[0].strip())
                    address = parts[1].strip()
                elif ":" in query:
                    from rpc.chains import CHAIN_NAME_TO_ID
                    parts = query.strip().split(":", 1)
                    address = parts[0].strip()
                    chain_field = parts[1].strip()
                    if chain_field.isdigit():
                        chain_id = int(chain_field)
                    else:
                        chain_id = CHAIN_NAME_TO_ID.get(chain_field.lower())
                        if chain_id is None:
                            return self._error_response(
                                f"Unknown chain: {chain_field}. "
                                f"Supported: ethereum, polygon, arbitrum, base, sepolia"
                            )
                else:
                    return self._error_response("Format: chain_id|0xAddress or address:chainName")
                if not address.startswith("0x") or len(address) != 42:
                    return self._error_response("Invalid EVM address")
                from rpc.gateway import RPCGateway, WEB3_AVAILABLE
                if not WEB3_AVAILABLE:
                    return self._error_response("RPC requires: pip install web3")
                gw = RPCGateway()
                try:
                    balance_wei = await gw.get_balance(chain_id, address)
                    balance_eth = balance_wei / 10**18
                    lines = []
                    lines.append(info_line(""))
                    lines.append(info_line(f"  Balance for {address}"))
                    lines.append(separator())
                    lines.append(info_line(f"  Chain:   {chain_id}"))
                    lines.append(info_line(f"  Balance: {balance_wei} wei"))
                    lines.append(info_line(f"           {balance_eth:.6f} native"))
                    lines.append(info_line(""))
                    lines.append(menu_link("  <- Back to RPC", "/rpc", h, p))
                    lines.append(".\r\n")
                    return "".join(lines)
                finally:
                    await gw.close()
            except ImportError:
                return self._error_response("RPC requires: pip install web3")
            except ValueError as e:
                return self._error_response(f"Invalid input: {e}")
            except Exception as e:
                return self._error_response(f"RPC error: {e}")

        elif selector.startswith("/rpc/token"):
            query = selector.split("\t", 1)[1] if "\t" in selector else ""
            if not query and "?" in selector:
                query = selector.split("?", 1)[1]
            if not query:
                return self._error_response(
                    "Usage: chain_id|token_address|wallet_address or tokenAddress:ownerAddress:chainName"
                )
            # Support both formats:
            # Legacy:  chain_id|token_address|wallet_address (pipe, 3 fields)
            # Browser: tokenAddress:ownerAddress:chainName (colon, 3 fields)
            try:
                if "|" in query:
                    parts = query.strip().split("|")
                    if len(parts) != 3:
                        return self._error_response("Pipe format: chain_id|token_address|wallet_address")
                    chain_id = int(parts[0].strip())
                    token_addr = parts[1].strip()
                    wallet_addr = parts[2].strip()
                elif ":" in query:
                    from rpc.chains import CHAIN_NAME_TO_ID
                    parts = query.strip().split(":")
                    if len(parts) != 3:
                        return self._error_response("Colon format: tokenAddress:ownerAddress:chainName")
                    token_addr = parts[0].strip()
                    wallet_addr = parts[1].strip()
                    chain_field = parts[2].strip()
                    if chain_field.isdigit():
                        chain_id = int(chain_field)
                    else:
                        chain_id = CHAIN_NAME_TO_ID.get(chain_field.lower())
                        if chain_id is None:
                            return self._error_response(
                                f"Unknown chain: {chain_field}. "
                                f"Supported: ethereum, polygon, arbitrum, base, sepolia"
                            )
                else:
                    return self._error_response(
                        "Format: chain_id|token_address|wallet_address or tokenAddress:ownerAddress:chainName"
                    )
                from rpc.gateway import RPCGateway, WEB3_AVAILABLE
                if not WEB3_AVAILABLE:
                    return self._error_response("RPC requires: pip install web3")
                gw = RPCGateway()
                try:
                    balance = await gw.get_token_balance(chain_id, token_addr, wallet_addr)
                    lines = []
                    lines.append(info_line(""))
                    lines.append(info_line("  ERC-20 Token Balance"))
                    lines.append(separator())
                    lines.append(info_line(f"  Chain:   {chain_id}"))
                    lines.append(info_line(f"  Token:   {token_addr}"))
                    lines.append(info_line(f"  Wallet:  {wallet_addr}"))
                    lines.append(info_line(f"  Balance: {balance} (raw units)"))
                    lines.append(info_line(""))
                    lines.append(menu_link("  <- Back to RPC", "/rpc", h, p))
                    lines.append(".\r\n")
                    return "".join(lines)
                finally:
                    await gw.close()
            except ImportError:
                return self._error_response("RPC requires: pip install web3")
            except Exception as e:
                return self._error_response(f"RPC error: {e}")

        elif selector.startswith("/rpc/gas"):
            query = selector.split("\t", 1)[1] if "\t" in selector else ""
            if not query and "?" in selector:
                query = selector.split("?", 1)[1]
            if not query:
                return self._error_response("Usage: chain_id|to_address|value_wei or JSON {to, value, chain}")
            try:
                # Try JSON parse first (Browser sends JSON via Type 7 query)
                json_params = None
                try:
                    json_params = json.loads(query.strip())
                except (json.JSONDecodeError, ValueError):
                    pass

                if json_params and isinstance(json_params, dict):
                    from rpc.chains import CHAIN_NAME_TO_ID
                    chain_field = json_params.get("chain", "")
                    if isinstance(chain_field, str) and not chain_field.isdigit():
                        chain_id = CHAIN_NAME_TO_ID.get(chain_field.lower())
                        if chain_id is None:
                            return self._error_response(
                                f"Unknown chain name: {chain_field}. "
                                f"Supported: ethereum, polygon, arbitrum, base, sepolia"
                            )
                    else:
                        chain_id = int(chain_field)
                    to_address = json_params.get("to", "")
                    value_hex = json_params.get("value", "0")
                    value_wei = int(value_hex, 16) if isinstance(value_hex, str) and value_hex.startswith("0x") else int(value_hex)
                else:
                    # Fall back to pipe-delimited: chain_id|to_address|value_wei
                    parts = query.strip().split("|")
                    if len(parts) != 3:
                        return self._error_response("Format: chain_id|to_address|value_wei")
                    chain_id = int(parts[0].strip())
                    to_address = parts[1].strip()
                    value_wei = int(parts[2].strip())

                from rpc.gateway import RPCGateway, WEB3_AVAILABLE
                if not WEB3_AVAILABLE:
                    return self._error_response("RPC requires: pip install web3")
                gw = RPCGateway()
                try:
                    gas = await gw.estimate_gas(chain_id, {"to": to_address, "value": value_wei})
                    # If request was JSON, return JSON response for Browser
                    if json_params:
                        result = {
                            "gasLimit": str(gas),
                            "maxFeePerGas": "0",
                            "maxPriorityFeePerGas": "0",
                        }
                        return json.dumps(result) + "\r\n.\r\n"
                    # Otherwise return Gopher menu for human clients
                    lines = []
                    lines.append(info_line(""))
                    lines.append(info_line("  Gas Estimate"))
                    lines.append(separator())
                    lines.append(info_line(f"  Chain: {chain_id}"))
                    lines.append(info_line(f"  To:    {to_address}"))
                    lines.append(info_line(f"  Value: {value_wei} wei"))
                    lines.append(info_line(f"  Gas:   {gas}"))
                    lines.append(info_line(""))
                    lines.append(menu_link("  <- Back to RPC", "/rpc", h, p))
                    lines.append(".\r\n")
                    return "".join(lines)
                finally:
                    await gw.close()
            except ImportError:
                return self._error_response("RPC requires: pip install web3")
            except (ValueError, KeyError, TypeError) as e:
                return self._error_response(f"Invalid gas params: {e}")
            except Exception as e:
                return self._error_response(f"RPC error: {e}")

        elif selector.startswith("/rpc/broadcast"):
            query = selector.split("\t", 1)[1] if "\t" in selector else ""
            if not query and "?" in selector:
                query = selector.split("?", 1)[1]
            if not query:
                return self._error_response(
                    "Usage: session_id:signed_tx_hex or session_id|chain_id|signed_tx_hex"
                )
            # Support both formats:
            # Browser: session_id:signed_tx_hex (colon, 2 fields — chain_id parsed from tx)
            # Legacy:  session_id|chain_id|signed_tx_hex (pipe, 3 fields)
            try:
                if "|" in query:
                    parts = query.strip().split("|")
                    if len(parts) != 3:
                        return self._error_response("Pipe format: session_id|chain_id|signed_tx_hex")
                    session_id = parts[0].strip()
                    chain_id = int(parts[1].strip())
                    signed_tx = parts[2].strip()
                elif ":" in query:
                    session_id, signed_tx = query.strip().split(":", 1)
                    session_id = session_id.strip()
                    signed_tx = signed_tx.strip()
                    chain_id = _extract_chain_id_from_tx(signed_tx)
                else:
                    return self._error_response(
                        "Usage: session_id:signed_tx_hex or session_id|chain_id|signed_tx_hex"
                    )
                from rpc.gateway import RPCGateway, WEB3_AVAILABLE
                if not WEB3_AVAILABLE:
                    return self._error_response("RPC requires: pip install web3")
                gw = RPCGateway()
                try:
                    tx_hash = await gw.broadcast(chain_id, signed_tx, session_id=session_id)
                    lines = []
                    lines.append(info_line(""))
                    lines.append(info_line("  Transaction Broadcast"))
                    lines.append(separator())
                    lines.append(info_line(f"  Chain:   {chain_id}"))
                    lines.append(info_line(f"  TX Hash: {tx_hash}"))
                    lines.append(info_line(""))
                    lines.append(menu_link("  <- Back to RPC", "/rpc", h, p))
                    lines.append(".\r\n")
                    return "".join(lines)
                finally:
                    await gw.close()
            except ImportError:
                return self._error_response("RPC requires: pip install web3")
            except PermissionError as e:
                return self._error_response(f"Auth required: {e}")
            except Exception as e:
                return self._error_response(f"Broadcast error: {e}")

        elif selector == "/pid":
            pillar_name = self.config.get("pillar_name", "REFInet Pillar")
            onion = self.tor_manager.get_onion_address() if self.tor_manager else None
            return build_pid_document(self.pid_data, pillar_name=pillar_name,
                                      onion_address=onion)

        elif selector == "/transactions":
            txs = get_recent_transactions(self.pid_data["pid"])
            return build_transactions_document(txs)

        elif selector == "/peers":
            peers = get_peers()
            return build_peers_document(peers, hostname=h, port=p)

        elif selector == "/ledger":
            tx_today = get_tx_count_today(self.pid_data["pid"])
            return build_ledger_document(self.pid_data["pid"], tx_today)

        elif selector.startswith("/search"):
            query = selector.split("\t", 1)[1] if "\t" in selector else ""
            if not query and "?" in selector:
                query = selector.split("?", 1)[1]
            if not query:
                lines = []
                lines.append(info_line(""))
                lines.append(info_line("  REFINET SEARCH"))
                lines.append(separator())
                lines.append(info_line(""))
                lines.append(search_link("  Search REFInet", "/search", h, p))
                lines.append(info_line(""))
                lines.append(menu_link("  ← Back to Root", "/", h, p))
                lines.append(".\r\n")
                return "".join(lines)
            results = search_content(query.strip())
            lines = []
            lines.append(info_line(""))
            lines.append(info_line(f"  SEARCH RESULTS: \"{query.strip()}\""))
            lines.append(separator())
            lines.append(info_line(""))
            if results:
                lines.append(info_line(f"  {len(results)} result(s) found"))
                lines.append(info_line(""))
                for r in results:
                    lines.append(menu_link(f"  {r['name']}", r["selector"], h, p))
            else:
                lines.append(info_line("  No results found."))
            lines.append(info_line(""))
            lines.append(search_link("  Search again", "/search", h, p))
            lines.append(menu_link("  ← Back to Root", "/", h, p))
            lines.append(".\r\n")
            return "".join(lines)

        # --- Static file serving from gopherroot ---
        else:
            return self._serve_static(selector)

    def _serve_static(self, selector: str) -> str:
        """
        Serve a static file or directory from gopherroot.

        If selector points to a directory with a 'gophermap', serve that.
        If it points to a file, serve the file contents.
        Otherwise, generate a directory listing.
        """
        # Sanitize selector to prevent directory traversal
        clean = selector.lstrip("/").replace("..", "")
        target = (GOPHER_ROOT / clean).resolve()
        if not str(target).startswith(str(GOPHER_ROOT.resolve())):
            return self._error_response(f"Not found: {selector}")

        if not target.exists():
            return self._error_response(f"Not found: {selector}")

        if target.is_file():
            try:
                return target.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                logger.error(f"Failed to read {selector}: {e}")
                return self._error_response(f"Cannot read: {selector}")

        if target.is_dir():
            gophermap = target / "gophermap"
            if gophermap.exists():
                return gophermap.read_text(encoding="utf-8", errors="replace")
            # Auto-generate directory listing
            return self._auto_directory(target, selector)

        return self._error_response(f"Unknown: {selector}")

    def _auto_directory(self, path: Path, selector: str) -> str:
        """Auto-generate a Gopher menu from a directory listing."""
        h = self.hostname
        p = self.port
        lines = []
        lines.append(info_line(f"  Directory: {selector}"))
        lines.append(separator())
        lines.append(info_line(""))

        for item in sorted(path.iterdir()):
            if item.name.startswith(".") or item.name == "gophermap":
                continue
            rel = f"{selector.rstrip('/')}/{item.name}"
            if item.is_dir():
                lines.append(menu_link(f"  {item.name}/", rel, h, p))
            else:
                lines.append(f"0  {item.name}\t{rel}\t{h}\t{p}\r\n")

        lines.append(info_line(""))
        lines.append(menu_link("  ← Back to Root", "/", h, p))
        lines.append(".\r\n")
        return "".join(lines)

    def _build_pillar_status_response(self, hostname: str, port: int) -> str:
        """
        Machine-readable Pillar status for Browser TOFU bootstrap.
        Returns key:value lines the Browser parses to extract the public key.
        Minimal — only fields needed for identity verification.
        """
        lines = []
        lines.append(f"pid:{self.pid_data['pid']}\r\n")
        lines.append(f"public_key:{self.pid_data['public_key']}\r\n")
        lines.append(f"pillar_name:{self.config.get('pillar_name', 'REFInet Pillar')}\r\n")
        lines.append(f"protocol_version:{PROTOCOL_VERSION}\r\n")
        lines.append(f"port:{self.port}\r\n")
        lines.append(".\r\n")
        return "".join(lines)

    def _error_response(self, message: str) -> str:
        """Generate a Gopher error menu."""
        lines = []
        lines.append(info_line(""))
        lines.append(info_line(f"  ERROR: {message}"))
        lines.append(info_line(""))
        lines.append(menu_link("  ← Back to Root", "/", self.hostname, self.port))
        lines.append(".\r\n")
        return "".join(lines)

    def _render_dapp_detail(self, dapp, hostname: str, port: int) -> str:
        """Render a DApp definition as a Gopher menu."""
        lines = []
        lines.append(info_line(""))
        lines.append(info_line(f"  DAPP: {dapp.name}"))
        lines.append(separator())
        lines.append(info_line(""))
        lines.append(info_line(f"  Version:  {dapp.version}"))
        lines.append(info_line(f"  Chain:    {dapp.chain_id}"))
        lines.append(info_line(f"  Contract: {dapp.contract}"))
        lines.append(info_line(f"  Author:   {dapp.author_pid[:16]}..." if dapp.author_pid else ""))
        lines.append(info_line(f"  {dapp.description}"))
        lines.append(info_line(""))
        if dapp.abi_functions:
            lines.append(info_line("  ABI Functions:"))
            for fn in dapp.abi_functions:
                lines.append(info_line(f"    {fn}"))
            lines.append(info_line(""))
        if dapp.warnings:
            lines.append(info_line("  Warnings:"))
            for w in dapp.warnings:
                lines.append(info_line(f"    ! {w}"))
            lines.append(info_line(""))
        lines.append(separator())
        lines.append(menu_link("  \u2190 Back to DApps", "/dapps", hostname, port))
        lines.append(menu_link("  \u2190 Back to Root", "/", hostname, port))
        lines.append(info_line(""))
        lines.append(".\r\n")
        return "".join(lines)

    async def _route_rpc_status(self, hostname: str, port: int) -> str:
        """RPC gateway status — test chain connectivity.

        Runs all chain connectivity tests in parallel with a 10s total cap
        so the route responds quickly even when RPCs are unreachable.
        """
        try:
            from rpc.gateway import RPCGateway, WEB3_AVAILABLE
            if not WEB3_AVAILABLE:
                return build_rpc_menu({}, hostname, port, available=False)
            gw = RPCGateway()
            from rpc.chains import DEFAULT_CHAINS

            async def _test_one(chain_id, chain):
                latency = await gw.test_connection(chain_id, timeout=5.0)
                return chain_id, {
                    "name": chain["name"],
                    "symbol": chain["symbol"],
                    "latency": latency,
                }

            try:
                results = await asyncio.wait_for(
                    asyncio.gather(
                        *[_test_one(cid, c) for cid, c in DEFAULT_CHAINS.items()],
                        return_exceptions=True,
                    ),
                    timeout=10.0,
                )
                statuses = {}
                for r in results:
                    if isinstance(r, tuple):
                        statuses[r[0]] = r[1]
            except asyncio.TimeoutError:
                # If the whole batch times out, report all as unreachable
                statuses = {
                    cid: {"name": c["name"], "symbol": c["symbol"], "latency": None}
                    for cid, c in DEFAULT_CHAINS.items()
                }
            finally:
                await gw.close()

            return build_rpc_menu(statuses, hostname, port)
        except ImportError:
            return build_rpc_menu({}, hostname, port, available=False)

    async def start(self):
        """Start the Gopher server."""
        server = await asyncio.start_server(
            self.handle_client, self.host, self.port
        )

        short_pid = get_short_pid(self.pid_data)
        addrs = ", ".join(str(s.getsockname()) for s in server.sockets)

        if self.is_refinet:
            # Full banner for REFInet server (port 7070)
            print()
            print("  ╔══════════════════════════════════════════╗")
            print("  ║         R E F I n e t   P I L L A R     ║")
            print("  ╚══════════════════════════════════════════╝")
            print()
            print(f"  🌐 REFInet server listening on {addrs}")
            print(f"  🆔 Pillar ID: {short_pid}...")
            print(f"  📂 Gopherroot: {GOPHER_ROOT}")
            print(f"  💾 Live DB: {self.pid_data['pid'][:8]}... initialized")
            print()
            print("  You are now part of Gopherspace.")
            print()
            print("  Connect with:")
            print(f"    curl gopher://localhost:{self.port}/")
            print(f"    lynx gopher://localhost:{self.port}")
            print()
            print("  Press Ctrl+C to shut down.")
            print()
        else:
            # Short banner for standard Gopher server (port 70)
            print(f"  🌐 Gopher server (standard) listening on {addrs}")

        logger.info(f"{'REFInet' if self.is_refinet else 'Gopher'} server started on {addrs} | PID: {short_pid}")

        async with server:
            await server.serve_forever()
