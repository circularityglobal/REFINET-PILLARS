"""Chain discovery: the staking directory becomes verified peers."""

import socket

import pytest

from crypto.pid import generate_pid, get_private_key
from crypto.wellknown import build_well_known
from integration.websocket_bridge import BlockedDestination
from mesh import chain_discovery as cd
from mesh.staking import StakeStatus


def _pillar(domain):
    pid = generate_pid()
    doc = build_well_known(pid, get_private_key(pid),
                           {"public_domain": domain, "port": 7070})
    return pid["pid"], doc


class Reader:
    def __init__(self, entries):
        # pid -> (active, endpoint)
        self.entries = entries

    async def directory(self):
        return list(self.entries)

    async def status(self, pid):
        active, endpoint = self.entries[pid]
        return StakeStatus(pid=pid, active=active, operator="0x" + "ab" * 20, endpoint=endpoint)


async def test_discover_once_records_only_verified_active_peers():
    own_pid, _ = _pillar("me.example.com")
    good_pid, good_doc = _pillar("good.example.com")
    inactive_pid, inactive_doc = _pillar("idle.example.com")
    liar_pid, _ = _pillar("liar.example.com")
    _, someone_elses_doc = _pillar("liar.example.com")   # right domain, wrong key
    unreachable_pid, _ = _pillar("down.example.com")

    docs = {
        "good.example.com": good_doc,
        "idle.example.com": inactive_doc,
        "liar.example.com": someone_elses_doc,
    }

    async def fetch(domain):
        if domain not in docs:
            raise ConnectionRefusedError(domain)
        return docs[domain]

    reader = Reader({
        own_pid: (True, "me.example.com"),
        good_pid: (True, "good.example.com"),
        inactive_pid: (False, "idle.example.com"),
        liar_pid: (True, "liar.example.com"),
        unreachable_pid: (True, "down.example.com"),
    })
    recorded = []
    n = await cd.discover_once(own_pid, reader, fetch=fetch,
                               upsert=lambda **kw: recorded.append(kw))
    assert n == 1
    assert recorded[0]["pid"] == good_pid
    assert recorded[0]["hostname"] == "good.example.com"
    assert recorded[0]["port"] == 7070


async def test_gopher_host_must_be_the_verified_domain():
    pid = generate_pid()
    # Signed by the right key and claims the domain, but sends replication elsewhere
    doc = build_well_known(pid, get_private_key(pid), {
        "public_domain": "pillar.example.com", "hostname": "x", "port": 7070})
    doc_elsewhere = build_well_known(pid, get_private_key(pid), {
        "public_domain": "", "hostname": "10.0.0.5", "port": 7070,
        "linked_domains": ["pillar.example.com"]})

    async def fetch_ok(domain):
        return doc

    async def fetch_elsewhere(domain):
        return doc_elsewhere

    reader = Reader({pid["pid"]: (True, "pillar.example.com")})
    assert (await cd.discover_peer(pid["pid"], reader, fetch_ok))["hostname"] == "pillar.example.com"
    assert await cd.discover_peer(pid["pid"], reader, fetch_elsewhere) is None


async def test_no_endpoint_no_fetch():
    pid, _ = _pillar("x.example.com")

    async def fetch(domain):
        raise AssertionError("not fetched")

    assert await cd.discover_peer(pid, Reader({pid: (True, "")}), fetch) is None


async def test_fetch_refuses_non_domains():
    with pytest.raises(ValueError):
        await cd.fetch_well_known("localhost")
    with pytest.raises(ValueError):
        await cd.fetch_well_known("10.0.0.5")


async def test_fetch_refuses_private_addresses(monkeypatch):
    def fake_getaddrinfo(host, port, *a, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(BlockedDestination):
        await cd.fetch_well_known("internal.example.com")
