# REFInet Pillar — Wire Format Reference

All Type 7 query routes receive input as: `selector\tquery\r\n`

The query portion uses the delimiter noted below. Routes that support dual formats
accept either delimiter — the Pillar auto-detects based on the presence of `|` (pipe)
vs `:` (colon) in the query.

---

## Type 7 Search Routes

| Route | Delimiter | Field Order | Example |
|---|---|---|---|
| `/auth/challenge` | `:` | `address:chainId` | `0xd8dA...96045:1` |
| `/auth/challenge` | (plain) | `address` | `0xd8dA...96045` |
| `/auth/verify` | `\|` | `address\|signature\|base64(message)` | `0xABC...\|0x1234...\|SGVsbG8=` |
| `/rpc/balance` | `\|` | `chain_id\|0xAddress` | `1\|0xd8dA...96045` |
| `/rpc/balance` | `:` | `address:chainName` | `0xd8dA...96045:ethereum` |
| `/rpc/token` | `\|` | `chain_id\|tokenAddress\|walletAddress` | `1\|0xA0b8...\|0xd8dA...` |
| `/rpc/token` | `:` | `tokenAddress:ownerAddress:chainName` | `0xA0b8...:0xd8dA...:ethereum` |
| `/rpc/gas` | JSON | `{"to","value","data","chain"}` | `{"to":"0x...","chain":"ethereum"}` |
| `/rpc/gas` | `\|` | `chain_id\|to_address\|value_wei` | `1\|0xd8dA...\|1000000000` |
| `/rpc/broadcast` | `:` | `sessionToken:signedTxHex` | `abc...64chars:02f8...` |
| `/rpc/broadcast` | `\|` | `session_id\|chain_id\|signed_tx_hex` | `abc...\|1\|02f8...` |
| `/search` | (plain) | `search_query` | `uniswap` |
| `/proof/receipt` | JSON | `{"receipt":{...},"public_key":"<64 hex>"}` | see below |

---

## Chain Name Resolution

When a route accepts a `chainName` field, the following lowercase names are recognized:

| Name | Chain ID |
|------|----------|
| `ethereum` | 1 |
| `polygon` | 137 |
| `arbitrum` | 42161 |
| `base` | 8453 |
| `sepolia` | 11155111 |
| `avalanche` | 43114 |
| `fuji` | 43113 |
| `base-sepolia` | 84532 |
| `xdc` | 50 |
| `apothem` | 51 |

An operator can add more in `~/.refinet/chains.json` without waiting for a
release; those names resolve here too.

Numeric chain IDs are also accepted in place of names.

---

## Signed formats

These are specified in the whitepaper; this file only points at them so the
wire reference stays one page.

| Format | Where | What it signs |
|---|---|---|
| Response trailer | whitepaper §5.1 | `sig` over the raw body (unchanged); `sig1` over `REFINET-RESPONSE-v1 \|\| pid \n selector \n time \n hash`, so a signed answer cannot be replayed for another request |
| Wallet binding | whitepaper §5.15 | An EIP-4361 message whose statement is `I bind this wallet to REFINET Pillar <pid> as its <deployer\|operator>`. It is never a sign-in message, and a sign-in message is never accepted as one |
| Identity document | `/identity/v3.json` | `REFINET-IDENTITY-v3 \|\| SHA-256(canonical JSON)`. `/identity.json` continues to serve schema 2 unchanged |
| Witness / receipt | whitepaper §7 | `REFINET-WITNESS-v1 \|\| pid \n resource \n fetched_at \n hash \n status`. Submitted to `/proof/receipt` by the **requester**, never minted by the server |
| Mesh announcement | whitepaper §5.5 | `REFINET-ANNOUNCE-v1 \|\| pid \n hostname \n port \n timestamp` |

Canonical JSON is `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`, UTF-8.

---

## Notes

- **`/proof/receipt`**: the receipt is the §3.3 attestation object signed by the requester's Ed25519 key, with that key alongside it. Re-submitting the same receipt is a no-op (`RECEIPT ALREADY ON FILE`), and intake is capped per requester and per day.
- **`/auth/challenge`**: The `chainId` field is optional. If omitted, defaults to `1` (Ethereum mainnet). The Browser always sends `address:chainId`.
- **`/auth/verify`**: The message field is always base64-encoded by the Browser (SIWE messages contain newlines). Plain text is accepted as a fallback for direct Gopher clients.
- **`/rpc/broadcast`**: When using the colon format (Browser), chain_id is extracted from the signed transaction bytes (EIP-155/EIP-1559/EIP-2930). When using the pipe format (legacy), chain_id is explicit.
- **`/rpc/gas`**: JSON is tried first. Falls back to pipe-delimited if JSON parsing fails.
- **Pipe vs colon detection**: If the query contains a `|` character, pipe format is assumed. Otherwise, colon format is assumed. This works because hex values, addresses, and chain names never contain `|`.
