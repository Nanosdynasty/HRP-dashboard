"""Microsoft token/transport regressions. Password/MFA/session/access scenarios live in test_company_auth.py."""
import base64
import json
import time
import logging
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from authlib.jose import JsonWebToken
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from starlette.websockets import WebSocket, WebSocketDisconnect
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from access_control import (AccessControl, AccessMiddleware, AccessStore, AuthConfig,
                           COOKIE, FLOW_COOKIE, MicrosoftIdentity, CallbackLogFilter, digest)

TENANT = "12345678-1234-1234-1234-123456789012"
ISSUER = f"https://login.microsoftonline.com/{TENANT}/v2.0"


@pytest.fixture
def system(tmp_path):
    config = AuthConfig(client_id="test-client", client_secret="not-a-real-secret",
                        admin_issuer=ISSUER, admin_subject="owner")
    access = AccessControl(config, tmp_path / "access.sqlite3")
    app = FastAPI()
    app.include_router(access.router())

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    def protected(path: str):
        return {"data": "protected"}

    @app.websocket("/ws")
    async def socket(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("connected")
        await websocket.receive_text()

    app.add_middleware(AccessMiddleware, access=access)
    return access, TestClient(app, base_url=config.base_url)


def identity(subject="owner", email="owner@example.com", issuer=ISSUER):
    return {"iss": issuer, "sub": subject, "email": email, "name": subject}


def sign_in(access, client, subject="owner", email="owner@example.com"):
    token = access.store.login(identity(subject, email), access.config)
    client.cookies.set(COOKIE, token)
    session = access.store.session(token)
    return token, {"X-CSRF-Token": session["csrf"]}


def approved_viewer(access, client):
    access.store.login(identity(), access.config)
    access.store.invite("viewer@example.com", True, 1)
    token = access.store.login(identity("viewer", "viewer@example.com"), access.config)
    row = access.store.session(token)
    access.store.update_account(row["id"], "approved", "viewer", 1)
    return sign_in(access, client, "viewer", "viewer@example.com")


























@pytest.fixture
def signing_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.public_key().public_numbers()
    encode = lambda n: base64.urlsafe_b64encode(n.to_bytes((n.bit_length()+7)//8, "big")).decode().rstrip("=")
    return key, {"keys":[{"kty":"RSA","use":"sig","alg":"RS256","kid":"test-key","n":encode(numbers.n),"e":encode(numbers.e)}]}


@pytest.mark.parametrize("tenant", [TENANT, "9188040d-6c67-4c5b-b112-36a304b66dad"])
def test_work_and_personal_signed_identity(system, signing_key, tenant):
    access, _ = system
    key, keys = signing_key
    claims = {"iss":f"https://login.microsoftonline.com/{tenant}/v2.0", "tid":tenant,
              "sub":"a-real-subject", "aud":"test-client", "exp":int(time.time())+300,
              "iat":int(time.time()), "nonce":"nonce"}
    token = JsonWebToken(["RS256"]).encode({"alg":"RS256","kid":"test-key"}, claims, key).decode()
    assert MicrosoftIdentity.validate_token(token, keys, access.config, "nonce")["sub"] == "a-real-subject"


@pytest.mark.parametrize("changed", [{"aud":"another-client"},{"nonce":"another-nonce"},
                                     {"exp":1},{"iss":"https://evil.example"},{"tid":"not-a-tenant"}])
def test_bad_token_claims_rejected(system, signing_key, changed):
    access, _ = system
    key, keys = signing_key
    claims = {"iss":ISSUER,"tid":TENANT,"sub":"someone","aud":"test-client",
              "exp":int(time.time())+300,"iat":int(time.time()),"nonce":"nonce",**changed}
    token = JsonWebToken(["RS256"]).encode({"alg":"RS256","kid":"test-key"},claims,key).decode()
    with pytest.raises(Exception):
        MicrosoftIdentity.validate_token(token,keys,access.config,"nonce")


def test_bad_signature_rejected(system, signing_key):
    access, _ = system
    _, keys = signing_key
    other_key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
    claims = {"iss":ISSUER,"tid":TENANT,"sub":"someone","aud":"test-client",
              "exp":int(time.time())+300,"iat":int(time.time()),"nonce":"nonce"}
    token = JsonWebToken(["RS256"]).encode({"alg":"RS256","kid":"test-key"},claims,other_key).decode()
    with pytest.raises(Exception):
        MicrosoftIdentity.validate_token(token,keys,access.config,"nonce")


@pytest.mark.parametrize("changed", [{},{"aud":"wrong-client"},{"nonce":"wrong-nonce"},
                                     {"email_verified":False},{"iss":"https://fake-google.example"},
                                     {"exp":1}])
def test_google_identity_token_validation(signing_key, changed):
    from access_control import GoogleIdentity
    key,keys=signing_key
    claims={"iss":"https://accounts.google.com","sub":"google-stable-subject",
            "aud":"google-client","email":"person@gmail.com","email_verified":True,
            "exp":int(time.time())+300,"iat":int(time.time()),"nonce":"nonce",**changed}
    token=JsonWebToken(["RS256"]).encode({"alg":"RS256","kid":"test-key"},claims,key).decode()
    if changed:
        with pytest.raises(Exception):
            GoogleIdentity.validate_token(token,keys,"google-client","nonce")
    else:
        assert GoogleIdentity.validate_token(token,keys,"google-client","nonce")["sub"]=="google-stable-subject"


def test_azure_app_service_fails_closed_with_sqlite(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBSITE_SITE_NAME", "howe-robinson-dashboard")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("APP_AUTH_ENABLED", "false")
    monkeypatch.setenv("AUTH_BASE_URL", "https://dashboard.azurewebsites.net")
    monkeypatch.delenv("RENDER", raising=False)
    config = AuthConfig.from_env(tmp_path)
    assert config.production and config.enabled
    assert "incompatible" in config.storage_error


def test_production_cannot_opt_out_and_render_requires_real_mount(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_AUTH_ENABLED", "false")
    monkeypatch.setenv("AUTH_BASE_URL", "https://dashboard.example")
    config = AuthConfig.from_env(tmp_path)
    assert config.enabled
    monkeypatch.setenv("RENDER", "true")
    assert "persistent disk" in AuthConfig.from_env(tmp_path).storage_error




def test_callback_codes_never_reach_uvicorn_access_logs():
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 1,
                               '%s - "%s %s HTTP/%s" %d',
                               ("127.0.0.1", "GET", "/auth/callback?code=secret&state=private", "1.1", 303), None)
    CallbackLogFilter().filter(record)
    assert "secret" not in record.getMessage()
    assert "private" not in record.getMessage()




def test_authorize_uses_pkce_nonce_and_fixed_callback(system):
    from urllib.parse import urlparse, parse_qs
    access, _ = system
    url = asyncio.run(access.identity.authorization_url("state-value", "nonce-value", "a"*43))
    params = parse_qs(urlparse(url).query)
    assert params["state"] == ["state-value"]
    assert params["nonce"] == ["nonce-value"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["redirect_uri"] == [access.config.base_url+"/auth/callback"]
    assert params["scope"] == ["openid profile email"]
