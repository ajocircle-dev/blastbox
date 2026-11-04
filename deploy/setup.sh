#!/usr/bin/env bash
# One-shot setup for a fresh Ubuntu 24.04 / Debian 12+ Vultr Cloud Compute VM.
# Usage (as root, from a checkout of this repo):  DOMAIN=example.com bash deploy/setup.sh
# DOMAIN is optional. Without it Caddy serves plain HTTP on port 80.
# Not yet run against a real VM.
set -euo pipefail

APP_DIR=/opt/blastbox
ENV_FILE=/etc/blastbox.env
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"

[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }

echo "== packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q ca-certificates curl gnupg python3 debian-keyring debian-archive-keyring apt-transport-https ufw

echo "== docker (official convenience script)"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

echo "== gVisor (optional, skipped if it fails)"
if ! command -v runsc >/dev/null; then
  if curl -fsSL https://gvisor.dev/archive.key | gpg --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg; then
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" \
      > /etc/apt/sources.list.d/gvisor.list
    apt-get update -q && apt-get install -y -q runsc && runsc install && systemctl restart docker || echo "gVisor install failed, continuing with runc"
  fi
fi

echo "== sandbox image"
docker pull python:3.12-alpine

echo "== app user and code"
id blastbox >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin blastbox
usermod -aG docker blastbox
mkdir -p "$APP_DIR"
cp -r "$SRC_DIR/blastbox" "$APP_DIR/"
chown -R blastbox:blastbox "$APP_DIR"

echo "== env file"
if [ ! -f "$ENV_FILE" ]; then
  install -m 600 -o root -g root "$SRC_DIR/deploy/blastbox.env.example" "$ENV_FILE"
  if docker info --format '{{json .Runtimes}}' | grep -q runsc; then
    sed -i 's/^SANDBOX_RUNTIME=.*/SANDBOX_RUNTIME=runsc/' "$ENV_FILE"
  fi
  echo "Edit $ENV_FILE and set VULTR_INFERENCE_API_KEY, then: systemctl restart blastbox"
fi

echo "== systemd service"
install -m 644 "$SRC_DIR/deploy/blastbox.service" /etc/systemd/system/blastbox.service
systemctl daemon-reload
systemctl enable --now blastbox

echo "== caddy"
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q && apt-get install -y -q caddy
fi
SITE="${DOMAIN:-:80}"
sed "s|{\$SITE}|$SITE|" "$SRC_DIR/deploy/Caddyfile" > /etc/caddy/Caddyfile
systemctl reload caddy || systemctl restart caddy

echo "== firewall: ssh, http, https only. The app port 8080 stays local."
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable

echo "== done. Health: curl -s http://127.0.0.1:8080/healthz"
