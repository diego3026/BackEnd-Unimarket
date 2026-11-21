"""Comisión de UniMarket por tienda y por mes.

- Base: lo que el cliente pagó por los productos (total del pedido menos el domicilio)
  de los pedidos entregados en el mes, más los cancelados que el cliente dice haber
  recibido (disputa abierta o confirmada).
- Pedidos hechos durante los primeros COMMISSION_FREE_DAYS días desde la aprobación
  de la tienda: 0 %.
- Tasa escalonada marginal: hasta COMMISSION_TIER_LIMIT en el mes paga la tasa baja;
  solo el excedente paga la tasa normal (vender más nunca hace pagar más por lo anterior).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import BusinessRuleError
from app.models import Order, Store
from app.models.enums import OrderStatus, StoreStatus


def month_range(month: str | None) -> tuple[str, datetime, datetime]:
    today = datetime.now(UTC)
    if not month:
        month = f"{today.year:04d}-{today.month:02d}"
    try:
        y, m = (int(x) for x in month.split("-"))
        start = datetime(y, m, 1, tzinfo=UTC)
    except (ValueError, TypeError):
        raise BusinessRuleError("Mes inválido, usa AAAA-MM", code="invalid_month") from None
    end = datetime(y + (m == 12), 1 if m == 12 else m + 1, 1, tzinfo=UTC)
    return month, start, end


def commission_for(base: int) -> int:
    low = min(base, settings.commission_tier_limit)
    high = max(base - settings.commission_tier_limit, 0)
    return round(low * settings.commission_low_rate + high * settings.commission_high_rate)


def free_until(store: Store) -> datetime | None:
    if not store.approved_at:
        return None
    return store.approved_at + timedelta(days=settings.commission_free_days)


def statement(db: Session, store: Store, month: str | None) -> dict:
    month, start, end = month_range(month)
    disputed = and_(
        Order.status == OrderStatus.cancelled,
        or_(
            Order.dispute_status == "confirmed",
            and_(Order.customer_confirmation == "received", Order.dispute_status != "dismissed"),
        ),
        Order.cancelled_at >= start,
        Order.cancelled_at < end,
    )
    delivered = and_(Order.status == OrderStatus.delivered, Order.delivered_at >= start, Order.delivered_at < end)
    orders = db.scalars(
        select(Order).where(Order.store_id == store.id, or_(delivered, disputed)).order_by(Order.id)
    ).all()
    limit_free = free_until(store)
    lines, sales, free_sales = [], 0, 0
    for o in orders:
        amount = max(o.total - o.delivery_fee, 0)
        is_free = bool(limit_free and o.created_at < limit_free)
        kind = "disputed" if o.status == OrderStatus.cancelled else "delivered"
        lines.append(
            dict(
                order_id=o.id,
                date=o.delivered_at or o.cancelled_at or o.created_at,
                amount=amount,
                kind=kind,
                free=is_free,
            )
        )
        if is_free:
            free_sales += amount
        else:
            sales += amount
    return dict(
        store_id=store.id,
        store_name=store.name,
        month=month,
        free_until=limit_free,
        orders=len(lines),
        disputed_orders=sum(1 for ln in lines if ln["kind"] == "disputed"),
        total_sales=sales + free_sales,
        free_sales=free_sales,
        chargeable_sales=sales,
        tier_limit=settings.commission_tier_limit,
        low_rate=settings.commission_low_rate,
        high_rate=settings.commission_high_rate,
        commission=commission_for(sales),
        lines=lines,
    )


def all_statements(db: Session, month: str | None) -> list[dict]:
    stores = db.scalars(select(Store).where(Store.status != StoreStatus.pending).order_by(Store.name)).all()
    out = []
    for s in stores:
        st = statement(db, s, month)
        if st["orders"]:
            st["lines"] = []
            out.append(st)
    return out


def store_by_id(db: Session, store_id: uuid.UUID) -> Store:
    store = db.get(Store, store_id)
    if not store:
        from app.core.errors import NotFound

        raise NotFound("Tienda no encontrada", code="store_not_found")
    return store
