from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk, utcnow
from app.models.enums import FulfillmentMode, OrderStatus, PaymentKind, PaymentStatus
from app.models.user import _enum


class Order(Timestamps, Base):
    """Pedido. El id es numérico (#1045) para mostrarlo y dictarlo fácilmente."""

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("subtotal >= 0", name="subtotal_positive"),
        CheckConstraint("total >= 0", name="total_positive"),
        Index("ix_orders_store_status", "store_id", "status"),
        Index("ix_orders_customer_created", "customer_id", "created_at"),
        UniqueConstraint("customer_id", "idempotency_key", name="uq_orders_customer_idempotency"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(start=1001), primary_key=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id", ondelete="RESTRICT"))

    status: Mapped[OrderStatus] = mapped_column(_enum(OrderStatus), default=OrderStatus.pending)
    mode: Mapped[FulfillmentMode] = mapped_column(_enum(FulfillmentMode))
    place_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("campus_places.id"))
    notes: Mapped[str] = mapped_column(String(300), default="")
    pickup_code: Mapped[str] = mapped_column(String(4))

    # Montos calculados en el servidor (en pesos)
    subtotal: Mapped[int] = mapped_column(Integer)
    product_discount: Mapped[int] = mapped_column(Integer, default=0)
    coupon_discount: Mapped[int] = mapped_column(Integer, default=0)
    coupon_code: Mapped[str] = mapped_column(String(20), default="")
    promotion_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("promotions.id", ondelete="SET NULL"))
    delivery_fee: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer)

    payment_kind: Mapped[PaymentKind] = mapped_column(_enum(PaymentKind))
    payment_status: Mapped[PaymentStatus] = mapped_column(_enum(PaymentStatus), default=PaymentStatus.pending)
    payment_method_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("payment_methods.id", ondelete="SET NULL")
    )
    payment_label: Mapped[str] = mapped_column(String(60), default="")
    # Transferencias: referencia que reporta el cliente y fechas de reporte/confirmación
    payment_reference: Mapped[str] = mapped_column(String(60), default="", server_default="")
    payment_reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Fecha de cada cambio de estado: {"pending": "...", "preparing": "..."}
    history: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    cancel_reason: Mapped[str] = mapped_column(String(200), default="")
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # customer | seller
    cancelled_by: Mapped[str] = mapped_column(String(10), default="", server_default="")
    # La tienda canceló con el pago ya reportado o confirmado: debe devolver el dinero
    paid_cancelled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Respuesta del cliente cuando la tienda cancela: received | not_received
    customer_confirmation: Mapped[str] = mapped_column(String(15), default="", server_default="")
    # Revisión del admin: open | confirmed (cuenta como venta) | dismissed
    dispute_status: Mapped[str] = mapped_column(String(12), default="", server_default="", index=True)
    dispute_note: Mapped[str] = mapped_column(String(300), default="", server_default="")
    idempotency_key: Mapped[str | None] = mapped_column(String(80))

    lines: Mapped[list[OrderLine]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderLine.id"
    )
    review: Mapped[Review | None] = relationship(back_populates="order", uselist=False)
    customer = relationship("User", foreign_keys=[customer_id])
    store = relationship("Store", foreign_keys=[store_id])
    place = relationship("CampusPlace", foreign_keys=[place_id])


class OrderLine(Base):
    """Copia del producto al momento de comprar (nombre y precio no cambian después)."""

    __tablename__ = "order_lines"
    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("products.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(40), default="")
    image_url: Mapped[str] = mapped_column(String(500), default="")
    list_price: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[int] = mapped_column(Integer)  # con descuento automático aplicado
    quantity: Mapped[int] = mapped_column(SmallInteger)

    order: Mapped[Order] = relationship(back_populates="lines")


class Review(UUIDPk, Timestamps, Base):
    __tablename__ = "reviews"
    __table_args__ = (CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),)

    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), unique=True)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    rating: Mapped[int] = mapped_column(SmallInteger)
    comment: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    seller_reply: Mapped[str] = mapped_column(Text, default="")

    order: Mapped[Order] = relationship(back_populates="review")
    customer = relationship("User", foreign_keys=[customer_id])


class PaymentMethod(UUIDPk, Timestamps, Base):
    """Tarjeta guardada. Nunca se guarda el número completo ni el CVV:
    solo marca, últimos 4 y el token que entrega la pasarela (Wompi, ePayco…)."""

    __tablename__ = "payment_methods"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    brand: Mapped[str] = mapped_column(String(20))
    last4: Mapped[str] = mapped_column(String(4))
    holder: Mapped[str] = mapped_column(String(120))
    exp_month: Mapped[int] = mapped_column(SmallInteger)
    exp_year: Mapped[int] = mapped_column(SmallInteger)
    provider: Mapped[str] = mapped_column(String(30), default="manual")
    provider_token: Mapped[str] = mapped_column(String(200), default="")
    is_default: Mapped[bool] = mapped_column(default=False)


class Address(UUIDPk, Timestamps, Base):
    __tablename__ = "addresses"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(40))
    address: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(60), default="Santa Marta")
    details: Mapped[str] = mapped_column(String(200), default="")
    place_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("campus_places.id", ondelete="SET NULL"))
    latitude: Mapped[float | None] = mapped_column()
    longitude: Mapped[float | None] = mapped_column()
    is_default: Mapped[bool] = mapped_column(default=False)


class Notification(UUIDPk, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_created", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(30))  # order, promotion, system
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)  # {"orderId": 1045}
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(UUIDPk, Base):
    """Registro de acciones administrativas (aprobar tiendas, suspender usuarios…)."""

    __tablename__ = "audit_logs"

    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(60))
    target_type: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
