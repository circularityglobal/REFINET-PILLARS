"""What a Pillar on a public domain must refuse.

Every test here asserts the SECURE behaviour. They all failed against the
code as first written: a Pillar deployed the way docs/OPERATORS.md describes
served its own vault listing, its RPC relay and its session-minting auth
routes to anyone on the internet, over both transports.
"""

import asyncio
import json

import pytest

from core.gopher_server import GopherServer
from integration.http_gateway import HTTPGateway, selector_from_path

APP = "https://app.example.com"


@pytest.fixture
async def public_pillar(tmp_path, monkeypatch):
    """A Pillar configured the way a public VPS deployment configures it."""
    monkeypatch.setattr("core.config.CONFIG_FILE", tmp_path / ".refinet" / "config.json")
    monkeypatch.setattr("core.config.GOPHER_ROOT", tmp_path / "gopherroot")
    (tmp_path / "gopherroot").mkdir()
    server = GopherServer(host="127.0.0.1", port=0, hostname="localhost")
    server.public_mode = True
    config = {"public_domain": "pillar.example.com", "port": 7070,
              "http_gateway_enabled": True}
    gw = HTTPGateway(server, cors_origins=[APP], config_loader=lambda: config)
    http = await asyncio.start_server(gw.handle, "127.0.0.1", 0)
    yield server, http.sockets[0].getsockname()[1]
    http.close()
    await http.wait_closed()


async def _get(port, path):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"GET {path} HTTP/1.1\r\nHost: x\r\n\r\n".encode("latin-1"))
    await writer.drain()
    raw = await asyncio.wait_for(reader.read(), timeout=10)
    writer.close()
    head, _, body = raw.partition(b"\r\n\r\n")
    return int(head.decode("latin-1").split("\r\n")[0].split()[1]), body.decode("utf-8", "replace")


# ------------------------------------------------------------------
# The selector parser itself
# ------------------------------------------------------------------

def test_encoded_tab_is_not_an_argument_delimiter():
    """%09 decodes to the tab every Gopher route splits its arguments on.

    Without this, /g/<route>%09<args> reaches any route with any argument.
    """
    with pytest.raises(ValueError):
        selector_from_path("/g/auth/zkp-verify%09{}")
    with pytest.raises(ValueError):
        selector_from_path("/g/rpc/broadcast?x%09y")


# ------------------------------------------------------------------
# Routes that must never answer a public caller
# ------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/g/vault",
    "/g/settings",
    "/g/auth",
    "/g/rpc/balance%091:0x0000000000000000000000000000000000000000",
    "/g/rpc/broadcast%09session:deadbeef",
    "/g/auth/zkp-verify%09{}",
])
async def test_private_routes_are_not_served_over_http(public_pillar, path):
    _, port = public_pillar
    status, body = await _get(port, path)
    # 400 for a malformed selector, 404 for a refused one. What must never
    # happen is a 200 carrying the route's real answer.
    assert status in (400, 404), f"{path} answered {status} with: {body[:200]}"
    assert "session id" not in body.lower()


@pytest.mark.parametrize("selector", [
    "/vault",
    "/settings",
    "/auth",
    "/rpc/balance\t1:0x0000000000000000000000000000000000000000",
])
async def test_private_routes_are_refused_on_public_gopher(public_pillar, selector):
    """Port 7070 is published straight to the internet by deploy/vps, so the
    gate cannot live in the HTTP gateway alone."""
    server, _ = public_pillar
    body, _sig = await server.respond(selector)
    assert "not available" in body.lower() or "not found" in body.lower(), \
        f"{selector} answered: {body[:200]}"


async def test_vault_contents_never_reach_a_public_caller(public_pillar):
    server, port = public_pillar
    status, body = await _get(port, "/g/vault")
    assert status == 404
    assert "VAULT" not in body.upper()
    assert "ITEMS" not in body.upper()


# ------------------------------------------------------------------
# Key-possession auth must not accept a self-signed proof
# ------------------------------------------------------------------

async def test_self_signed_proof_cannot_mint_a_session(public_pillar):
    """The expected public key and context were read out of the caller's own
    proof, making both binding checks tautologies: any freshly generated
    keypair authenticated as anybody."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from crypto.zkp import SchnorrZKP

    server, _ = public_pillar
    attacker = Ed25519PrivateKey.generate()
    proof = SchnorrZKP.prove(attacker, context="anything-i-like")

    body, _sig = await server.respond("/auth/zkp-verify\t" + json.dumps(proof))
    assert "session id" not in body.lower(), f"a session was minted: {body[:300]}"


# ------------------------------------------------------------------
# Key-possession auth, independent of transport gating
# ------------------------------------------------------------------

@pytest.fixture
async def private_pillar(tmp_path, monkeypatch):
    """A Pillar that is NOT public: the route gate above does not apply, so
    these tests exercise the authentication itself."""
    monkeypatch.setattr("core.config.CONFIG_FILE", tmp_path / ".refinet" / "config.json")
    monkeypatch.setattr("core.config.GOPHER_ROOT", tmp_path / "gopherroot")
    (tmp_path / "gopherroot").mkdir()
    server = GopherServer(host="127.0.0.1", port=0, hostname="localhost")
    server.public_mode = False
    return server


async def _challenge(server) -> str:
    import re
    body, _ = await server.respond("/auth/zkp-challenge")
    m = re.search(r"Context:\s*([0-9a-f]{32})", body)
    assert m, f"no challenge issued: {body[:300]}"
    return m.group(1)


async def test_a_stranger_key_is_refused_even_on_a_private_pillar(private_pillar):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from crypto.zkp import SchnorrZKP

    context = await _challenge(private_pillar)
    attacker = Ed25519PrivateKey.generate()
    proof = SchnorrZKP.prove(attacker, context=context)

    body, _ = await private_pillar.respond("/auth/zkp-verify\t" + json.dumps(proof))
    assert "session id" not in body.lower(), f"stranger authenticated: {body[:300]}"


async def test_a_caller_chosen_context_is_refused(private_pillar):
    """The whole bypass was that the caller supplied the context."""
    from crypto.zkp import SchnorrZKP
    proof = SchnorrZKP.prove(private_pillar.private_key, context="i-made-this-up")
    body, _ = await private_pillar.respond("/auth/zkp-verify\t" + json.dumps(proof))
    assert "session id" not in body.lower()
    assert "challenge" in body.lower()


async def test_the_operator_key_authenticates_with_a_real_challenge(private_pillar):
    from crypto.zkp import SchnorrZKP
    context = await _challenge(private_pillar)
    proof = SchnorrZKP.prove(private_pillar.private_key, context=context)
    body, _ = await private_pillar.respond("/auth/zkp-verify\t" + json.dumps(proof))
    assert "session id" in body.lower(), f"the operator could not authenticate: {body[:300]}"


async def test_a_challenge_cannot_be_replayed(private_pillar):
    from crypto.zkp import SchnorrZKP
    context = await _challenge(private_pillar)
    proof = SchnorrZKP.prove(private_pillar.private_key, context=context)

    first, _ = await private_pillar.respond("/auth/zkp-verify\t" + json.dumps(proof))
    assert "session id" in first.lower()

    replay, _ = await private_pillar.respond("/auth/zkp-verify\t" + json.dumps(proof))
    assert "session id" not in replay.lower(), "a spent challenge was accepted again"
