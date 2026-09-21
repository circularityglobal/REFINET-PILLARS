#!/usr/bin/env bash
# One-command REFInet Pillar install on a fresh VPS (Ubuntu/Debian).
#
#   curl -fsSL https://refinet.io/pillar/install-vps.sh | sudo bash -s -- pillar.example.com
#   (that path proxies to this file on main; any other site path returns the
#    site's HTML, which must never be piped into a shell)
#   # or, from a clone:  sudo deploy/vps/install.sh pillar.example.com
#
# Installs Docker if missing, clones the repo to /opt/refinet-pillar, writes
# deploy/vps/.env, starts the Pillar behind Caddy, and prints its Pillar ID.
set -euo pipefail

DOMAIN="${1:-${PILLAR_DOMAIN:-}}"
REPO="${REFINET_REPO:-https://github.com/circularityglobal/REFINET-PILLARS.git}"
REF="${REFINET_REF:-main}"
DIR="${REFINET_DIR:-/opt/refinet-pillar}"

if [[ -z "$DOMAIN" ]]; then
  echo "usage: install.sh <pillar-domain>   e.g. install.sh pillar.example.com" >&2
  exit 1
fi
if [[ $EUID -ne 0 ]]; then
  echo "run as root (sudo)" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "==> Installing Docker"
  curl -fsSL https://get.docker.com | sh
fi

if [[ ! -d "$DIR/.git" ]]; then
  echo "==> Cloning $REPO ($REF) to $DIR"
  git clone --depth 1 --branch "$REF" "$REPO" "$DIR"
fi
cd "$DIR/deploy/vps"

if [[ ! -f .env ]]; then
  cp .env.example .env
  sed -i "s|^PILLAR_DOMAIN=.*|PILLAR_DOMAIN=$DOMAIN|" .env
  sed -i "s|^APP_ORIGIN=.*|APP_ORIGIN=${APP_ORIGIN:-}|" .env
  sed -i "s|^APP_DOMAIN=.*|APP_DOMAIN=${APP_DOMAIN:-}|" .env
  sed -i "s|^STAKING_CONTRACT=.*|STAKING_CONTRACT=${STAKING_CONTRACT:-}|" .env
fi

PUBLIC_IP="$(curl -fsS4 https://api.ipify.org || true)"
RESOLVED="$(getent ahostsv4 "$DOMAIN" | awk '{print $1; exit}' || true)"
if [[ -n "$PUBLIC_IP" && "$RESOLVED" != "$PUBLIC_IP" ]]; then
  echo "!! $DOMAIN resolves to '${RESOLVED:-nothing}', this server is $PUBLIC_IP."
  echo "!! Add an A record for $DOMAIN -> $PUBLIC_IP; Caddy retries the certificate until it does."
fi

echo "==> Starting the Pillar"
docker compose up -d --build

echo "==> Waiting for the Pillar ID"
for _ in $(seq 1 60); do
  PID_LINE="$(docker compose logs pillar 2>/dev/null | grep -Eo 'PID [0-9a-f]{16}' | head -1 || true)"
  [[ -n "$PID_LINE" ]] && break
  sleep 2
done
FULL_PID="$(docker compose exec -T -u refinet pillar python3 -c 'import json,pathlib;print(json.loads((pathlib.Path.home()/".refinet/pid.json").read_text())["pid"])')"

cat <<MSG

  REFInet Pillar is running.

    Pillar ID:     $FULL_PID
    Domain proof:  https://$DOMAIN/.well-known/refinet.json
    Gopher:        gopher://$DOMAIN:7070

  Next:
    1. Bind your staking wallet (sign in the wallet you will stake from):
         docker compose -f $DIR/deploy/vps/docker-compose.yml exec -u refinet pillar \\
           python3 pillar.py identity rebind --address 0xYOURWALLET --chain 50
    2. Stake 100,000 REFI for this Pillar ID with endpoint "$DOMAIN"
       (portal, or PillarStaking.register(pid, amount, "$DOMAIN")).
    3. Back up the pillar-data Docker volume: it holds the Pillar's key.

MSG
