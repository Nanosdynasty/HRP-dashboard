"""Graph delivery from a scoped Microsoft 365 mailbox or owner-consented Outlook."""
from __future__ import annotations

import os
import re
import uuid
from urllib.parse import quote

import httpx


class MailConfigurationError(RuntimeError):
    pass


class Microsoft365Mail:
    def __init__(self):
        self.tenant = os.getenv("MS365_MAIL_TENANT_ID", "").strip()
        self.client_id = os.getenv("MS365_MAIL_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("MS365_MAIL_CLIENT_SECRET", "").strip()
        self.sender = os.getenv("MS365_MAIL_SENDER", "").strip().casefold()

    @property
    def configured(self):
        try:
            uuid.UUID(self.tenant)
            uuid.UUID(self.client_id)
        except ValueError:
            return False
        return bool(self.client_secret and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", self.sender)
                    and self.sender.rsplit("@",1)[1] not in {"outlook.com","hotmail.com","live.com","msn.com"})

    async def send(self, recipient: str, subject: str, body: str):
        if not self.configured:
            raise MailConfigurationError("Microsoft 365 mail is not configured.")
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", recipient) or len(recipient) > 254:
            raise ValueError("Invalid recipient.")
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/token",
                data={"client_id":self.client_id,"client_secret":self.client_secret,
                      "scope":"https://graph.microsoft.com/.default","grant_type":"client_credentials"})
            response.raise_for_status()
            access_token = response.json()["access_token"]
            response = await client.post(
                "https://graph.microsoft.com/v1.0/users/" + quote(self.sender, safe="") + "/sendMail",
                headers={"Authorization":"Bearer " + access_token},
                json={"message":{"subject":subject,
                                 "body":{"contentType":"Text","content":body},
                                 "toRecipients":[{"emailAddress":{"address":recipient}}]},
                      "saveToSentItems":True})
            response.raise_for_status()


class OutlookPersonalMail:
    """Owner-consented Graph sender for a personal Microsoft mailbox."""

    def __init__(self, store, cipher, owner_id, client_id, client_secret):
        self.store,self.cipher,self.owner_id=store,cipher,owner_id
        self.client_id,self.client_secret=client_id,client_secret
        self.sender=os.getenv("MAIL_PERSONAL_SENDER","").strip().casefold()

    @property
    def connect_ready(self):
        return bool(self.store and self.cipher and self.owner_id and self.client_id and self.client_secret
                    and re.fullmatch(r"[^\s@]+@(outlook\.com|hotmail\.com|live\.com|msn\.com)",self.sender))

    @property
    def configured(self):
        if not self.connect_ready:return False
        with self.store.db() as db:
            return bool(db.execute("SELECT 1 FROM mail_connections WHERE account_id=? AND sender=?",
                                   (self.owner_id,self.sender)).fetchone())

    def connect(self, refresh_token):
        if not self.connect_ready or not refresh_token:
            raise MailConfigurationError("Personal mail connection is unavailable.")
        encrypted=self.cipher.encrypt(refresh_token.encode()).decode()
        with self.store.db() as db:
            db.execute("INSERT INTO mail_connections(account_id,sender,refresh_token,connected_at) "
                       "VALUES(?,?,?,strftime('%s','now')) ON CONFLICT(account_id) DO UPDATE SET "
                       "sender=excluded.sender,refresh_token=excluded.refresh_token,connected_at=excluded.connected_at",
                       (self.owner_id,self.sender,encrypted))
            self.store.event(db,self.owner_id,"personal_mail_connected")

    async def send(self, recipient: str, subject: str, body: str):
        if not self.configured:
            raise MailConfigurationError("Personal Outlook mail is not connected.")
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",recipient) or len(recipient)>254:
            raise ValueError("Invalid recipient.")
        with self.store.db() as db:
            row=db.execute("SELECT refresh_token FROM mail_connections WHERE account_id=? AND sender=?",
                           (self.owner_id,self.sender)).fetchone()
        refresh_token=self.cipher.decrypt(row[0].encode()).decode()
        async with httpx.AsyncClient(timeout=15) as client:
            response=await client.post("https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
                data={"client_id":self.client_id,"client_secret":self.client_secret,
                      "grant_type":"refresh_token","refresh_token":refresh_token})
            response.raise_for_status()
            token=response.json()
            replacement=token.get("refresh_token")
            if replacement:
                encrypted=self.cipher.encrypt(replacement.encode()).decode()
                with self.store.db() as db:
                    db.execute("UPDATE mail_connections SET refresh_token=? WHERE account_id=? AND sender=? AND refresh_token=?",
                               (encrypted,self.owner_id,self.sender,row[0]))
            response=await client.post("https://graph.microsoft.com/v1.0/me/sendMail",
                headers={"Authorization":"Bearer "+token["access_token"]},
                json={"message":{"subject":subject,"body":{"contentType":"Text","content":body},
                                 "toRecipients":[{"emailAddress":{"address":recipient}}]},
                      "saveToSentItems":True})
            response.raise_for_status()
