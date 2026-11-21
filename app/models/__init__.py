"""Importa todos los modelos para que Alembic y las relaciones los encuentren."""

from app.db.base import Base
from app.models.order import (
    Address,
    AuditLog,
    Notification,
    Order,
    OrderLine,
    PaymentMethod,
    Review,
)
from app.models.product import Favorite, Product, Promotion
from app.models.store import CampusPlace, PayoutAccount, Store, StoreDocument
from app.models.user import OneTimeToken, RefreshToken, User

__all__ = [
    "Address",
    "AuditLog",
    "Base",
    "CampusPlace",
    "Favorite",
    "Notification",
    "OneTimeToken",
    "Order",
    "OrderLine",
    "PaymentMethod",
    "PayoutAccount",
    "Product",
    "Promotion",
    "RefreshToken",
    "Review",
    "Store",
    "StoreDocument",
    "User",
]
