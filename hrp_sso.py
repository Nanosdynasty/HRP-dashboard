"""Single-tenant HRP Entra sign-in. Enabled only after IT provisions the app."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode, urlparse

import httpx
from authlib.jose import JsonWebSignature
from fastapi import APIRouter, HTTPException, Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from section_permissions import SECTIONS
from access_control import COOKIE, FLOW_COOKIE, IDLE_SECONDS, MICROSOFT, SESSION_SECONDS, digest, page

log = logging.getLogger("hrp_sso")
FRESH_SECONDS = 15 * 60
ASSERTION_LIFETIME = 300
ROLE_PREFIX = "HRP."


def permissions_for_roles(roles):
    """Unknown roles convey no access; Edit includes View."""
    if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
        raise ValueError("Invalid role claim.")
    if "HRP.Admin" in roles:
        return "admin", dict.fromkeys(SECTIONS, "edit")
    grants = dict.fromkeys(SECTIONS, "hidden")
    for section in SECTIONS:
        if f"{ROLE_PREFIX}{section}.Edit" in roles:
            grants[section] = "edit"
        elif f"{ROLE_PREFIX}{section}.View" in roles:
            grants[section] = "view"
    if all(level == "hidden" for level in grants.values()):
        raise ValueError("No dashboard role has been assigned by HRP IT.")
    return "viewer", grants


class HRPSSO:
    def __init__(self, access):
        self.access = access
        self.config = access.config
        self.store = access.store
        self.tenant = os.getenv("HRP_ENTRA_TENANT_ID", "").strip()
        self.client_id = os.getenv("HRP_ENTRA_CLIENT_ID", "").strip()
        self.certificate = os.getenv("HRP_ENTRA_CERT_PATH", "").strip()
        self.private_key = os.getenv("HRP_ENTRA_PRIVATE_KEY_PATH", "").strip()
        self.domains = {d.strip().casefold() for d in os.getenv("HRP_ENTRA_EMAIL_DOMAINS", "").split(",") if d.strip()}
        self.error = ""
        try:
            self.tenant = str(uuid.UUID(self.tenant))
            uuid.UUID(self.client_id)
            if not self.domains or any("." not in d or "@" in d for d in self.domains):
                raise ValueError("Invalid HRP email domains")
            cert_path, key_path = Path(self.certificate), Path(self.private_key)
            if not cert_path.is_file() or not key_path.is_file():
                raise ValueError("Certificate and private key must exist")
            from cryptography import x509
            from cryptography.hazmat.primitives import serialization
            cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
            key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
            if cert.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo) != key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo):
                raise ValueError("Certificate and private key do not match")
            if cert.not_valid_after_utc.timestamp() <= time.time() + 86400:
                raise ValueError("Certificate expires within 24 hours")
            self.cert_der = cert.public_bytes(serialization.Encoding.DER)
            self.key_pem = key_path.read_bytes()
        except (ValueError, OSError, TypeError) as exc:
            self.error = type(exc).__name__
        if self.store:
            with self.store.db() as db:
                db.execute("""CREATE TABLE IF NOT EXISTS sso_sessions (
                    hash TEXT PRIMARY KEY, oid TEXT NOT NULL, tid TEXT NOT NULL,
                    email TEXT NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL,
                    permissions TEXT NOT NULL, csrf TEXT NOT NULL, ip TEXT NOT NULL,
                    created_at REAL NOT NULL, validated_at REAL NOT NULL,
                    last_seen REAL NOT NULL, expires_at REAL NOT NULL)""")
                db.execute("CREATE INDEX IF NOT EXISTS sso_sessions_oid ON sso_sessions(oid)")

    @property
    def configured(self):
        return not self.error and not self.config.storage_error and bool(self.store)

    def _endpoint(self, name):
        return f"{MICROSOFT}/{self.tenant}/oauth2/v2.0/{name}"

    def _client_assertion(self):
        now = int(time.time())
        thumbprint = base64.urlsafe_b64encode(hashlib.sha256(self.cert_der).digest()).rstrip(b"=").decode()
        header = {"alg": "PS256", "typ": "JWT", "x5t#S256": thumbprint}
        claims = {"aud": self._endpoint("token"), "iss": self.client_id,
                  "sub": self.client_id, "jti": str(uuid.uuid4()),
                  "nbf": now, "iat": now, "exp": now + ASSERTION_LIFETIME}
        return JsonWebSignature().serialize_compact(header, json.dumps(claims).encode(), self.key_pem).decode()

    def _ip(self, request):
        # Uvicorn trusts X-Forwarded-For only from the loopback Caddy proxy.
        return request.client.host if request.client else "unknown"

    def session(self, token, touch=True):
        if not token or not self.store:
            return None
        now = time.time()
        with self.store.db() as db:
            row = db.execute("SELECT * FROM sso_sessions WHERE hash=?", (digest(token),)).fetchone()
            if not row:
                return None
            if row["expires_at"] <= now or row["last_seen"] <= now - IDLE_SECONDS:
                db.execute("DELETE FROM sso_sessions WHERE hash=?", (row["hash"],))
                return None
            if touch:
                db.execute("UPDATE sso_sessions SET last_seen=? WHERE hash=?", (now, row["hash"]))
        user = dict(row)
        user["permissions"] = json.loads(user["permissions"])
        user["status"] = "approved"
        return user

    def fresh(self, user, request):
        return (user and user["validated_at"] > time.time() - FRESH_SECONDS
                and user["ip"] == self._ip(request))

    def revoke(self, token):
        with self.store.db() as db:
            db.execute("DELETE FROM sso_sessions WHERE hash=?", (digest(token),))

    def issue(self, claims, request):
        if claims.get("tid") != self.tenant or str(claims.get("acct")) != "0":
            raise ValueError("Only HRP tenant member identities are eligible.")
        oid = str(uuid.UUID(str(claims["oid"])))
        label = str(claims.get("preferred_username") or claims.get("email") or "").strip().casefold()
        if label.count("@") != 1 or label.rsplit("@", 1)[1] not in self.domains:
            raise ValueError("HRP account email domain was not verified.")
        role, grants = permissions_for_roles(claims.get("roles"))
        token, csrf, now = secrets.token_urlsafe(32), secrets.token_urlsafe(32), time.time()
        with self.store.db() as db:
            db.execute("DELETE FROM sso_sessions WHERE expires_at<? OR last_seen<?", (now, now-IDLE_SECONDS))
            db.execute("INSERT INTO sso_sessions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (digest(token), oid, self.tenant, label, str(claims.get("name") or label)[:200],
                        role, json.dumps(grants), csrf, self._ip(request), now, now, now, now+SESSION_SECONDS))
            self.store.event(db, None, "hrp_sso_login", oid)
        return token

    async def _exchange(self, code, nonce, verifier):
        data = {"grant_type": "authorization_code", "client_id": self.client_id,
                "code": code, "redirect_uri": self.config.base_url + "/auth/callback",
                "code_verifier": verifier, "client_assertion_type":
                "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                "client_assertion": self._client_assertion()}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(self._endpoint("token"), data=data)
            response.raise_for_status()
            token = response.json()
            keys_response = await client.get(f"{MICROSOFT}/{self.tenant}/discovery/v2.0/keys")
            keys_response.raise_for_status()
        from access_control import MicrosoftIdentity
        config = type("TokenConfig", (), {"client_id": self.client_id})()
        claims = MicrosoftIdentity.validate_token(token["id_token"], keys_response.json(), config,
                                                   nonce, token.get("access_token"))
        if claims.get("tid") != self.tenant:
            raise ValueError("Wrong tenant")
        return claims

    def router(self):
        router = APIRouter()

        @router.get("/auth/login")
        async def login(request: Request, start: bool = False, email: str = ""):
            if request.headers.get("host", "").casefold() != urlparse(self.config.base_url).netloc.casefold():
                return RedirectResponse(self.config.base_url + "/auth/login", 303)
            if not self.configured:
                response = page("HRP sign-in unavailable", "The HRP identity configuration is incomplete. Contact IT.")
                response.status_code = 503
                return response
            if not start:
                return HTMLResponse('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Howe Robinson sign-in</title><link rel="stylesheet" href="/static/auth/auth.css"></head><body><main class="access-card"><img src="/static/img/howe-robinson-logo.svg" alt="Howe Robinson Partners"><h1>Sign in with your HRP work account</h1><p>Access and Microsoft Authenticator checks are managed by HRP IT.</p><form action="/auth/login" method="get"><input type="hidden" name="start" value="1"><label>HRP email<input type="email" name="email" autocomplete="username" required></label><button type="submit">Continue with Microsoft</button></form></main></body></html>', headers={"Cache-Control": "no-store", "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
            label = email.strip().casefold()
            if label.count("@") != 1 or label.rsplit("@", 1)[1] not in self.domains:
                raise HTTPException(403, "Use your HRP work email address.")
            state, cookie, nonce, verifier = self.store.new_flow()
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            url = self._endpoint("authorize") + "?" + urlencode({
                "client_id": self.client_id, "response_type": "code", "redirect_uri": self.config.base_url + "/auth/callback",
                "response_mode": "query", "scope": "openid profile email", "state": state,
                "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256",
                "login_hint": label})
            response = RedirectResponse(url, 303)
            response.set_cookie(FLOW_COOKIE, cookie, max_age=600, httponly=True,
                                secure=self.config.secure_cookie, samesite="lax", path="/auth")
            response.headers["Cache-Control"] = "no-store"
            return response

        @router.get("/auth/callback")
        async def callback(request: Request):
            if not self.configured:
                raise HTTPException(503, "HRP sign-in unavailable.")
            response = None
            try:
                flow = self.store.consume_flow(request.query_params.get("state", ""), request.cookies.get(FLOW_COOKIE, ""))
                if request.query_params.get("error") or not request.query_params.get("code"):
                    raise ValueError("Sign-in cancelled")
                claims = await self._exchange(request.query_params["code"], flow["nonce"], flow["verifier"])
                old = request.cookies.get(COOKIE)
                if old:
                    self.revoke(old)
                token = self.issue(claims, request)
                response = RedirectResponse("/", 303)
                response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                                    secure=self.config.secure_cookie, samesite="lax", path="/")
            except Exception as exc:
                log.warning("HRP sign-in failed: %s", type(exc).__name__)
                response = page("Sign-in could not be completed", "Your HRP identity or assigned dashboard role could not be verified. Contact HRP IT.")
                response.status_code = 403
            response.delete_cookie(FLOW_COOKIE, path="/auth")
            response.headers["Cache-Control"] = "no-store"
            return response

        @router.get("/auth/status")
        async def status():
            return RedirectResponse("/auth/login", 303)

        @router.get("/api/auth/me")
        async def me(request: Request):
            if not self.configured:
                raise HTTPException(503, "HRP sign-in unavailable.")
            user = self.session(request.cookies.get(COOKIE, ""))
            if not user or not self.fresh(user, request):
                raise HTTPException(401, "HRP sign-in required.")
            return JSONResponse({"enabled": True, "sso": True, "authenticated": True, "status": "approved",
                                 "email": user["email"], "name": user["name"], "role": user["role"],
                                 "permissions": user["permissions"], "sections": SECTIONS, "csrf": user["csrf"]},
                                headers={"Cache-Control": "no-store"})

        @router.post("/auth/logout")
        async def logout(request: Request):
            self.revoke(request.cookies.get(COOKIE, ""))
            response = JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})
            response.delete_cookie(COOKIE, path="/")
            return response

        @router.post("/api/admin/sso/sessions/revoke")
        async def revoke_sessions(request: Request):
            user = self.session(request.cookies.get(COOKIE, ""))
            if not user or user["role"] != "admin" or not self.fresh(user, request):
                raise HTTPException(403, "HRP administrator role required.")
            body = await request.json()
            try:
                oid = str(uuid.UUID(str(body["oid"])))
            except (KeyError, ValueError, TypeError):
                raise HTTPException(400, "A valid Entra object ID is required.") from None
            with self.store.db() as db:
                db.execute("DELETE FROM sso_sessions WHERE oid=?", (oid,))
                self.store.event(db, None, "hrp_sso_sessions_revoked", oid)
            return {"ok": True}

        return router
