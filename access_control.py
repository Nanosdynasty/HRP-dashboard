"""Microsoft identity login and revocable, identity-bound dashboard access.

Email claims only label requests. Approval always binds a validated issuer/sub.
No Microsoft access/refresh tokens are stored after the callback.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

log = logging.getLogger("access")
COOKIE = "hrp_session"
FLOW_COOKIE = "hrp_login_flow"
SESSION_SECONDS = 8 * 3600
IDLE_SECONDS = 30 * 60
SESSION_CHECK_SECONDS = 5
MICROSOFT = "https://login.microsoftonline.com"
# Explicit operations which do not change shared source data or permissions.
VIEWER_POSTS = frozenset({
    "/api/route", "/api/voyage/calculate", "/api/voyage/export",
    "/api/port-activity/analyze", "/api/port-activity/export",
    "/api/ais/snapshot", "/api/vessel/track", "/api/chat",
    "/api/coal/research/query", "/auth/logout",
})
AUTOMATION_POSTS = frozenset({
    "/api/coal/refresh", "/api/news/refresh", "/api/river-levels/refresh",
    "/api/imd/coastal-weather/refresh", "/api/bmkg/marine-weather/refresh",
    "/api/sea/marine-weather/refresh", "/api/major-port-weather/refresh",
    "/api/weather/cyclones/refresh",
})
PUBLIC_PATHS = frozenset({
    "/auth/login", "/auth/callback", "/auth/status", "/api/auth/me",
    "/api/health", "/static/auth/auth.css", "/static/auth/login.js",
    "/static/auth/access.js", "/static/img/howe-robinson-logo.svg",
})


class CallbackLogFilter(logging.Filter):
    """Uvicorn normally logs the callback query containing authorization codes."""
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            target = str(args[2])
            if target.split("?", 1)[0] in {"/auth/callback", "/auth/google/callback", "/auth/mail/callback"}:
                args[2] = target.split("?", 1)[0]
                record.args = tuple(args)
        return True


logging.getLogger("uvicorn.access").addFilter(CallbackLogFilter())


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def email_label(value: str) -> str:
    value = value.strip().casefold()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value) or len(value) > 254:
        raise ValueError("Enter a complete email address.")
    return value


@dataclass
class AuthConfig:
    enabled: bool = True
    production: bool = False
    base_url: str = "http://127.0.0.1:8000"
    client_id: str = ""
    client_secret: str = ""
    admin_issuer: str = ""
    admin_subject: str = ""
    automation_token: str = ""
    storage_error: str = ""

    @classmethod
    def from_env(cls, storage: Path):
        azure = bool(os.getenv("WEBSITE_SITE_NAME"))
        production = azure or bool(os.getenv("RENDER")) or os.getenv("APP_ENV", "development").lower() == "production"
        enabled = production or os.getenv("HRP_SSO_ENABLED", "").lower() == "true" or os.getenv("APP_AUTH_ENABLED", "true").lower() != "false"
        base = os.getenv("AUTH_BASE_URL", os.getenv("RENDER_EXTERNAL_URL", "http://127.0.0.1:8000")).rstrip("/")
        parsed = urlparse(base)
        error = ""
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:
            error = "AUTH_BASE_URL must be an origin without a path."
        if production and parsed.scheme != "https":
            error = "Production authentication requires an HTTPS AUTH_BASE_URL."
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            error = "HTTP authentication is allowed only on localhost. Use HTTPS for hosted access."
        # A configured folder is not proof of a mounted Render disk.
        if os.getenv("RENDER") and not os.path.ismount(storage):
            error = "Access storage requires a persistent disk mounted at HRP_STORAGE_DIR."
        if azure:
            # App Service's shared /home filesystem does not support SQLite's
            # exclusive locks. Use an Azure VM's managed disk for this release.
            error = "Azure App Service shared storage is incompatible with the SQLite access database. Use a persistent VM disk."
        return cls(enabled, production, base,
                   os.getenv("MICROSOFT_CLIENT_ID", "").strip(),
                   os.getenv("MICROSOFT_CLIENT_SECRET", "").strip(),
                   os.getenv("AUTH_ADMIN_ISSUER", "").strip(),
                   os.getenv("AUTH_ADMIN_SUBJECT", "").strip(),
                   os.getenv("APP_ADMIN_TOKEN", "").strip(), error)

    @property
    def configured(self):
        return bool(self.client_id and self.client_secret and not self.storage_error)

    @property
    def secure_cookie(self):
        return self.base_url.startswith("https://")


class AccessStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS accounts (
              id INTEGER PRIMARY KEY, issuer TEXT NOT NULL, subject TEXT NOT NULL,
              email TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL,
              role TEXT NOT NULL DEFAULT 'viewer', created_at REAL NOT NULL,
              UNIQUE(issuer, subject));
            CREATE TABLE IF NOT EXISTS invitations (
              email TEXT PRIMARY KEY, active INTEGER NOT NULL, created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (
              hash TEXT PRIMARY KEY, account_id INTEGER NOT NULL, csrf TEXT NOT NULL,
              created_at REAL NOT NULL, last_seen REAL NOT NULL, expires_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS flows (
              hash TEXT PRIMARY KEY, cookie_hash TEXT NOT NULL, nonce TEXT NOT NULL,
              verifier TEXT NOT NULL, created_at REAL NOT NULL, provider TEXT NOT NULL DEFAULT 'microsoft');
            CREATE TABLE IF NOT EXISTS audit (
              id INTEGER PRIMARY KEY, occurred_at REAL NOT NULL,
              actor INTEGER, action TEXT NOT NULL, target TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            if "provider" not in {row[1] for row in db.execute("PRAGMA table_info(flows)")}:
                db.execute("ALTER TABLE flows ADD COLUMN provider TEXT NOT NULL DEFAULT 'microsoft'")

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def event(db, actor, action, target=""):
        db.execute("INSERT INTO audit(occurred_at,actor,action,target) VALUES(?,?,?,?)",
                   (time.time(), actor, action, str(target)[:500]))

    def _bootstrap_owner(self, db, config: AuthConfig):
        if not config.admin_issuer or not config.admin_subject:
            return False
        if db.execute("SELECT 1 FROM settings WHERE key='owner_bootstrapped'").fetchone():
            return False
        # Accounts are created only after a validated Microsoft callback.
        row = db.execute("SELECT id FROM accounts WHERE issuer=? AND subject=?",
                         (config.admin_issuer, config.admin_subject)).fetchone()
        if not row:
            return False
        db.execute("UPDATE accounts SET status='approved',role='admin' WHERE id=?", (row["id"],))
        db.execute("INSERT INTO settings VALUES('owner_bootstrapped','true')")
        self.event(db, row["id"], "owner_bootstrapped", row["id"])
        return True

    def bootstrap_owner(self, config: AuthConfig):
        """Activate the configured, previously verified owner once on restart."""
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._bootstrap_owner(db, config)

    def login(self, claims, config: AuthConfig):
        issuer, subject = claims["iss"], claims["sub"]
        label = str(claims.get("email") or claims.get("preferred_username") or "")[:254].strip().casefold()
        name = str(claims.get("name") or label or "Microsoft account")[:200]
        now = time.time()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM accounts WHERE issuer=? AND subject=?", (issuer, subject)).fetchone()
            if not row:
                invited = db.execute("SELECT 1 FROM invitations WHERE email=? AND active=1", (label,)).fetchone()
                status = "pending" if invited else "unapproved"
                db.execute("INSERT INTO accounts(issuer,subject,email,name,status,created_at) VALUES(?,?,?,?,?,?)",
                           (issuer, subject, label, name, status, now))
                row = db.execute("SELECT * FROM accounts WHERE issuer=? AND subject=?", (issuer, subject)).fetchone()
            else:
                db.execute("UPDATE accounts SET email=?,name=? WHERE id=?", (label, name, row["id"]))
            self._bootstrap_owner(db, config)
            # An invitation added after the first login permits a new request, not access.
            db.execute("UPDATE accounts SET status='pending' WHERE id=? AND status='unapproved' AND EXISTS "
                       "(SELECT 1 FROM invitations WHERE email=? AND active=1)", (row["id"], label))
            self.event(db, row["id"], "login")
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            db.execute("DELETE FROM sessions WHERE expires_at<? OR last_seen<?", (now, now-IDLE_SECONDS))
            db.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?)", (digest(token), row["id"], csrf, now, now, now+SESSION_SECONDS))
        return token

    def session(self, token: str, touch=True):
        if not token:
            return None
        now = time.time()
        with self.db() as db:
            row = db.execute("SELECT a.*,s.csrf,s.hash,s.expires_at,s.last_seen FROM sessions s JOIN accounts a "
                             "ON a.id=s.account_id WHERE s.hash=?", (digest(token),)).fetchone()
            if not row:
                return None
            if row["expires_at"] <= now or row["last_seen"] <= now-IDLE_SECONDS:
                db.execute("DELETE FROM sessions WHERE hash=?", (row["hash"],))
                return None
            if touch:
                db.execute("UPDATE sessions SET last_seen=? WHERE hash=?", (now, row["hash"]))
            return dict(row)

    def logout(self, token):
        with self.db() as db:
            row = db.execute("SELECT account_id FROM sessions WHERE hash=?", (digest(token),)).fetchone()
            db.execute("DELETE FROM sessions WHERE hash=?", (digest(token),))
            if row:
                self.event(db, row[0], "logout")

    def new_flow(self, provider="microsoft"):
        if provider not in {"microsoft","google","microsoft_mail"}:
            raise ValueError("Unsupported identity provider.")
        state, cookie, nonce, verifier = [secrets.token_urlsafe(32) for _ in range(4)]
        with self.db() as db:
            db.execute("DELETE FROM flows WHERE created_at<?", (time.time()-600,))
            if db.execute("SELECT count(*) FROM flows").fetchone()[0] >= 10000:
                raise HTTPException(429, "Too many sign-in attempts. Please wait and try again.")
            db.execute("INSERT INTO flows VALUES(?,?,?,?,?,?)", (digest(state), digest(cookie), nonce, verifier, time.time(),provider))
        return state, cookie, nonce, verifier

    def consume_flow(self, state, cookie, provider="microsoft"):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM flows WHERE hash=?", (digest(state),)).fetchone()
            if not row or row["provider"] != provider or row["created_at"] < time.time()-600 or not hmac.compare_digest(row["cookie_hash"], digest(cookie)):
                raise ValueError("Login expired or could not be verified. Start sign-in again.")
            db.execute("DELETE FROM flows WHERE hash=?", (digest(state),))
        return dict(row)

    def listing(self):
        with self.db() as db:
            return {"accounts": [dict(r) for r in db.execute("SELECT * FROM accounts ORDER BY created_at DESC")],
                    "invitations": [dict(r) for r in db.execute("SELECT * FROM invitations ORDER BY email")],
                    "audit": [dict(r) for r in db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 100")]}

    def invite(self, value, active, actor):
        label = email_label(value)
        with self.db() as db:
            db.execute("INSERT INTO invitations VALUES(?,?,?) ON CONFLICT(email) DO UPDATE SET active=excluded.active",
                       (label, int(active), time.time()))
            if active:
                db.execute("UPDATE accounts SET status='pending' WHERE email=? AND status='unapproved'", (label,))
            self.event(db, actor, "invitation_enabled" if active else "invitation_disabled", label)

    def update_account(self, account_id, status, role, actor):
        if status not in {"approved", "revoked"} or role not in {"admin", "viewer"}:
            raise ValueError("Choose approved/revoked and admin/viewer.")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
            if not row:
                raise ValueError("Account not found.")
            if status == "approved" and row["status"] != "approved":
                invited = db.execute("SELECT 1 FROM invitations WHERE email=? AND active=1", (row["email"],)).fetchone()
                if not invited:
                    raise ValueError("Add an active email invitation before approving this identity.")
            if row["status"] == "approved" and row["role"] == "admin" and (status != "approved" or role != "admin"):
                count = db.execute("SELECT count(*) FROM accounts WHERE status='approved' AND role='admin'").fetchone()[0]
                if count <= 1:
                    raise ValueError("The last active administrator cannot be revoked or demoted.")
            db.execute("UPDATE accounts SET status=?,role=? WHERE id=?", (status, role, account_id))
            # Role changes and approvals require a fresh login as well as revocations.
            db.execute("DELETE FROM sessions WHERE account_id=?", (account_id,))
            self.event(db, actor, f"account_{status}_{role}", account_id)


class MicrosoftIdentity:
    def __init__(self, config):
        self.config = config
        self.keys = None
        self.keys_at = 0

    def client(self, scope="openid profile email", redirect_path="/auth/callback"):
        from authlib.integrations.httpx_client import AsyncOAuth2Client
        return AsyncOAuth2Client(self.config.client_id, self.config.client_secret,
                                 redirect_uri=self.config.base_url + redirect_path,
                                 scope=scope, token_endpoint_auth_method="client_secret_post",
                                 code_challenge_method="S256", timeout=20)

    async def authorization_url(self, state, nonce, verifier):
        async with self.client() as client:
            url, _ = client.create_authorization_url(MICROSOFT + "/common/oauth2/v2.0/authorize",
                                                      state=state, nonce=nonce, code_verifier=verifier,
                                                      response_mode="query", prompt="select_account")
        return url

    async def jwks(self, force=False):
        if force or not self.keys or time.time()-self.keys_at > 3600:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(MICROSOFT + "/common/discovery/v2.0/keys")
                response.raise_for_status()
                self.keys = response.json()
                self.keys_at = time.time()
        return self.keys

    @staticmethod
    def validate_token(token, keys, config, nonce, access_token=None):
        from authlib.jose import JsonWebToken
        from authlib.oidc.core import CodeIDToken
        # Unverified tenant is used ONLY to constrain the expected signed issuer.
        part = token.split(".")[1]
        if len(part) > 24000:
            raise ValueError("Invalid identity token.")
        untrusted = json.loads(base64.urlsafe_b64decode(part + "="*((-len(part)) % 4)))
        tenant = str(uuid.UUID(untrusted["tid"]))
        issuer = f"{MICROSOFT}/{tenant}/v2.0"
        permitted = [k for k in keys["keys"] if not k.get("issuer") or
                     k["issuer"].replace("{tenantid}", tenant) == issuer]
        claims = JsonWebToken(["RS256"]).decode(token, {"keys": permitted}, claims_cls=CodeIDToken,
            claims_options={"iss": {"essential": True, "value": issuer},
                            "aud": {"essential": True, "value": config.client_id},
                            "sub": {"essential": True}, "exp": {"essential": True},
                            "iat": {"essential": True}, "tid": {"essential": True, "value": tenant},
                            "nonce": {"essential": True, "value": nonce}},
            claims_params={"client_id": config.client_id, "nonce": nonce, "access_token": access_token})
        claims.validate(leeway=30)
        return dict(claims)

    async def exchange(self, code, nonce, verifier):
        async with self.client() as client:
            token = await client.fetch_token(MICROSOFT + "/common/oauth2/v2.0/token", code=code,
                                              code_verifier=verifier)
        keys = await self.jwks()
        # Fetch rotated keys only when the token's signing key is unknown.
        header_part = token["id_token"].split(".")[0]
        header = json.loads(base64.urlsafe_b64decode(header_part + "="*((-len(header_part)) % 4)))
        if header.get("kid") not in {k.get("kid") for k in keys["keys"]}:
            keys = await self.jwks(force=True)
        return self.validate_token(token["id_token"], keys, self.config, nonce, token.get("access_token"))

    async def mail_authorization_url(self, state, nonce, verifier):
        async with self.client("openid profile email offline_access Mail.Send", "/auth/mail/callback") as client:
            url, _ = client.create_authorization_url(MICROSOFT + "/consumers/oauth2/v2.0/authorize",
                state=state, nonce=nonce, code_verifier=verifier, response_mode="query", prompt="select_account")
        return url

    async def mail_exchange(self, code, nonce, verifier):
        async with self.client("openid profile email offline_access Mail.Send", "/auth/mail/callback") as client:
            token = await client.fetch_token(MICROSOFT + "/consumers/oauth2/v2.0/token",
                                             code=code, code_verifier=verifier)
        keys = await self.jwks()
        header_part = token["id_token"].split(".")[0]
        header = json.loads(base64.urlsafe_b64decode(header_part + "="*((-len(header_part)) % 4)))
        if header.get("kid") not in {k.get("kid") for k in keys["keys"]}:
            keys = await self.jwks(force=True)
        claims = self.validate_token(token["id_token"], keys, self.config, nonce, token.get("access_token"))
        if not token.get("refresh_token") or "Mail.Send" not in token.get("scope", "").split():
            raise ValueError("Mail.Send consent or offline refresh access was not granted.")
        return claims, token["refresh_token"]


class GoogleIdentity:
    """Google identity verification for access requests; never grants dashboard access."""

    def __init__(self, client_id, client_secret, base_url):
        self.client_id, self.client_secret, self.base_url = client_id, client_secret, base_url
        self.keys, self.keys_at = None, 0

    def client(self):
        from authlib.integrations.httpx_client import AsyncOAuth2Client
        return AsyncOAuth2Client(self.client_id, self.client_secret,
                                 redirect_uri=self.base_url + "/auth/google/callback",
                                 scope="openid profile email", token_endpoint_auth_method="client_secret_post",
                                 code_challenge_method="S256", timeout=20)

    async def authorization_url(self, state, nonce, verifier):
        async with self.client() as client:
            url, _ = client.create_authorization_url("https://accounts.google.com/o/oauth2/v2/auth",
                state=state, nonce=nonce, code_verifier=verifier, prompt="select_account")
        return url

    async def jwks(self, force=False):
        if force or not self.keys or time.time()-self.keys_at > 3600:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get("https://www.googleapis.com/oauth2/v3/certs")
                response.raise_for_status()
                self.keys, self.keys_at = response.json(), time.time()
        return self.keys

    @staticmethod
    def validate_token(token, keys, client_id, nonce, access_token=None):
        from authlib.jose import JsonWebToken
        from authlib.oidc.core import CodeIDToken
        claims = JsonWebToken(["RS256"]).decode(token, keys, claims_cls=CodeIDToken,
            claims_options={"iss": {"essential": True, "value": "https://accounts.google.com"},
                            "aud": {"essential": True, "value": client_id},
                            "sub": {"essential": True}, "exp": {"essential": True},
                            "iat": {"essential": True},
                            "nonce": {"essential": True, "value": nonce},
                            "email": {"essential": True},
                            "email_verified": {"essential": True, "value": True}},
            claims_params={"client_id": client_id, "nonce": nonce, "access_token": access_token})
        claims.validate(leeway=30)
        return dict(claims)

    async def exchange(self, code, nonce, verifier):
        async with self.client() as client:
            token = await client.fetch_token("https://oauth2.googleapis.com/token", code=code,
                                             code_verifier=verifier)
        keys = await self.jwks()
        header_part = token["id_token"].split(".")[0]
        header = json.loads(base64.urlsafe_b64decode(header_part + "="*((-len(header_part)) % 4)))
        if header.get("kid") not in {k.get("kid") for k in keys["keys"]}:
            keys = await self.jwks(force=True)
        return self.validate_token(token["id_token"], keys, self.client_id, nonce,
                                   token.get("access_token"))


def page(title, message, *, identity=None, login=False):
    details = ""
    if identity:
        details = ("<p>Share these identity identifiers with the administrator for approval. "
                   "They are identifiers, not passwords.</p><dl><dt>Account label</dt><dd>" + html.escape(identity["email"]) +
                   "</dd><dt>Issuer</dt><dd>" + html.escape(identity["issuer"]) +
                   "</dd><dt>Subject</dt><dd>" + html.escape(identity["subject"]) + "</dd></dl>")
    action = '<a class="button" href="/auth/login?start=1">Sign in with Microsoft</a>' if login else ""
    if identity:
        action += '<button id="logout" type="button">Sign out</button><script src="/static/auth/login.js"></script>'
    return HTMLResponse('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
        'content="width=device-width,initial-scale=1"><title>Howe Robinson · Access</title>'
        '<link rel="stylesheet" href="/static/auth/auth.css"></head><body><main class="access-card">'
        '<img src="/static/img/howe-robinson-logo.svg" alt="Howe Robinson Partners"><h1>' + html.escape(title) +
        '</h1><p>' + html.escape(message) + '</p>' + details + action + '</main></body></html>',
        headers={"Cache-Control": "no-store", "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})


class InvitationInput(BaseModel):
    email: str = Field(max_length=254)
    active: bool = True


class ApprovalInput(BaseModel):
    status: str
    role: str = "viewer"


class AccessControl:
    def __init__(self, config: AuthConfig, path: Path):
        self.config = config
        self.store = None
        try:
            if not config.storage_error:
                self.store = AccessStore(path)
                if config.configured and os.getenv("HRP_SSO_ENABLED", "").lower() != "true":
                    self.store.bootstrap_owner(config)
        except (OSError, sqlite3.Error):
            config.storage_error = "Access storage is unavailable."
            log.error("Access storage unavailable; protected access disabled")
        self.identity = MicrosoftIdentity(config)
        self.google_identity = GoogleIdentity(os.getenv("GOOGLE_CLIENT_ID", "").strip(),
                                              os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
                                              config.base_url)
        self.company = None
        self.sso = None
        if os.getenv("HRP_SSO_ENABLED", "").lower() == "true":
            from hrp_sso import HRPSSO
            self.sso = HRPSSO(self)
        elif self.store:
            from company_auth import CompanyAccess
            self.company = CompanyAccess(self)

    def current(self, request, touch=True):
        if self.sso:
            return self.sso.session(request.cookies.get(COOKIE, ""), touch)
        return self.store.session(request.cookies.get(COOKIE, ""), touch) if self.store else None

    def admin(self, request):
        user = self.current(request)
        if not self.company or not self.company.authenticated(user) or user["role"] != "admin":
            raise HTTPException(403, "Administrator access required.")
        return user

    def router(self):
        if self.sso:
            return self.sso.router()
        if self.company:
            return self.company.router()
        router = APIRouter()

        @router.get("/auth/login", response_class=HTMLResponse)
        async def login(request: Request, start: bool = False):
            # The flow cookie must live on the callback host. In particular,
            # localhost and 127.0.0.1 do not share cookies. Match Host rather than
            # the internal scheme so HTTPS termination on Render does not loop.
            canonical_host = urlparse(self.config.base_url).netloc.casefold()
            if request.headers.get("host", "").casefold() != canonical_host:
                return RedirectResponse(self.config.base_url + "/auth/login" + ("?start=1" if start else ""), 303)
            if self.config.storage_error:
                response = page("Access storage unavailable", self.config.storage_error)
                response.status_code = 503
                return response
            if not self.config.configured:
                return page("Microsoft sign-in setup required", "The administrator must configure the Microsoft app registration before login is available. No dashboard data is accessible while setup is incomplete.")
            if not start:
                return page("Sign in to the dashboard", "Access is limited to approved Microsoft accounts. Work and personal accounts are supported.", login=True)
            state, cookie, nonce, verifier = self.store.new_flow()
            url = await self.identity.authorization_url(state, nonce, verifier)
            response = RedirectResponse(url, 303)
            response.set_cookie(FLOW_COOKIE, cookie, max_age=600, httponly=True, secure=self.config.secure_cookie, samesite="lax", path="/auth")
            response.headers["Cache-Control"] = "no-store"
            return response

        @router.get("/auth/callback")
        async def callback(request: Request):
            if not self.config.configured or not self.store:
                raise HTTPException(503, "Microsoft sign-in is not configured.")
            phase = "flow"
            try:
                flow = self.store.consume_flow(request.query_params.get("state", ""), request.cookies.get(FLOW_COOKIE, ""))
                if request.query_params.get("error") or not request.query_params.get("code"):
                    raise ValueError("Microsoft sign-in was cancelled or denied.")
                phase = "identity_exchange"
                claims = await self.identity.exchange(request.query_params["code"], flow["nonce"], flow["verifier"])
                phase = "session"
                old = request.cookies.get(COOKIE)
                if old:
                    self.store.logout(old)
                token = self.store.login(claims, self.config)
                user = self.store.session(token)
                response = RedirectResponse("/" if user["status"] == "approved" else "/auth/status", 303)
                response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True, secure=self.config.secure_cookie, samesite="lax", path="/")
            except Exception as exc:
                # No error/token/code/URL payloads in logs or browser output.
                log.warning("Microsoft login failed: phase=%s kind=%s", phase, type(exc).__name__)
                with self.store.db() as db:
                    self.store.event(db, None, "login_failed")
                response = page("Sign-in could not be completed", "The sign-in expired, was cancelled, or could not be verified. Start Microsoft sign-in again.", login=True)
                response.status_code = 400
            response.delete_cookie(FLOW_COOKIE, path="/auth")
            response.headers["Cache-Control"] = "no-store"
            return response

        @router.get("/auth/status")
        async def status(request: Request):
            user = self.current(request)
            if not user:
                return RedirectResponse("/auth/login", 303)
            if user["status"] == "approved":
                return RedirectResponse("/", 303)
            pending = user["status"] == "pending"
            return page("Awaiting administrator approval" if pending else "Account not approved",
                        "Your Microsoft identity has been verified, but dashboard access has not been granted. Contact the administrator.", identity=user)

        @router.get("/api/auth/me")
        async def me(request: Request):
            if not self.config.enabled:
                return {"enabled": False, "role": "development", "status": "development"}
            if not self.store:
                raise HTTPException(503, "Access storage unavailable.")
            user = self.current(request)
            if not user:
                raise HTTPException(401, "Sign-in required.")
            return JSONResponse({"enabled": True, **{key: user[key] for key in ("email", "name", "role", "status", "issuer", "subject", "csrf")}}, headers={"Cache-Control": "no-store"})

        @router.post("/auth/logout")
        async def logout(request: Request):
            self.store.logout(request.cookies.get(COOKIE, ""))
            response = JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})
            response.delete_cookie(COOKIE, path="/")
            return response

        @router.get("/api/admin/access")
        async def access(request: Request):
            self.admin(request)
            return self.store.listing()

        @router.post("/api/admin/access/invitations")
        async def invite(request: Request, body: InvitationInput):
            user = self.admin(request)
            try:
                self.store.invite(body.email, body.active, user["id"])
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            return {"ok": True}

        @router.post("/api/admin/access/accounts/{account_id}")
        async def approve(request: Request, account_id: int, body: ApprovalInput):
            user = self.admin(request)
            try:
                self.store.update_account(account_id, body.status, body.role, user["id"])
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            return {"ok": True}

        return router


class AccessMiddleware:
    """Gate HTTP and WebSocket paths before route/static handlers execute."""
    def __init__(self, app, access: AccessControl):
        self.app, self.access = app, access

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        config = self.access.config
        request = Request({**scope, "type": "http"})
        path, method = scope["path"], scope.get("method", "GET")
        from section_permissions import requirements, can, SHELL_ASSETS
        company = self.access.company
        sso = self.access.sso
        if not sso:
            from company_auth import PUBLIC, screen
        else:
            PUBLIC = frozenset()
        if path == "/" and method == "GET" and config.enabled:
            current = self.access.current(request) if self.access.store else None
            if sso and (not current or not sso.fresh(current, request)):
                return await RedirectResponse("/auth/login", 303)(scope, receive, send)
            if not sso and (not company or not company.authenticated(current)):
                google_action = ('<a class="button" href="/auth/google/verify">Request access with Google / Gmail</a>'
                                 if company.access.google_identity.client_id and company.access.google_identity.client_secret else '')
                landing = screen("Your market intelligence desk", '<p>Shipping, commodities and operational intelligence for approved Howe Robinson colleagues.</p>'
                    '<div class="landing-actions"><a class="button" href="/auth/verify">Request access with Microsoft</a>'
                    + google_action + '<a class="button secondary" href="/auth/login">Log in</a></div>'
                    '<p>A verified Microsoft or Google identity can request access. Owner approval, a dashboard password and a phone authenticator are required before any dashboard data is available.</p>')
                return await landing(scope, receive, send)
        if path in PUBLIC - {"/"} and scope["type"] == "http" and company:
            return await self.app(scope, receive, send)
        if path in PUBLIC_PATHS and scope["type"] == "http":
            return await self.app(scope, receive, send)
        if not config.enabled and not sso:
            # Explicit local/test opt-out never becomes a remote access bypass.
            host = (scope.get("client") or ("", 0))[0]
            if not config.production and host in {"127.0.0.1", "::1", "testclient"}:
                return await self.app(scope, receive, send)
        async def reject(status, detail):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 4401 if status == 401 else 4403})
            elif method in {"GET", "HEAD"} and not path.startswith("/api/") and status in {401, 403}:
                response = RedirectResponse("/auth/login" if status == 401 else "/auth/status", 303)
                await response(scope, receive, send)
            else:
                await JSONResponse({"detail": detail}, status, headers={"Cache-Control": "no-store"})(scope, receive, send)
        if config.storage_error or not self.access.store:
            return await reject(503, "Access storage unavailable.")
        if not (sso.configured if sso else config.configured):
            if path == "/" and method == "GET":
                return await RedirectResponse("/auth/login", 303)(scope, receive, send)
            return await reject(503, "Microsoft sign-in is not configured.")
        # Deliberately not a general administrator/session bypass.
        automation = (method == "POST" and path in AUTOMATION_POSTS and config.automation_token
                      and hmac.compare_digest(request.headers.get("X-Admin-Token", ""), config.automation_token)
                      and not request.headers.get("origin") and not request.cookies.get(COOKIE))
        if automation:
            scope["automation_authorized"] = True
            return await self.app(scope, receive, send)
        try:
            user = self.access.current(request)
        except (OSError, sqlite3.Error):
            return await reject(503, "Access storage unavailable.")
        if not user:
            return await reject(401, "Sign-in required.")
        if sso and not sso.fresh(user, request):
            return await reject(401, "Fresh HRP sign-in required.")
        if company and not company.authenticated(user):
            return await reject(403, "Password and authenticator login required.")
        if user["status"] != "approved" and path != "/auth/logout":
            return await reject(403, "Account approval required.")
        force_refresh = request.query_params.get("force", "").lower() in {"true", "1", "yes"}
        mutation = method not in {"GET", "HEAD", "OPTIONS"}
        if company or sso:
            if path.startswith("/api/admin/") or path == "/auth/access-requests":
                if user["role"] != "admin":
                    return await reject(403, "Owner administrator access required.")
                if sso and path != "/api/admin/sso/sessions/revoke":
                    return await reject(403, "Access assignment is managed by HRP IT.")
                if company and path not in {"/api/admin/access", "/auth/access-requests"} and not re.fullmatch(r"/api/admin/access/accounts/\d+(?:/reset-factor)?", path):
                    return await reject(403, "Unclassified access operation.")
            elif path in {"/", "/api/trackers", "/api/selectors/ports", "/auth/logout"} or path in SHELL_ASSETS:
                pass
            else:
                policy = requirements(path, method, request.query_params)
                if not policy or not all(can(user, section, policy[1]) for section in policy[0]):
                    return await reject(403, "This section or operation is not permitted.")
                scope["section_edit_authorized"] = policy[1]
        elif user["role"] != "admin" and (path.startswith("/api/admin/") or force_refresh or (mutation and path not in VIEWER_POSTS)):
            return await reject(403, "Administrator access required.")
        if mutation or force_refresh:
            if (not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), user["csrf"])
                    or (request.headers.get("origin") and request.headers["origin"] != config.base_url)):
                return await reject(403, "Request verification failed. Reload the page and try again.")
        scope["auth_user"] = user
        if scope["type"] == "websocket":
            if request.headers.get("origin") != config.base_url:
                return await reject(403, "Invalid connection origin.")
            # Keep an idle or send-only connection from outliving approval/session expiry.
            token = request.cookies.get(COOKIE, "")
            async def guard():
                while True:
                    await asyncio.sleep(SESSION_CHECK_SECONDS)
                    try:
                        current = self.access.current(Request({**scope, "type": "http"}), touch=False)
                    except (OSError, sqlite3.Error):
                        current = None
                    if not current or current["status"] != "approved" or (company and not company.authenticated(current)) or (sso and not sso.fresh(current, request)):
                        return
            app_task = asyncio.create_task(self.app(scope, receive, send))
            guard_task = asyncio.create_task(guard())
            done, _ = await asyncio.wait({app_task, guard_task}, return_when=asyncio.FIRST_COMPLETED)
            if guard_task in done and not app_task.done():
                await send({"type": "websocket.close", "code": 4401})
            for task in (app_task, guard_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(app_task, guard_task, return_exceptions=True)
            if app_task in done:
                app_task.result()
            return
        async def no_cache(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"]
                message["headers"] = headers + [(b"cache-control", b"no-store")]
            await send(message)
        return await self.app(scope, receive, no_cache)
