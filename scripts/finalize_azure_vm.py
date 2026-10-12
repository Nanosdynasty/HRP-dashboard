"""Remove one-time owner configuration after a verified hosted login."""
import os
import sqlite3
from pathlib import Path
from dotenv import dotenv_values

config_path = Path('/etc/hrp/dashboard.env')
config = dotenv_values(config_path)
with sqlite3.connect('/var/lib/hrp/_access/access.sqlite3') as db:
    owner = db.execute('SELECT status,role FROM accounts WHERE issuer=? AND subject=?',
                       (config['AUTH_ADMIN_ISSUER'], config['AUTH_ADMIN_SUBJECT'])).fetchone()
    assert owner == ('approved', 'admin'), 'Verified owner must be approved before finalization.'
    assert db.execute("SELECT value FROM settings WHERE key='owner_bootstrapped'").fetchone() == ('true',)
lines = config_path.read_text().splitlines()
pending = config_path.with_suffix('.pending')
fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, 'w') as target:
    target.write('\n'.join(line for line in lines if not line.startswith(('AUTH_ADMIN_ISSUER=', 'AUTH_ADMIN_SUBJECT='))) + '\n')
os.replace(pending, config_path)
Path('/home/hrpadmin/dashboard.env').unlink(missing_ok=True)
print('Verified owner persisted; one-time bootstrap settings removed; private config mode 0600.')
