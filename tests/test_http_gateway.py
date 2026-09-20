"""HTTP gateway: signed Gopher answers over HTTP, and what it refuses."""

import asyncio
import json

import pytest

from core.gopher_server import GopherServer
from crypto.signing import SIG_BEGIN, SIG_END, verify_response_block
from crypto.wellknown import verify_well_known
from integration.http_gateway import HTTPGateway, selector_from_path

APP = "https://app.example.com"


@pytest.fixture
async def gateway(tmp_path, monkeypatch):
    monkeypatch.setattr("core.config.CONFIG_FILE", tmp_path / ".refinet" / "config.json")
    monkeypatch.setattr("core.config.GOPHER_ROOT", tmp_path / "gopherroot")
    (tmp_path / "gopherroot").mkdir()
    server = GopherServer(host="127.0.0.1", port=0, hostname="localhost")
    config = {"public_domain": "pillar.example.com", "port": 7070,
              "http_gateway_enabled": True}
    gw = HTTPGateway(server, cors_origins=[APP], config_loader=lambda: config)
    http = await asyncio.start_server(gw.handle, "127.0.0.1", 0)
    gopher = await asyncio.start_server(server.handle_client, "127.0.0.1", 0)
    yield server, http.sockets[0].getsockname()[1], gopher.sockets[0].getsockname()[1], gw
    for s in (http, gopher):
        s.close()
        await s.wait_closed()


async def _http(port, request: str):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(request.encode("latin-1"))
    await writer.drain()
    raw = await asyncio.wait_for(reader.read(), timeout=10)
    writer.close()
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split()[1])
    headers = {}
    for line in lines[1:]:
        k, v = line.split(":", 1)
        headers[k.strip().lower()] = v.strip()
    return status, headers, body


async def _get(port, path, extra=""):
    return await _http(port, f"GET {path} HTTP/1.1\r\nHost: x\r\n{extra}\r\n")


def _trailer_from_headers(h):
    return (f"\r\n{SIG_BEGIN}\r\n"
            f"pid:{h['x-refinet-pid']}\r\npubkey:{h['x-refinet-pubkey']}\r\n"
            f"sig:{h['x-refinet-sig']}\r\nhash:{h['x-refinet-hash']}\r\n"
            f"v:{h['x-refinet-v']}\r\nselector:{h['x-refinet-selector']}\r\n"
            f"time:{h['x-refinet-time']}\r\nsig1:{h['x-refinet-sig1']}\r\n{SIG_END}\r\n")


async def test_selector_answer_verifies_like_a_gopher_answer(gateway):
    server, port, _, gw = gateway
    status, h, body = await _get(port, "/g/status.json")
    assert status == 200
    assert h["content-type"].startswith("application/json")
    assert h["x-refinet-selector"] == "/status.json"
    result = verify_response_block(body.decode("utf-8") + _trailer_from_headers(h))
    assert result["valid"] and result["envelope_valid"]
    assert result["pid"] == server.pid_data["pid"]
    assert json.loads(body.decode().rstrip().rstrip(".").rstrip())["pid"] == server.pid_data["pid"]


async def test_same_body_as_the_gopher_listener(gateway):
    _, port, gport, gw = gateway
    _, _, body = await _get(port, "/g/pid")
    reader, writer = await asyncio.open_connection("127.0.0.1", gport)
    writer.write(b"/pid\r\n")
    await writer.drain()
    raw = (await asyncio.wait_for(reader.read(), timeout=10)).decode()
    writer.close()
    assert raw.split("\r\n" + SIG_BEGIN)[0] == body.decode()


async def test_root_selector(gateway):
    _, port, _, gw = gateway
    status, h, _ = await _get(port, "/g/")
    assert status == 200 and h["x-refinet-selector"] == "/"


async def test_well_known_is_signed_and_public(gateway):
    server, port, _, gw = gateway
    status, h, body = await _get(port, "/.well-known/refinet.json", "Origin: https://any.site\r\n")
    assert status == 200
    assert h["access-control-allow-origin"] == "*"
    doc = json.loads(body)
    assert verify_well_known(doc, expected_pid=server.pid_data["pid"],
                             expected_domain="pillar.example.com") == (True, "valid")


async def test_health(gateway):
    server, port, _, gw = gateway
    status, _, body = await _get(port, "/health")
    assert status == 200 and json.loads(body)["pid"] == server.pid_data["pid"]


async def test_cors_only_for_configured_origins(gateway):
    _, port, _, gw = gateway
    _, h, _ = await _get(port, "/g/pid", f"Origin: {APP}\r\n")
    assert h["access-control-allow-origin"] == APP
    assert "X-Refinet-Sig1" in h["access-control-expose-headers"]
    _, h, _ = await _get(port, "/g/pid", "Origin: https://evil.example\r\n")
    assert "access-control-allow-origin" not in h


async def test_preflight(gateway):
    _, port, _, gw = gateway
    status, h, _ = await _http(port, f"OPTIONS /g/pid HTTP/1.1\r\nOrigin: {APP}\r\n\r\n")
    assert status == 204
    assert h["access-control-allow-origin"] == APP
    assert "GET" in h["access-control-allow-methods"]


async def test_only_reads(gateway):
    _, port, _, gw = gateway
    status, h, _ = await _http(port, "POST /g/pid HTTP/1.1\r\nContent-Length: 0\r\n\r\n")
    assert status == 405 and "GET" in h["allow"]


async def test_head_has_no_body(gateway):
    _, port, _, gw = gateway
    status, h, body = await _http(port, "HEAD /g/pid HTTP/1.1\r\n\r\n")
    assert status == 200 and body == b"" and int(h["content-length"]) > 0


async def test_unknown_path_and_bad_selector(gateway):
    _, port, _, gw = gateway
    assert (await _get(port, "/index.html"))[0] == 404
    assert (await _get(port, "/g/pid%0d%0a/status.json"))[0] == 400
    assert (await _get(port, "/g/download/pillar-latest.tar.gz"))[0] == 404


async def test_rate_limited(gateway):
    server, port, _, gw = gateway
    gw.rate_limiter.max_requests = 1
    assert (await _get(port, "/health"))[0] == 200
    assert (await _get(port, "/health"))[0] == 429
    # The Gopher listener has its own budget; HTTP traffic never spends it
    assert server.rate_limiter.is_allowed("127.0.0.1")


async def test_forwarded_for_is_ignored_unless_trusted(gateway):
    _, port, _, gw = gateway
    gw.rate_limiter.max_requests = 2
    for _ in range(2):
        assert (await _get(port, "/health", "X-Forwarded-For: 9.9.9.9\r\n"))[0] == 200
    # Not trusted: every request is counted against the real peer anyway
    assert (await _get(port, "/health", "X-Forwarded-For: 8.8.8.8\r\n"))[0] == 429


async def test_spoofed_forwarded_for_neither_bypasses_nor_blocks(gateway):
    _, port, _, gw = gateway
    gw.trust_proxy = True
    gw.rate_limiter.max_requests = 2
    # A client rotating the header: our proxy appends the real address last,
    # so all of these are the same client and the limit still bites.
    codes = [(await _get(port, "/health", f"X-Forwarded-For: 9.9.9.{i}, 203.0.113.5\r\n"))[0]
             for i in range(5)]
    assert codes.count(429) >= 2, codes
    # And a victim named in the client-supplied part is not blocked
    assert gw.rate_limiter.is_allowed("9.9.9.1")


async def test_header_name_with_trailing_space_is_not_a_header(gateway):
    _, port, _, gw = gateway
    gw.trust_proxy = True
    gw.rate_limiter.max_requests = 1
    assert (await _get(port, "/health", "X-Forwarded-For : 9.9.9.9\r\n"))[0] == 200
    # It was ignored, so this counted against the real peer, not 9.9.9.9
    assert (await _get(port, "/health"))[0] == 429


async def test_non_ascii_selector_is_answered(gateway):
    _, port, _, gw = gateway
    status, h, _ = await _get(port, "/g/holes/%E4%B8%AD%E6%96%87")
    assert status == 200
    assert "%E4%B8%AD" in h["x-refinet-selector"].upper()


async def test_garbage_request_is_closed_quietly(gateway):
    _, port, _, gw = gateway
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b"\x00\x01\x02\r\n\r\n")
    await writer.drain()
    raw = await asyncio.wait_for(reader.read(), timeout=10)
    writer.close()
    assert raw.startswith(b"HTTP/1.1 400")


async def test_well_known_over_gopher(gateway):
    server, _, gport, gw = gateway
    reader, writer = await asyncio.open_connection("127.0.0.1", gport)
    writer.write(b"/.well-known/refinet.json\r\n")
    await writer.drain()
    raw = (await asyncio.wait_for(reader.read(), timeout=10)).decode()
    writer.close()
    from mesh.admission import parse_signed_json
    doc = parse_signed_json(raw)
    assert verify_well_known(doc, expected_pid=server.pid_data["pid"])[0]


@pytest.mark.parametrize("target,selector", [
    ("/g", ""),
    ("/g/", ""),
    ("/g/status.json", "/status.json"),
    ("/g/search?refinet", "/search?refinet"),
    ("/g/holes/my%20site", "/holes/my site"),
    ("/status.json", None),
    ("/gx/pid", None),
])
def test_selector_from_path(target, selector):
    assert selector_from_path(target) == selector
