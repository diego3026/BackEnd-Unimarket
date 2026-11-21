"""Comisión escalonada, meses gratis y control de cancelaciones."""

from datetime import timedelta

from sqlalchemy import update

from app.db.session import SessionLocal
from app.models import Store
from app.services.commissions import commission_for
from app.services.pricing import now

API = "/api/v1"


def _order(client, customer, seller, payment="cash", qty=2):
    p1 = seller["products"][0]
    r = client.post(
        f"{API}/orders",
        headers={**customer, "Idempotency-Key": f"k-{payment}-{qty}-{now().timestamp()}"},
        json={
            "storeId": seller["store"]["id"],
            "lines": [{"productId": p1["id"], "quantity": qty}],
            "mode": "pickup",
            "paymentKind": payment,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _deliver(client, seller, order):
    h = seller["headers"]
    for st in ("preparing", "ready"):
        assert (
            client.post(f"{API}/seller/orders/{order['id']}/status", headers=h, json={"status": st}).status_code == 200
        )
    r = client.post(
        f"{API}/seller/orders/{order['id']}/status",
        headers=h,
        json={"status": "delivered", "pickupCode": order["pickupCode"]},
    )
    assert r.status_code == 200, r.text


def _age_store(store_id: str, days: int) -> None:
    with SessionLocal() as db:
        db.execute(update(Store).where(Store.id == store_id).values(approved_at=now() - timedelta(days=days)))
        db.commit()


def test_marginal_rates():
    assert commission_for(0) == 0
    assert commission_for(400_000) == 4_000  # todo a 1 %
    assert commission_for(700_000) == 5_000 + 4_000  # 500 mil a 1 % + 200 mil a 2 %


def test_first_two_months_are_free(client, seller, customer):
    _deliver(client, seller, _order(client, customer, seller))
    st = client.get(f"{API}/seller/commissions", headers=seller["headers"]).json()
    assert st["freeUntil"] is not None
    assert st["totalSales"] == 18000 and st["freeSales"] == 18000 and st["commission"] == 0

    # Tienda aprobada hace 61 días: los pedidos de ahora ya pagan 1 %
    _age_store(seller["store"]["id"], 61)
    _deliver(client, seller, _order(client, customer, seller, qty=1))
    st = client.get(f"{API}/seller/commissions", headers=seller["headers"]).json()
    assert st["chargeableSales"] == 27000 and st["commission"] == 270


def test_cancel_with_payment_is_flagged(client, seller, customer, admin_headers):
    _age_store(seller["store"]["id"], 90)
    order = _order(client, customer, seller, payment="breb")
    client.post(f"{API}/orders/{order['id']}/payment-report", headers=customer, json={"reference": "M123"})
    r = client.post(
        f"{API}/seller/orders/{order['id']}/status",
        headers=seller["headers"],
        json={"status": "cancelled", "reason": "Sin producto"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["paidCancelled"] is True and r.json()["disputeStatus"] == "open"

    disputes = client.get(f"{API}/admin/disputes", headers=admin_headers).json()
    assert [d["id"] for d in disputes] == [order["id"]]
    admin_notes = client.get(f"{API}/me/notifications", headers=admin_headers).json()
    assert admin_notes["total"] >= 1

    # El admin confirma que sí fue una venta: entra en la comisión
    r = client.post(f"{API}/admin/orders/{order['id']}/dispute", headers=admin_headers, json={"decision": "confirmed"})
    assert r.json()["disputeStatus"] == "confirmed"
    st = client.get(f"{API}/seller/commissions", headers=seller["headers"]).json()
    assert st["disputedOrders"] == 1 and st["commission"] == 180


def test_customer_contradicts_cancellation(client, seller, customer, admin_headers):
    order = _order(client, customer, seller)
    client.post(
        f"{API}/seller/orders/{order['id']}/status",
        headers=seller["headers"],
        json={"status": "cancelled", "reason": "Cerramos temprano"},
    )
    notes = client.get(f"{API}/me/notifications", headers=customer).json()["items"]
    assert notes[0]["data"]["askReceived"] is True

    r = client.post(f"{API}/orders/{order['id']}/cancel-feedback", headers=customer, json={"received": True})
    assert r.status_code == 200 and r.json()["customerConfirmation"] == "received"
    assert r.json()["disputeStatus"] == "open"
    r = client.post(f"{API}/orders/{order['id']}/cancel-feedback", headers=customer, json={"received": False})
    assert r.json()["error"]["code"] == "already_answered"

    risk = client.get(f"{API}/admin/stores-risk", headers=admin_headers).json()
    assert risk[0]["contradictedByCustomer"] == 1 and risk[0]["alert"] is True

    # Si el admin la descarta, deja de contar
    client.post(f"{API}/admin/orders/{order['id']}/dispute", headers=admin_headers, json={"decision": "dismissed"})
    st = client.get(f"{API}/seller/commissions", headers=seller["headers"]).json()
    assert st["disputedOrders"] == 0


def test_feedback_only_for_store_cancellations(client, seller, customer):
    order = _order(client, customer, seller)
    client.post(f"{API}/orders/{order['id']}/cancel", headers=customer, json={"reason": "Me equivoqué"})
    r = client.post(f"{API}/orders/{order['id']}/cancel-feedback", headers=customer, json={"received": True})
    assert r.json()["error"]["code"] == "not_cancelled_by_store"


def test_store_cannot_cancel_after_ready(client, seller, customer):
    order = _order(client, customer, seller)
    h = seller["headers"]
    for st in ("preparing", "ready"):
        client.post(f"{API}/seller/orders/{order['id']}/status", headers=h, json={"status": st})
    r = client.post(f"{API}/seller/orders/{order['id']}/status", headers=h, json={"status": "cancelled"})
    assert r.json()["error"]["code"] == "cannot_cancel"


def test_high_cancel_rate_alerts_admin(client, seller, customer, admin_headers):
    for _ in range(5):
        o = _order(client, customer, seller, qty=1)
        client.post(
            f"{API}/seller/orders/{o['id']}/status",
            headers=seller["headers"],
            json={"status": "cancelled", "reason": "x"},
        )
    risk = client.get(f"{API}/admin/stores-risk", headers=admin_headers).json()[0]
    assert risk["cancelRate"] == 1.0 and risk["alert"] is True
    titles = [n["title"] for n in client.get(f"{API}/me/notifications", headers=admin_headers).json()["items"]]
    assert any("cancela muchos pedidos" in t for t in titles)
