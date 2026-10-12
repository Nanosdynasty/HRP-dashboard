import asyncio

import httpx
from cryptography.fernet import Fernet
from access_control import AccessStore

import mail_delivery


def test_microsoft365_graph_sender_uses_only_configured_mailbox(monkeypatch):
    monkeypatch.setenv("MS365_MAIL_TENANT_ID","12345678-1234-1234-1234-123456789012")
    monkeypatch.setenv("MS365_MAIL_CLIENT_ID","12345678-1234-1234-1234-123456789013")
    monkeypatch.setenv("MS365_MAIL_CLIENT_SECRET","test-only-secret")
    monkeypatch.setenv("MS365_MAIL_SENDER","dashboard@howerob.com")
    seen=[]
    def handle(request):
        seen.append(request)
        if request.url.path.endswith('/token'):
            return httpx.Response(200,json={"access_token":"test-only-access-token"})
        return httpx.Response(202)
    transport=httpx.MockTransport(handle)
    original=httpx.AsyncClient
    monkeypatch.setattr(mail_delivery.httpx,"AsyncClient",lambda **kwargs:original(transport=transport,**kwargs))
    sender=mail_delivery.Microsoft365Mail()
    asyncio.run(sender.send("person@gmail.com","Reset","A test-only reset notice"))
    assert len(seen)==2
    assert str(seen[1].url)=="https://graph.microsoft.com/v1.0/users/dashboard%40howerob.com/sendMail"
    assert seen[1].headers['authorization']=='Bearer test-only-access-token'
    assert 'person@gmail.com' in seen[1].content.decode()


def test_personal_outlook_sender_uses_encrypted_delegated_refresh_token(monkeypatch,tmp_path):
    monkeypatch.setenv('MAIL_PERSONAL_SENDER','owner@outlook.com')
    store=AccessStore(tmp_path/'access.sqlite3')
    with store.db() as db:
        db.execute('CREATE TABLE mail_connections(account_id INTEGER PRIMARY KEY,sender TEXT,refresh_token TEXT,connected_at REAL)')
    cipher=Fernet(Fernet.generate_key())
    sender=mail_delivery.OutlookPersonalMail(store,cipher,1,'client','secret')
    sender.connect('original-refresh')
    with store.db() as db:
        encrypted=db.execute('SELECT refresh_token FROM mail_connections').fetchone()[0]
    assert 'original-refresh' not in encrypted
    seen=[]
    def handle(request):
        seen.append(request)
        if request.url.path.endswith('/token'):
            assert b'original-refresh' in request.content
            return httpx.Response(200,json={'access_token':'delegated-access','refresh_token':'rotated-refresh'})
        return httpx.Response(202)
    original=httpx.AsyncClient
    monkeypatch.setattr(mail_delivery.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handle),**kwargs))
    asyncio.run(sender.send('person@gmail.com','Reset','A test-only reset notice'))
    assert str(seen[1].url)=='https://graph.microsoft.com/v1.0/me/sendMail'
    assert seen[1].headers['authorization']=='Bearer delegated-access'
    with store.db() as db:
        rotated=db.execute('SELECT refresh_token FROM mail_connections').fetchone()[0]
    assert cipher.decrypt(rotated.encode()).decode()=='rotated-refresh'


def test_personal_mailbox_cannot_use_app_only_work_mail_mode(monkeypatch):
    monkeypatch.setenv('MS365_MAIL_TENANT_ID','12345678-1234-1234-1234-123456789012')
    monkeypatch.setenv('MS365_MAIL_CLIENT_ID','12345678-1234-1234-1234-123456789013')
    monkeypatch.setenv('MS365_MAIL_CLIENT_SECRET','test-secret')
    monkeypatch.setenv('MS365_MAIL_SENDER','owner@outlook.com')
    assert not mail_delivery.Microsoft365Mail().configured
