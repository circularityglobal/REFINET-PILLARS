# REFInet Bootstrap Node — Deployment Guide

**Goal:** Get `gopher://gopher.refinet.io:7070` live and serving content from a Fly.io machine, with DNS resolving, health badge updating, and peer discovery working for the entire mesh.

This guide walks through every step from zero infrastructure to a running bootstrap Pillar. Each step includes the exact command, where to run it, and what to verify before moving on.

---

## Prerequisites

| Tool | Install | Verify |
|------|---------|--------|
| **Fly CLI** | `brew install flyctl` or `curl -L https://fly.io/install.sh \| sh` | `flyctl version` |
| **GitHub CLI** | `brew install gh` | `gh auth status` |
| **Python 3.9+** | Already installed | `python3 --version` |
| **Git** | Already installed | `git status` (from project root) |

You also need:
- A [Fly.io account](https://fly.io/app/sign-up) (free tier works)
- Admin access to the [REFINET-PILLARS GitHub repo](https://github.com/circularityglobal/REFINET-PILLARS)
- DNS control for the `refinet.io` domain

---

## Step 1: Generate the Bootstrap Node Identity

Run this **once, locally, on a trusted machine**. This generates the Ed25519 keypair that becomes the permanent identity of the bootstrap node.

```bash
cd /path/to/REFINET-PILLARS   # wherever you cloned the repo
python3 scripts/bootstrap_keygen.py > /tmp/bootstrap_pid.json
```

This prints the full `pid.json` to stdout and a summary to stderr:

```
============================================================
  BOOTSTRAP NODE IDENTITY
============================================================
  PID:        <64-char hex — this is the node's public identity>
  Public key: <64-char hex — this is the Ed25519 public key>
============================================================
```

**Save these two values.** You'll need them for `deploy/peers.json.example` and `README.md` in Step 6.

**Security:** The file at `/tmp/bootstrap_pid.json` contains the private key. It must never be committed to git. After Step 2, securely delete it:

```bash
rm -P /tmp/bootstrap_pid.json   # macOS secure delete
# or: shred -u /tmp/bootstrap_pid.json   # Linux
```

---

## Step 2: Store the Identity as Secrets

The bootstrap identity is stored in two places:
1. **Fly.io secrets** — so the headless start script can seed `~/.refinet/pid.json` on boot
2. **GitHub Actions secrets** — so CI/CD can pass it to Fly on deploy

### 2a. Fly.io Secret

```bash
flyctl secrets set REFINET_PID_JSON="$(cat /tmp/bootstrap_pid.json)" --app refinet-pillar
```

If the app doesn't exist yet (it won't on first run), this command will fail. That's fine — Step 3 creates the app, and Step 4 sets the secret.

### 2b. GitHub Actions Secret

Go to: **https://github.com/circularityglobal/REFINET-PILLARS/settings/secrets/actions**

Or use the CLI:

```bash
gh secret set REFINET_PID_JSON < /tmp/bootstrap_pid.json
```

You also need the Fly API token for CI/CD deploys:

```bash
# Generate a Fly.io deploy token
flyctl tokens create deploy --app refinet-pillar

# Store it in GitHub
gh secret set FLY_API_TOKEN
# (paste the token when prompted)
```

### Verify

```bash
gh secret list
```

Expected output should include:
```
FLY_API_TOKEN    Updated 2026-XX-XX
REFINET_PID_JSON Updated 2026-XX-XX
```

---

## Step 3: Create the Fly.io Application

The `fly.toml` in the repo already defines the app configuration. Create the app on Fly:

```bash
cd /path/to/REFINET-PILLARS   # wherever you cloned the repo

# Create the app (uses fly.toml settings: app name = refinet-pillar, region = sjc)
flyctl apps create refinet-pillar

# Create the persistent volume for SQLite data
flyctl volumes create refinet_data --region sjc --size 1 --app refinet-pillar
```

### What `fly.toml` configures

| Setting | Value | Purpose |
|---------|-------|---------|
| `app` | `refinet-pillar` | Fly app name |
| `primary_region` | `sjc` | San Jose (low-latency US West) |
| `internal_port` | `7070` | Pillar listens here inside the container |
| `ports` | `7070`, `70` | External ports Fly exposes |
| `auto_stop_machines` | `false` | Pillar must always be online |
| `min_machines_running` | `1` | At least one machine always up |
| `mounts` | `refinet_data → /home/refinet/.refinet` | Persistent volume for SQLite + identity |

### Verify

```bash
flyctl apps list
# Should show: refinet-pillar

flyctl volumes list --app refinet-pillar
# Should show: refinet_data, 1 GB, sjc
```

---

## Step 4: Deploy the Bootstrap Node

### Option A: Deploy from Local Machine

```bash
cd /path/to/REFINET-PILLARS   # wherever you cloned the repo

# Set the PID secret (if not done in Step 2a)
flyctl secrets set REFINET_PID_JSON="$(cat /tmp/bootstrap_pid.json)" --app refinet-pillar

# Deploy
flyctl deploy --app refinet-pillar
```

### Option B: Deploy via GitHub Actions (Automated)

Push to `main` triggers `.github/workflows/deploy.yml` which:
1. Runs the full test suite
2. Deploys to Fly.io using `FLY_API_TOKEN`
3. Sets the `REFINET_PID_JSON` secret on the Fly app

```bash
git push origin main
# Monitor: https://github.com/circularityglobal/REFINET-PILLARS/actions
```

### Verify Deployment

```bash
# Check app status
flyctl status --app refinet-pillar

# Check logs
flyctl logs --app refinet-pillar

# Expected log output:
#   Headless start: PID abcd1234... ready, DB seeded.
#   [refinet] INFO: REFInet server listening on 0.0.0.0:7070
```

---

## Step 5: Configure DNS

The Pillar needs `gopher.refinet.io` to resolve to the Fly.io machine's IP.

### 5a. Get the Fly.io IP Address

```bash
flyctl ips list --app refinet-pillar
```

This returns both IPv4 and IPv6 addresses. You need both.

### 5b. Set DNS Records

In your DNS provider (Cloudflare, Route 53, Namecheap, etc.), create these records for `refinet.io`:

| Type | Name | Value | Proxy | TTL |
|------|------|-------|-------|-----|
| `A` | `gopher` | `<IPv4 from flyctl ips list>` | **OFF** (DNS only) | 300 |
| `AAAA` | `gopher` | `<IPv6 from flyctl ips list>` | **OFF** (DNS only) | 300 |

**Important:** If using Cloudflare, the proxy (orange cloud) **must be OFF**. Gopher uses raw TCP on non-HTTP ports. Cloudflare's proxy only handles HTTP/HTTPS and will silently drop Gopher connections.

### 5c. Allocate a Dedicated IPv4 on Fly (if needed)

Fly.io shared IPv4 may not work for non-HTTP TCP. Allocate a dedicated IP:

```bash
flyctl ips allocate-v4 --shared=false --app refinet-pillar
flyctl ips allocate-v6 --app refinet-pillar
```

Then update DNS with the new IPs.

### Verify DNS

```bash
# Check DNS resolution
dig gopher.refinet.io A +short
dig gopher.refinet.io AAAA +short

# Test Gopher connectivity
echo "" | nc -w5 gopher.refinet.io 7070

# Full Gopher request
curl gopher://gopher.refinet.io:7070/
```

Expected: The root menu of the REFInet Pillar, ending with a signature block.

---

## Step 6: Update peers.json with Real Bootstrap Identity

Now that the bootstrap node has a permanent PID, update the example peers file so new Pillars can discover it.

### 6a. Update `deploy/peers.json.example`

Replace the placeholder values with the real PID and public key from Step 1:

```json
[
  {
    "hostname": "gopher.refinet.io",
    "port": 7070,
    "pid": "<64-CHAR-HEX-PID-FROM-STEP-1>",
    "public_key": "<64-CHAR-HEX-PUBKEY-FROM-STEP-1>",
    "pillar_name": "REFInet Bootstrap Pillar"
  }
]
```

### 6b. Update `README.md`

The "Connect to the Mesh" section at the bottom of `README.md` has the same placeholders. Update them with the real values.

### 6c. Commit and Push

```bash
git add deploy/peers.json.example README.md
git commit -m "chore: populate bootstrap node PID in peers.json"
git push origin main
```

---

## Step 7: Verify End-to-End

Run these checks in order. All must pass.

### 7a. Gopher Connectivity

```bash
# Root menu
curl gopher://gopher.refinet.io:7070/

# Status endpoint
printf "/status.json\r\n" | nc -w5 gopher.refinet.io 7070

# PID endpoint
printf "/pid\r\n" | nc -w5 gopher.refinet.io 7070
```

### 7b. Health Badge

Trigger the health workflow manually:

```bash
gh workflow run health.yml
```

Or wait up to 15 minutes for the cron schedule. After it runs:

1. Check the workflow: https://github.com/circularityglobal/REFINET-PILLARS/actions/workflows/health.yml
2. The badge at `.github/badges/pillar-status.svg` should update from "offline" to "online"
3. The badge in `README.md` should render green on GitHub

### 7c. Peer Discovery

On a local machine, copy the peers file and start a Pillar:

```bash
cp deploy/peers.json.example ~/.refinet/peers.json
python3 pillar.py
```

Expected log output:
```
[refinet] INFO: Loaded 1 bootstrap peer(s) from peers.json
```

The local Pillar should replicate the registry from the bootstrap node within 5 minutes (the replication interval).

### 7d. Standard Gopher Port (70)

Fly.io maps external port 70 to internal port 7070. Test it:

```bash
curl gopher://gopher.refinet.io:70/
```

This should return the same root menu as port 7070 (standard Gopher serves the same content).

---

## Step 8: Optional — PyPI and Docker Hub Publish

These are independent of the live node but complete the distribution picture.

### PyPI

```bash
cd /path/to/REFINET-PILLARS   # wherever you cloned the repo
python3 -m build
twine upload dist/*
```

Verify: https://pypi.org/project/refinet-pillar/

### Docker Hub

```bash
docker build -t refinet/pillar:0.3.0 -t refinet/pillar:latest .
docker push refinet/pillar:0.3.0
docker push refinet/pillar:latest
```

Verify: https://hub.docker.com/r/refinet/pillar

### MkDocs Documentation Site

```bash
mkdocs gh-deploy
```

Verify: https://docs.refinet.io (requires a CNAME in DNS pointing to GitHub Pages)

---

## Troubleshooting

### "Connection refused" on port 7070

1. Check the app is running: `flyctl status --app refinet-pillar`
2. Check logs for startup errors: `flyctl logs --app refinet-pillar`
3. Verify the secret is set: `flyctl secrets list --app refinet-pillar`
4. Check if the volume mounted: Look for `Headless start: PID ... ready` in logs

### "FATAL: REFINET_PID_JSON environment variable is not set"

The secret wasn't set on Fly:
```bash
flyctl secrets set REFINET_PID_JSON="$(cat /tmp/bootstrap_pid.json)" --app refinet-pillar
```

### DNS not resolving

- Wait 5 minutes for DNS propagation
- Verify the record exists: `dig gopher.refinet.io A`
- If using Cloudflare, ensure the proxy is **OFF** (grey cloud, not orange)

### Health badge stuck on "offline"

1. Run the workflow manually: `gh workflow run health.yml`
2. Check workflow logs: https://github.com/circularityglobal/REFINET-PILLARS/actions/workflows/health.yml
3. The workflow uses `nc` to probe `gopher.refinet.io:7070` — if DNS or the node is down, it reports offline

### Bootstrap peer rejected by other Pillars

If other Pillars log `Bootstrap peer rejected: PID ... does not match public key`:
- The PID in `peers.json` doesn't match the public key
- Regenerate: The PID must equal `SHA-256(public_key_bytes)`
- Verify: `python3 -c "import hashlib; print(hashlib.sha256(bytes.fromhex('<PUBLIC_KEY>')).hexdigest())"`

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────┐
│                     GitHub Repository                       │
│  circularityglobal/REFINET-PILLARS                         │
│                                                             │
│  Secrets:                                                   │
│    FLY_API_TOKEN       → Fly.io deploy auth                │
│    REFINET_PID_JSON    → Bootstrap node identity            │
│                                                             │
│  Workflows:                                                 │
│    deploy.yml          → push main → test → fly deploy     │
│    health.yml          → cron 15m → probe → badge          │
│    test.yml            → PR/push → pytest                  │
│    release.yml         → tag v* → PyPI + GitHub Release    │
└───────────────┬─────────────────────────────┬───────────────┘
                │                             │
                ▼                             ▼
┌───────────────────────┐     ┌───────────────────────────────┐
│      Fly.io           │     │         DNS                   │
│  App: refinet-pillar  │     │  gopher.refinet.io            │
│  Region: sjc          │     │    A    → <Fly IPv4>          │
│  Volume: refinet_data │     │    AAAA → <Fly IPv6>          │
│                       │     └───────────────────────────────┘
│  Ports:               │
│    7070 → 7070 (TCP)  │
│    70   → 7070 (TCP)  │
│                       │
│  Container:           │
│    Dockerfile          │
│    → headless_start.py │
│    → pillar.py run     │
└───────────────────────┘
```

---

## Checklist

Use this to track progress:

- [ ] **Step 1:** Bootstrap identity generated (`bootstrap_keygen.py`)
- [ ] **Step 2a:** `REFINET_PID_JSON` set in Fly.io secrets
- [ ] **Step 2b:** `REFINET_PID_JSON` set in GitHub Actions secrets
- [ ] **Step 2b:** `FLY_API_TOKEN` set in GitHub Actions secrets
- [ ] **Step 3:** Fly.io app created (`refinet-pillar`)
- [ ] **Step 3:** Persistent volume created (`refinet_data`)
- [ ] **Step 4:** Deployed successfully (logs show PID ready)
- [ ] **Step 5a:** Fly.io IPs obtained
- [ ] **Step 5b:** DNS A/AAAA records created for `gopher.refinet.io`
- [ ] **Step 5c:** DNS resolves correctly (`dig gopher.refinet.io`)
- [ ] **Step 6:** `peers.json.example` updated with real PID
- [ ] **Step 7a:** `curl gopher://gopher.refinet.io:7070/` returns root menu
- [ ] **Step 7b:** Health badge shows "online"
- [ ] **Step 7c:** Local Pillar connects to bootstrap node
- [ ] **Step 7d:** Port 70 works (`curl gopher://gopher.refinet.io:70/`)
- [ ] **Step 8:** PyPI published (optional)
- [ ] **Step 8:** Docker Hub published (optional)
- [ ] **Step 8:** MkDocs deployed (optional)

---

*REFInet v0.3.0 — Deployment Guide*
