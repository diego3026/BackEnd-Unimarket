from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, HttpUrl, field_validator, model_validator

from app.models.enums import DocumentStatus, StoreStatus
from app.schemas.common import CamelModel, InputModel

PLACE_KINDS = "building|delivery|entrance|food|parking|service|sports|other"


class CampusPlaceOut(CamelModel):
    """Pin del mapa. `kind`: building, delivery, entrance, food, parking, service, sports u other."""

    id: str
    name: str
    hint: str
    description: str = ""
    kind: str = "building"
    is_delivery_point: bool = True
    x: float
    y: float
    latitude: float | None
    longitude: float | None


class PlaceAdminOut(CampusPlaceOut):
    is_active: bool


class PlaceIn(InputModel):
    """Crear un pin (admin). Las coordenadas son obligatorias."""

    name: str = Field(min_length=2, max_length=80)
    hint: str = Field("", max_length=120)
    description: str = Field("", max_length=500)
    kind: str = Field("building", pattern=f"^({PLACE_KINDS})$")
    is_delivery_point: bool = False
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    is_active: bool = True


class PlaceUpdateIn(InputModel):
    name: str | None = Field(None, min_length=2, max_length=80)
    hint: str | None = Field(None, max_length=120)
    description: str | None = Field(None, max_length=500)
    kind: str | None = Field(None, pattern=f"^({PLACE_KINDS})$")
    is_delivery_point: bool | None = None
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    is_active: bool | None = None


# Llave Bre-B: @alias, celular, correo o número de documento (vacío para quitarla)
BREB_KEY_PATTERN = r"^(@[A-Za-z0-9._-]{3,40}|3\d{9}|[^@\s]+@[^@\s]+\.[a-z]{2,}|\d{5,15})?$"


def _url(v: str | None) -> str | None:
    if v in (None, ""):
        return v
    HttpUrl(v)  # valida formato http(s)
    return v


class StoreSettingsFields(InputModel):
    """Campos que el emprendedor edita en "Configurar tienda"."""

    is_open: bool | None = None
    allows_delivery: bool | None = None
    allows_pickup: bool | None = None
    delivery_fee: int | None = Field(None, ge=0, le=50_000)
    min_order: int | None = Field(None, ge=0, le=1_000_000)
    prep_minutes: int | None = Field(None, ge=0, le=240)
    pickup_place_id: str | None = Field(None, max_length=32)
    pickup_notes: str | None = Field(None, max_length=200)
    accepts_cash: bool | None = None
    accepts_nequi: bool | None = None
    accepts_card: bool | None = None
    accepts_breb: bool | None = None
    nequi_phone: str | None = Field(None, pattern=r"^(3\d{9})?$")
    breb_key: str | None = Field(None, max_length=60, pattern=BREB_KEY_PATTERN)
    phone: str | None = Field(None, max_length=20)
    # Local físico: dirección y ubicación. Enviar latitude/longitude en null lo quita.
    address: str | None = Field(None, max_length=200)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)

    @model_validator(mode="after")
    def _location_pair(self):
        sent = {"latitude", "longitude"} & self.model_fields_set
        if sent and (len(sent) == 1 or (self.latitude is None) != (self.longitude is None)):
            raise ValueError("Envía latitud y longitud juntas")
        return self


class StoreCreateIn(StoreSettingsFields):
    """ "Quiero vender": crea la tienda del usuario (queda pendiente de aprobación)."""

    name: str = Field(min_length=3, max_length=80)
    category: str = Field(min_length=2, max_length=40)
    description: str = Field("", max_length=2000)
    image_url: str = Field("", max_length=500)
    schedule: str = Field("Lun a Vie · 8:00 a. m. – 5:00 p. m.", max_length=120)
    menu_sections: list[str] = Field(default_factory=list, max_length=20)

    _u = field_validator("image_url")(_url)


class StoreUpdateIn(StoreSettingsFields):
    name: str | None = Field(None, min_length=3, max_length=80)
    category: str | None = Field(None, min_length=2, max_length=40)
    description: str | None = Field(None, max_length=2000)
    image_url: str | None = Field(None, max_length=500)
    schedule: str | None = Field(None, max_length=120)
    menu_sections: list[str] | None = Field(None, max_length=20)

    _u = field_validator("image_url")(_url)


class StoreSettingsOut(CamelModel):
    is_open: bool
    allows_delivery: bool
    allows_pickup: bool
    delivery_fee: int
    min_order: int
    prep_minutes: int
    pickup_place_id: str | None
    pickup_notes: str
    accepts_cash: bool
    accepts_nequi: bool
    accepts_card: bool
    accepts_breb: bool
    phone: str
    address: str = ""
    latitude: float | None = None
    longitude: float | None = None


class StoreOut(StoreSettingsOut):
    id: uuid.UUID
    name: str
    category: str
    description: str
    image_url: str
    schedule: str
    menu_sections: list[str]
    owner_name: str = ""
    status: StoreStatus
    rating: float
    rating_count: int
    pickup_place: CampusPlaceOut | None = None
    created_at: datetime


class StoreAdminOut(StoreOut):
    owner_id: uuid.UUID
    owner_email: str = ""
    review_note: str


class PayoutAccountIn(InputModel):
    bank_name: str = Field(min_length=2, max_length=60)
    account_type: str = Field(pattern="^(ahorros|corriente|nequi|daviplata)$")
    account_number: str = Field(pattern=r"^\d{6,20}$")
    holder_name: str = Field(min_length=3, max_length=120)
    holder_document: str = Field(pattern=r"^\d{5,15}$")


class PayoutAccountOut(CamelModel):
    bank_name: str
    account_type: str
    account_number_masked: str
    holder_name: str
    is_verified: bool
    updated_at: datetime


class StoreDocumentIn(InputModel):
    name: str = Field(min_length=2, max_length=80)
    file_url: str = Field(max_length=500)

    _u = field_validator("file_url")(_url)


class StoreDocumentOut(CamelModel):
    id: uuid.UUID
    name: str
    file_url: str
    status: DocumentStatus
    review_note: str
    created_at: datetime


class EarningsOut(CamelModel):
    """Resumen de "Ganancias" del emprendedor."""

    total_sales: int
    delivered_orders: int
    active_orders: int
    cancelled_orders: int
    average_ticket: int
    rating: float
    rating_count: int
    sales_by_day: list[dict]
    top_products: list[dict]
