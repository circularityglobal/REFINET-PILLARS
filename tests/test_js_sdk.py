"""The npm SDK (sdk/js) verifies what this Pillar signs, freshly, every run."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from crypto.pid import generate_pid, get_private_key
from crypto.signing import build_signature_trailer
from crypto.wellknown import build_well_known
from integration.http_gateway import SIGNATURE_HEADERS, trailer_fields

SDK = Path(__file__).resolve().parent.parent / "sdk" / "js" / "src" / "index.js"

SCRIPT = """
import { verifyWellKnown, verifyAnswer } from %s;
const input = JSON.parse(process.argv[1]);
const wk = await verifyWellKnown(input.doc, { pid: input.pid, domain: "pillar.example.com" });
const ans = await verifyAnswer(input.body, input.headers);
console.log(JSON.stringify({ wellKnown: wk.valid, answer: ans.valid, envelope: ans.envelopeValid }));
"""


def _node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    major = int(subprocess.run([node, "-p", "process.versions.node.split('.')[0]"],
                               capture_output=True, text=True).stdout.strip() or 0)
    if major < 20:
        pytest.skip("the SDK needs Node >= 20")
    return node


def test_sdk_verifies_python_signatures():
    node = _node()
    pid = generate_pid()
    key = get_private_key(pid)
    doc = build_well_known(pid, key, {
        "public_domain": "pillar.example.com", "linked_domains": ["exämple.com"],
        "port": 7070, "http_gateway_enabled": True})
    body = json.dumps({"pid": pid["pid"], "note": "naïve   \"q\""}, indent=2,
                      ensure_ascii=False) + "\r\n.\r\n"
    trailer = build_signature_trailer(body.encode(), key, pid["pid"], pid["public_key"],
                                      "/status.json", 1789846737)
    headers = {SIGNATURE_HEADERS[k]: v for k, v in trailer_fields(trailer).items()}
    payload = json.dumps({"pid": pid["pid"], "doc": doc, "body": body, "headers": headers},
                         ensure_ascii=False)
    out = subprocess.run(
        [node, "--input-type=module", "-e", SCRIPT % json.dumps(SDK.as_uri()), payload],
        capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == {"wellKnown": True, "answer": True, "envelope": True}
