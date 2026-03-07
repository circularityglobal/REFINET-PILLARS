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

Numeric chain IDs are also accepted in place of names.

---

## Notes

- **`/auth/challenge`**: The `chainId` field is optional. If omitted, defaults to `1` (Ethereum mainnet). The Browser always sends `address:chainId`.
- **`/auth/verify`**: The message field is always base64-encoded by the Browser (SIWE messages contain newlines). Plain text is accepted as a fallback for direct Gopher clients.
- **`/rpc/broadcast`**: When using the colon format (Browser), chain_id is extracted from the signed transaction bytes (EIP-155/EIP-1559/EIP-2930). When using the pipe format (legacy), chain_id is explicit.
- **`/rpc/gas`**: JSON is tried first. Falls back to pipe-delimited if JSON parsing fails.
- **Pipe vs colon detection**: If the query contains a `|` character, pipe format is assumed. Otherwise, colon format is assumed. This works because hex values, addresses, and chain names never contain `|`.
