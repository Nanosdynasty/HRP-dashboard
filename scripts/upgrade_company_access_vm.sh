#!/bin/bash
# Reviewed upgrade on the existing VM; no resources, ports or paid plans are created.
set -euo pipefail
if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
  echo 'Usage: sudo bash upgrade_company_access_vm.sh /path/reviewed-dashboard.zip' >&2
  exit 2
fi
backup="/var/backups/hrp/company-access-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -o root -g root -m 700 "$backup"
rollback() {
  status=$?
  trap - ERR
  systemctl stop hrp-dashboard || true
  if [ -f "$backup/runtime.tgz" ]; then tar -xzf "$backup/runtime.tgz" -C /opt/hrp; fi
  if [ -f "$backup/dashboard.env" ]; then cp -p "$backup/dashboard.env" /etc/hrp/dashboard.env; fi
  if [ -f "$backup/access.sqlite3" ]; then
    cp "$backup/access.sqlite3" /var/lib/hrp/_access/access.sqlite3
    chown hrp:hrp /var/lib/hrp/_access/access.sqlite3
    chmod 640 /var/lib/hrp/_access/access.sqlite3
  fi
  systemctl start hrp-dashboard || true
  echo 'Upgrade failed; the prior runtime and access snapshot were restored.' >&2
  exit "$status"
}
trap rollback ERR
systemctl stop hrp-dashboard
cp -p /etc/hrp/dashboard.env "$backup/dashboard.env"
chmod 600 "$backup/dashboard.env"
tar --exclude='.venv' --exclude='__pycache__' -czf "$backup/runtime.tgz" -C /opt/hrp .
python3 - "$backup/access.sqlite3" <<'PY'
import sqlite3,sys,os
with sqlite3.connect('/var/lib/hrp/_access/access.sqlite3') as source, sqlite3.connect(sys.argv[1]) as target:
    source.backup(target)
os.chmod(sys.argv[1],0o600)
PY
unzip -oq "$1" -d /opt/hrp
chown -R hrp:hrp /opt/hrp
runuser -u hrp -- /opt/hrp/.venv/bin/python -m pip install -r /opt/hrp/requirements.txt --quiet
/opt/hrp/.venv/bin/python /opt/hrp/scripts/configure_company_auth.py --env /etc/hrp/dashboard.env
systemctl start hrp-dashboard
trap - ERR
echo 'Code upgraded with database and configuration backups. Owner must complete fresh Azure password/MFA setup.'
