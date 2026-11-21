"""Pines del mapa (admin) y ubicación del local de las tiendas."""

from tests.conftest import auth, register

PIN = {
    "name": "Entrada principal",
    "hint": "Portería de la Cra 32",
    "kind": "entrance",
    "latitude": 11.2236,
    "longitude": -74.1872,
}


def test_admin_manages_pins(client, admin_headers, customer):
    # Solo el admin crea pines
    assert client.post("/api/v1/admin/places", headers=customer, json=PIN).status_code == 403
    r = client.post("/api/v1/admin/places", headers=admin_headers, json=PIN)
    assert r.status_code == 201, r.text
    pin = r.json()
    assert pin["id"].startswith("entrada-principal-")
    assert pin["isDeliveryPoint"] is False and pin["isActive"] is True

    public = {p["id"]: p for p in client.get("/api/v1/campus/places").json()}
    assert public[pin["id"]]["kind"] == "entrance"

    r = client.patch(
        f"/api/v1/admin/places/{pin['id']}",
        headers=admin_headers,
        json={"isDeliveryPoint": True, "description": "Frente a la portería"},
    )
    assert r.json()["isDeliveryPoint"] is True

    assert client.delete(f"/api/v1/admin/places/{pin['id']}", headers=admin_headers).status_code == 204
    from app.core.middleware import micro_cache

    micro_cache.clear()
    assert pin["id"] not in {p["id"] for p in client.get("/api/v1/campus/places").json()}
    listed = {p["id"]: p for p in client.get("/api/v1/admin/places", headers=admin_headers).json()}
    assert listed[pin["id"]]["isActive"] is False


def test_guide_pin_is_not_a_pickup_point(client, admin_headers):
    pin = client.post("/api/v1/admin/places", headers=admin_headers, json=PIN).json()
    h = auth(register(client, email="tienda@test.co"))
    r = client.post(
        "/api/v1/seller/store", headers=h, json={"name": "Mi tienda", "category": "Comida", "pickupPlaceId": pin["id"]}
    )
    assert r.status_code == 422 or r.json()["error"]["code"] == "invalid_place", r.text


def test_pin_in_use_cannot_be_removed(client, admin_headers, seller):
    r = client.delete("/api/v1/admin/places/b8", headers=admin_headers)
    assert r.json()["error"]["code"] == "place_in_use"


def test_store_physical_location(client, seller):
    h = seller["headers"]
    r = client.patch("/api/v1/seller/store", headers=h, json={"latitude": 11.23})
    assert r.status_code == 422
    r = client.patch(
        "/api/v1/seller/store",
        headers=h,
        json={"address": "Calle 29 #5-10, local 3", "latitude": 11.2401, "longitude": -74.2110},
    )
    assert r.status_code == 200, r.text
    assert r.json()["latitude"] == 11.2401 and r.json()["address"].startswith("Calle 29")
    # Quitar el local físico
    r = client.patch("/api/v1/seller/store", headers=h, json={"latitude": None, "longitude": None})
    assert r.json()["latitude"] is None and r.json()["address"].startswith("Calle 29")
