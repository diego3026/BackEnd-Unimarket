from app.db.session import SessionLocal
from app.models import OneTimeToken
from tests.conftest import PASSWORD, auth, register


def test_register_login_me(client):
    tokens = register(client)
    assert tokens["user"]["role"] == "consumer"
    assert "passwordHash" not in tokens["user"]
    me = client.get("/api/v1/me", headers=auth(tokens))
    assert me.status_code == 200
    assert me.json()["email"] == "cliente@test.co"

    r = client.post("/api/v1/auth/login", json={"email": "CLIENTE@test.co", "password": PASSWORD})
    assert r.status_code == 200


def test_register_rejects_weak_password_and_duplicates(client):
    r = client.post(
        "/api/v1/auth/register",
        json={"fullName": "Ana", "email": "a@test.co", "phone": "3001112233", "password": "abc", "acceptTerms": True},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    register(client, email="dup@test.co")
    r = client.post(
        "/api/v1/auth/register",
        json={
            "fullName": "Ana B",
            "email": "dup@test.co",
            "phone": "3001112233",
            "password": PASSWORD,
            "acceptTerms": True,
        },
    )
    assert r.status_code == 409


def test_register_rejects_unknown_fields(client):
    # Nadie puede registrarse como admin enviando "role".
    r = client.post(
        "/api/v1/auth/register",
        json={
            "fullName": "Hacker",
            "email": "h@test.co",
            "phone": "3001112233",
            "password": PASSWORD,
            "acceptTerms": True,
            "role": "admin",
        },
    )
    assert r.status_code == 422


def test_login_wrong_password_is_generic(client):
    register(client)
    a = client.post("/api/v1/auth/login", json={"email": "cliente@test.co", "password": "Otra12345"})
    b = client.post("/api/v1/auth/login", json={"email": "nadie@test.co", "password": "Otra12345"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_refresh_rotation_and_reuse_detection(client):
    tokens = register(client)
    first = tokens["refreshToken"]
    r = client.post("/api/v1/auth/refresh", json={"refreshToken": first})
    assert r.status_code == 200
    second = r.json()["refreshToken"]
    assert second != first
    # Reusar el token viejo revoca toda la familia (incluido el nuevo).
    assert client.post("/api/v1/auth/refresh", json={"refreshToken": first}).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refreshToken": second}).status_code == 401


def test_change_password_invalidates_tokens(client):
    tokens = register(client)
    h = auth(tokens)
    r = client.post("/api/v1/me/password", headers=h, json={"currentPassword": PASSWORD, "newPassword": "NuevaClave99"})
    assert r.status_code == 200
    assert client.get("/api/v1/me", headers=h).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refreshToken": tokens["refreshToken"]}).status_code == 401
    assert (
        client.post("/api/v1/auth/login", json={"email": "cliente@test.co", "password": "NuevaClave99"}).status_code
        == 200
    )


def test_password_reset_flow(client, monkeypatch):
    register(client)
    sent = {}
    monkeypatch.setattr("app.services.auth.send_email", lambda to, s, body: sent.update(body=body))
    r = client.post("/api/v1/auth/forgot-password", json={"email": "cliente@test.co"})
    assert r.status_code == 202
    token = sent["body"].split("token=")[1].split()[0]
    # Correo inexistente: misma respuesta.
    assert client.post("/api/v1/auth/forgot-password", json={"email": "x@test.co"}).status_code == 202
    r = client.post("/api/v1/auth/reset-password", json={"token": token, "newPassword": "Recuperada1"})
    assert r.status_code == 200
    # El token es de un solo uso.
    assert (
        client.post("/api/v1/auth/reset-password", json={"token": token, "newPassword": "Otra12345"}).status_code == 401
    )
    with SessionLocal() as db:
        assert all(t.token_hash != token for t in db.query(OneTimeToken))  # solo se guarda el hash


def test_invalid_and_missing_tokens(client):
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me", headers={"Authorization": "Bearer abc.def.ghi"}).status_code == 401


def test_security_headers(client):
    r = client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "X-Request-ID" in r.headers
