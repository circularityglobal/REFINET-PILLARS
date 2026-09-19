"""pillar-vectors.json is reproducible and every vector verifies on its own."""

import json

from core.gopherhole import verify_gopherhole_signature
from crypto.attestation import verify_witness
from crypto.signing import verify_response_block
from tests import vectors


def _fixture() -> dict:
    return json.loads(vectors.FIXTURE_PATH.read_text())


def test_fixture_matches_code_byte_for_byte():
    assert vectors.FIXTURE_PATH.read_text() == vectors.render(), (
        "pillar-vectors.json is stale: run python3 -m tests.vectors --write"
    )


def test_registry_vector_verifies():
    rec = _fixture()["registry_record"]
    assert verify_gopherhole_signature(rec)


def test_registry_vector_with_foreign_pid_fails():
    rec = dict(_fixture()["registry_record"])
    rec["pid"] = "0" * 64
    assert not verify_gopherhole_signature(rec)


def test_response_vector_verifies_both_signatures():
    v = _fixture()["response_block"]
    result = verify_response_block(v["response"])
    assert result["valid"] and result["legacy_valid"] and result["envelope_valid"]
    assert result["selector"] == v["selector"]
    assert int(result["time"]) == v["time"]


def test_response_vector_replayed_for_other_selector_fails_envelope():
    v = _fixture()["response_block"]
    forged = v["response"].replace(f"selector:{v['selector']}", "selector:/holes/other")
    result = verify_response_block(forged)
    assert result["legacy_valid"]          # the body signature alone cannot tell
    assert result["envelope_valid"] is False
    assert not result["valid"]


def test_witness_vector_verifies():
    v = _fixture()["witness_attestation"]
    ok, reason = verify_witness(v["attestation"], v["public_key"])
    assert ok, reason
    tampered = dict(v["attestation"], status="mismatch")
    assert not verify_witness(tampered, v["public_key"])[0]
