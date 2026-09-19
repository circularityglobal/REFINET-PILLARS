"""The response trailer stays backwards compatible while gaining an envelope (F9)."""

import time

import pytest

from crypto.pid import generate_pid, get_private_key
from crypto.signing import (
    SIG_BEGIN, build_signature_trailer, verify_response_block, verify_signature,
    hash_content,
)


@pytest.fixture
def signed():
    pid_data = generate_pid()
    key = get_private_key(pid_data)
    body = "iHello\tfake\t(NULL)\t0\r\n.\r\n"
    now = int(time.time())
    trailer = build_signature_trailer(
        body.encode(), key, pid_data["pid"], pid_data["public_key"], "/about", now)
    return pid_data, body, now, body + trailer


class TestLegacyCompatibility:
    def test_legacy_fields_are_present_and_first(self, signed):
        _, _, _, text = signed
        block = text.split(SIG_BEGIN)[1]
        order = [line.split(":", 1)[0] for line in block.strip().splitlines()
                 if ":" in line and not line.startswith("---")]
        assert order[:4] == ["pid", "pubkey", "sig", "hash"]

    def test_sig_still_verifies_over_the_raw_body(self, signed):
        pid_data, body, _, text = signed
        fields = dict(
            line.split(":", 1) for line in text.split(SIG_BEGIN)[1].splitlines()
            if ":" in line and not line.startswith("---")
        )
        assert verify_signature(body.encode(), fields["sig"].strip(),
                                pid_data["public_key"])
        assert fields["hash"].strip() == hash_content(body.encode())

    def test_block_still_comes_after_the_body(self, signed):
        _, body, _, text = signed
        assert text.startswith(body)


class TestEnvelopeSignature:
    def test_both_signatures_verify(self, signed):
        _, _, now, text = signed
        result = verify_response_block(text)
        assert result["valid"]
        assert result["legacy_valid"] and result["envelope_valid"]
        assert result["selector"] == "/about"
        assert int(result["time"]) == now

    def test_body_tampering_fails_everything(self, signed):
        _, _, _, text = signed
        result = verify_response_block(text.replace("Hello", "Hullo"))
        assert not result["valid"]
        assert not result["legacy_valid"] and not result["hash_valid"]

    def test_same_bytes_replayed_under_another_selector_fail(self, signed):
        _, _, _, text = signed
        result = verify_response_block(text.replace("selector:/about", "selector:/evil"))
        assert result["legacy_valid"]
        assert result["envelope_valid"] is False
        assert not result["valid"]

    def test_pre_v1_block_is_still_accepted(self, signed):
        """A Pillar running an older release signs only the body."""
        _, _, _, text = signed
        legacy = "\r\n".join(
            line for line in text.split("\r\n")
            if not line.startswith(("v:", "selector:", "time:", "sig1:"))
        )
        result = verify_response_block(legacy)
        assert result["valid"]
        assert result["envelope_valid"] is None

    def test_unsigned_text_is_reported(self):
        assert verify_response_block("just a body")["reason"] == "unsigned"
