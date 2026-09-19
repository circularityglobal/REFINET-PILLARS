# The TradeSphere bridge: what Pillars now implement

**For:** the TradeSphere engineering team.
**From:** REFINET Pillars, release 0.5.0.
**Answers:** the audit of `d13a729` ("REFINET Pillars: what to change so TradeSphere can build on them").

All twenty findings are addressed. This document records **only the places
where we deviated from the proposal**, and what you need to write your
verifier against. Everything not listed here matches the proposal as written.

A fixture is committed at `tests/fixtures/pillar-vectors.json`, produced by
`python3 -m tests.vectors --write` and verified by `tests/test_vectors.py`.
Copy it into your repository and pin it from
`apps/api/test/unit/pillarVectors.test.ts`.

## The deviations

Every one of these exists for the same reason: a Pillar in the field, or a
browser extension already installed, must not break when its operator upgrades.

### 1. The envelope signature is `sig1`, not `sig` (§3.3)

The proposal redefines `sig:` in the response trailer as the signature over
the envelope. `sig:` currently signs the raw body, and both the bundled
extension (`background.js`) and released REFInet Browser builds verify it that
way, so redefining it would have broken every existing verifier.

The four original lines keep their meaning, and the envelope is additive:

```
---BEGIN REFINET SIGNATURE---
pid:<64 hex>
pubkey:<64 hex>
sig:<Ed25519 over the raw body>          <- unchanged
hash:<SHA-256 of the body>               <- unchanged
v:1
selector:<the selector answered>
time:<unix seconds>
sig1:<Ed25519 over "REFINET-RESPONSE-v1" || pid \n selector \n time \n hash>
---END REFINET SIGNATURE---
```

**Verify `sig1`.** It is exactly the §3.3 signature; only the field name
differs. A block with no `v:1` line comes from a Pillar older than 0.5.0.
The same fields (`v`, `selector`, `time`, `sig1`) are added to the WebSocket
response envelope.

The preimage is the domain string followed directly by the newline-joined
fields, with no separator after the domain. `envelope_preimage_hex` in the
`response_block` vector pins the exact bytes.

### 2. Identity v3 is served at `/identity/v3.json`

`/identity.json` still serves the schema-2 document, byte-compatible with what
it served before. The v3 document (§3.2, with `bindings`, `authority` and
`document_signature`) is at **`/identity/v3.json`**. Fetch that one.

`bindings` lists only §3.1 bindings, oldest first. A Pillar whose only binding
predates 0.5.0 serves an empty list until its operator re-signs with their
wallet (a `rebind`, which cannot happen silently). That is the correct answer
for stage 2: link it only when a §3.1 binding exists.

`document_signature` is Ed25519 over `"REFINET-IDENTITY-v3" || SHA-256(canonical JSON)`,
where canonical JSON is `sort_keys=True, separators=(",", ":"), ensure_ascii=False`,
UTF-8, over the document without `document_signature`.

### 3. Binding chain ids are not restricted to the gateway's table

The proposal asks that a binding's chain id be validated against the chains the
Pillar knows. An EOA binding accepts any positive chain id, so an operator on a
network we have not shipped can still bind. A known chain **is** required for
the EIP-1271 path, since that check is an on-chain call. Your side should
refuse a binding whose `chain_id` is not the company's network — that check
belongs to you.

### 4. Namespaced selectors are opt-in

`/holes/<slug>` keeps working and stays the default; `/holes/<pid16>/<slug>` is
available through `hole create --namespaced`. Flipping the default would break
every existing link and gophermap. Verification rejects a namespaced selector
whose namespace is not the record's own PID.

### 5. The bridge's Origin rules default to today's behaviour

`websocket_extension_ids` and `websocket_require_origin` exist in
`config.json`, and both default off, because an unpacked extension has a random
id and a hard default would lock operators out of their own Pillar. This does
not affect the bridge.

### 6. The release tarball is still tracked

`gopherroot/holes/refinet/products/pillar/download/pillar-latest.tar.gz` stays
in git until a release asset exists to fetch instead; removing it now would
break the download link the gophermap publishes. The committed `__pycache__`
files and the local editor settings file are gone.

## What is ready for you now

| Stage | What Pillars provide |
|---|---|
| **2 · Link a Pillar to a company** | F1–F5 are done. Binding messages are §3.1 exactly. `/identity/v3.json` serves the v3 document. `link_pillar` can be written against the `binding_identity_v3` vector |
| **3 · Pillars as a second witness** | The §3.3 attestation format is implemented in `crypto/attestation.py` and pinned by the `witness_attestation` vector, so your verifier can be written now. The `/witness/<url-hash>` route and the fetcher wait on your published manifest — send us its shape and we will add them |
| **4 · Rewards** | F10 and F12 are done ahead of the token phase: a service proof is a requester-signed receipt (`/proof/receipt`), and every amount is an integer in base units with its asset, never a float |

### 7. Receipt intake is idempotent and capped

`/proof/receipt` derives its `proof_id` from the receipt's signature, so
submitting the same receipt twice stores one row and answers
`RECEIPT ALREADY ON FILE` rather than `RECEIPT ACCEPTED`. Both are success.

Intake is also capped per requester per day (500) and per Pillar per day
(5000), and a `resource` longer than 512 characters is refused. `service_proofs`
is append-only and undeletable, so unbounded intake would be the same disk-fill
your audit flagged in F11. If phase 3 needs higher volume, these are constants
in `core/gopher_server.py` and we should agree on the numbers together.

## Vectors

`tests/fixtures/pillar-vectors.json` contains:

- `registry_record` — a signed gopherhole record with its `signing_payload`
- `response_block` — a full response with the v1 trailer, plus
  `envelope_preimage_hex`
- `binding_identity_v3` — a §3.1 binding (message, wallet signature, Pillar
  counter-signature) and the identity v3 document that publishes it
- `witness_attestation` — a §3.3 attestation with the signer's public key

The keys are fixed test keys derived from constants in `tests/vectors.py`. They
must never hold funds.

## Notes for your verifier

- `pid == SHA-256(public_key)` is now checked everywhere a record claims a PID.
  Check it too: it is what stops a record claiming a PID whose key it lacks.
- A nonce is spent on first use, successful or not. If you re-drive a binding
  after a failure, request a new challenge.
- A binding challenge expires in 10 minutes; a login challenge in 15.
- The SIWE `domain` line is now the Pillar's own authority (its hostname, or
  `<pid>.pillar.refinet` when it has none), and `URI`/`Resources` carry the full
  64-hex PID. Wallets that warn on a domain/origin mismatch may show that
  warning; the message text is what is signed, and it is what you verify.
