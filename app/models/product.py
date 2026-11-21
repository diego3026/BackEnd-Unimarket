from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk, utcnow
from app.models.enums import DiscountType, PromotionKind
from app.models.user import _enum

if TYPE_CHECKING:
    from app.models.store import Store


class Product(UUIDPk, Timestamps, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price >= 0", name="price_positive"),
        CheckConstraint("stock >= 0", name="stock_positive"),
        Index("ix_products_store_available", "store_id", "is_available"),
    )

    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(40), index=True)  # Sección del menú
    price: Mapped[int] = mapped_column(Integer)  # Pesos colombianos (sin decimales)
    image_url: Mapped[str] = mapped_column(String(500), default="")
    stock: Mapped[int] = mapped_column(Integer, default=0)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False)
    # El admin puede ocultar un producto que incumple las normas.
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    rating_avg: Mapped[float] = mapped_column(Float, default=0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)

    store: Mapped[Store] = relationship(back_populates="products")


class Promotion(UUIDPk, Timestamps, Base):
    """Descuento automático en productos o cupón con código."""

    __tablename__ = "promotions"
    __table_args__ = (
        CheckConstraint("value > 0", name="value_positive"),
        CheckConstraint("min_purchase >= 0", name="min_purchase_positive"),
        UniqueConstraint("store_id", "code", name="uq_promotions_store_code"),
    )

    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(80))
    kind: Mapped[PromotionKind] = mapped_column(_enum(PromotionKind))
    type: Mapped[DiscountType] = mapped_column(_enum(DiscountType))
    value: Mapped[int] = mapped_column(Integer)  # % o pesos según `type`
    product_ids: Mapped[list[str]] = mapped_column(JSON, default=list)  # vacío = todo el menú
    code: Mapped[str | None] = mapped_column(String(20))  # Solo cupones, en mayúsculas
    min_purchase: Mapped[int] = mapped_column(Integer, default=0)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    max_uses: Mapped[int | None] = mapped_column(Integer)
    max_uses_per_user: Mapped[int | None] = mapped_column(Integer, default=1)


class Favorite(Base):
    __tablename__ = "favorites"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
