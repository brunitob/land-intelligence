"""Login propio: contraseñas con scrypt, sesión por cookie, CSRF y freno a la fuerza bruta."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from patagonia_land.auth import hash_password, verify_password
from tests.conftest import requires_db

H = {"X-Requested-With": "fetch"}


def test_password_hash_roundtrip():
    h = hash_password("una-clave-larga-123")
    assert h.startswith("scrypt$") and "una-clave" not in h
    assert verify_password("una-clave-larga-123", h)
    assert not verify_password("otra-clave-larga-123", h)
    assert not verify_password("x", "basura")
    assert hash_password("misma") != hash_password("misma")  # sal distinta


@pytest.fixture
def secured(monkeypatch):
    from patagonia_land.config import get_settings

    monkeypatch.setattr(get_settings(), "api_token", "token-de-prueba")
    monkeypatch.setattr(get_settings(), "cookie_secure", False)  # TestClient habla http
    # Base de TEST: sin esto, correr la suite varias veces en 15 min llega al tope de fallos por IP (429).
    from sqlalchemy import text

    from patagonia_land.db.session import session_scope
    with session_scope() as s:
        s.execute(text("TRUNCATE login_attempts"))


@pytest.fixture
def user():
    from patagonia_land.db.models import User
    from patagonia_land.db.session import session_scope

    name = f"u{uuid.uuid4().hex[:8]}"
    with session_scope() as s:
        s.add(User(username=name, password_hash=hash_password("clave-correcta-123")))
    return name


@requires_db
def test_session_login_logout_and_csrf(secured, user):
    from patagonia_land.api.main import app

    c = TestClient(app)
    assert c.get("/sources").status_code == 401
    assert c.get("/sources", headers={"Authorization": "Bearer token-de-prueba"}).status_code == 200
    assert c.post("/auth/login", json={"username": user, "password": "mal-12345678"}, headers=H).status_code == 401
    # Sin el encabezado anti-CSRF no se acepta ni el login.
    assert c.post("/auth/login", json={"username": user, "password": "clave-correcta-123"}).status_code == 403
    r = c.post("/auth/login", json={"username": user.upper(), "password": "clave-correcta-123"}, headers=H)
    assert r.status_code == 200
    ck = r.headers["set-cookie"].lower()
    assert "httponly" in ck and "samesite=strict" in ck
    assert c.get("/auth/me").json()["username"] == user
    assert c.get("/sources").status_code == 200
    assert c.post("/geo/analyze").status_code == 403          # cambio sin encabezado: rechazado
    assert c.post("/geo/analyze", headers=H).status_code == 202
    assert c.post("/auth/logout").status_code == 204
    assert c.get("/sources").status_code == 401


@requires_db
def test_bruteforce_is_throttled(secured, user):
    from patagonia_land.api.main import app

    c = TestClient(app)
    for _ in range(5):
        assert c.post("/auth/login", json={"username": user, "password": "nop-nop-nop-1"}, headers=H).status_code == 401
    r = c.post("/auth/login", json={"username": user, "password": "clave-correcta-123"}, headers=H)
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
