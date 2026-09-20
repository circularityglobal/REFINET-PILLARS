"""/.well-known/refinet.json: build, verify, and what it refuses."""

import copy

import pytest

from crypto.pid import generate_pid, get_private_key
from crypto.wellknown import (
    build_well_known, gopher_endpoint, is_valid_domain, normalize_domain,
    verify_well_known,
)

CONFIG = {
    "public_domain": "Pillar.Example.com",
    "linked_domains": ["example.com", "https://App.Example.com/"],
    "port": 7070,
    "http_gateway_enabled": True,
    "staking_chain_id": 50,
    "staking_contracts": ["0x" + "11" * 20],
}


@pytest.fixture
def pillar():
    pid = generate_pid()
    return pid, get_private_key(pid)


def test_round_trip(pillar):
    pid, key = pillar
    doc = build_well_known(pid, key, CONFIG)
    assert doc["schema"] == "refinet-pillar/1"
    assert doc["domain"] == "pillar.example.com"
    assert doc["linked_domains"] == ["app.example.com", "example.com"]
    assert doc["endpoints"] == {"gopher": "gopher://pillar.example.com:7070",
                                "http": "https://pillar.example.com"}
    assert doc["staking"] == {"chain_id": 50, "contracts": CONFIG["staking_contracts"]}
    assert verify_well_known(doc, expected_pid=pid["pid"],
                             expected_domain="pillar.example.com") == (True, "valid")


def test_linked_domain_is_claimed(pillar):
    pid, key = pillar
    doc = build_well_known(pid, key, CONFIG)
    assert verify_well_known(doc, expected_domain="example.com")[0]
    ok, why = verify_well_known(doc, expected_domain="other.com")
    assert not ok and "does not claim" in why


def test_tampering_breaks_the_signature(pillar):
    pid, key = pillar
    doc = build_well_known(pid, key, CONFIG)
    forged = copy.deepcopy(doc)
    forged["endpoints"]["gopher"] = "gopher://evil.example:7070"
    assert verify_well_known(forged) == (False, "signature does not verify")


def test_foreign_key_and_pid_are_refused(pillar):
    pid, key = pillar
    doc = build_well_known(pid, key, CONFIG)
    other = generate_pid()
    assert verify_well_known(doc, expected_pid=other["pid"])[1] == "document names a different PID"
    swapped = dict(doc, public_key=other["public_key"])
    assert verify_well_known(swapped)[1] == "public key does not hash to pid"


def test_malformed_documents(pillar):
    assert not verify_well_known({})[0]
    assert not verify_well_known({"schema": "refinet-pillar/1"})[0]
    assert not verify_well_known("nope")[0]


def test_no_http_endpoint_without_gateway_or_domain(pillar):
    pid, key = pillar
    doc = build_well_known(pid, key, {"hostname": "10.0.0.5", "port": 7070})
    assert doc["domain"] == ""
    assert doc["endpoints"] == {"gopher": "gopher://10.0.0.5:7070"}
    doc = build_well_known(pid, key, dict(CONFIG, http_gateway_enabled=False))
    assert "http" not in doc["endpoints"]


def test_gopher_endpoint(pillar):
    pid, key = pillar
    doc = build_well_known(pid, key, CONFIG)
    assert gopher_endpoint(doc) == ("pillar.example.com", 7070)
    assert gopher_endpoint({"endpoints": {}}) is None


@pytest.mark.parametrize("raw,norm", [
    ("Pillars.Google.com", "pillars.google.com"),
    ("https://pillars.google.com/path", "pillars.google.com"),
    ("pillar.example.com.", "pillar.example.com"),
])
def test_normalize(raw, norm):
    assert normalize_domain(raw) == norm


@pytest.mark.parametrize("value,ok", [
    ("pillars.google.com", True),
    ("a.b", True),
    ("localhost", False),
    ("10.0.0.5", False),
    ("under_score.com", False),
    ("-lead.com", False),
    ("", False),
    ("a" * 64 + ".com", False),
])
def test_is_valid_domain(value, ok):
    assert is_valid_domain(value) is ok
