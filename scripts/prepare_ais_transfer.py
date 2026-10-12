"""Prepare only the already-authorized AIS provider key for private VM transfer."""
import os
from pathlib import Path
from dotenv import dotenv_values

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    key=dotenv_values(root/'.env').get('AISSTREAM_API_KEY')
    if not key or '\n' in key or '\r' in key:raise SystemExit('No valid local AIS key is configured.')
    destination=root/'uploads'/'_azure'/'ais-transfer.env'
    destination.parent.mkdir(parents=True,exist_ok=True)
    with os.fdopen(os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600),'w') as output:
        output.write('AISSTREAM_API_KEY='+key+'\n')
    print('AIS key only prepared privately. Microsoft/password/authenticator credentials are excluded.')
