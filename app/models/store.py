from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk
from app.models.enums import DocumentStatus, StoreStatus
from app.models.user import _enum

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.user import User


class CampusPlace(Base):
    """Punto del campus (Bloque 8, Biblioteca…). x/y van de 0 a 1 en el mapa ilustrado."""

    __tablename__ = "campus_places"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    hint: Mapped[str] = mapped_column(String(120), default="")
    x: Mapped[float] = mapped_column(Float, default=0.5)
    y: Mapped[float] = mapped_column(Float, default=0.5)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Store(UUIDPk, Timestamps, Base):
    """Emprendimiento de un estudiante, con la configuración de "Configurar tienda"."""

    __tablename__ = "stores"
    __table_args__ = (
        CheckConstraint("delivery_fee >= 0", name="delivery_fee_positive"),
        CheckConstraint("min_order >= 0", name="min_order_positive"),
        CheckConstraint("prep_minutes BETWEEN 0 AND 240", name="prep_minutes_range"),
        Index("ix_stores_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), unique=True)
    name: Mapped[str] = mapped_column(String(80), index=True)
    category: Mapped[str] = mapped_column(String(40), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str] = mapped_column(String(500), default="")
    schedule: Mapped[str] = mapped_column(String(120), default="Lun a Vie · 8:00 a. m. – 5:00 p. m.")
    menu_sections: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[StoreStatus] = mapped_column(_enum(StoreStatus), default=StoreStatus.pending, index=True)
    review_note: Mapped[str] = mapped_column(String(300), default="")

    # Configuración de pedidos
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)
    allows_delivery: Mapped[bool] = mapped_column(Boolean, default=True)
    allows_pickup: Mapped[bool] = mapped_column(Boolean, default=True)
    delivery_fee: Mapped[int] = mapped_column(Integer, default=2000)
    min_order: Mapped[int] = mapped_column(Integer, default=0)
    prep_minutes: Mapped[int] = mapped_column(Integer, default=15)
    pickup_place_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("campus_places.id", ondelete="SET NULL"))
    pickup_notes: Mapped[str] = mapped_column(String(200), default="")
    accepts_cash: Mapped[bool] = mapped_column(Boolean, default=True)
    accepts_nequi: Mapped[bool] = mapped_column(Boolean, default=False)
    accepts_card: Mapped[bool] = mapped_column(Boolean, default=False)
    accepts_breb: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Datos para que el cliente transfiera directo al emprendedor (sin comisión)
    nequi_phone: Mapped[str] = mapped_column(String(20), default="", server_default="")
    breb_key: Mapped[str] = mapped_column(String(60), default="", server_default="")
    phone: Mapped[str] = mapped_column(String(20), default="")

    # Calificación agregada (se recalcula con cada reseña)
    rating_avg: Mapped[float] = mapped_column(Float, default=0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)

    owner: Mapped[User] = relationship(back_populates="store")
    pickup_place: Mapped[CampusPlace | None] = relationship()
    products: Mapped[list[Product]] = relationship(back_populates="store")


class PayoutAccount(UUIDPk, Timestamps, Base):
    """Cuenta bancaria donde el emprendedor recibe sus ganancias. El número va cifrado."""

    __tablename__ = "payout_accounts"

    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id", ondelete="CASCADE"), unique=True)
    bank_name: Mapped[str] = mapped_column(String(60))
    account_type: Mapped[str] = mapped_column(String(20))  # ahorros | corriente | nequi | daviplata
    account_number_encrypted: Mapped[str] = mapped_column(String(300))
    account_last4: Mapped[str] = mapped_column(String(4))
    holder_name: Mapped[str] = mapped_column(String(120))
    holder_document: Mapped[str] = mapped_column(String(300))  # cifrado
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)


class StoreDocument(UUIDPk, Timestamps, Base):
    """Documentos que pide el admin (cédula, carné estudiantil, RUT…)."""

    __tablename__ = "store_documents"

    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    file_url: Mapped[str] = mapped_column(String(500))
    status: Mapped[DocumentStatus] = mapped_column(_enum(DocumentStatus), default=DocumentStatus.pending)
    review_note: Mapped[str] = mapped_column(String(300), default="")
