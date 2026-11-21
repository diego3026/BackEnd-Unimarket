"""Billetera, direcciones, favoritos y notificaciones del usuario."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import Field, field_validator, model_validator

from app.schemas.common import CamelModel, InputModel


class PaymentMethodIn(InputModel):
    """Datos de una tarjeta YA tokenizada por la pasarela.

    La app nunca debe enviar el número completo ni el CVV a este backend:
    la pasarela (Wompi/ePayco/Mercado Pago) devuelve un token y los últimos 4.
    """

    brand: str = Field(pattern="^(Visa|Mastercard|Amex|Diners|Otra)$")
    last4: str = Field(pattern=r"^\d{4}$")
    holder: str = Field(min_length=3, max_length=120)
    exp_month: int = Field(ge=1, le=12)
    exp_year: int = Field(ge=2024, le=2100)
    provider: str = Field("manual", max_length=30)
    provider_token: str = Field("", max_length=200)
    is_default: bool = False

    @field_validator("holder")
    @classmethod
    def _no_digits(cls, v: str) -> str:
        if re.search(r"\d{6,}", v):
            raise ValueError("No envíes números de tarjeta en el nombre")
        return v.upper()


class PaymentMethodOut(CamelModel):
    id: uuid.UUID
    brand: str
    last4: str
    holder: str
    expiry: str = ""
    is_default: bool
    created_at: datetime


class AddressIn(InputModel):
    label: str = Field(min_length=2, max_length=40)
    address: str = Field(min_length=3, max_length=200)
    city: str = Field("Santa Marta", max_length=60)
    details: str = Field("", max_length=200)
    place_id: str | None = Field(None, max_length=32)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    is_default: bool = False

    @model_validator(mode="after")
    def _coords(self) -> AddressIn:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Envía latitud y longitud juntas")
        return self


class AddressOut(CamelModel):
    id: uuid.UUID
    label: str
    address: str
    city: str
    details: str
    place_id: str | None
    latitude: float | None
    longitude: float | None
    is_default: bool


class NotificationOut(CamelModel):
    id: uuid.UUID
    type: str
    title: str
    body: str
    data: dict
    is_read: bool = False
    created_at: datetime


class UnreadCountOut(CamelModel):
    unread: int
