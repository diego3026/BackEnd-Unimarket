"""Pedidos del cliente: cotizar, comprar, seguir, cancelar y calificar."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, status

from app.api.deps import DB, CurrentUser, Paging
from app.schemas.common import Page
from app.schemas.order import (
    CheckoutQuoteOut,
    OrderCancelIn,
    OrderCreateIn,
    OrderOut,
    PaymentReportIn,
    ReviewIn,
    ReviewOut,
)
from app.schemas.product import CouponCheckIn, CouponCheckOut
from app.services.catalog import CatalogService
from app.services.orders import OrderService

router = APIRouter(prefix="/orders", tags=["Pedidos"])


@router.post("/quote", response_model=CheckoutQuoteOut)
def quote(data: OrderCreateIn, user: CurrentUser, db: DB):
    """Calcula los totales del checkout sin crear el pedido."""
    return OrderService(db).quote(user, data)


@router.post("/coupon-check", response_model=CouponCheckOut)
def check_coupon(data: CouponCheckIn, user: CurrentUser, db: DB):
    return CatalogService(db).check_coupon(user, data)


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(
    data: OrderCreateIn,
    user: CurrentUser,
    db: DB,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=80)] = None,
):
    """Crea el pedido. Envía `Idempotency-Key` para no duplicarlo si la red falla y se reintenta."""
    return OrderService(db).create(user, data, idempotency_key)


@router.get("", response_model=Page[OrderOut])
def my_orders(user: CurrentUser, db: DB, paging: Paging, active: bool | None = None):
    return OrderService(db).my_orders(user, active=active, page=paging)


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: int, user: CurrentUser, db: DB):
    """Detalle para seguimiento (cliente, tienda o admin)."""
    return OrderService(db).get(user, order_id)


@router.post("/{order_id}/cancel", response_model=OrderOut)
def cancel_order(order_id: int, data: OrderCancelIn, user: CurrentUser, db: DB):
    return OrderService(db).cancel_by_customer(user, order_id, data.reason)


@router.post("/{order_id}/payment-report", response_model=OrderOut)
def report_payment(order_id: int, data: PaymentReportIn, user: CurrentUser, db: DB):
    """Avisa a la tienda que ya transferiste (Nequi o Bre-B). Ella confirma cuando le llegue."""
    return OrderService(db).report_payment(user, order_id, data.reference)


@router.post("/{order_id}/review", response_model=ReviewOut, status_code=status.HTTP_201_CREATED)
def review_order(order_id: int, data: ReviewIn, user: CurrentUser, db: DB):
    return OrderService(db).review(user, order_id, data)
