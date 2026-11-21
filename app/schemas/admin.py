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
