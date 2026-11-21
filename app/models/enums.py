"""Valores fijos compartidos con la app (mismos nombres que los enums de Dart)."""

from __future__ import annotations

import enum


class UserRole(str, enum.Enum):
    consumer = "consumer"
    entrepreneur = "entrepreneur"
    admin = "admin"


class UserStatus(str, enum.Enum):
    active = "active"
    suspended = "suspended"


class StoreStatus(str, enum.Enum):
    pending = "pending"  # Esperando revisión del administrador
    approved = "approved"
    rejected = "rejected"
    suspended = "suspended"


class FulfillmentMode(str, enum.Enum):
    delivery = "delivery"
    pickup = "pickup"


class PromotionKind(str, enum.Enum):
    product_discount = "productDiscount"  # Rebaja automática en el precio
    coupon = "coupon"  # Código que el cliente escribe al pagar


class DiscountType(str, enum.Enum):
    percent = "percent"
    fixed = "fixed"


class PaymentKind(str, enum.Enum):
    cash = "cash"  # Efectivo al recibir o recoger
    nequi = "nequi"  # Transferencia al Nequi del emprendedor
    breb = "breb"  # Transferencia inmediata Bre-B (llave del emprendedor), sin comisión
    card = "card"  # Tarjeta por pasarela (Mercado Pago), cuando se active

    @property
    def is_transfer(self) -> bool:
        return self in (PaymentKind.nequi, PaymentKind.breb)


class PaymentStatus(str, enum.Enum):
    pending = "pending"  # Aún no se ha pagado
    reported = "reported"  # El cliente dice que ya transfirió; falta que la tienda confirme
    authorized = "authorized"
    paid = "paid"
    refunded = "refunded"
    failed = "failed"


class OrderStatus(str, enum.Enum):
    pending = "pending"
    preparing = "preparing"
    ready = "ready"  # Listo para recoger
    on_the_way = "onTheWay"
    delivered = "delivered"
    cancelled = "cancelled"

    @property
    def is_active(self) -> bool:
        return self not in (OrderStatus.delivered, OrderStatus.cancelled)


class DocumentStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class TokenPurpose(str, enum.Enum):
    verify_email = "verify_email"
    reset_password = "reset_password"
