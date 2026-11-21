"""Protecciones de la API: clave de app, bloqueo por intentos y tamaño de petición."""

from app.core.config import settings
from tests.conftest import PASSWORD, register


def test_app_key_required_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "app_client_keys", "clave-app-1,clave-app-2")
    r = client.get("/api/v1/campus/places")
    assert r.status_code == 403 and r.json()["error"]["code"] == "client_not_allowed"
    assert client.get("/api/v1/campus/places", headers={"X-App-Key": "otra"}).status_code == 403
    assert client.get("/api/v1/campus/places", headers={"X-App-Key": "clave-app-2"}).status_code == 200
    # Railway debe poder revisar la salud sin clave
    assert client.get("/health").status_code == 200


def test_account_locks_after_failed_logins(client):
    register(client)
    bad = {"email": "cliente@test.co", "password": "Mala12345"}
    for _ in range(settings.max_failed_logins):
        assert client.post("/api/v1/auth/login", json=bad).status_code == 401
    # Bloqueada: ni la clave correcta entra durante el bloqueo
    r = client.post("/api/v1/auth/login", json={"email": "cliente@test.co", "password": PASSWORD})
    assert r.status_code == 429 and r.json()["error"]["code"] == "account_locked"


def test_body_too_large(client):
    r = client.post(
        "/api/v1/auth/login",
        content=b"x" * (settings.max_body_bytes + 1),
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 413


def test_root_reveals_nothing(client):
    assert client.get("/").json() == {"status": "ok"}
