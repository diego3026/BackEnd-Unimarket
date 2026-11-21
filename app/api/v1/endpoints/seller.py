"""Panel del emprendedor: su tienda, menú, promociones, pedidos y ganancias."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import DB, CurrentUser, Paging, Seller
from app.models.enums import OrderStatus
from app.schemas.common import Page
from app.schemas.order import OrderOut, OrderStatusIn, PaymentConfirmIn, ReviewOut, ReviewReplyIn
from app.schemas.product import (
    ProductAdminOut,
    ProductIn,
    ProductUpdateIn,
    PromotionIn,
    PromotionOut,
)
from app.schemas.store import (
    EarningsOut,
    PayoutAccountIn,
    PayoutAccountOut,
    StoreCreateIn,
    StoreDocumentIn,
    StoreDocumentOut,
    StoreOut,
    StoreUpdateIn,
)
from app.services import mappers
from app.services.catalog import CatalogService
from app.services.orders import OrderService

router = APIRouter(prefix="/seller", tags=["Emprendedor"])


@router.post("/store", response_model=StoreOut, status_code=status.HTTP_201_CREATED)
def create_store(data: StoreCreateIn, user: CurrentUser, db: DB):
    """ "Quiero vender": registra la tienda. Queda pendiente hasta que el admin la apruebe."""
    return CatalogService(db).create_store(user, data)


@router.get("/store", response_model=StoreOut)
def my_store(user: Seller, db: DB):
    return mappers.store_out(CatalogService(db).my_store(user))


@router.patch("/store", response_model=StoreOut)
def update_store(data: StoreUpdateIn, user: Seller, db: DB):
    """Configurar tienda: abierto/cerrado, domicilio, recogida, medios de pago…"""
    return CatalogService(db).update_store(user, data)


@router.get("/payout-account", response_model=PayoutAccountOut)
def get_payout(user: Seller, db: DB):
    return CatalogService(db).get_payout(user)


@router.put("/payout-account", response_model=PayoutAccountOut)
def set_payout(data: PayoutAccountIn, user: Seller, db: DB):
    """Cuenta para recibir pagos. El número se guarda cifrado y solo se muestran los últimos 4."""
    return CatalogService(db).set_payout(user, data)


@router.get("/documents", response_model=list[StoreDocumentOut])
def documents(user: Seller, db: DB):
    return CatalogService(db).documents(user)


@router.post("/documents", response_model=StoreDocumentOut, status_code=status.HTTP_201_CREATED)
def add_document(data: StoreDocumentIn, user: Seller, db: DB):
    return CatalogService(db).add_document(user, data)


@router.get("/earnings", response_model=EarningsOut)
def earnings(user: Seller, db: DB, days: Annotated[int, Query(ge=1, le=365)] = 30):
    return CatalogService(db).earnings(user, days)


# ----------------------------------------------------------------- menú
@router.get("/products", response_model=list[ProductAdminOut])
def my_products(user: Seller, db: DB):
    return CatalogService(db).my_products(user)


@router.post("/products", response_model=ProductAdminOut, status_code=status.HTTP_201_CREATED)
def create_product(data: ProductIn, user: Seller, db: DB):
    return CatalogService(db).create_product(user, data)


@router.patch("/products/{product_id}", response_model=ProductAdminOut)
def update_product(product_id: uuid.UUID, data: ProductUpdateIn, user: Seller, db: DB):
    return CatalogService(db).update_product(user, product_id, data)


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(product_id: uuid.UUID, user: Seller, db: DB):
    CatalogService(db).delete_product(user, product_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ----------------------------------------------------------- promociones
@router.get("/promotions", response_model=list[PromotionOut])
def my_promotions(user: Seller, db: DB):
    return CatalogService(db).my_promotions(user)


@router.post("/promotions", response_model=PromotionOut, status_code=status.HTTP_201_CREATED)
def create_promotion(data: PromotionIn, user: Seller, db: DB):
    return CatalogService(db).create_promotion(user, data)


@router.put("/promotions/{promo_id}", response_model=PromotionOut)
def update_promotion(promo_id: uuid.UUID, data: PromotionIn, user: Seller, db: DB):
    return CatalogService(db).update_promotion(user, promo_id, data)


@router.post("/promotions/{promo_id}/pause", response_model=PromotionOut)
def pause_promotion(promo_id: uuid.UUID, user: Seller, db: DB):
    return CatalogService(db).toggle_promotion(user, promo_id, False)


@router.post("/promotions/{promo_id}/resume", response_model=PromotionOut)
def resume_promotion(promo_id: uuid.UUID, user: Seller, db: DB):
    return CatalogService(db).toggle_promotion(user, promo_id, True)


@router.delete("/promotions/{promo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_promotion(promo_id: uuid.UUID, user: Seller, db: DB):
    CatalogService(db).delete_promotion(user, promo_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------- pedidos
@router.get("/orders", response_model=Page[OrderOut])
def store_orders(
    user: Seller,
    db: DB,
    paging: Paging,
    active: bool | None = None,
    status_: Annotated[OrderStatus | None, Query(alias="status")] = None,
):
    return OrderService(db).store_orders(user, active=active, status=status_, page=paging)


@router.post("/orders/{order_id}/status", response_model=OrderOut)
def change_status(order_id: int, data: OrderStatusIn, user: Seller, db: DB):
    """Avanza el pedido al siguiente estado (o lo rechaza con `cancelled`)."""
    return OrderService(db).change_status(user, order_id, data)


@router.post("/orders/{order_id}/payment-confirm", response_model=OrderOut)
def confirm_payment(order_id: int, data: PaymentConfirmIn, user: Seller, db: DB):
    """Confirma si la transferencia llegó (`received: true`) o no."""
    return OrderService(db).confirm_payment(user, order_id, data.received)


@router.post("/orders/{order_id}/review-reply", response_model=ReviewOut)
def reply_review(order_id: int, data: ReviewReplyIn, user: Seller, db: DB):
    return OrderService(db).reply_review(user, order_id, data.reply)
