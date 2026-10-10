#!/usr/bin/env bash
# One-time host setup for agent-dev (needs sudo). Idempotent.
#   sudo bash setup-host.sh   (from the agent-dev-brain folder)
# 1. installs Docker Engine + Compose plugin from the official Docker apt repo
# 2. authorizes agent-dev's SSH key on the brain bare repo: restrict + localhost only
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Lancialo con sudo"; exit 1; }

DIR=$(cd "$(dirname "$0")" && pwd)
PUBKEY=$DIR/state/ssh/id_ed25519.pub
AK=/home/brain/.ssh/authorized_keys

# --- 1. Docker (https://docs.docker.com/engine/install/ubuntu/)
if ! command -v docker >/dev/null; then
  apt-get update
  apt-get install -y ca-certificates curl
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

# --- 2. SSH key for agent-dev -> brain@127.0.0.1:brain.git (git-shell only)
KEYBODY=$(awk '{print $2}' "$PUBKEY")
grep -q "$KEYBODY" "$AK" || \
  echo "restrict,from=\"127.0.0.1,::1\" $(cat "$PUBKEY")" | sudo -u brain tee -a "$AK" >/dev/null

echo
echo "== verifica"
docker --version
docker compose version
getent passwd brain | cut -d: -f7
grep agent-dev "$AK" | cut -c1-60
echo
# Di proposito l'utente NON entra nel gruppo docker (equivale a root): docker si usa con sudo.
echo "✅ Fatto. Docker si usa con sudo: sudo docker compose …"
