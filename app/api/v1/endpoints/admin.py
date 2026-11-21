"""Panel del administrador."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import DB, Admin, Paging
from app.models.enums import StoreStatus, UserRole, UserStatus
from app.schemas.admin import (
    AdminUserOut,
    AdminUserUpdateIn,
    CommissionStatementOut,
    DocumentReviewIn,
    ProductModerationIn,
    ReportOut,
    StoreReviewIn,
    StoreRiskOut,
)
from app.schemas.auth import UserOut
from app.schemas.common import Page
from app.schemas.order import DisputeDecisionIn, OrderOut
from app.schemas.product import ProductAdminOut
from app.schemas.store import PlaceAdminOut, PlaceIn, PlaceUpdateIn, StoreAdminOut, StoreDocumentOut
from app.services.admin import AdminService, PlacesAdmin
from app.services.commissions import all_statements, statement, store_by_id
from app.services.integrity import store_metrics

router = APIRouter(prefix="/admin", tags=["Administrador"])


@router.get("/users", response_model=Page[AdminUserOut])
def users(
    admin: Admin,
    db: DB,
    paging: Paging,
    q: Annotated[str | None, Query(max_length=60)] = None,
    role: UserRole | None = None,
    status: UserStatus | None = None,
):
    return AdminService(db, admin).list_users(q=q, role=role, status=status, page=paging)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: uuid.UUID, data: AdminUserUpdateIn, admin: Admin, db: DB):
    """Cambia rol o suspende/reactiva (suspender cierra todas sus sesiones)."""
    return AdminService(db, admin).update_user(user_id, data)


@router.get("/stores", response_model=Page[StoreAdminOut])
def stores(
    admin: Admin,
    db: DB,
    paging: Paging,
    status: StoreStatus | None = None,
    q: Annotated[str | None, Query(max_length=60)] = None,
):
    return AdminService(db, admin).list_stores(status=status, q=q, page=paging)


@router.post("/stores/{store_id}/review", response_model=StoreAdminOut)
def review_store(store_id: uuid.UUID, data: StoreReviewIn, admin: Admin, db: DB):
    """Aprueba, rechaza o suspende una tienda."""
    return AdminService(db, admin).review_store(store_id, data)


@router.get("/stores/{store_id}/documents", response_model=list[StoreDocumentOut])
def store_documents(store_id: uuid.UUID, admin: Admin, db: DB):
    return AdminService(db, admin).store_documents(store_id)


@router.post("/documents/{document_id}/review", response_model=StoreDocumentOut)
def review_document(document_id: uuid.UUID, data: DocumentReviewIn, admin: Admin, db: DB):
    return AdminService(db, admin).review_document(document_id, data)


@router.get("/documents/{document_id}/file")
def document_file(document_id: uuid.UUID, admin: Admin, db: DB):
    """Enlace temporal (5 min) para ver un documento privado. Queda en la bitácora."""
    return {"url": AdminService(db, admin).document_file_url(document_id), "expiresIn": 300}


@router.get("/products", response_model=Page[ProductAdminOut])
def products(
    admin: Admin,
    db: DB,
    paging: Paging,
    q: Annotated[str | None, Query(max_length=60)] = None,
    hidden: bool | None = None,
):
    return AdminService(db, admin).list_products(q=q, hidden=hidden, page=paging)


@router.post("/products/{product_id}/moderate", response_model=ProductAdminOut)
def moderate(product_id: uuid.UUID, data: ProductModerationIn, admin: Admin, db: DB):
    return AdminService(db, admin).moderate_product(product_id, data.is_hidden)


@router.get("/reports", response_model=ReportOut)
def reports(admin: Admin, db: DB, days: Annotated[int, Query(ge=1, le=365)] = 30):
    return AdminService(db, admin).report(days)


# ------------------------------------------------------------------ pines del mapa
@router.get("/places", response_model=list[PlaceAdminOut])
def places(admin: Admin, db: DB):
    """Todos los pines, incluidos los desactivados."""
    return PlacesAdmin(db, admin).list()


@router.post("/places", response_model=PlaceAdminOut, status_code=status.HTTP_201_CREATED)
def create_place(data: PlaceIn, admin: Admin, db: DB):
    """Nuevo pin. Con `isDeliveryPoint` sirve para entregar y recoger pedidos."""
    return PlacesAdmin(db, admin).create(data)


@router.patch("/places/{place_id}", response_model=PlaceAdminOut)
def update_place(place_id: str, data: PlaceUpdateIn, admin: Admin, db: DB):
    return PlacesAdmin(db, admin).update(place_id, data)


@router.delete("/places/{place_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_place(place_id: str, admin: Admin, db: DB):
    """Desactiva el pin (los pedidos antiguos lo siguen mostrando)."""
    PlacesAdmin(db, admin).delete(place_id)


# ------------------------------------------------------------------ comisiones
@router.get("/commissions", response_model=list[CommissionStatementOut])
def commissions(admin: Admin, db: DB, month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None):
    """Comisión del mes de cada tienda con ventas (sin el detalle por pedido)."""
    return all_statements(db, month)


@router.get("/commissions/{store_id}", response_model=CommissionStatementOut)
def store_commission(
    store_id: uuid.UUID, admin: Admin, db: DB, month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None
):
    return statement(db, store_by_id(db, store_id), month)


# ------------------------------------------------------- cancelaciones y disputas
@router.get("/stores-risk", response_model=list[StoreRiskOut])
def stores_risk(admin: Admin, db: DB, days: Annotated[int, Query(ge=1, le=365)] = 30):
    """Cancelaciones por tienda; `alert` marca las que hay que revisar."""
    return store_metrics(db, days=days)


@router.get("/disputes", response_model=list[OrderOut])
def disputes(admin: Admin, db: DB):
    """Pedidos cancelados en revisión (el cliente dice que sí los recibió o tenían pago)."""
    return AdminService(db, admin).open_disputes()


@router.post("/orders/{order_id}/dispute", response_model=OrderOut)
def resolve_dispute(order_id: int, data: DisputeDecisionIn, admin: Admin, db: DB):
    """confirmed: cuenta como venta (paga comisión). dismissed: se descarta."""
    return AdminService(db, admin).resolve_dispute(order_id, data)
