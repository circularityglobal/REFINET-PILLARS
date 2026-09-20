# @refinet/pillar

Pair your app with a [REFInet Pillar](https://github.com/circularityglobal/REFINET-PILLARS):
deploy it next to your app, prove your domain, stake for it on XDC, and verify
everything it signs. No dependencies; Node 20+ or any modern browser.

## Before you go live

```bash
npx @refinet/pillar init --app-domain example.com --pillar-domain pillar.example.com
npx @refinet/pillar deploy --ssh root@<vps-ip>
npx @refinet/pillar bind --ssh root@<vps-ip> --address 0xYourWallet
npx @refinet/pillar stake
npx @refinet/pillar doctor
```

| Command | What it does |
|---|---|
| `init` | Writes `refinet.config.json`; makes your app serve `/.well-known/refinet.json` from the Pillar (`vercel.json`, `_redirects` or `netlify.toml`); adds `npm run pillar:doctor` |
| `deploy` | Installs the Pillar on a VPS over SSH, behind Caddy with TLS for your Pillar domain |
| `bind` | Binds your staking wallet to the Pillar: prints the message to sign, sends back the signature |
| `stake` | Prints the approve + `register` transactions for 100,000 REFI on XDC |
| `doctor` | Checks DNS, both domain proofs, signed gateway answers, the stake, the on-chain endpoint and the binding. Exits 1 until everything passes |

The full walkthrough, including running Pillars on your own infrastructure, is
[docs/OPERATORS.md](https://github.com/circularityglobal/REFINET-PILLARS/blob/main/docs/OPERATORS.md).

## Library

```js
import { createPillarClient, verifyWellKnown, fetchWellKnown, stakeStatus } from "@refinet/pillar";

// Every answer is verified against the Pillar's Ed25519 key before you see it
const pillar = createPillarClient("https://pillar.example.com", { pid: PILLAR_ID });
const status = await pillar.json("/status.json");

// Does example.com claim this Pillar?
const doc = await fetchWellKnown("example.com");
const { valid } = await verifyWellKnown(doc, { pid: PILLAR_ID, domain: "example.com" });

// Is it staked?
const s = await stakeStatus(STAKING_CONTRACT, PILLAR_ID);   // { active, operator, endpoint, stakeUnits }
```

| Export | |
|---|---|
| `createPillarClient(url, { pid })` | `get(selector)`, `json(selector)`, `wellKnown()` — each answer verified, optionally pinned to one Pillar ID |
| `verifyAnswer(body, headers)` | Checks `X-Refinet-*` signatures on a gateway answer |
| `verifyWellKnown(doc, { pid, domain })` | Checks a domain proof |
| `fetchWellKnown(domain)` | `GET https://<domain>/.well-known/refinet.json` |
| `stakeStatus(contract, pid, { rpc })` | Reads PillarStaking on XDC |

License: AGPL-3.0-or-later.
