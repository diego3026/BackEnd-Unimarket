"""Control de cancelaciones: disputas, métricas por tienda y alertas al admin.

Reglas (también en los Términos y Condiciones):
- La tienda solo cancela pedidos pendientes o en preparación.
- Si cancela con el pago reportado o confirmado, el pedido queda marcado
  ("pagado y cancelado") para revisión y la tienda debe devolver el dinero.
- Cuando la tienda cancela, el cliente puede decir si sí recibió el pedido; si
  dice que sí, se abre una disputa y el pedido cuenta como venta para la comisión
  mientras el admin no la descarte.
- Si una tienda cancela más del porcentaje configurado en 30 días, se avisa al admin.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import Integer, case, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Order, Store, User
from app.models.enums import OrderStatus, UserRole, UserStatus
from app.services.notifications import notify
from app.services.pricing import now


def notify_admins(db: Session, title: str, body: str, data: dict | None = None) -> None:
    admins = db.scalars(select(User.id).where(User.role == UserRole.admin, User.status == UserStatus.active))
    for admin_id in admins:
        notify(db, admin_id, type_="system", title=title, body=body, data=data or {})


def store_metrics(db: Session, *, days: int = 30, store_id: uuid.UUID | None = None) -> list[dict]:
    """Métricas de cancelación por tienda en los últimos `days` días."""
    since = now() - timedelta(days=days)
    cancelled = Order.status == OrderStatus.cancelled
    by_seller = cancelled & (Order.cancelled_by == "seller")
    accepted = func.coalesce(Order.history["preparing"].as_string(), "") != ""

    def count(cond):
        return func.sum(case((cond, 1), else_=0)).cast(Integer)

    stmt = (
        select(
            Store.id,
            Store.name,
            func.count(Order.id),
            count(cancelled),
            count(by_seller),
            count(by_seller & accepted),
            count(by_seller & Order.paid_cancelled),
            count(by_seller & (Order.customer_confirmation == "received")),
            count(Order.dispute_status == "open"),
        )
        .join(Order, Order.store_id == Store.id)
        .where(Order.created_at >= since)
        .group_by(Store.id, Store.name)
    )
    if store_id:
        stmt = stmt.where(Store.id == store_id)
    out = []
    for sid, name, total, canc, seller, after_accept, paid, contradicted, open_disputes in db.execute(stmt):
        rate = (canc or 0) / total if total else 0.0
        out.append(
            dict(
                store_id=sid,
                store_name=name,
                orders=total,
                cancelled=canc or 0,
                cancelled_by_store=seller or 0,
                cancelled_after_accept=after_accept or 0,
                cancelled_with_payment=paid or 0,
                contradicted_by_customer=contradicted or 0,
                open_disputes=open_disputes or 0,
                cancel_rate=round(rate, 3),
                alert=(total >= settings.cancel_alert_min_orders and rate > settings.cancel_alert_rate)
                or (paid or 0) > 0
                or (contradicted or 0) > 0,
            )
        )
    out.sort(key=lambda m: (not m["alert"], -m["cancel_rate"]))
    return out


def check_cancel_rate(db: Session, store: Store) -> None:
    """Avisa al admin cuando la tienda supera el umbral de cancelaciones."""
    metrics = store_metrics(db, store_id=store.id)
    if not metrics:
        return
    m = metrics[0]
    if m["orders"] >= settings.cancel_alert_min_orders and m["cancel_rate"] > settings.cancel_alert_rate:
        notify_admins(
            db,
            f"{store.name} cancela muchos pedidos",
            f"{round(m['cancel_rate'] * 100)} % de sus pedidos de los últimos 30 días fueron cancelados "
            f"({m['cancelled']} de {m['orders']}).",
            {"storeId": str(store.id)},
        )
