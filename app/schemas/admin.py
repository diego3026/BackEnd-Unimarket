from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.models.enums import DocumentStatus, StoreStatus, UserRole, UserStatus
from app.schemas.common import CamelModel, InputModel


class AdminUserOut(CamelModel):
    id: uuid.UUID
    email: str
    full_name: str
    phone: str
    role: UserRole
    status: UserStatus
    email_verified: bool
    created_at: datetime
    last_login_at: datetime | None
    total_orders: int = 0
    total_spent: int = 0


class AdminUserUpdateIn(InputModel):
    role: UserRole | None = None
    status: UserStatus | None = None


class StoreReviewIn(InputModel):
    status: StoreStatus
    note: str = Field("", max_length=300)


class ProductModerationIn(InputModel):
    is_hidden: bool


class DocumentReviewIn(InputModel):
    status: DocumentStatus
    note: str = Field("", max_length=300)


class ReportOut(CamelModel):
    users_by_role: dict[str, int]
    stores_by_status: dict[str, int]
    orders_total: int
    orders_by_status: dict[str, int]
    gross_sales: int
    average_ticket: int
    orders_by_day: list[dict]
    top_stores: list[dict]
    top_categories: list[dict]
    from_date: datetime
    to_date: datetime


class CommissionLineOut(CamelModel):
    order_id: int
    date: datetime
    amount: int
    kind: str  # delivered | disputed
    free: bool


class CommissionStatementOut(CamelModel):
    """Comisión de una tienda en un mes. Tasa marginal: hasta `tierLimit` paga `lowRate`."""

    store_id: uuid.UUID
    store_name: str
    month: str
    free_until: datetime | None
    orders: int
    disputed_orders: int
    total_sales: int
    free_sales: int
    chargeable_sales: int
    tier_limit: int
    low_rate: float
    high_rate: float
    commission: int
    lines: list[CommissionLineOut] = []


class StoreRiskOut(CamelModel):
    """Cancelaciones de una tienda en el periodo y si amerita revisión."""

    store_id: uuid.UUID
    store_name: str
    orders: int
    cancelled: int
    cancelled_by_store: int
    cancelled_after_accept: int
    cancelled_with_payment: int
    contradicted_by_customer: int
    open_disputes: int
    cancel_rate: float
    alert: bool
