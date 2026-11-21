"""Pruebas contra PostgreSQL real (TEST_DATABASE_URL), con las migraciones de Alembic."""

from __future__ import annotations

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL", "postgresql+psycopg://unimarket:unimarket@localhost:5432/unimarket_test"
)
os.environ.setdefault("AUTO_APPROVE_STORES", "false")
os.environ.setdefault("ENABLE_RESEARCH_API", "false")

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from alembic import command  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, User  # noqa: E402
from app.models.enums import UserRole  # noqa: E402

PASSWORD = "Clave12345"


@pytest.fixture(scope="session", autouse=True)
def _schema():
    cfg = Config("alembic.ini")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean():
    from app.core.middleware import micro_cache

    micro_cache.clear()
    yield
    micro_cache.clear()
    tables = [t.name for t in reversed(Base.metadata.sorted_tables) if t.name != "campus_places"]
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def register(client, email="cliente@test.co", name="Laura Cliente", phone="3001112233"):
    r = client.post(
        "/api/v1/auth/register",
        json={"fullName": name, "email": email, "phone": phone, "password": PASSWORD, "acceptTerms": True},
    )
    assert r.status_code == 201, r.text
    return r.json()


def auth(tokens) -> dict:
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


@pytest.fixture
def admin_headers(client):
    with SessionLocal() as db:
        db.add(
            User(
                email="admin@test.co",
                password_hash=hash_password(PASSWORD),
                full_name="Admin",
                role=UserRole.admin,
                email_verified=True,
            )
        )
        db.commit()
    r = client.post("/api/v1/auth/login", json={"email": "admin@test.co", "password": PASSWORD})
    return auth(r.json())


@pytest.fixture
def seller(client, admin_headers):
    """Emprendedor con tienda aprobada y dos productos."""
    tokens = register(client, email="vendedor@test.co", name="Otto Pérez", phone="3002223344")
    h = auth(tokens)
    r = client.post(
        "/api/v1/seller/store",
        headers=h,
        json={
            "name": "Sandwiches Otto",
            "category": "Comida",
            "pickupPlaceId": "b8",
            "deliveryFee": 2000,
            "acceptsBreb": True,
            "brebKey": "@ottosandwich",
        },
    )
    assert r.status_code == 201, r.text
    store = r.json()
    assert store["status"] == "pending"
    r = client.post(f"/api/v1/admin/stores/{store['id']}/review", headers=admin_headers, json={"status": "approved"})
    assert r.status_code == 200, r.text
    p1 = client.post(
        "/api/v1/seller/products",
        headers=h,
        json={"name": "Sándwich Clásico", "category": "Sándwiches", "price": 9000, "stock": 5},
    ).json()
    p2 = client.post(
        "/api/v1/seller/products",
        headers=h,
        json={"name": "Jugo natural", "category": "Bebidas", "price": 4000, "stock": 10},
    ).json()
    return {"headers": h, "store": store, "products": [p1, p2]}


@pytest.fixture
def customer(client):
    return auth(register(client))
