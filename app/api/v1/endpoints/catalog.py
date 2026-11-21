"""Endpoints públicos (sin iniciar sesión): campus, tiendas, productos y cupones."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.deps import DB, Paging
from app.schemas.common import Page
from app.schemas.order import ReviewOut
from app.schemas.product import ProductOut, PromotionOut
from app.schemas.store import CampusPlaceOut, StoreOut
from app.services.catalog import CatalogService

router = APIRouter(tags=["Catálogo"])


@router.get("/campus/places", response_model=list[CampusPlaceOut])
def campus_places(db: DB):
    """Lugares del campus para entregas y puntos de recogida."""
    return CatalogService(db).campus_places()


@router.get("/categories", response_model=list[str])
def categories(db: DB):
    return CatalogService(db).categories()


@router.get("/stores", response_model=Page[StoreOut])
def list_stores(
    db: DB,
    paging: Paging,
    q: Annotated[str | None, Query(max_length=60)] = None,
    category: Annotated[str | None, Query(max_length=40)] = None,
    open_only: Annotated[bool, Query(alias="openOnly")] = False,
):
    return CatalogService(db).list_stores(q=q, category=category, open_only=open_only, page=paging)


@router.get("/stores/{store_id}", response_model=StoreOut)
def get_store(store_id: uuid.UUID, db: DB):
    return CatalogService(db).get_public_store(store_id)


@router.get("/stores/{store_id}/products", response_model=Page[ProductOut])
def store_products(store_id: uuid.UUID, db: DB, paging: Paging):
    return CatalogService(db).list_products(
        page=paging,
        q=None,
        category=None,
        store_id=store_id,
        featured=None,
        min_price=None,
        max_price=None,
        sort="default",
    )


@router.get("/stores/{store_id}/reviews", response_model=Page[ReviewOut])
def store_reviews(store_id: uuid.UUID, db: DB, paging: Paging):
    return CatalogService(db).store_reviews(store_id, paging)


@router.get("/stores/{store_id}/coupons", response_model=list[PromotionOut])
def store_coupons(store_id: uuid.UUID, db: DB):
    return CatalogService(db).public_coupons(store_id)


@router.get("/products", response_model=Page[ProductOut])
def list_products(
    db: DB,
    paging: Paging,
    q: Annotated[str | None, Query(max_length=60)] = None,
    category: Annotated[str | None, Query(max_length=40)] = None,
    store_id: Annotated[uuid.UUID | None, Query(alias="storeId")] = None,
    featured: bool | None = None,
    min_price: Annotated[int | None, Query(alias="minPrice", ge=0)] = None,
    max_price: Annotated[int | None, Query(alias="maxPrice", ge=0)] = None,
    sort: Literal["default", "price_asc", "price_desc", "rating", "newest"] = "default",
):
    """Búsqueda y listado. `discountPrice` trae el precio con la promoción vigente."""
    return CatalogService(db).list_products(
        page=paging,
        q=q,
        category=category,
        store_id=store_id,
        featured=featured,
        min_price=min_price,
        max_price=max_price,
        sort=sort,
    )


@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: uuid.UUID, db: DB):
    return CatalogService(db).get_product(product_id)


@router.get("/promotions/coupons", response_model=list[PromotionOut])
def public_coupons(db: DB):
    """Cupones vigentes de todas las tiendas (pantalla Promos)."""
    return CatalogService(db).public_coupons(None)


@router.get("/promotions/discounts", response_model=list[PromotionOut])
def public_discounts(db: DB):
    """Descuentos automáticos vigentes (banners de Inicio)."""
    return CatalogService(db).public_discounts()
