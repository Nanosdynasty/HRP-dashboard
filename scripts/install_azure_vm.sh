#!/bin/bash
# Run as root on Ubuntu 24.04 after uploading the reviewed package and config.
set -euo pipefail
if [ "$#" -ne 2 ]; then
  echo "Usage: sudo bash install_azure_vm.sh /path/dashboard.zip hostname" >&2
  exit 2
fi
package="$1"
hostname="$2"
if [[ ! "$hostname" =~ ^[a-z0-9][a-z0-9.-]+[a-z0-9]$ ]]; then
  echo "Invalid DNS hostname" >&2
  exit 2
fi
if [ ! -s /etc/hrp/dashboard.env ]; then
  echo "Create the private /etc/hrp/dashboard.env before installing." >&2
  exit 2
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-dev gcc unzip caddy
id hrp >/dev/null 2>&1 || useradd --system --home-dir /var/lib/hrp --shell /usr/sbin/nologin hrp
install -d -o hrp -g hrp -m 750 /var/lib/hrp /opt/hrp
install -d -o root -g root -m 700 /etc/hrp
chmod 600 /etc/hrp/dashboard.env
# Runtime archive never contains .env, access records, or retained AIS history.
unzip -oq "$package" -d /opt/hrp
chown -R hrp:hrp /opt/hrp
runuser -u hrp -- python3 -m venv /opt/hrp/.venv
runuser -u hrp -- /opt/hrp/.venv/bin/python -m pip install -r /opt/hrp/requirements.txt

cat > /etc/systemd/system/hrp-dashboard.service <<'UNIT'
[Unit]
Description=Howe Robinson Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=hrp
Group=hrp
WorkingDirectory=/opt/hrp
EnvironmentFile=/etc/hrp/dashboard.env
Environment=APP_ENV=production
Environment=HRP_STORAGE_DIR=/var/lib/hrp
ExecStart=/opt/hrp/.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=on-failure
RestartSec=10
TimeoutStopSec=60
UMask=0027
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/caddy/Caddyfile <<CADDY
$hostname {
    encode gzip
    reverse_proxy 127.0.0.1:8000
}
CADDY
caddy validate --config /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable hrp-dashboard caddy
systemctl restart hrp-dashboard
systemctl restart caddy
echo "Installed. Verify HTTPS health, anonymous API denial, and Microsoft sign-in."
