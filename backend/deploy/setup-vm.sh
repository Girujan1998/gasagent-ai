#!/usr/bin/env bash
# One-time bootstrap for a fresh Debian VM (e.g. GCP e2-micro Always Free):
# FlareSolverr (localhost-only) + the FastAPI backend as a systemd service
# + Caddy in front for free automatic HTTPS via the <ip>.sslip.io trick.
#
# Run this ON THE VM over SSH, as the default non-root user (it uses sudo
# where needed). Edit REPO_URL below first if the repo isn't public.
set -euo pipefail

REPO_URL="https://github.com/Girujan1998/gasagent-ai.git"
APP_DIR="$HOME/gasagent-ai"

echo "==> 1/7: system packages"
sudo apt-get update -y
sudo apt-get install -y docker.io git curl gnupg apt-transport-https debian-keyring debian-archive-keyring
sudo systemctl enable --now docker

echo "==> 2/7: FlareSolverr (bound to localhost only — never internet-reachable)"
sudo docker rm -f flaresolverr >/dev/null 2>&1 || true
sudo docker run -d --name flaresolverr \
  -p 127.0.0.1:8191:8191 \
  --restart unless-stopped \
  ghcr.io/flaresolverr/flaresolverr:latest

echo "==> 3/7: uv + Python 3.13 (py-gasbuddy needs >=3.13)"
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

echo "==> 4/7: app code + venv"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull
else
  git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR/backend"
uv venv --python 3.13 .venv
.venv/bin/pip install -r requirements.txt

echo "==> 5/7: secrets file — EDIT /etc/gasagent/backend.env AFTER THIS RUNS"
sudo mkdir -p /etc/gasagent
if [ ! -f /etc/gasagent/backend.env ]; then
  sudo tee /etc/gasagent/backend.env > /dev/null <<'ENVEOF'
GEMINI_API_KEY=REPLACE_ME
NREL_API_KEY=REPLACE_ME
OCM_API_KEY=REPLACE_ME
EIA_API_KEY=REPLACE_ME
GASBUDDY_SOLVER_URL=http://127.0.0.1:8191/v1
ENVEOF
fi
sudo chown "$USER":"$USER" /etc/gasagent/backend.env
sudo chmod 600 /etc/gasagent/backend.env

echo "==> 6/7: backend systemd service (binds to 127.0.0.1 only — Caddy fronts it)"
sudo tee /etc/systemd/system/gasagent-backend.service > /dev/null <<EOF
[Unit]
Description=GasAgent.ai backend
After=network.target docker.service

[Service]
User=$USER
WorkingDirectory=$APP_DIR/backend
EnvironmentFile=/etc/gasagent/backend.env
ExecStart=$APP_DIR/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now gasagent-backend

echo "==> 7/7: Caddy (auto HTTPS, no domain needed — uses <external-ip>.sslip.io)"
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update -y
sudo apt-get install -y caddy

EXTERNAL_IP=$(curl -s -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip")
SSLIP_HOST="${EXTERNAL_IP}.sslip.io"

sudo tee /etc/caddy/Caddyfile > /dev/null <<EOF
${SSLIP_HOST} {
    reverse_proxy 127.0.0.1:8001
}
EOF
sudo systemctl restart caddy

cat <<EOF

=========================================================================
Done. Two things left, both manual:

1. Edit the real secrets in:  sudo nano /etc/gasagent/backend.env
   then:                      sudo systemctl restart gasagent-backend

2. Make sure your GCP firewall allows inbound 80/443 (see the separate
   firewall command — this script can't do that part, it runs outside
   the VM).

Once both are done, this should work from anywhere:
   curl https://${SSLIP_HOST}/api/v1/health
=========================================================================
EOF
