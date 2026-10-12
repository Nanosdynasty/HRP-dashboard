"""Create the separate MFA key in ignored local configuration without displaying it."""
from pathlib import Path
import argparse
import os
from cryptography.fernet import Fernet

def configure(path):
    content=path.read_text(encoding='utf-8') if path.exists() else ''
    lines=content.splitlines()
    configured=any(line.startswith('AUTH_MFA_ENCRYPTION_KEY=') and line.partition('=')[2].strip() for line in lines)
    if configured:
        print('Existing authenticator key preserved.')
        return
    lines=[line for line in lines if not line.startswith('AUTH_MFA_ENCRYPTION_KEY=')]
    lines.append('AUTH_MFA_ENCRYPTION_KEY='+Fernet.generate_key().decode())
    pending=path.with_name(path.name+'.mfa-pending')
    with os.fdopen(os.open(pending,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600),'w',encoding='utf-8') as output:
        output.write('\n'.join(lines)+'\n')
    os.replace(pending,path)
    if os.name!='nt':os.chmod(path,0o600)
    print('Authenticator key saved privately. All Microsoft identities require individual owner approval.')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env',type=Path,default=Path(__file__).resolve().parents[1]/'.env')
    configure(parser.parse_args().env)
