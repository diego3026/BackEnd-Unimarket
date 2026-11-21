from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, field_validator, model_validator

from app.models.enums import DiscountType, PromotionKind
from app.schemas.common import CamelModel, InputModel
from app.schemas.store import _url


class ProductIn(InputModel):
    name: str = Field(min_length=2, max_length=100)
    description: str = Field("", max_length=2000)
    category: str = Field(min_length=2, max_length=40)
    price: int = Field(ge=0, le=10_000_000)
    image_url: str = Field("", max_length=500)
    stock: int = Field(0, ge=0, le=100_000)
    is_available: bool = True
    is_featured: bool = False

    _u = field_validator("image_url")(_url)


class ProductUpdateIn(InputModel):
    name: str | None = Field(None, min_length=2, max_length=100)
    description: str | None = Field(None, max_length=2000)
    category: str | None = Field(None, min_length=2, max_length=40)
    price: int | None = Field(None, ge=0, le=10_000_000)
    image_url: str | None = Field(None, max_length=500)
    stock: int | None = Field(None, ge=0, le=100_000)
    is_available: bool | None = None
    is_featured: bool | None = None

    _u = field_validator("image_url")(_url)


class ProductOut(CamelModel):
    """`discountPrice` es el precio con la promoción automática vigente (o null)."""

    id: uuid.UUID
    store_id: uuid.UUID
    store_name: str = ""
    name: str
    description: str
    category: str
    price: int
    discount_price: int | None = None
    image_url: str
    stock: int
    is_available: bool
    is_featured: bool
    rating: float
    rating_count: int
    created_at: datetime


class ProductAdminOut(ProductOut):
    is_hidden: bool


class PromotionIn(InputModel):
    title: str = Field(min_length=3, max_length=80)
    kind: PromotionKind
    type: DiscountType
    value: int = Field(gt=0)
    product_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    code: str | None = Field(None, min_length=3, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")
    min_purchase: int = Field(0, ge=0)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    active: bool = True
    max_uses: int | None = Field(None, ge=1)
    max_uses_per_user: int | None = Field(1, ge=1)

    @model_validator(mode="after")
    def _rules(self) -> PromotionIn:
        if self.type == DiscountType.percent and self.value > 90:
            raise ValueError("El porcentaje máximo es 90 %")
        if self.kind == PromotionKind.coupon and not self.code:
            raise ValueError("Los cupones necesitan un código")
        if self.kind == PromotionKind.product_discount:
            self.code = None
        if self.code:
            self.code = self.code.upper()
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("La fecha final debe ser posterior a la inicial")
        return self


class PromotionOut(CamelModel):
    id: uuid.UUID
    store_id: uuid.UUID
    store_name: str = ""
    title: str
    kind: PromotionKind
    type: DiscountType
    value: int
    product_ids: list[str]
    code: str | None
    min_purchase: int
    starts_at: datetime | None
    ends_at: datetime | None
    active: bool
    uses: int
    max_uses: int | None
    max_uses_per_user: int | None
    is_running: bool = False


class CouponCheckIn(InputModel):
    store_id: uuid.UUID
    code: str = Field(min_length=3, max_length=20)
    subtotal: int = Field(ge=0)


class CouponCheckOut(CamelModel):
    valid: bool
    discount: int = 0
    message: str = ""
    promotion: PromotionOut | None = None
