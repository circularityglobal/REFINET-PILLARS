import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  canonicalJson, compareCodePoints, createPillarClient, formatRefi, gopherText,
  normalizeDomain, stakeStatus, verifyAnswer, verifyWellKnown,
} from "../src/index.js";

// Signed by the Python Pillar (crypto/wellknown.py, crypto/signing.py)
const fx = JSON.parse(readFileSync(new URL("./python-signed.json", import.meta.url), "utf8"));

test("a Python-signed domain proof verifies", async () => {
  const r = await verifyWellKnown(fx.well_known, { pid: fx.pid, domain: "pillar.example.com" });
  assert.deepEqual(r, { valid: true, reason: "valid", pid: fx.pid });
});

test("linked domains, including non-ASCII ones, are claimed", async () => {
  assert.equal((await verifyWellKnown(fx.well_known, { domain: "example.com" })).valid, true);
  assert.equal((await verifyWellKnown(fx.well_known, { domain: "ünicode.example" })).valid, true);
  const r = await verifyWellKnown(fx.well_known, { domain: "other.com" });
  assert.equal(r.valid, false);
  assert.match(r.reason, /does not claim/);
});

test("a tampered domain proof is refused", async () => {
  const forged = structuredClone(fx.well_known);
  forged.endpoints.gopher = "gopher://evil.example:7070";
  assert.equal((await verifyWellKnown(forged)).reason, "signature does not verify");
  assert.equal((await verifyWellKnown(fx.well_known, { pid: "f".repeat(64) })).reason, "document names a different PID");
  assert.equal((await verifyWellKnown({ schema: "nope" })).valid, false);
});

test("a Python-signed gateway answer verifies, envelope included", async () => {
  const r = await verifyAnswer(fx.answer.body, fx.answer.headers);
  assert.equal(r.valid, true);
  assert.equal(r.envelopeValid, true);
  assert.equal(r.pid, fx.pid);
  assert.equal(r.selector, "/status.json");
});

test("an answer replayed for another selector fails the envelope", async () => {
  const headers = { ...fx.answer.headers, "X-Refinet-Selector": "/other" };
  const r = await verifyAnswer(fx.answer.body, headers);
  assert.equal(r.bodySignatureValid, true);
  assert.equal(r.envelopeValid, false);
  assert.equal(r.valid, false);
});

test("an answer stripped of its envelope is a downgrade, not a pass", async () => {
  // The signature fields travel as detached headers: a proxy or CDN can drop
  // two of them and leave the body-only signature, which binds no selector.
  const { "X-Refinet-V": _v, "X-Refinet-Sig1": _s, ...stripped } = fx.answer.headers;
  const r = await verifyAnswer(fx.answer.body, stripped);
  assert.equal(r.bodySignatureValid, true);
  assert.equal(r.envelopeValid, null);
  assert.equal(r.valid, false);
});

test("the client refuses an answer signed for another selector", async () => {
  const fakeFetch = async () => new Response(fx.answer.body, { headers: fx.answer.headers });
  const client = createPillarClient("https://pillar.example.com", { fetch: fakeFetch });
  await assert.rejects(client.get("/some/other/thing.json"),
    /Asked for \/some\/other\/thing.json, got an answer signed for \/status.json/);
});

test("a stale domain proof can be refused by age", async () => {
  assert.equal((await verifyWellKnown(fx.well_known, { maxAgeSec: 60 })).valid, false);
  assert.equal((await verifyWellKnown(fx.well_known, { maxAgeSec: 10 ** 12 })).valid, true);
});

test("an altered body fails", async () => {
  const r = await verifyAnswer(fx.answer.body.replace("héllo", "hello"), fx.answer.headers);
  assert.equal(r.valid, false);
});

test("client verifies, unwraps JSON and pins the PID", async () => {
  const fakeFetch = async (url) => {
    assert.equal(url, "https://pillar.example.com/g/status.json");
    return new Response(fx.answer.body, { headers: fx.answer.headers });
  };
  const client = createPillarClient("https://pillar.example.com/", { pid: fx.pid, fetch: fakeFetch });
  const status = await client.json("/status.json");
  assert.equal(status.pid, fx.pid);

  const wrongPid = createPillarClient("https://pillar.example.com", { pid: "a".repeat(64), fetch: fakeFetch });
  await assert.rejects(wrongPid.get("/status.json"), /not a{64}/);

  const tampered = async () => new Response(fx.answer.body + " ", { headers: fx.answer.headers });
  await assert.rejects(createPillarClient("https://p.example", { fetch: tampered }).get("/status.json"), /does not verify/);
});

test("stakeStatus decodes PillarStaking answers", async () => {
  const w = (n) => BigInt(n).toString(16).padStart(64, "0");
  const endpoint = Buffer.from("pillar.example.com").toString("hex").padEnd(64, "0");
  const answers = {
    "5c36901c": w(1),
    "63ea4ab2": "0".repeat(24) + "ab".repeat(20),
    "ab091871": w(32) + w(18) + endpoint,
    "07177c9c": w(100_001n * 10n ** 18n),
  };
  const fakeFetch = async (_url, init) => {
    const { params } = JSON.parse(init.body);
    return new Response(JSON.stringify({ result: "0x" + answers[params[0].data.slice(2, 10)] }));
  };
  const s = await stakeStatus("0x" + "11".repeat(20), fx.pid, { fetch: fakeFetch });
  assert.deepEqual(s, {
    active: true, registered: true, operator: "0x" + "ab".repeat(20),
    endpoint: "pillar.example.com", stakeUnits: 100_001n * 10n ** 18n,
  });
  await assert.rejects(stakeStatus("0x11", "nope", { fetch: fakeFetch }), /not a PID/);
});

test("helpers", () => {
  assert.equal(canonicalJson({ b: 1, a: [true, null, "é"] }), '{"a":[true,null,"é"],"b":1}');
  // Python sorts keys by code point; JS's default sort would put "\u{10000}"
  // (a surrogate pair) before "\uffff" and hash a different document.
  assert.equal(canonicalJson({ "\uffff": 1, "\u{10000}": 2 }), '{"\uffff":1,"\u{10000}":2}');
  assert.ok(compareCodePoints("\uffff", "\u{10000}") < 0);
  assert.equal(normalizeDomain("https://Pillar.Example.com/x"), "pillar.example.com");
  assert.equal(gopherText('{"a":1}\r\n.\r\n'), '{"a":1}');
  assert.equal(formatRefi(100_000n * 10n ** 18n), "100,000");
  assert.equal(formatRefi(99_999_500_000_000_000_000_000n), "99,999.5");
});
