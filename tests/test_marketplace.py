"""Flujo completo cliente ↔ emprendedor y reglas de seguridad de los pedidos."""

from tests.conftest import auth, register


def _order(client, headers, seller, **extra):
    p1, p2 = seller["products"]
    body = {
        "storeId": seller["store"]["id"],
        "lines": [{"productId": p1["id"], "quantity": 2}, {"productId": p2["id"], "quantity": 1}],
        "mode": "pickup",
        "paymentKind": "cash",
        **extra,
    }
    return client.post("/api/v1/orders", headers=headers, json=body)


def test_pending_store_is_not_public(client, admin_headers):
    h = auth(register(client, email="nuevo@test.co"))
    store = client.post("/api/v1/seller/store", headers=h, json={"name": "Nueva", "category": "Comida"}).json()
    assert client.get(f"/api/v1/stores/{store['id']}").status_code == 404
    assert client.get("/api/v1/me", headers=h).json()["role"] == "entrepreneur"


def test_catalog_and_automatic_discount(client, seller):
    h = seller["headers"]
    p1 = seller["products"][0]
    r = client.post(
        "/api/v1/seller/promotions",
        headers=h,
        json={
            "title": "Combo del día",
            "kind": "productDiscount",
            "type": "fixed",
            "value": 2000,
            "productIds": [p1["id"]],
        },
    )
    assert r.status_code == 201, r.text
    products = client.get("/api/v1/products", params={"q": "sánd"}).json()
    assert products["total"] == 1
    assert products["items"][0]["discountPrice"] == 7000
    assert client.get("/api/v1/promotions/discounts").json()[0]["title"] == "Combo del día"


def test_full_order_flow_pickup(client, seller, customer):
    h_seller = seller["headers"]
    client.post(
        "/api/v1/seller/promotions",
        headers=h_seller,
        json={
            "title": "Cupón",
            "kind": "coupon",
            "type": "percent",
            "value": 10,
            "code": "otto10",
            "minPurchase": 10000,
        },
    )

    quote = client.post(
        "/api/v1/orders/quote",
        headers=customer,
        json={
            "storeId": seller["store"]["id"],
            "lines": [{"productId": seller["products"][0]["id"], "quantity": 2}],
            "mode": "pickup",
            "paymentKind": "cash",
            "couponCode": "OTTO10",
        },
    ).json()
    assert quote["subtotal"] == 18000 and quote["couponDiscount"] == 1800 and quote["total"] == 16200

    r = _order(client, customer, seller, couponCode="OTTO10")
    assert r.status_code == 201, r.text
    order = r.json()
    assert order["subtotal"] == 22000
    assert order["couponDiscount"] == 2200
    assert order["deliveryFee"] == 0
    assert order["total"] == 19800
    assert order["placeId"] == "b8"  # punto de recogida de la tienda
    code = order["pickupCode"]
    assert len(code) == 4

    # El emprendedor ve el pedido pero NO el código de recogida.
    seller_orders = client.get("/api/v1/seller/orders", headers=h_seller, params={"active": True}).json()
    assert seller_orders["items"][0]["pickupCode"] is None
    assert seller_orders["items"][0]["nextStatus"] == "preparing"

    # Inventario descontado
    mine = {p["name"]: p for p in client.get("/api/v1/seller/products", headers=h_seller).json()}
    assert mine["Sándwich Clásico"]["stock"] == 3

    # No se puede saltar estados
    r = client.post(f"/api/v1/seller/orders/{order['id']}/status", headers=h_seller, json={"status": "delivered"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_transition"
    for st in ("preparing", "ready"):
        assert (
            client.post(
                f"/api/v1/seller/orders/{order['id']}/status", headers=h_seller, json={"status": st}
            ).status_code
            == 200
        )
    wrong = "0000" if code != "0000" else "1111"
    r = client.post(
        f"/api/v1/seller/orders/{order['id']}/status",
        headers=h_seller,
        json={"status": "delivered", "pickupCode": wrong},
    )
    assert r.json()["error"]["code"] == "invalid_pickup_code"
    r = client.post(
        f"/api/v1/seller/orders/{order['id']}/status",
        headers=h_seller,
        json={"status": "delivered", "pickupCode": code},
    )
    assert r.status_code == 200
    assert r.json()["paymentStatus"] == "paid"

    # El cliente recibe notificaciones de cada estado
    notes = client.get("/api/v1/me/notifications", headers=customer).json()
    assert notes["total"] == 3

    # Reseña (solo una vez) y promedio de la tienda
    r = client.post(
        f"/api/v1/orders/{order['id']}/review",
        headers=customer,
        json={"rating": 5, "comment": "¡Delicioso!", "tags": ["Rápido"]},
    )
    assert r.status_code == 201
    assert client.post(f"/api/v1/orders/{order['id']}/review", headers=customer, json={"rating": 4}).status_code == 422
    store = client.get(f"/api/v1/stores/{seller['store']['id']}").json()
    assert store["rating"] == 5 and store["ratingCount"] == 1

    # El cupón tenía máximo 1 uso por usuario
    r = _order(client, customer, seller, couponCode="OTTO10")
    assert r.json()["error"]["code"] == "invalid_coupon"

    earnings = client.get("/api/v1/seller/earnings", headers=h_seller).json()
    assert earnings["totalSales"] == 19800 and earnings["deliveredOrders"] == 1


def test_server_ignores_client_prices_and_checks_stock(client, seller, customer):
    p1 = seller["products"][0]
    # Campos extra como "price" o "total" se rechazan.
    r = client.post(
        "/api/v1/orders",
        headers=customer,
        json={
            "storeId": seller["store"]["id"],
            "lines": [{"productId": p1["id"], "quantity": 1, "price": 1}],
            "mode": "pickup",
            "paymentKind": "cash",
        },
    )
    assert r.status_code == 422
    r = client.post(
        "/api/v1/orders",
        headers=customer,
        json={
            "storeId": seller["store"]["id"],
            "lines": [{"productId": p1["id"], "quantity": 6}],
            "mode": "pickup",
            "paymentKind": "cash",
        },
    )
    assert r.json()["error"]["code"] == "out_of_stock"


def test_cancel_restores_stock_and_only_owner_sees_order(client, seller, customer):
    order = _order(client, customer, seller).json()
    other = auth(register(client, email="otro@test.co", phone="3005556677"))
    # Otro usuario no puede ver ni cancelar el pedido (404, no revela que existe).
    assert client.get(f"/api/v1/orders/{order['id']}", headers=other).status_code == 404
    assert client.post(f"/api/v1/orders/{order['id']}/cancel", headers=other, json={}).status_code == 404
    r = client.post(f"/api/v1/orders/{order['id']}/cancel", headers=customer, json={"reason": "Me equivoqué"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    mine = {p["name"]: p for p in client.get("/api/v1/seller/products", headers=seller["headers"]).json()}
    assert mine["Sándwich Clásico"]["stock"] == 5


def test_idempotent_order_creation(client, seller, customer):
    h = {**customer, "Idempotency-Key": "abc-123"}
    a = _order(client, h, seller).json()
    b = _order(client, h, seller).json()
    assert a["id"] == b["id"]
    assert client.get("/api/v1/orders", headers=customer).json()["total"] == 1


def test_delivery_requires_place_and_store_rules(client, seller, customer):
    r = _order(client, customer, seller, mode="delivery")
    assert r.status_code == 422
    r = _order(client, customer, seller, mode="delivery", placeId="b2")
    assert r.status_code == 201 and r.json()["deliveryFee"] == 2000
    client.patch("/api/v1/seller/store", headers=seller["headers"], json={"isOpen": False})
    r = _order(client, customer, seller)
    assert r.json()["error"]["code"] == "store_closed"


def test_seller_cannot_touch_other_store(client, seller, admin_headers):
    h2 = auth(register(client, email="otra@test.co", phone="3009998877"))
    client.post("/api/v1/seller/store", headers=h2, json={"name": "Otra tienda", "category": "Postres"})
    pid = seller["products"][0]["id"]
    assert client.patch(f"/api/v1/seller/products/{pid}", headers=h2, json={"price": 1}).status_code == 404
    assert client.delete(f"/api/v1/seller/products/{pid}", headers=h2).status_code == 404


def test_role_guards(client, customer, seller):
    assert client.get("/api/v1/admin/users", headers=customer).status_code == 403
    assert client.get("/api/v1/seller/orders", headers=customer).status_code == 403
    assert client.get("/api/v1/admin/users", headers=seller["headers"]).status_code == 403


def test_cards_never_store_full_number(client, customer):
    r = client.post(
        "/api/v1/me/payment-methods",
        headers=customer,
        json={"brand": "Visa", "last4": "4242", "holder": "Laura Cliente", "expMonth": 12, "expYear": 2030},
    )
    assert r.status_code == 201 and r.json()["isDefault"] is True and r.json()["expiry"] == "12/30"
    r = client.post(
        "/api/v1/me/payment-methods",
        headers=customer,
        json={"brand": "Visa", "number": "4242424242424242", "holder": "X", "expMonth": 1, "expYear": 2030},
    )
    assert r.status_code == 422


def test_payout_account_is_encrypted(client, seller):
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import PayoutAccount

    r = client.put(
        "/api/v1/seller/payout-account",
        headers=seller["headers"],
        json={
            "bankName": "Bancolombia",
            "accountType": "ahorros",
            "accountNumber": "12345678901",
            "holderName": "Otto Pérez",
            "holderDocument": "1082000000",
        },
    )
    assert r.status_code == 200
    assert r.json()["accountNumberMasked"].endswith("8901")
    assert "12345678901" not in r.text
    with SessionLocal() as db:
        acc = db.scalar(select(PayoutAccount))
        assert "12345678901" not in acc.account_number_encrypted


def test_admin_suspend_user_kills_session(client, admin_headers, customer):
    me = client.get("/api/v1/me", headers=customer).json()
    r = client.patch(f"/api/v1/admin/users/{me['id']}", headers=admin_headers, json={"status": "suspended"})
    assert r.status_code == 200
    assert client.get("/api/v1/me", headers=customer).status_code == 401
    report = client.get("/api/v1/admin/reports", headers=admin_headers)
    assert report.status_code == 200 and report.json()["usersByRole"]["consumer"] == 1


def test_concurrent_orders_never_oversell(client, seller):
    """10 clientes compran a la vez el mismo producto con 5 unidades: solo 5 lo logran."""
    from concurrent.futures import ThreadPoolExecutor

    buyers = [auth(register(client, email=f"c{i}@test.co", phone=f"30011100{i:02d}")) for i in range(10)]
    pid = seller["products"][0]["id"]

    def buy(h):
        return client.post(
            "/api/v1/orders",
            headers=h,
            json={
                "storeId": seller["store"]["id"],
                "lines": [{"productId": pid, "quantity": 1}],
                "mode": "pickup",
                "paymentKind": "cash",
            },
        ).status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(buy, buyers))
    assert codes.count(201) == 5
    assert codes.count(422) == 5
    mine = {p["name"]: p for p in client.get("/api/v1/seller/products", headers=seller["headers"]).json()}
    assert mine["Sándwich Clásico"]["stock"] == 0
