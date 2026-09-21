# Run a REFInet Pillar on your domain

**For:** founders adding a Pillar to their app before it goes live, and
organisations running Pillars on their own infrastructure.
**Covers:** release 0.6.0.

A Pillar is a server you run next to your app. It holds its own signing key,
answers on its own domain (for example `pillar.example.com`), and joins the
REFInet mesh once 100,000 REFI are staked for it on XDC. Your app gets a signed,
verifiable backend of its own; the network gets one more node it can check.

Three things are true of every admitted Pillar, and anyone can check each one:

```
pillar.example.com  --serves-->  Pillar ID  --bound to-->  your wallet  --staked-->  100,000 REFI
   (domain proof)                  (key)      (wallet signature)            (XDC contract)
```

---

## The fast path: add a Pillar to your app

You need: an app on its own domain (Vercel, Netlify, or anything that can proxy
one path), a small Linux VPS with SSH access, a wallet on XDC with 100,000 REFI
(and a little XDC for gas), and Node 20 or later.

```bash
cd your-app
npx @refinet/pillar init --app-domain example.com --pillar-domain pillar.example.com
```

> Until `@refinet/pillar` is published to npm, run it from a clone:
> `node /path/to/REFINET-PILLARS/sdk/js/bin/refinet-pillar.js init …`, and pass
> `--ref <branch>` to `deploy` while the installer is not yet on `main`.

`init` writes `refinet.config.json`, makes your app serve
`/.well-known/refinet.json` by proxying it from the Pillar (a rewrite in
`vercel.json`, or `_redirects` / `netlify.toml` on Netlify), and adds a
`pillar:doctor` script. Commit those changes.

1. **DNS.** At your registrar (Namecheap or any other), add an A record:
   `pillar` → your VPS's IP address.
2. **Deploy the Pillar.**
   ```bash
   npx @refinet/pillar deploy --ssh root@<vps-ip>
   ```
   This installs Docker if needed, starts the Pillar behind Caddy (which gets
   the TLS certificate), and prints the Pillar ID. The key is created on the
   VPS and never leaves it.
3. **Bind the wallet you will stake from.**
   ```bash
   npx @refinet/pillar bind --ssh root@<vps-ip> --address 0xYourWallet
   ```
   Sign the message it shows with that wallet (`personal_sign`) and paste the
   signature back. The binding is published at
   `https://pillar.example.com/g/identity/v3.json`.
4. **Stake.**
   ```bash
   npx @refinet/pillar stake
   ```
   prints the two transactions to send from the bound wallet: approve REFI,
   then `register(pillarId, 100000 REFI, "pillar.example.com")`.
5. **Check, then go live.**
   ```bash
   npm run pillar:doctor
   ```
   It verifies the DNS, the domain proof on both the Pillar and your app, that
   gateway answers are signed by your Pillar, the stake, the on-chain endpoint,
   and that the staking wallet is bound. It exits non-zero until all of them
   pass, so it can gate a deploy:
   ```json
   "scripts": { "prebuild": "refinet-pillar doctor" }
   ```

---

## Using the Pillar from your app

The Pillar's HTTP gateway serves every Gopher selector at
`https://pillar.example.com/g/<selector>`, with its signature in `X-Refinet-*`
headers. The SDK verifies each answer in the browser or on the server:

```js
import { createPillarClient } from "@refinet/pillar";

const pillar = createPillarClient("https://pillar.example.com", { pid: PILLAR_ID });
const status = await pillar.json("/status.json");   // throws if the signature fails
```

Browsers may call the gateway only from the origins you allow
(`APP_ORIGIN` in the VPS `.env`, `REFINET_CORS_ORIGINS` elsewhere). The
wallet sign-in bridge is at `wss://pillar.example.com/ws` for the same
origins.

---

## Running it by hand on a VPS

```bash
git clone https://github.com/circularityglobal/REFINET-PILLARS.git
cd REFINET-PILLARS/deploy/vps
cp .env.example .env        # set PILLAR_DOMAIN, APP_ORIGIN, APP_DOMAIN
docker compose up -d --build
docker compose logs pillar | grep PILLAR_ID
```

or `sudo deploy/vps/install.sh pillar.example.com`, which does the same and
checks the DNS first. Bind from the server:

```bash
docker compose exec -u refinet pillar python3 pillar.py identity rebind --address 0xYourWallet --chain 50
```

Open TCP 80 and 443 (Caddy) and 7070 (Gopher). Nothing else needs to be public.

**Back up the `pillar-data` volume.** It holds the Pillar's key. Losing it
means a new Pillar ID, and re-staking under it after the 14-day cooldown.

---

## Organisations: many Pillars under one domain

A company can run any number of Pillars — `pillar-0.pillars.example.com`,
`pillar-1.pillars.example.com`, … — on its own cloud. Rules that do not bend:

- **One Pillar per hostname.** A domain proof names exactly one Pillar ID.
- **One key per Pillar.** Each replica creates its own key in its own volume;
  never share or copy one between replicas.
- **One stake per Pillar.** Each Pillar ID needs its own 100,000 REFI and its
  own `register` call with its own endpoint. One wallet can stake many.

`deploy/kubernetes/pillar.yaml` is a StatefulSet that does this: each pod
derives its domain from its name, creates its key on first start, and exposes
Gopher (7070), the bridge (7075) and the HTTP gateway (7080) for your ingress
and TCP load balancer. `/health` on the gateway is the readiness probe.

Any hosting works — a VPS, Kubernetes, a managed container service — as long as
the Pillar has a persistent volume, a public TCP port for Gopher, and a TLS
proxy for the gateway on its domain.

The container's entrypoint starts as root only long enough to hand a
root-owned volume to the `refinet` user, then drops root before any Pillar
code runs. Where the platform already starts it unprivileged (the Kubernetes
manifest sets `runAsUser: 999`), that step is skipped and nothing runs as root
at all.

---

## Staking rules

The contract is `contracts/src/PillarStaking.sol` on XDC (chain 50). REFI is
`0x2D010d707da973E194e41D7eA52617f8F969BD23`.

| Rule | Value |
|---|---|
| Stake to be active | 100,000 REFI per Pillar ID; more is allowed |
| Offline fee | 1 REFI per inactive UTC day |
| Lowest a fee can take a stake | 99,999 REFI — the fee pauses rewards; it never takes more |
| Below 100,000 | the Pillar is inactive and earns nothing; top up, then stay online for the 2-day window to clear |
| After an offline day | the Pillar is inactive for 2 days whatever it has staked, then readmits itself |
| Extra stake | a buffer against the *fee*: each REFI above 100,000 covers one offline day. It does not keep you admitted while you are down |
| Unstaking | `requestUnstake` deactivates at once; `withdraw` after 14 days returns everything. Whole days spent deactivated are never charged, even if you cancel; the request and cancel days themselves are |
| Fees go to | the rewards pool address. **Reward distribution is not live yet** — see below |

A day is recorded inactive by the liveness monitor when the Pillar did not
answer most of that day's checks. Short restarts and deploys do not count.
A day the Pillar was down is recorded whatever its state when the monitor
runs, so the record cannot be suppressed by unstaking around it.

**Rewards are not being distributed yet.** There is no distributor contract
and no emission schedule; nothing pays REFI to an operator today. What exists
is the evidence trail: every inactive day is recorded on-chain from the day
the contract is deployed, so whenever distribution does start it can be
settled against a record that was never retroactive. Stake today for mesh
admission and for that record — not for an income stream. This page will say
so plainly when that changes.

**Coming back after an offline day.** The record deactivates the Pillar for two
days. Topping back up to 100,000 REFI is necessary if a fee took you under it,
but it is not sufficient and it is not urgent: a top-up is not evidence that
you are online, or 1 REFI would buy instant readmission. Bring the Pillar back
up, make sure it answers the monitor, and it readmits itself two days after the
last recorded day with nothing more to do. If `refinet-pillar doctor` still
reports you inactive after that, the monitor is still recording days against
you — check that your endpoint resolves and serves `/.well-known/refinet.json`.

Registering a Pillar ID on-chain proves only that someone staked for it; it
does not prove they hold its key. Pillars check a peer's signed identity
document against the staking wallet before trusting it, so a stake pointed at
a Pillar ID whose key the staker does not hold earns nothing and is admitted
nowhere.

The reverse is the one thing to know: because the first caller wins, someone
can register *your* Pillar ID before you do. They gain nothing by it — they
cannot pass the identity check — but they do hold that ID, and the contract has
no way to take it back. If it happens, generate a new Ed25519 key: the Pillar
ID is its SHA-256, so a new key is a new ID, and you register that one instead.
It costs a key rotation, not your stake.

---

## Settings

A Pillar in a container is configured entirely by environment variables; they
override `~/.refinet/config.json` and are never written to it.

| Variable | Default | Meaning |
|---|---|---|
| `REFINET_GENERATE_PID` | — | `1`: create the key on first start if the volume has none |
| `REFINET_PID_PASSWORD` | — | encrypt the key at rest (needed on every start) |
| `REFINET_PUBLIC_DOMAIN` | — | the Pillar's domain; its on-chain endpoint |
| `REFINET_LINKED_DOMAINS` | — | app domains that serve this Pillar's domain proof |
| `REFINET_HTTP_GATEWAY` | off | serve the HTTP gateway |
| `REFINET_HTTP_GATEWAY_HOST` / `_PORT` | `127.0.0.1` / `7080` | where it listens |
| `REFINET_HTTP_TRUST_PROXY` | off | honour `X-Forwarded-For` (only behind your own proxy) |
| `REFINET_CORS_ORIGINS` | — | origins allowed to call the gateway from a browser |
| `REFINET_WEBSOCKET_HOST` | `127.0.0.1` | where the browser bridge listens |
| `REFINET_WEBSOCKET_ORIGINS` | — | web origins admitted to the bridge |
| `REFINET_STAKING_CHAIN_ID` | `50` | XDC mainnet; `51` for Apothem |
| `REFINET_STAKING_CONTRACTS` | — | PillarStaking address(es), comma-separated |
| `REFINET_STAKING_RPC` | chain table | RPC URL override |
| `REFINET_MESH_REQUIRE_STAKE` | off | replicate only from staked, bound peers |
| `REFINET_CHAIN_DISCOVERY` | on | find peers through the staking directory |

Every one of these is off or empty by default. A Pillar that sets none of them
behaves exactly as 0.5.0 did.

---

## Upgrading and rolling back

0.6.0 adds; it does not change what 0.5.0 serves. Gopher answers, signature
trailers, `/identity.json`, `/identity/v3.json`, the browser extension
protocol and the test vectors are unchanged, and `config.json` files from 0.5.0
load as they are. To roll back, run the 0.5.0 image against the same volume:
the key, the ledger and the bindings are read the same way.

The staking contract is not upgradeable. If it is ever replaced, the new
address is added beside the old one in `REFINET_STAKING_CONTRACTS` — a Pillar
active in either counts — and operators move by unstaking from the old one.
No one can block a withdrawal.
