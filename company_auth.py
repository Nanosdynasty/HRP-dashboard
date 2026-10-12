"""Identity-verified onboarding, password + TOTP authentication and section grants.

Microsoft/Google verification cookies and password challenges can never authorize data.
Secrets remain in credentials, outside the account records returned to administrators.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import html
import io
import json
import os
import secrets
import sqlite3
import time
import uuid
from urllib.parse import urlparse

import pyotp
import qrcode
import qrcode.image.svg
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from section_permissions import SECTIONS, LEVELS
from mail_delivery import Microsoft365Mail, OutlookPersonalMail

PRE_COOKIE = "hrp_verification"
BROWSER_COOKIE = "hrp_auth_browser"
PUBLIC = {"/", "/auth/login", "/auth/verify", "/auth/callback", "/auth/google/verify",
          "/auth/google/callback", "/auth/mail/connect", "/auth/mail/callback",
          "/auth/status", "/auth/setup", "/auth/email-reset",
          "/auth/logout", "/api/auth/me", "/api/auth/browser", "/api/auth/request",
          "/api/auth/password", "/api/auth/mfa/enrol", "/api/auth/mfa/qr",
          "/api/auth/mfa/confirm", "/api/auth/login", "/api/auth/challenge",
          "/api/auth/reset", "/api/auth/lost-factor", "/api/auth/email-reset/request",
          "/api/auth/email-reset/complete", "/static/auth/company.js", "/static/auth/access-v2.js"}
HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(32))

def hashed(text):
    return hashlib.sha256(text.encode()).hexdigest()

def reply(payload, status=200):
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})

def company_email(value):
    value = str(value).strip().casefold()
    if len(value) > 254 or not __import__('re').fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise HTTPException(403, "Your identity provider must supply a valid email login label. Contact the owner if it is unavailable.")
    return value

def password_value(value):
    if not isinstance(value, str) or not 15 <= len(value) <= 128:
        raise HTTPException(400, "Use a password containing 15–128 characters.")
    return value

def screen(title, body, view="landing"):
    return HTMLResponse('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Howe Robinson · '+html.escape(title)+'</title><link rel="stylesheet" href="/static/auth/auth.css"></head>'
        '<body><main class="access-card company-card" data-view="'+view+'"><img src="/static/img/howe-robinson-logo.svg" alt="Howe Robinson Partners">'
        '<p class="eyebrow">MARKET INTELLIGENCE</p><h1>'+html.escape(title)+'</h1>'+body+
        '<p id="auth-message" role="status" aria-live="polite"></p><nav><a href="/">Home</a> · <a href="/auth/status">Check request status / account setup</a></nav>'
        '</main><script src="/static/auth/company.js"></script></body></html>', headers={"Cache-Control":"no-store",
        "Content-Security-Policy":"default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})

class CompanyAccess:
    def __init__(self, access):
        self.access, self.store, self.config = access, access.store, access.config
        self.work_mail = Microsoft365Mail()
        self.tenant = os.getenv("AUTH_COMPANY_TENANT_ID", "").strip().lower()
        try:
            self.tenant = str(uuid.UUID(self.tenant))
        except ValueError:
            self.tenant = ""
        self.cipher = None
        key = os.getenv("AUTH_MFA_ENCRYPTION_KEY", "").strip()
        try:
            if key:
                self.cipher = Fernet(key.encode())
        except (ValueError, TypeError):
            pass
        self.migrate()
        with self.store.db() as db:
            existing={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            reset_migrated={"email_reset_tokens","mail_connections"}.issubset(existing)
        if not reset_migrated:
            backup=self.store.path.with_name(self.store.path.name+".pre-email-reset-"+str(time.time_ns())+".bak")
            with sqlite3.connect(backup) as destination, self.store.db() as source:
                source.backup(destination)
            if os.name!="nt":os.chmod(backup,0o600)
        with self.store.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS email_reset_tokens("
                       "hash TEXT PRIMARY KEY,account_id INTEGER NOT NULL,created_at REAL NOT NULL,"
                       "expires_at REAL NOT NULL,version INTEGER NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS mail_connections("
                       "account_id INTEGER PRIMARY KEY,sender TEXT NOT NULL,"
                       "refresh_token TEXT NOT NULL,connected_at REAL NOT NULL)")
        self.personal_mail=OutlookPersonalMail(self.store,self.cipher,self.owner(),
            self.config.client_id,self.config.client_secret)
        self.mail=self.personal_mail if self.personal_mail.sender else self.work_mail

    def migrate(self):
        with self.store.db() as db:
            migrated = db.execute("SELECT 1 FROM settings WHERE key='company_auth_v1'").fetchone()
        if migrated:
            return
        # SQLite backup includes committed WAL contents; never copy an open database file.
        backup = self.store.path.with_name(self.store.path.name + ".pre-company-" + str(time.time_ns()) + ".bak")
        with sqlite3.connect(backup) as destination, self.store.db() as source:
            source.backup(destination)
        if os.name != "nt":
            os.chmod(backup, 0o600)
        with self.store.db() as db:
            db.executescript("""
              BEGIN IMMEDIATE;
              CREATE TABLE IF NOT EXISTS credentials(account_id INTEGER PRIMARY KEY,
                password_hash TEXT, seed TEXT, pending_seed TEXT, last_counter INTEGER DEFAULT -1,
                enrolled_at REAL, version INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS section_grants(account_id INTEGER,section TEXT,level TEXT,
                PRIMARY KEY(account_id,section));
              CREATE TABLE IF NOT EXISTS access_requests(account_id INTEGER PRIMARY KEY,name TEXT,reason TEXT,
                submitted_at REAL,reviewed_at REAL,reset_requested_at REAL,reset_approved_at REAL);
              CREATE TABLE IF NOT EXISTS verifications(hash TEXT PRIMARY KEY,account_id INTEGER,kind TEXT,
                csrf TEXT,created_at REAL,expires_at REAL,version INTEGER);
              CREATE TABLE IF NOT EXISTS browser_csrf(hash TEXT PRIMARY KEY,csrf TEXT,expires_at REAL);
              CREATE TABLE IF NOT EXISTS recovery_codes(account_id INTEGER,hash TEXT,PRIMARY KEY(account_id,hash));
              CREATE TABLE IF NOT EXISTS full_sessions(hash TEXT PRIMARY KEY,version INTEGER);
              CREATE TABLE IF NOT EXISTS auth_limits(bucket TEXT PRIMARY KEY,start REAL,count INTEGER);
            """)
            owner = db.execute("SELECT actor FROM audit WHERE action='owner_bootstrapped' ORDER BY id LIMIT 1").fetchone()
            if owner:
                db.execute("INSERT OR REPLACE INTO settings VALUES('company_owner_id',?)", (str(owner[0]),))
            db.execute("DELETE FROM sessions")
            db.execute("DELETE FROM flows")
            db.execute("INSERT INTO settings VALUES('company_auth_v1','1')")
            self.store.event(db, None, "company_auth_migrated")

    def owner(self, db=None):
        if db is None:
            with self.store.db() as connection:
                return self.owner(connection)
        row = db.execute("SELECT value FROM settings WHERE key='company_owner_id'").fetchone()
        return int(row[0]) if row else None

    def ready(self):
        if not self.cipher:
            raise HTTPException(503, "Authenticator encryption is not configured. Contact the owner.")

    def permitted_identity(self, claims, existing=None):
        if existing and existing["id"] == self.owner():
            return existing["email"]
        # Issuer/sub come only from a validated identity token. Domains and
        # tenants no longer restrict requests; approval still binds the identity.
        return company_email(claims.get("preferred_username") or claims.get("email") or "")

    def eligible(self, account):
        if account["id"] == self.owner():
            return True
        try:
            company_email(account["email"])
            if account["issuer"] == "https://accounts.google.com":
                return True
            match=__import__('re').fullmatch(r"https://login\.microsoftonline\.com/([0-9a-f-]{36})/v2\.0",account["issuer"])
            return bool(match and uuid.UUID(match[1]))
        except (HTTPException,ValueError):
            return False

    def verify_identity(self, claims):
        self.ready()
        if claims.get("iss") == "https://accounts.google.com" and claims.get("email_verified") is not True:
            raise HTTPException(403, "Google has not verified this email address.")
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM accounts WHERE issuer=? AND subject=?", (claims["iss"], claims["sub"])).fetchone()
            label = self.permitted_identity(claims, row)
            if row and label != row["email"]:
                raise HTTPException(403, "The verified login ID changed. Owner review is required; accounts are never linked by email.")
            if not row:
                db.execute("INSERT INTO accounts(issuer,subject,email,name,status,created_at) VALUES(?,?,?,?,?,?)",
                           (claims["iss"], claims["sub"], label, str(claims.get("name", ""))[:200], "unapproved", time.time()))
                row = db.execute("SELECT * FROM accounts WHERE issuer=? AND subject=?", (claims["iss"], claims["sub"])).fetchone()
            self.store.event(db, row["id"], "microsoft_verified")
            return self.pre_token(db, row["id"], "identity", 600)

    def pre_token(self, db, account_id, kind, lifetime):
        now = time.time()
        db.execute("DELETE FROM verifications WHERE expires_at<?", (now,))
        version = db.execute("SELECT version FROM credentials WHERE account_id=?", (account_id,)).fetchone()
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        db.execute("INSERT INTO verifications VALUES(?,?,?,?,?,?,?)", (hashed(token), account_id, kind, csrf, now, now+lifetime, version[0] if version else 0))
        return token

    def verified_locked(self, db, user, approved=True):
        """Recheck verification under the same write lock as a security mutation."""
        row=db.execute("SELECT v.version,a.status,COALESCE(c.version,0) AS current_version FROM verifications v "
            "JOIN accounts a ON a.id=v.account_id LEFT JOIN credentials c ON c.account_id=a.id "
            "WHERE v.hash=? AND v.account_id=? AND v.expires_at>?",(user['hash'],user['id'],time.time())).fetchone()
        if not row or row['version']!=row['current_version']:
            raise HTTPException(401,"Verify your identity again; this verification expired or was invalidated.")
        if row['status'] in {'rejected','revoked'} or (approved and row['status']!='approved'):
            raise HTTPException(403,"Active approval required.")

    def pre(self, request, kinds=("identity",), approved=False):
        with self.store.db() as db:
            row = db.execute("SELECT a.*,v.kind,v.csrf,v.hash,v.created_at AS verified_at,v.version AS verified_version "
                "FROM verifications v JOIN accounts a ON a.id=v.account_id WHERE v.hash=? AND v.expires_at>?",
                (hashed(request.cookies.get(PRE_COOKIE, "")), time.time())).fetchone()
            credential = db.execute("SELECT version FROM credentials WHERE account_id=?", (row["id"],)).fetchone() if row else None
        if not row or row["kind"] not in kinds or row["verified_version"] != (credential[0] if credential else 0):
            raise HTTPException(401, "Verify your identity again or restart login.")
        row = dict(row)
        if not self.eligible(row) or row["status"] in {"rejected", "revoked"} or (approved and row["status"] != "approved"):
            raise HTTPException(403, "Active administrator approval is required.")
        return row

    def grants(self, account):
        if account["id"] == self.owner():
            return dict.fromkeys(SECTIONS, "edit")
        with self.store.db() as db:
            assigned = dict(db.execute("SELECT section,level FROM section_grants WHERE account_id=?", (account["id"],)).fetchall())
        return {section: assigned.get(section, "hidden") for section in SECTIONS}

    def authenticated(self, user):
        if not user or not self.cipher or not self.eligible(user) or user["status"] != "approved":
            return False
        with self.store.db() as db:
            row = db.execute("SELECT 1 FROM full_sessions f JOIN credentials c ON c.account_id=? "
                "WHERE f.hash=? AND f.version=c.version AND c.enrolled_at IS NOT NULL AND c.password_hash IS NOT NULL", (user["id"], user["hash"])).fetchone()
        if not row:
            return False
        user["role"] = "admin" if user["id"] == self.owner() else "viewer"
        user["permissions"] = self.grants(user)
        return True

    def rate(self, bucket, limit=8, seconds=900):
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            now = time.time()
            db.execute("DELETE FROM auth_limits WHERE start<?", (now-86400,))
            row = db.execute("SELECT * FROM auth_limits WHERE bucket=?", (bucket,)).fetchone()
            if row and row["start"] > now-seconds and row["count"] >= limit:
                raise HTTPException(429, "Too many attempts. Wait fifteen minutes before trying again.")
            db.execute("INSERT INTO auth_limits VALUES(?,?,1) ON CONFLICT(bucket) DO UPDATE SET "
                "start=excluded.start,count=?", (bucket, row["start"] if row and row["start"] > now-seconds else now,
                row["count"]+1 if row and row["start"] > now-seconds else 1))

    def csrf(self, request, value):
        if request.headers.get("origin") not in {None, self.config.base_url} or not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), value):
            raise HTTPException(403, "Reload this page and try again.")

    def public_csrf(self, request):
        with self.store.db() as db:
            row = db.execute("SELECT csrf FROM browser_csrf WHERE hash=? AND expires_at>?", (hashed(request.cookies.get(BROWSER_COOKIE,"")), time.time())).fetchone()
        if not row:
            raise HTTPException(403, "Reload this page and try again.")
        self.csrf(request, row[0])

    def issue_session(self, db, account):
        token, csrf, now = secrets.token_urlsafe(32), secrets.token_urlsafe(32), time.time()
        credential = db.execute("SELECT version FROM credentials WHERE account_id=? AND enrolled_at IS NOT NULL", (account["id"],)).fetchone()
        current = db.execute("SELECT * FROM accounts WHERE id=?", (account["id"],)).fetchone()
        if not credential or current["status"] != "approved" or not self.eligible(dict(current)):
            raise HTTPException(403, "Approval and complete authenticator setup are required.")
        db.execute("DELETE FROM sessions WHERE expires_at<? OR last_seen<?", (now, now-1800))
        db.execute("DELETE FROM full_sessions WHERE hash NOT IN (SELECT hash FROM sessions)")
        db.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?)", (hashed(token),account["id"],csrf,now,now,now+28800))
        db.execute("INSERT INTO full_sessions VALUES(?,?)", (hashed(token), credential[0]))
        self.store.event(db, account["id"], "password_mfa_login")
        return token

    def cookie(self, response, name, token, age=600):
        response.set_cookie(name, token, max_age=age, httponly=True, secure=self.config.secure_cookie, samesite="lax", path="/")
        return response

    def factor(self, db, account_id, code, pending=False, allow_recovery=True):
        credential = db.execute("SELECT * FROM credentials WHERE account_id=?", (account_id,)).fetchone()
        seed = credential["pending_seed" if pending else "seed"] if credential else None
        if not seed:
            raise HTTPException(400, "Authenticator enrolment is required.")
        try:
            secret = self.cipher.decrypt(seed.encode()).decode()
        except InvalidToken:
            raise HTTPException(503, "Authenticator storage cannot be decrypted. Contact the owner.") from None
        now = int(time.time() // 30)
        # RFC 6238: tolerate one interval of clock drift, consume the counter atomically.
        for counter in (now, now-1, now+1):
            if counter > credential["last_counter"] and hmac.compare_digest(pyotp.TOTP(secret).at(counter*30), str(code)):
                db.execute("UPDATE credentials SET last_counter=? WHERE account_id=?", (counter,account_id))
                return
        if allow_recovery and not pending and isinstance(code, str) and len(code) >= 16:
            removed = db.execute("DELETE FROM recovery_codes WHERE account_id=? AND hash=?", (account_id,hashed(code.strip().upper())))
            if removed.rowcount:
                self.store.event(db,account_id,"recovery_code_consumed")
                return
        raise HTTPException(400, "Invalid or already used authenticator / recovery code.")

    def enrolment(self, account):
        with self.store.db() as db:
            row = db.execute("SELECT password_hash,enrolled_at FROM credentials WHERE account_id=?", (account["id"],)).fetchone()
        return "active" if row and row["password_hash"] and row["enrolled_at"] else "setup_required"

    def review(self, actor, account_id, status, permissions):
        if status not in {"approved", "rejected", "revoked"} or not isinstance(permissions,dict) or set(permissions) != set(SECTIONS) or any(v not in LEVELS for v in permissions.values()):
            raise HTTPException(400, "Choose a valid status and a grant for every section.")
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
            if not row or not self.eligible(dict(row)):
                raise HTTPException(400, "A verified company identity is required.")
            if account_id == self.owner(db):
                raise HTTPException(400, "The owner cannot be revoked, demoted or assigned reduced permissions.")
            if not db.execute("SELECT 1 FROM access_requests WHERE account_id=?", (account_id,)).fetchone():
                raise HTTPException(400, "This identity has not submitted a request.")
            # A login label is not an identity key. Conflicts must be reviewed, never auto-linked.
            if status == "approved" and db.execute("SELECT 1 FROM accounts WHERE email=? AND id<>? AND status='approved'", (row["email"],account_id)).fetchone():
                raise HTTPException(409, "Another approved identity has this login ID. Resolve the conflict before approval.")
            db.execute("UPDATE accounts SET status=?,role='viewer' WHERE id=?", (status,account_id))
            db.execute("UPDATE access_requests SET reviewed_at=? WHERE account_id=?", (time.time(),account_id))
            db.executemany("INSERT OR REPLACE INTO section_grants VALUES(?,?,?)", [(account_id,s,v) for s,v in permissions.items()])
            db.execute("DELETE FROM sessions WHERE account_id=?", (account_id,))
            db.execute("DELETE FROM verifications WHERE account_id=?", (account_id,))
            self.store.event(db,actor,"access_"+status,json.dumps({"account":account_id,"permissions":permissions},sort_keys=True))

    def router(self):
        router = APIRouter()

        @router.get("/auth/login")
        async def login_page(request: Request, start: bool=False):
            if start:
                return RedirectResponse("/auth/verify",303)
            google_setup=('<a href="/auth/google/verify">verify Google / Gmail</a>'
                if self.access.google_identity.client_id and self.access.google_identity.client_secret else '')
            reset_action=('<details><summary>Forgot dashboard password?</summary><p>Enter the approved email address. We will send a short-lived link. You will also need your phone authenticator.</p>'
                '<form id="email-reset-request-form"><label>Approved email<input name="email" type="email" autocomplete="email" required maxlength="254"></label><button>Send reset link</button></form></details>'
                if self.mail.configured else '<p>Forgot password? Verify the same sign-in account again to use the existing reset process.</p>')
            return screen("Log in", '<p>Use your approved login ID, dashboard password and phone authenticator.</p>'
                '<form id="login-form"><label>Email<input name="email" type="email" autocomplete="username" required maxlength="254"></label>'
                '<label>Password<input name="password" type="password" autocomplete="current-password" required minlength="15" maxlength="128"></label><button>Continue</button></form>'
                '<form id="challenge-form" hidden><label>Authenticator or recovery code<input name="code" autocomplete="one-time-code" required maxlength="64"></label><button>Log in</button></form>'
                '<p>First-time setup: <a href="/auth/verify">verify Microsoft</a>'
                + (' or '+google_setup if google_setup else '') + '.</p>'
                + reset_action,"login")

        @router.get("/auth/verify")
        async def verify(request: Request):
            self.ready()
            if not self.config.configured:
                raise HTTPException(503,"Microsoft verification is not configured.")
            if request.headers.get("host","").casefold() != urlparse(self.config.base_url).netloc.casefold():
                return RedirectResponse(self.config.base_url+"/auth/verify",303)
            from access_control import FLOW_COOKIE
            state,cookie,nonce,verifier = self.store.new_flow()
            response = RedirectResponse(await self.access.identity.authorization_url(state,nonce,verifier),303)
            response.set_cookie(FLOW_COOKIE,cookie,max_age=600,httponly=True,secure=self.config.secure_cookie,samesite="lax",path="/auth")
            response.headers["Cache-Control"]="no-store"
            return response

        @router.get("/auth/google/verify")
        async def google_verify(request: Request):
            self.ready()
            identity=self.access.google_identity
            if not identity.client_id or not identity.client_secret:
                raise HTTPException(503,"Google request verification is not configured.")
            if request.headers.get("host","").casefold() != urlparse(self.config.base_url).netloc.casefold():
                return RedirectResponse(self.config.base_url+"/auth/google/verify",303)
            from access_control import FLOW_COOKIE
            state,cookie,nonce,verifier=self.store.new_flow(provider="google")
            response=RedirectResponse(await identity.authorization_url(state,nonce,verifier),303)
            response.set_cookie(FLOW_COOKIE,cookie,max_age=600,httponly=True,
                                secure=self.config.secure_cookie,samesite="lax",path="/auth")
            response.headers["Cache-Control"]="no-store"
            return response

        @router.get("/auth/callback")
        async def callback(request: Request):
            from access_control import FLOW_COOKIE, COOKIE
            self.ready()
            if not self.config.configured:
                raise HTTPException(503,"Microsoft verification is not configured.")
            try:
                flow=self.store.consume_flow(request.query_params.get("state",""),request.cookies.get(FLOW_COOKIE,""))
                if request.query_params.get("error") or not request.query_params.get("code"):
                    raise ValueError("cancelled")
                claims=await self.access.identity.exchange(request.query_params["code"],flow["nonce"],flow["verifier"])
                token=self.verify_identity(claims)
                response=self.cookie(RedirectResponse("/auth/status",303),PRE_COOKIE,token)
                self.store.logout(request.cookies.get(COOKIE,""))
                response.delete_cookie(COOKIE,path="/")
            except HTTPException as exc:
                response=screen("Verification unavailable",'<p>'+html.escape(str(exc.detail))+'</p>')
                response.status_code=exc.status_code
            except Exception as exc:
                import logging
                logging.getLogger("access").warning("Company verification failed: kind=%s",type(exc).__name__)
                response=screen("Verification failed",'<p>Start Microsoft verification again. No access has been granted.</p>')
                response.status_code=400
            response.delete_cookie(FLOW_COOKIE,path="/auth")
            return response

        @router.get("/auth/google/callback")
        async def google_callback(request: Request):
            from access_control import FLOW_COOKIE, COOKIE
            self.ready()
            identity=self.access.google_identity
            if not identity.client_id or not identity.client_secret:
                raise HTTPException(503,"Google request verification is not configured.")
            try:
                flow=self.store.consume_flow(request.query_params.get("state",""),request.cookies.get(FLOW_COOKIE,""),provider="google")
                if request.query_params.get("error") or not request.query_params.get("code"):
                    raise ValueError("cancelled")
                claims=await identity.exchange(request.query_params["code"],flow["nonce"],flow["verifier"])
                token=self.verify_identity(claims)
                response=self.cookie(RedirectResponse("/auth/status",303),PRE_COOKIE,token)
                self.store.logout(request.cookies.get(COOKIE,""))
                response.delete_cookie(COOKIE,path="/")
            except Exception as exc:
                import logging
                logging.getLogger("access").warning("Google verification failed: kind=%s",type(exc).__name__)
                with self.store.db() as db:self.store.event(db,None,"google_verification_failed")
                response=screen("Verification failed",'<p>Start Google verification again. No access has been granted.</p>')
                response.status_code=400
            response.delete_cookie(FLOW_COOKIE,path="/auth")
            response.headers["Cache-Control"]="no-store"
            return response

        @router.get("/auth/mail/connect")
        async def mail_connect(request: Request):
            self.access.admin(request)
            if not self.personal_mail.connect_ready:
                raise HTTPException(503,"Personal Outlook sender is not configured.")
            if request.headers.get("host","").casefold()!=urlparse(self.config.base_url).netloc.casefold():
                return RedirectResponse(self.config.base_url+"/auth/mail/connect",303)
            from access_control import FLOW_COOKIE
            state,cookie,nonce,verifier=self.store.new_flow(provider="microsoft_mail")
            response=RedirectResponse(await self.access.identity.mail_authorization_url(state,nonce,verifier),303)
            response.set_cookie(FLOW_COOKIE,cookie,max_age=600,httponly=True,
                                secure=self.config.secure_cookie,samesite="lax",path="/auth")
            response.headers["Cache-Control"]="no-store"
            return response

        @router.get("/auth/mail/callback")
        async def mail_callback(request: Request):
            from access_control import FLOW_COOKIE
            owner=self.access.admin(request)
            if not self.personal_mail.connect_ready:
                raise HTTPException(503,"Personal Outlook sender is not configured.")
            try:
                flow=self.store.consume_flow(request.query_params.get("state",""),
                    request.cookies.get(FLOW_COOKIE,""),provider="microsoft_mail")
                if request.query_params.get("error") or not request.query_params.get("code"):
                    raise ValueError("cancelled")
                claims,refresh_token=await self.access.identity.mail_exchange(
                    request.query_params["code"],flow["nonce"],flow["verifier"])
                label=company_email(claims.get("preferred_username") or claims.get("email") or "")
                if claims["iss"]!=owner["issuer"] or claims["sub"]!=owner["subject"] or label!=self.personal_mail.sender:
                    raise ValueError("The consented mailbox is not the approved owner identity.")
                self.personal_mail.connect(refresh_token)
                response=RedirectResponse("/auth/access-requests",303)
            except Exception as exc:
                import logging
                logging.getLogger("access").warning("Personal mail connection failed: kind=%s",type(exc).__name__)
                with self.store.db() as db:self.store.event(db,owner["id"],"personal_mail_connection_failed")
                response=screen("Mail connection failed",'<p>The owner mailbox could not be verified or consent was not completed. Return to Access requests and try again.</p>')
                response.status_code=400
            response.delete_cookie(FLOW_COOKIE,path="/auth")
            response.headers["Cache-Control"]="no-store"
            return response

        @router.get("/auth/status")
        @router.get("/auth/setup")
        async def status(request: Request):
            # The page renders no protected data; the status request uses a verification cookie.
            return screen("Your access request",'<section id="request-status">Checking your account…</section>',"status")

        @router.get("/auth/email-reset")
        async def email_reset_page(request: Request):
            return screen("Reset dashboard password",'<p>Use the link sent to your approved email address, your phone authenticator and a new password. The link expires after 15 minutes.</p>'
                '<form id="email-reset-complete-form"><label>New password<input name="password" type="password" autocomplete="new-password" minlength="15" maxlength="128" required></label>'
                '<label>Six-digit authenticator code<input name="code" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" required></label>'
                '<button>Reset password</button></form>',"email-reset")

        @router.get("/api/auth/browser")
        def browser(request: Request):
            self.rate("browser:"+hashed(request.client.host if request.client else "unknown"),limit=100)
            token,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
            with self.store.db() as db:
                db.execute("DELETE FROM browser_csrf WHERE expires_at<?",(time.time(),))
                db.execute("INSERT INTO browser_csrf VALUES(?,?,?)",(hashed(token),csrf,time.time()+3600))
            return self.cookie(reply({"csrf":csrf,"google_available":bool(self.access.google_identity.client_id and self.access.google_identity.client_secret),
                                      "email_reset_available":self.mail.configured}),BROWSER_COOKIE,token,3600)

        @router.get("/api/auth/me")
        def me(request: Request):
            if not self.config.enabled:
                return reply({"enabled":False,"permissions":dict.fromkeys(SECTIONS,"edit"),"status":"development","role":"development"})
            user=self.access.current(request)
            full=self.authenticated(user)
            if not full:
                # Rejected / revoked states are visible only to the verified identity.
                with self.store.db() as db:
                    row=db.execute("SELECT a.*,v.csrf FROM verifications v JOIN accounts a ON a.id=v.account_id WHERE v.hash=? AND v.expires_at>? AND v.kind='identity'",
                        (hashed(request.cookies.get(PRE_COOKIE,"")),time.time())).fetchone()
                user=dict(row) if row else None
            if not user:
                raise HTTPException(401,"Verify your Microsoft or Google identity, or log in.")
            state=self.enrolment(user) if user["status"]=="approved" else user["status"]
            return reply({"enabled":True,"authenticated":full,"status":user["status"],"enrolment":state,
                "email":user["email"],"name":user["name"],"issuer":user["issuer"],"subject":user["subject"],
                "role":"admin" if user["id"]==self.owner() else "viewer","csrf":user["csrf"],
                "permissions":self.grants(user) if full else dict.fromkeys(SECTIONS,"hidden"),"sections":SECTIONS})

        async def body(request):
            raw=b""
            async for chunk in request.stream():
                raw+=chunk
                if len(raw)>8192:
                    raise HTTPException(413,"Request too large.")
            try:
                value=json.loads(raw)
                if not isinstance(value,dict): raise ValueError()
                return value
            except (ValueError,TypeError):
                raise HTTPException(400,"A JSON object is required.") from None

        @router.post("/api/auth/request")
        async def request_access(request: Request):
            user=self.pre(request);self.csrf(request,user["csrf"])
            data=await body(request)
            name,reason=str(data.get("name","")).strip(),str(data.get("reason","")).strip()
            if not 1<=len(name)<=200 or not 10<=len(reason)<=2000:
                raise HTTPException(400,"Enter your name and a reason of 10–2000 characters.")
            with self.store.db() as db:
                db.execute("BEGIN IMMEDIATE")
                self.verified_locked(db,user,approved=False)
                current=db.execute("SELECT status FROM accounts WHERE id=?",(user["id"],)).fetchone()[0]
                if current not in {"unapproved","pending"}:
                    raise HTTPException(409,"This request has already been reviewed.")
                db.execute("INSERT OR IGNORE INTO access_requests(account_id,name,reason,submitted_at) VALUES(?,?,?,?)",(user["id"],name,reason,time.time()))
                db.execute("UPDATE accounts SET status='pending',name=? WHERE id=?",(name,user["id"]))
                self.store.event(db,user["id"],"access_requested",user["id"])
            return reply({"state":"pending"})

        @router.post("/api/auth/password")
        async def password(request: Request):
            self.ready();user=self.pre(request,approved=True);self.csrf(request,user["csrf"])
            self.rate("setup:"+str(user["id"]))
            data=await body(request);value=password_value(data.get("password"))
            result=await run_in_threadpool(HASHER.hash,value)
            with self.store.db() as db:
                db.execute("BEGIN IMMEDIATE")
                self.verified_locked(db,user)
                if db.execute("SELECT 1 FROM credentials WHERE account_id=? AND password_hash IS NOT NULL",(user["id"],)).fetchone():
                    raise HTTPException(409,"Use the password-reset flow to change an existing password.")
                if db.execute("SELECT status FROM accounts WHERE id=?",(user["id"],)).fetchone()[0]!="approved":
                    raise HTTPException(403,"Approval required.")
                db.execute("INSERT INTO credentials(account_id,password_hash) VALUES(?,?) ON CONFLICT(account_id) DO UPDATE SET password_hash=excluded.password_hash",(user["id"],result))
                self.store.event(db,user["id"],"password_setup")
            return reply({"state":"mfa_required"})

        @router.post("/api/auth/mfa/enrol")
        async def enrol(request: Request):
            self.ready();user=self.pre(request,approved=True);self.csrf(request,user["csrf"])
            self.rate("enrol:"+str(user["id"]),limit=10)
            with self.store.db() as db:
                db.execute("BEGIN IMMEDIATE")
                self.verified_locked(db,user)
                credential=db.execute("SELECT * FROM credentials WHERE account_id=?",(user["id"],)).fetchone()
                if not credential or not credential["password_hash"] or credential["enrolled_at"]:
                    raise HTTPException(409,"Set up your password first; an active authenticator cannot be replaced here.")
                if not credential["pending_seed"]:
                    encrypted=self.cipher.encrypt(pyotp.random_base32().encode()).decode()
                    db.execute("UPDATE credentials SET pending_seed=? WHERE account_id=?",(encrypted,user["id"]))
            return reply({"qr_url":"/api/auth/mfa/qr","state":"confirm_code"})

        @router.get("/api/auth/mfa/qr")
        def qr(request: Request):
            self.ready();user=self.pre(request,approved=True)
            with self.store.db() as db:
                credential=db.execute("SELECT pending_seed,enrolled_at FROM credentials WHERE account_id=?",(user["id"],)).fetchone()
            if not credential or not credential[0] or credential[1]:
                raise HTTPException(404,"No pending authenticator enrolment.")
            seed=self.cipher.decrypt(credential[0].encode()).decode()
            uri=pyotp.TOTP(seed).provisioning_uri(user["email"],issuer_name="Howe Robinson Dashboard")
            output=io.BytesIO();qrcode.make(uri,image_factory=qrcode.image.svg.SvgPathImage).save(output)
            return Response(output.getvalue(),media_type="image/svg+xml",headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"})

        @router.post("/api/auth/mfa/confirm")
        async def confirm(request: Request):
            self.ready();user=self.pre(request,approved=True);self.csrf(request,user["csrf"])
            self.rate("factor:"+str(user["id"]));data=await body(request)
            codes=[secrets.token_hex(10).upper() for _ in range(10)]
            with self.store.db() as db:
                db.execute("BEGIN IMMEDIATE")
                self.verified_locked(db,user)
                credential=db.execute("SELECT enrolled_at FROM credentials WHERE account_id=?",(user["id"],)).fetchone()
                if not credential or credential[0]:raise HTTPException(409,"Authenticator already active or setup incomplete.")
                self.factor(db,user["id"],data.get("code",""),pending=True)
                db.execute("UPDATE credentials SET seed=pending_seed,pending_seed=NULL,enrolled_at=? WHERE account_id=?",(time.time(),user["id"]))
                db.executemany("INSERT INTO recovery_codes VALUES(?,?)",[(user["id"],hashed(c)) for c in codes])
                token=self.issue_session(db,user)
                db.execute("DELETE FROM verifications WHERE account_id=?",(user["id"],))
                self.store.event(db,user["id"],"mfa_enrolled")
            from access_control import COOKIE
            response=self.cookie(reply({"recovery_codes":codes,"state":"active"}),COOKIE,token,28800)
            response.delete_cookie(PRE_COOKIE,path="/")
            return response

        @router.post("/api/auth/login")
        async def password_login(request: Request):
            self.ready();self.public_csrf(request);data=await body(request)
            label=str(data.get("email","")).strip().casefold()
            self.rate("ip:"+hashed(request.client.host if request.client else "unknown"),limit=30)
            self.rate("login:"+hashed(label))
            with self.store.db() as db:
                rows=db.execute("SELECT a.*,c.password_hash,c.enrolled_at,c.version FROM accounts a JOIN credentials c ON c.account_id=a.id WHERE a.email=? AND a.status='approved'",(label,)).fetchall()
            user=dict(rows[0]) if len(rows)==1 else None
            valid=bool(user and self.eligible(user) and user["enrolled_at"])
            candidate=data.get("password","")
            if not isinstance(candidate,str) or len(candidate)>128: candidate=""
            def verify_password():
                try: return HASHER.verify(user["password_hash"] if valid else DUMMY_HASH,candidate)
                except (VerificationError,TypeError): return False
            good=await run_in_threadpool(verify_password)
            if not valid or not good:
                with self.store.db() as db:self.store.event(db,None,"password_login_failed")
                raise HTTPException(401,"Login could not be verified.")
            with self.store.db() as db:
                token=self.pre_token(db,user["id"],"challenge",300)
                row=db.execute("SELECT csrf FROM verifications WHERE hash=?",(hashed(token),)).fetchone()
            return self.cookie(reply({"state":"challenge","csrf":row[0]}),PRE_COOKIE,token,300)

        @router.post("/api/auth/challenge")
        async def challenge(request: Request):
            self.ready();user=self.pre(request,("challenge",),True);self.csrf(request,user["csrf"])
            self.rate("factor:"+str(user["id"]));data=await body(request)
            with self.store.db() as db:
                db.execute("BEGIN IMMEDIATE")
                # A successful challenge is single-use even under concurrent requests.
                if not db.execute("DELETE FROM verifications WHERE hash=?",(user["hash"],)).rowcount:
                    raise HTTPException(401,"Login challenge expired.")
                self.factor(db,user["id"],data.get("code",""))
                token=self.issue_session(db,user)
            from access_control import COOKIE
            response=self.cookie(reply({"state":"active"}),COOKIE,token,28800)
            response.delete_cookie(PRE_COOKIE,path="/")
            return response

        @router.post("/api/auth/reset")
        async def reset(request: Request):
            self.ready();user=self.pre(request,approved=True);self.csrf(request,user["csrf"])
            self.rate("factor:"+str(user["id"]));data=await body(request)
            value=password_value(data.get("password"));result=await run_in_threadpool(HASHER.hash,value)
            with self.store.db() as db:
                db.execute("BEGIN IMMEDIATE")
                self.verified_locked(db,user)
                if not db.execute("SELECT 1 FROM verifications WHERE hash=? AND expires_at>?",(user["hash"],time.time())).fetchone():
                    raise HTTPException(401,"Verify your identity again.")
                self.factor(db,user["id"],data.get("code",""))
                db.execute("UPDATE credentials SET password_hash=?,version=version+1 WHERE account_id=?",(result,user["id"]))
                db.execute("DELETE FROM sessions WHERE account_id=?",(user["id"],))
                db.execute("DELETE FROM verifications WHERE account_id=?",(user["id"],))
                self.store.event(db,user["id"],"password_reset")
            return reply({"state":"login_required"})

        @router.post("/api/auth/email-reset/request")
        async def request_email_reset(request: Request):
            self.ready();self.public_csrf(request)
            if not self.mail.configured:
                raise HTTPException(503,"Email password recovery is not configured. Use identity verification instead.")
            data=await body(request)
            try: label=company_email(data.get("email",""))
            except HTTPException: label=""
            self.rate("email-reset-ip:"+hashed(request.client.host if request.client else "unknown"),limit=12)
            self.rate("email-reset-label:"+hashed(label),limit=4)
            token=None;account=None
            with self.store.db() as db:
                rows=db.execute("SELECT a.*,c.version FROM accounts a JOIN credentials c ON c.account_id=a.id "
                    "WHERE a.email=? AND a.status='approved' AND c.enrolled_at IS NOT NULL "
                    "AND c.password_hash IS NOT NULL",(label,)).fetchall()
                if len(rows)==1 and self.eligible(dict(rows[0])):
                    account=dict(rows[0]);token=secrets.token_urlsafe(32)
                    db.execute("DELETE FROM email_reset_tokens WHERE account_id=? OR expires_at<?",(account["id"],time.time()))
                    db.execute("INSERT INTO email_reset_tokens VALUES(?,?,?,?,?)",
                        (hashed(token),account["id"],time.time(),time.time()+900,account["version"]))
            if account:
                try:
                    await self.mail.send(account["email"],"Howe Robinson dashboard password reset",
                        "A password reset was requested for your Howe Robinson dashboard account.\n\n"
                        "Open this link within 15 minutes and enter a code from your phone authenticator:\n"
                        + self.config.base_url + "/auth/email-reset#" + token + "\n\n"
                        "If you did not request this, you can ignore the message. Your password has not changed.")
                    with self.store.db() as db:self.store.event(db,account["id"],"email_reset_sent")
                except Exception as exc:
                    import logging
                    logging.getLogger("access").warning("Password reset mail delivery failed: kind=%s",type(exc).__name__)
                    with self.store.db() as db:
                        db.execute("DELETE FROM email_reset_tokens WHERE hash=?",(hashed(token),))
                        self.store.event(db,account["id"],"email_reset_delivery_failed")
            return reply({"message":"If this is an approved account and email delivery is available, a reset link has been sent."})

        @router.post("/api/auth/email-reset/complete")
        async def complete_email_reset(request: Request):
            self.ready();self.public_csrf(request)
            data=await body(request)
            token=data.get("token","")
            if not isinstance(token,str) or not 30<=len(token)<=128:
                raise HTTPException(400,"The reset link is invalid or expired.")
            self.rate("email-reset-factor:"+hashed(token),limit=8)
            value=password_value(data.get("password"))
            result=await run_in_threadpool(HASHER.hash,value)
            with self.store.db() as db:
                db.execute("BEGIN IMMEDIATE")
                row=db.execute("SELECT r.*,a.id,a.status,a.issuer,a.subject,a.email,a.name,a.role,a.created_at,"
                    "c.version AS current_version FROM email_reset_tokens r "
                    "JOIN accounts a ON a.id=r.account_id JOIN credentials c ON c.account_id=a.id "
                    "WHERE r.hash=? AND r.expires_at>?",(hashed(token),time.time())).fetchone()
                if not row or row["status"]!="approved" or row["version"]!=row["current_version"] or not self.eligible(dict(row)):
                    raise HTTPException(400,"The reset link is invalid or expired.")
                self.factor(db,row["account_id"],data.get("code",""),allow_recovery=False)
                if not db.execute("DELETE FROM email_reset_tokens WHERE hash=?",(hashed(token),)).rowcount:
                    raise HTTPException(400,"The reset link was already used.")
                db.execute("UPDATE credentials SET password_hash=?,version=version+1 WHERE account_id=?",
                           (result,row["account_id"]))
                db.execute("DELETE FROM sessions WHERE account_id=?",(row["account_id"],))
                db.execute("DELETE FROM verifications WHERE account_id=?",(row["account_id"],))
                db.execute("DELETE FROM email_reset_tokens WHERE account_id=?",(row["account_id"],))
                self.store.event(db,row["account_id"],"email_password_reset")
            return reply({"state":"login_required"})

        @router.post("/api/auth/lost-factor")
        async def lost(request: Request):
            user=self.pre(request,approved=True);self.csrf(request,user["csrf"])
            with self.store.db() as db:
                db.execute("BEGIN IMMEDIATE")
                self.verified_locked(db,user)
                db.execute("INSERT INTO access_requests(account_id,reset_requested_at) VALUES(?,?) ON CONFLICT(account_id) DO UPDATE SET reset_requested_at=excluded.reset_requested_at,reset_approved_at=NULL",(user["id"],time.time()))
                self.store.event(db,user["id"],"lost_factor_requested")
            return reply({"state":"awaiting_owner_reset_approval"})

        @router.post("/auth/logout")
        def logout(request: Request):
            from access_control import COOKIE
            user=self.access.current(request)
            if user:self.csrf(request,user["csrf"])
            else:self.public_csrf(request)
            self.store.logout(request.cookies.get(COOKIE,""))
            with self.store.db() as db:db.execute("DELETE FROM verifications WHERE hash=?",(hashed(request.cookies.get(PRE_COOKIE,"")),))
            response=reply({"ok":True});response.delete_cookie(COOKIE,path="/");response.delete_cookie(PRE_COOKIE,path="/")
            return response

        @router.get("/auth/access-requests")
        def access_page(request: Request):
            self.access.admin(request)
            mail_section=''
            if self.personal_mail.sender:
                state='Connected' if self.personal_mail.configured else 'Not connected'
                action=('<a class="button" href="/auth/mail/connect">Connect owner Outlook mailbox</a>'
                    if self.personal_mail.connect_ready else '<p>Mail connection configuration is incomplete.</p>')
                mail_section='<section><h2>Password-reset sender</h2><p>'+html.escape(self.personal_mail.sender)+' · '+state+'</p>'+action+'</section>'
            return screen("Access requests",'<p>Review the verified identity and assign access separately for every section.</p>'
                +mail_section+'<a href="/">Return to dashboard</a><section id="requests-admin"></section>',"admin")

        @router.get("/api/admin/access")
        def listing(request: Request):
            self.access.admin(request)
            with self.store.db() as db:
                rows=[dict(r) for r in db.execute("SELECT a.*,r.reason,r.submitted_at,r.reviewed_at,r.reset_requested_at,r.reset_approved_at FROM accounts a LEFT JOIN access_requests r ON r.account_id=a.id ORDER BY CASE a.status WHEN 'pending' THEN 0 ELSE 1 END,r.submitted_at DESC")]
                audit=[dict(r) for r in db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 200")]
            for row in rows:
                row.update(permissions=self.grants(row),enrolment=self.enrolment(row),owner=row["id"]==self.owner())
            return reply({"accounts":rows,"audit":audit,"sections":SECTIONS,"pending_count":sum(r["status"]=="pending" for r in rows)})

        @router.post("/api/admin/access/accounts/{account_id}")
        async def review(request: Request, account_id:int):
            actor=self.access.admin(request);data=await body(request)
            self.review(actor["id"],account_id,data.get("status"),data.get("permissions"))
            return reply({"ok":True})

        @router.post("/api/admin/access/accounts/{account_id}/reset-factor")
        def approve_reset(request: Request,account_id:int):
            actor=self.access.admin(request)
            with self.store.db() as db:
                db.execute("BEGIN IMMEDIATE")
                if account_id==self.owner(db):
                    raise HTTPException(400,"Owner lost-factor recovery requires the documented server recovery procedure.")
                row=db.execute("SELECT * FROM access_requests WHERE account_id=?",(account_id,)).fetchone()
                if not row or not row["reset_requested_at"] or row["reset_approved_at"]:
                    raise HTTPException(400,"No pending lost-factor request.")
                db.execute("UPDATE access_requests SET reset_approved_at=? WHERE account_id=?",(time.time(),account_id))
                db.execute("UPDATE credentials SET password_hash=NULL,seed=NULL,pending_seed=NULL,enrolled_at=NULL,last_counter=-1,version=version+1 WHERE account_id=?",(account_id,))
                db.execute("DELETE FROM recovery_codes WHERE account_id=?",(account_id,))
                db.execute("DELETE FROM sessions WHERE account_id=?",(account_id,))
                db.execute("DELETE FROM verifications WHERE account_id=?",(account_id,))
                self.store.event(db,actor["id"],"lost_factor_reset_approved",account_id)
            return reply({"ok":True})
        return router
