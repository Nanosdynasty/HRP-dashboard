"""Explicit server-admin recovery of the existing owner; never creates an owner."""
import argparse
import sqlite3
import time
import os
from pathlib import Path

def recover(path,issuer,subject):
    with sqlite3.connect(path) as db:
        owner=db.execute("SELECT value FROM settings WHERE key='company_owner_id'").fetchone()
        identity=db.execute('SELECT id FROM accounts WHERE issuer=? AND subject=?',(issuer,subject)).fetchone()
        if not owner or not identity or int(owner[0])!=identity[0]:raise ValueError('The exact existing owner identity is required.')
        backup=Path(str(path)+'.owner-recovery-'+str(time.time_ns())+'.bak')
        with sqlite3.connect(backup) as target:db.backup(target)
        if os.name!='nt':os.chmod(backup,0o600)
        db.execute('BEGIN IMMEDIATE')
        db.execute('UPDATE credentials SET password_hash=NULL,seed=NULL,pending_seed=NULL,enrolled_at=NULL,last_counter=-1,version=version+1 WHERE account_id=?',(identity[0],))
        db.execute('DELETE FROM sessions WHERE account_id=?',(identity[0],))
        db.execute('DELETE FROM verifications WHERE account_id=?',(identity[0],))
        db.execute('DELETE FROM recovery_codes WHERE account_id=?',(identity[0],))
        db.execute('INSERT INTO audit(occurred_at,actor,action,target) VALUES(?,?,?,?)',(time.time(),identity[0],'owner_factor_server_reset',str(identity[0])))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True);parser.add_argument('--issuer',required=True);parser.add_argument('--subject',required=True)
    args=parser.parse_args()
    if not args.database.is_file():parser.error('Existing persistent access database required.')
    if input('Type RESET OWNER FACTOR to invalidate owner sessions and force setup: ')!='RESET OWNER FACTOR':raise SystemExit('Cancelled')
    recover(args.database,args.issuer,args.subject)
    print('Owner factors reset and audited. Fresh verification of the same Microsoft identity is required.')
