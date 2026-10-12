"""Offline HRP SSO checks with a synthetic tenant and test certificate."""
import base64
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock, patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from fastapi import FastAPI
from fastapi.testclient import TestClient

from access_control import AccessControl, AccessMiddleware, AuthConfig, COOKIE
from hrp_sso import permissions_for_roles

TENANT = "12345678-1234-1234-1234-123456789012"
CLIENT = "22345678-1234-1234-1234-123456789012"
OID = "32345678-1234-1234-1234-123456789012"


@pytest.fixture
def system(tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "HRP test")]))
            .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "HRP test")]))
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc)-timedelta(days=1))
            .not_valid_after(datetime.now(timezone.utc)+timedelta(days=30))
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / "public.pem", tmp_path / "private.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                          serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    for name, value in {"HRP_SSO_ENABLED":"true", "HRP_ENTRA_TENANT_ID":TENANT,
                        "HRP_ENTRA_CLIENT_ID":CLIENT, "HRP_ENTRA_EMAIL_DOMAINS":"howerob.com",
                        "HRP_ENTRA_CERT_PATH":str(cert_path), "HRP_ENTRA_PRIVATE_KEY_PATH":str(key_path)}.items():
        monkeypatch.setenv(name, value)
    access = AccessControl(AuthConfig(), tmp_path / "access.sqlite3")
    app = FastAPI()
    app.include_router(access.router())

    @app.get("/")
    def home():
        return {"ok": True}

    @app.get("/api/coal/dashboard")
    def coal():
        return {"data": "coal"}

    @app.get("/api/weather/cyclones")
    def weather():
        return {"data": "weather"}

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    app.add_middleware(AccessMiddleware, access=access)
    return access, TestClient(app, base_url="http://127.0.0.1:8000")


def claims(*, roles=None, tenant=TENANT, acct="0", email="person@howerob.com"):
    return {"tid":tenant, "oid":OID, "acct":acct, "preferred_username":email,
            "name":"Test Person", "roles":roles or ["HRP.india_coal.View"]}


def test_roles_fail_closed_and_edit_implies_view():
    with pytest.raises(ValueError):
        permissions_for_roles(["Other.Role"])
    role, grants = permissions_for_roles(["HRP.india_coal.Edit"])
    assert role == "viewer" and grants["india_coal"] == "edit"
    assert grants["weather"] == "hidden"


def test_hrp_membership_domain_and_admin(system):
    access, client = system
    assert access.sso.configured and access.company is None
    for bad in (claims(tenant="42345678-1234-1234-1234-123456789012"),
                claims(acct="1"), claims(email="person@gmail.com"),
                claims(roles=["Unknown"])):
        with pytest.raises(ValueError):
            access.sso.issue(bad, type("Request", (), {"client": type("Client", (), {"host":"testclient"})()})())
    request = type("Request", (), {"client": type("Client", (), {"host":"testclient"})()})()
    token = access.sso.issue(claims(roles=["HRP.Admin"]), request)
    client.cookies.set(COOKIE, token)
    assert client.get("/api/auth/me").json()["permissions"]["weather"] == "edit"


def test_login_is_tenant_specific_and_pkce(system):
    _, client = system
    assert client.get("/auth/login?start=1&email=person@gmail.com").status_code == 403
    response = client.get("/auth/login?start=1&email=person%40howerob.com", follow_redirects=False)
    assert response.status_code == 303
    target = urlparse(response.headers["location"])
    params = parse_qs(target.query)
    assert TENANT in target.path and params["code_challenge_method"] == ["S256"]
    assert params["nonce"] and params["state"] and params["login_hint"] == ["person@howerob.com"]


def test_certificate_client_assertion_is_signed_for_tenant_token_endpoint(system):
    access, _ = system
    assertion = access.sso._client_assertion().split(".")
    assert len(assertion) == 3
    decode = lambda part: base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
    header, payload = json.loads(decode(assertion[0])), json.loads(decode(assertion[1]))
    assert header["alg"] == "PS256" and header["x5t#S256"]
    assert payload["aud"].endswith(f"/{TENANT}/oauth2/v2.0/token")
    assert payload["iss"] == CLIENT and payload["sub"] == CLIENT
    cert = x509.load_der_x509_certificate(access.sso.cert_der)
    cert.public_key().verify(decode(assertion[2]), f"{assertion[0]}.{assertion[1]}".encode(),
                             padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size),
                             hashes.SHA256())


def test_callback_issues_session_only_for_verified_hrp_role(system):
    access, client = system
    start = client.get("/auth/login?start=1&email=person%40howerob.com", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    with patch.object(access.sso, "_exchange", new_callable=AsyncMock, return_value=claims()):
        response = client.get(f"/auth/callback?state={state}&code=test-code", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/"
    assert client.get("/api/auth/me").json()["email"] == "person@howerob.com"
    assert client.get("/api/coal/dashboard").status_code == 200


def test_section_enforcement_freshness_and_network_change(system):
    access, client = system
    request = type("Request", (), {"client": type("Client", (), {"host":"testclient"})()})()
    token = access.sso.issue(claims(), request)
    client.cookies.set(COOKIE, token)
    assert client.get("/api/coal/dashboard").status_code == 200
    assert client.get("/api/weather/cyclones").status_code == 403
    with access.store.db() as db:
        db.execute("UPDATE sso_sessions SET validated_at=validated_at-901 WHERE hash=?",
                   (__import__("access_control").digest(token),))
    assert client.get("/api/coal/dashboard").status_code == 401
    with access.store.db() as db:
        db.execute("UPDATE sso_sessions SET validated_at=validated_at+901,ip='another-network' WHERE hash=?",
                   (__import__("access_control").digest(token),))
    assert client.get("/api/coal/dashboard").status_code == 401


def test_unassigned_legacy_and_public_auth_routes_denied(system):
    access, client = system
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/coal/dashboard").status_code == 401
    assert client.get("/auth/google/verify", follow_redirects=False).status_code in (303, 401, 404)
    assert client.get("/auth/verify", follow_redirects=False).status_code in (303, 401, 404)
    assert client.get("/api/admin/access").status_code == 401


def test_emergency_revoke_requires_admin_and_csrf(system):
    access, client = system
    request = type("Request", (), {"client": type("Client", (), {"host":"testclient"})()})()
    viewer_token = access.sso.issue(claims(), request)
    client.cookies.set(COOKIE, viewer_token)
    assert client.post("/api/admin/sso/sessions/revoke", json={"oid":OID}).status_code == 403
    admin_token = access.sso.issue(claims(roles=["HRP.Admin"]), request)
    client.cookies.set(COOKIE, admin_token)
    assert client.post("/api/admin/sso/sessions/revoke", json={"oid":OID}).status_code == 403
    csrf = access.sso.session(admin_token)["csrf"]
    assert client.post("/api/admin/sso/sessions/revoke", json={"oid":OID},
                       headers={"X-CSRF-Token":csrf}).status_code == 200
    assert access.sso.session(viewer_token) is None
    assert access.sso.session(admin_token) is None
