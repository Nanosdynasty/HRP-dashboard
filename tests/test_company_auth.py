"""Auth tests use synthetic identities and isolated SQLite storage, never live credentials."""
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pyotp
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

from access_control import AccessControl, AccessMiddleware, AccessStore, AuthConfig, COOKIE, FLOW_COOKIE
from company_auth import PRE_COOKIE, HASHER
from section_permissions import SECTIONS, requirements

TENANT="12345678-1234-1234-1234-123456789012"
ISSUER=f"https://login.microsoftonline.com/{TENANT}/v2.0"
OWNER_ISSUER="https://login.microsoftonline.com/9188040d-6c67-4c5b-b112-36a304b66dad/v2.0"
PASSWORD="Test-only password for an isolated database 2026"

def claims(subject="colleague",email="colleague@howerob.com",tid=TENANT,issuer=ISSUER):
    return {"iss":issuer,"sub":subject,"tid":tid,"email":email,"preferred_username":email,"name":subject}

@pytest.fixture
def system(tmp_path,monkeypatch):
    monkeypatch.setenv("AUTH_MFA_ENCRYPTION_KEY",Fernet.generate_key().decode())
    monkeypatch.setenv("AUTH_COMPANY_TENANT_ID",TENANT)
    config=AuthConfig(client_id="synthetic",client_secret="synthetic",admin_issuer=OWNER_ISSUER,admin_subject="owner")
    store=AccessStore(tmp_path/"access.sqlite3")
    legacy=store.login(claims("owner","owner@outlook.com",issuer=OWNER_ISSUER),config)
    access=AccessControl(config,store.path)
    app=FastAPI();app.include_router(access.router())
    @app.api_route("/{path:path}",methods=["GET","POST","PUT","DELETE"])
    def protected(path:str):return {"data":"protected"}
    @app.websocket('/api/ais/stream')
    async def stream(websocket:WebSocket):
        await websocket.accept();await websocket.send_text('connected');await websocket.receive_text()
    app.add_middleware(AccessMiddleware,access=access)
    return access,TestClient(app,base_url=config.base_url),legacy

def verified(access,client,identity=None):
    token=access.company.verify_identity(identity or claims())
    client.cookies.set(PRE_COOKIE,token,domain='127.0.0.1')
    user=access.company.pre(type('R',(),{'cookies':{PRE_COOKIE:token}})())
    return user,{"X-CSRF-Token":user["csrf"],"Origin":access.config.base_url}

def approve(access,user,level="view"):
    grants=dict.fromkeys(SECTIONS,level)
    access.company.review(access.company.owner(),user["id"],"approved",grants)

def setup(access,client,identity=None,owner=False):
    user,headers=verified(access,client,identity)
    if not owner:
        assert client.post('/api/auth/request',json={"name":"Test colleague","reason":"Test access to approved sections"},headers=headers).status_code==200
        approve(access,user)
        user,headers=verified(access,client,identity)
    assert client.post('/api/auth/password',json={"password":PASSWORD},headers=headers).status_code==200
    assert client.post('/api/auth/mfa/enrol',json={},headers=headers).status_code==200
    assert client.get('/api/auth/mfa/qr').status_code==200
    with access.store.db() as db: encrypted=db.execute('SELECT pending_seed FROM credentials WHERE account_id=?',(user['id'],)).fetchone()[0]
    seed=access.company.cipher.decrypt(encrypted.encode()).decode()
    response=client.post('/api/auth/mfa/confirm',json={"code":pyotp.TOTP(seed).now()},headers=headers)
    assert response.status_code==200,response.text
    return user,seed,response.json()['recovery_codes']

def login_password(client,email="colleague@howerob.com",password=PASSWORD):
    csrf=client.get('/api/auth/browser').json()['csrf']
    return client.post('/api/auth/login',json={"email":email,"password":password},headers={"X-CSRF-Token":csrf})

def test_migration_backup_owner_binding_and_old_session_rejected(system):
    access,client,legacy=system
    assert list(access.store.path.parent.glob('*.bak'))
    assert access.company.owner()==1
    assert access.store.session(legacy) is None
    client.cookies.set(COOKIE,legacy)
    assert client.get('/api/ports').status_code==401
    assert 'Request access' in client.get('/').text
    assert client.get('/static/data/ais_sample_zones.json',follow_redirects=False).status_code in {303,401}

@pytest.mark.parametrize('email',['colleague@other-company.com','a@sub.howerob.com','a@outlook.com'])
def test_any_domain_can_request_but_never_inherits_approval(system,email):
    access,client,_=system
    user,h=verified(access,client,claims(email=email))
    assert user['status']=='unapproved'
    assert client.post('/api/auth/request',json={'name':'External colleague','reason':'Business analysis access'},headers=h).status_code==200
    assert client.get('/api/ports').status_code==401


def test_google_gmail_request_is_bound_to_google_subject_not_email(system):
    access,client,_=system
    google={"iss":"https://accounts.google.com","sub":"google-123","email":"colleague@gmail.com",
            "email_verified":True,"name":"Gmail colleague"}
    user,headers=verified(access,client,google)
    assert client.post('/api/auth/request',json={'name':'Gmail colleague','reason':'Shipping analysis access'},headers=headers).status_code==200
    assert client.get('/api/ports').status_code==401
    approve(access,user)
    other,_=verified(access,client,claims('microsoft-123','colleague@gmail.com'))
    assert other['id']!=user['id'] and other['status']=='unapproved'
    with pytest.raises(HTTPException):
        access.company.verify_identity({**google,"sub":"unverified","email_verified":False})


def test_google_callback_verifies_request_without_dashboard_session(system):
    from urllib.parse import parse_qs,urlparse
    access,client,_=system
    access.google_identity.client_id='google-client'
    access.google_identity.client_secret='test-secret'
    async def authorization(state,nonce,verifier):
        return 'https://accounts.google.com/o/oauth2/v2/auth?state='+state
    access.google_identity.authorization_url=authorization
    access.google_identity.exchange=AsyncMock(return_value={
        "iss":"https://accounts.google.com","sub":"g-1","email":"person@gmail.com",
        "email_verified":True,"name":"Google person"})
    start=client.get('/auth/google/verify',follow_redirects=False)
    assert start.status_code==303
    state=parse_qs(urlparse(start.headers['location']).query)['state'][0]
    callback=client.get('/auth/google/callback',params={'state':state,'code':'synthetic'},follow_redirects=False)
    assert callback.status_code==303 and callback.headers['location']=='/auth/status'
    assert client.get('/api/auth/me').json()['status']=='unapproved'
    assert client.get('/api/ports').status_code==401
    assert client.get('/auth/google/callback',params={'state':state,'code':'synthetic'},follow_redirects=False).status_code==400


def test_identity_flows_cannot_be_redeemed_at_the_other_provider(system):
    access,client,_=system
    state,cookie,nonce,verifier=access.store.new_flow(provider='google')
    with pytest.raises(ValueError):access.store.consume_flow(state,cookie,provider='microsoft')
    assert access.store.consume_flow(state,cookie,provider='google')['provider']=='google'


def test_owner_can_connect_only_the_same_personal_outlook_identity(system):
    from urllib.parse import parse_qs,urlparse
    access,client,_=system
    owner_claims=claims('owner','owner@outlook.com',issuer=OWNER_ISSUER)
    owner,seed,codes=setup(access,client,owner_claims,owner=True)
    access.company.personal_mail.sender='owner@outlook.com'
    access.company.mail=access.company.personal_mail
    async def authorization(state,nonce,verifier):
        return 'https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize?state='+state
    access.identity.mail_authorization_url=authorization
    access.identity.mail_exchange=AsyncMock(return_value=(owner_claims,'refresh-token-synthetic'))
    start=client.get('/auth/mail/connect',follow_redirects=False)
    assert start.status_code==303
    state=parse_qs(urlparse(start.headers['location']).query)['state'][0]
    done=client.get('/auth/mail/callback',params={'state':state,'code':'synthetic'},follow_redirects=False)
    assert done.status_code==303 and done.headers['location']=='/auth/access-requests'
    assert access.company.personal_mail.configured
    with access.store.db() as db:
        encrypted=db.execute('SELECT refresh_token FROM mail_connections WHERE account_id=?',(owner['id'],)).fetchone()[0]
    assert encrypted!='refresh-token-synthetic'
    assert 'Connected' in client.get('/auth/access-requests').text
    assert client.get('/auth/mail/callback',params={'state':state,'code':'synthetic'},follow_redirects=False).status_code==400


def test_mail_consent_from_same_email_but_other_subject_is_rejected(system):
    access,client,_=system
    owner_claims=claims('owner','owner@outlook.com',issuer=OWNER_ISSUER)
    setup(access,client,owner_claims,owner=True)
    access.company.personal_mail.sender='owner@outlook.com'
    async def authorization(state,nonce,verifier):
        return 'https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize?state='+state
    access.identity.mail_authorization_url=authorization
    access.identity.mail_exchange=AsyncMock(return_value=(claims('impostor','owner@outlook.com',issuer=OWNER_ISSUER),'not-stored'))
    from urllib.parse import parse_qs,urlparse
    start=client.get('/auth/mail/connect',follow_redirects=False)
    state=parse_qs(urlparse(start.headers['location']).query)['state'][0]
    assert client.get('/auth/mail/callback',params={'state':state,'code':'synthetic'},follow_redirects=False).status_code==400
    assert not access.company.personal_mail.configured


def test_email_reset_requires_mailbox_and_authenticator(system):
    access,client,_=system
    user,seed,codes=setup(access,client)
    sent=[]
    class Sender:
        configured=True
        async def send(self,recipient,subject,body):sent.append((recipient,subject,body))
    access.company.mail=Sender()
    csrf=client.get('/api/auth/browser').json()['csrf']
    response=client.post('/api/auth/email-reset/request',json={'email':user['email']},headers={'X-CSRF-Token':csrf})
    assert response.status_code==200 and len(sent)==1
    token=sent[0][2].split('/auth/email-reset#')[1].split()[0]
    with access.store.db() as db:
        assert db.execute('SELECT hash FROM email_reset_tokens').fetchone()[0]!=token
    assert client.post('/api/auth/email-reset/complete',json={'token':token,'password':PASSWORD+' changed','code':'000000'},headers={'X-CSRF-Token':csrf}).status_code==400
    assert client.post('/api/auth/email-reset/complete',json={'token':token,'password':PASSWORD+' changed','code':codes[0]},headers={'X-CSRF-Token':csrf}).status_code==400
    code=pyotp.TOTP(seed).at((int(time.time()//30)+1)*30)
    assert client.post('/api/auth/email-reset/complete',json={'token':token,'password':PASSWORD+' changed','code':code},headers={'X-CSRF-Token':csrf}).status_code==200
    assert client.post('/api/auth/email-reset/complete',json={'token':token,'password':PASSWORD+' changed again','code':code},headers={'X-CSRF-Token':csrf}).status_code==400
    assert login_password(client,password=PASSWORD).status_code==401
    assert login_password(client,password=PASSWORD+' changed').status_code==200


def test_email_reset_delivery_failure_keeps_account_and_removes_link(system):
    access,client,_=system
    user,seed,codes=setup(access,client)
    class FailingSender:
        configured=True
        async def send(self,recipient,subject,body):raise ConnectionError('mail unavailable')
    access.company.mail=FailingSender()
    csrf=client.get('/api/auth/browser').json()['csrf']
    response=client.post('/api/auth/email-reset/request',json={'email':user['email']},headers={'X-CSRF-Token':csrf})
    assert response.status_code==200
    with access.store.db() as db:
        assert db.execute('SELECT count(*) FROM email_reset_tokens').fetchone()[0]==0
    assert login_password(client,password=PASSWORD).status_code==200


def test_email_reset_unknown_and_revoked_accounts_do_not_receive_mail(system):
    access,client,_=system
    user,seed,codes=setup(access,client)
    sent=[]
    class Sender:
        configured=True
        async def send(self,recipient,subject,body):sent.append(body)
    access.company.mail=Sender()
    csrf=client.get('/api/auth/browser').json()['csrf']
    unknown=client.post('/api/auth/email-reset/request',json={'email':'nobody@gmail.com'},headers={'X-CSRF-Token':csrf})
    known=client.post('/api/auth/email-reset/request',json={'email':user['email']},headers={'X-CSRF-Token':csrf})
    assert unknown.json()==known.json() and len(sent)==1
    token=sent[0].split('/auth/email-reset#')[1].split()[0]
    access.company.review(access.company.owner(),user['id'],'revoked',dict.fromkeys(SECTIONS,'hidden'))
    code=pyotp.TOTP(seed).at((int(time.time()//30)+1)*30)
    assert client.post('/api/auth/email-reset/complete',json={'token':token,'password':PASSWORD+' changed','code':code},headers={'X-CSRF-Token':csrf}).status_code==400

def test_owner_email_lookalike_is_not_owner(system):
    access,client,_=system
    user,_=verified(access,client,claims('other','owner@outlook.com',issuer=OWNER_ISSUER))
    assert user['id']!=access.company.owner() and user['status']=='unapproved'

def test_encryption_required_but_no_tenant_requirement(system):
    access,client,_=system
    access.company.tenant=''
    assert access.company.verify_identity(claims())
    user,headers=verified(access,client,claims('owner','owner@outlook.com',issuer=OWNER_ISSUER))
    assert user['id']==1
    assert client.get('/api/ports').status_code==401
    access.company.cipher=None
    assert client.post('/api/auth/password',json={'password':PASSWORD},headers=headers).status_code==503

def test_pending_duplicate_rejected_and_revoked_setup(system):
    access,client,_=system
    user,headers=verified(access,client)
    for _ in range(2):assert client.post('/api/auth/request',json={'name':'Colleague','reason':'Please allow access to selected sections'},headers=headers).status_code==200
    with access.store.db() as db:assert db.execute('SELECT count(*) FROM access_requests').fetchone()[0]==1
    assert client.get('/api/auth/me').json()['enrolment']=='pending'
    assert client.post('/api/auth/password',json={'password':PASSWORD},headers=headers).status_code==403
    access.company.review(1,user['id'],'rejected',dict.fromkeys(SECTIONS,'hidden'))
    verified_token=access.company.pre_token
    # Status can show a fresh verified identity without permitting rejected setup.
    token=access.company.verify_identity(claims());client.cookies.set(PRE_COOKIE,token)
    assert client.get('/api/auth/me').json()['status']=='rejected'
    assert client.get('/api/coal/dashboard').status_code==401
    assert client.post('/api/auth/password',json={'password':PASSWORD},headers=headers).status_code in {401,403}

def test_setup_argon_encrypted_seed_recovery_once_and_password_login(system):
    access,client,_=system
    user,seed,codes=setup(access,client)
    assert len(codes)==len(set(codes))==10
    me=client.get('/api/auth/me').json();assert me['authenticated'] and me['enrolment']=='active'
    with access.store.db() as db:
        credential=dict(db.execute('SELECT * FROM credentials WHERE account_id=?',(user['id'],)).fetchone())
        assert credential['password_hash'].startswith('$argon2id$')
        assert credential['seed']!=seed and seed not in str(credential)
        assert not db.execute('SELECT 1 FROM recovery_codes WHERE hash=?',(codes[0],)).fetchone()
    client.cookies.clear()
    result=login_password(client);assert result.status_code==200
    challenge_headers={'X-CSRF-Token':result.json()['csrf']}
    # The counter used to enrol cannot be replayed for login.
    assert client.post('/api/auth/challenge',json={'code':pyotp.TOTP(seed).now()},headers=challenge_headers).status_code==400
    assert client.post('/api/auth/challenge',json={'code':codes[0]},headers=challenge_headers).status_code==200
    assert client.get('/api/ports').status_code==200
    client.cookies.clear();result=login_password(client)
    assert client.post('/api/auth/challenge',json={'code':codes[0]},headers={'X-CSRF-Token':result.json()['csrf']}).status_code==400

def test_all_section_levels_and_unclassified_paths(system):
    access,client,_=system
    user,seed,codes=setup(access,client)
    endpoints={'voyage_analysis':'/api/voyage/calculate','port_activity':'/api/port-activity/analyze','energy':'/api/map/solar','ports':'/api/ports','india_coal':'/api/coal/dashboard','commodities':'/api/map/iron_ore_mines','news':'/api/news','live_ais':'/api/ais/search','weather':'/api/weather','rivers':'/api/river-levels','voyage_distance':'/api/route'}
    readonly_posts={'voyage_analysis','port_activity','voyage_distance'}
    for section,path in endpoints.items():
        with access.store.db() as db:db.execute('INSERT OR REPLACE INTO section_grants VALUES(?,?,?)',(user['id'],section,'hidden'))
        assert (client.post(path,json={},headers={'X-CSRF-Token':client.get('/api/auth/me').json()['csrf']}) if section in readonly_posts else client.get(path)).status_code==403
        with access.store.db() as db:db.execute('UPDATE section_grants SET level=? WHERE account_id=? AND section=?',('view',user['id'],section))
        assert (client.post(path,json={},headers={'X-CSRF-Token':client.get('/api/auth/me').json()['csrf']}) if section in readonly_posts else client.get(path)).status_code==200
    csrf={'X-CSRF-Token':client.get('/api/auth/me').json()['csrf']}
    for path in ['/api/coal/upload','/api/news/refresh','/api/port-activity/upload','/api/river-levels/refresh','/api/weather/cyclones/refresh']:
        assert client.post(path,json={},headers=csrf).status_code==403
    with access.store.db() as db:db.execute("UPDATE section_grants SET level='edit' WHERE account_id=?",(user['id'],))
    assert client.post('/api/coal/upload',json={},headers=csrf).status_code==200
    assert client.post('/api/coal/upload',json={}).status_code==403
    assert client.get('/api/npp/power-dashboard?force=true').status_code==403
    for path in ['/api/admin/access','/api/unclassified','/openapi.json','/static/data/secret.json','/api/data/user_hidden']:
        assert client.get(path,follow_redirects=False).status_code in {303,403}

def test_owner_only_admin_no_email_link_and_last_owner_protected(system):
    access,client,_=system
    owner,_,_=setup(access,client,claims('owner','owner@outlook.com',issuer=OWNER_ISSUER),owner=True)
    result=client.get('/api/admin/access');assert result.status_code==200
    assert 'password_hash' not in result.text and 'seed' not in result.text
    with pytest.raises(HTTPException):access.company.review(owner['id'],owner['id'],'revoked',dict.fromkeys(SECTIONS,'hidden'))
    user,h=verified(access,client)
    client.post('/api/auth/request',json={'name':'Colleague','reason':'Business analysis access'},headers=h);approve(access,user)
    # A distinct Microsoft subject with the same label receives no inherited grants.
    other,h=verified(access,client,claims('other'))
    assert other['status']=='unapproved' and access.company.grants(other)==dict.fromkeys(SECTIONS,'hidden')
    client.post('/api/auth/request',json={'name':'Other','reason':'Another identity test'},headers=h)
    with pytest.raises(HTTPException) as exc:approve(access,other)
    assert exc.value.status_code==409

def test_reset_requires_fresh_identity_and_factor_ends_sessions(system):
    access,client,_=system
    user,seed,codes=setup(access,client);old=client.cookies.get(COOKIE)
    user,h=verified(access,client)
    assert client.post('/api/auth/reset',json={'password':PASSWORD+'new','code':'000000'},headers=h).status_code==400
    assert client.post('/api/auth/reset',json={'password':PASSWORD+'new','code':codes[0]},headers=h).status_code==200
    assert access.store.session(old) is None
    assert client.get('/api/ports').status_code==401
    assert login_password(client).status_code==401
    assert login_password(client,password=PASSWORD+'new').status_code==200

def test_reduction_revocation_persistence_and_rate_limits(system):
    access,client,_=system
    user,seed,codes=setup(access,client);token=client.cookies.get(COOKIE)
    access.company.review(1,user['id'],'approved',dict.fromkeys(SECTIONS,'hidden'))
    assert access.store.session(token) is None
    restarted=AccessControl(access.config,access.store.path)
    assert restarted.company.grants(user)==dict.fromkeys(SECTIONS,'hidden')
    assert restarted.company.enrolment(user)=='active'
    client.cookies.clear()
    for _ in range(8):assert login_password(client,password='wrong').status_code==401
    assert login_password(client,password='wrong').status_code==429

def test_policy_classifies_shared_and_cross_section_data():
    assert requirements('/api/map/solar','GET',{})==(['energy'],False)
    assert requirements('/api/layer-facets','GET',{'trackers':'solar,coal_mines'})==(['energy','commodities'],False)
    assert requirements('/api/unknown','GET',{}) is None
    assert requirements('/api/weather/cyclones/refresh','POST',{})==(['weather'],True)

def test_password_bounds_csrf_and_microsoft_verification_no_data(system):
    access,client,_=system
    user,h=verified(access,client);client.post('/api/auth/request',json={'name':'Colleague','reason':'Business analysis access'},headers=h);approve(access,user)
    user,h=verified(access,client)
    assert client.post('/api/auth/password',json={'password':PASSWORD}).status_code==403
    for candidate in ['short','x'*129]:assert client.post('/api/auth/password',json={'password':candidate},headers=h).status_code==400
    assert client.get('/api/ports').status_code==401

def test_authenticated_stream_reduction_and_origin(system,monkeypatch):
    import access_control as module
    access,client,_=system;user,_,_=setup(access,client)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/api/ais/stream',headers={'Origin':'https://evil.example','Cookie':COOKIE+'='+client.cookies.get(COOKIE)}):pass
    monkeypatch.setattr(module,'SESSION_CHECK_SECONDS',0.02)
    with client.websocket_connect('/api/ais/stream',headers={'Origin':access.config.base_url,'Cookie':COOKIE+'='+client.cookies.get(COOKIE)}) as ws:
        assert ws.receive_text()=='connected'
        access.company.review(1,user['id'],'approved',dict.fromkeys(SECTIONS,'hidden'))
        with pytest.raises(WebSocketDisconnect):ws.receive_text()

def test_lost_factor_admin_approval_invalidates_credentials_and_setup(system):
    access,client,_=system;user,_,_=setup(access,client);token=client.cookies.get(COOKIE)
    user,h=verified(access,client)
    assert client.post('/api/auth/lost-factor',json={},headers=h).status_code==200
    assert client.post(f'/api/admin/access/accounts/{user["id"]}/reset-factor',json={},headers=h).status_code==403
    # Separate owner client with complete MFA; no email link or bypass.
    owner_client=TestClient(client.app,base_url=access.config.base_url)
    setup(access,owner_client,claims('owner','owner@outlook.com',issuer=OWNER_ISSUER),owner=True)
    csrf=owner_client.get('/api/auth/me').json()['csrf']
    assert owner_client.post(f'/api/admin/access/accounts/{user["id"]}/reset-factor',json={},headers={'X-CSRF-Token':csrf}).status_code==200
    assert access.store.session(token) is None and access.company.enrolment(user)=='setup_required'
    assert client.post('/api/auth/password',json={'password':PASSWORD},headers=h).status_code==401
    _,h=verified(access,client)
    assert client.post('/api/auth/password',json={'password':PASSWORD},headers=h).status_code==200

@pytest.mark.parametrize('field',['expires_at','last_seen'])
def test_complete_session_expiry(system,field):
    access,client,_=system;setup(access,client)
    with access.store.db() as db:db.execute('UPDATE sessions SET '+field+'=?',(time.time()-3600,))
    assert client.get('/api/ports').status_code==401

def test_callback_verification_never_issues_session(system):
    access,client,_=system
    result=client.get('/auth/verify',follow_redirects=False);state=dict(__import__('urllib.parse',fromlist=['parse_qsl']).parse_qsl(__import__('urllib.parse',fromlist=['urlparse']).urlparse(result.headers['location']).query))['state']
    with patch.object(access.identity,'exchange',AsyncMock(return_value=claims())):
        callback=client.get('/auth/callback?state='+state+'&code=synthetic',follow_redirects=False)
    assert callback.status_code==303
    assert client.cookies.get(PRE_COOKIE) and not client.cookies.get(COOKIE)
    assert client.get('/api/ports').status_code==401
