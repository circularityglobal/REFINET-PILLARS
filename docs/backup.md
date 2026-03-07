# REFInet Pillar — Backup Guide

## Critical Files

All Pillar state lives under `~/.refinet/`. Back up these files to preserve
your identity, data, and Tor hidden service address across migrations.

| File | Purpose | Loss Impact |
|------|---------|-------------|
| `~/.refinet/pid.json` | REFInet Ed25519 keypair and PID | Pillar identity lost — new PID generated, all TOFU trust broken |
| `~/.refinet/tor_data/hs_privkey` | Tor hidden service private key | New .onion address generated — all Browser trust entries and peer records become stale |
| `~/.refinet/db/live.db` | 13-month rolling transaction ledger, peer registry, gopherholes | Transaction history, peer list, and gopherhole registrations lost |
| `~/.refinet/db/archive.db` | Yearly compressed historical records | Long-term audit trail lost |
| `~/.refinet/config.json` | Operator configuration (pillar name, ports, Tor settings) | Defaults regenerated — reconfigure manually |

## Backup Command

```bash
tar czf refinet-backup-$(date +%Y%m%d).tar.gz \
  ~/.refinet/pid.json \
  ~/.refinet/config.json \
  ~/.refinet/db/live.db \
  ~/.refinet/db/archive.db \
  ~/.refinet/tor_data/hs_privkey
```

## Restore

```bash
# Stop the Pillar first
tar xzf refinet-backup-YYYYMMDD.tar.gz -C /

# Restart — same PID, same .onion address
python3 pillar.py
```

## Security Notes

- `pid.json` contains your Ed25519 **private key**. Protect it like a wallet seed.
- `tor_data/hs_privkey` is the Tor hidden service private key. Anyone with this
  file can impersonate your `.onion` address.
- Both files should be stored encrypted at rest and never committed to version control.
- File permissions: `pid.json` and `hs_privkey` should be `0600` (owner read/write only).
