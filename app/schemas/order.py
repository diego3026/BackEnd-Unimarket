from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, model_validator

from app.models.enums import FulfillmentMode, OrderStatus, PaymentKind, PaymentStatus
from app.schemas.common import CamelModel, InputModel


class OrderLineIn(InputModel):
    product_id: uuid.UUID
    quantity: int = Field(ge=1, le=50)


class OrderCreateIn(InputModel):
    """El cliente solo envía qué quiere; precios y totales los calcula el servidor."""

    store_id: uuid.UUID
    lines: list[OrderLineIn] = Field(min_length=1, max_length=50)
    mode: FulfillmentMode
    place_id: str | None = Field(None, max_length=32)
    notes: str = Field("", max_length=300)
    coupon_code: str | None = Field(None, max_length=20)
    payment_kind: PaymentKind
    payment_method_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _rules(self) -> OrderCreateIn:
        if self.mode == FulfillmentMode.delivery and not self.place_id:
            raise ValueError("Elige el lugar del campus donde entregar")
        if self.payment_kind == PaymentKind.card and not self.payment_method_id:
            raise ValueError("Elige la tarjeta para pagar")
        ids = [ln.product_id for ln in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("Hay productos repetidos en el pedido")
        return self


class OrderLineOut(CamelModel):
    product_id: uuid.UUID | None
    name: str
    category: str
    image_url: str
    list_price: int
    unit_price: int
    quantity: int
    total: int = 0


class ReviewOut(CamelModel):
    id: uuid.UUID
    order_id: int
    store_id: uuid.UUID
    customer_name: str = ""
    rating: int
    comment: str
    tags: list[str]
    seller_reply: str
    created_at: datetime


class PayToOut(CamelModel):
    """Datos para transferir al emprendedor (solo los ve el cliente mientras debe pagar)."""

    kind: PaymentKind
    key: str
    holder_name: str
    amount: int
    reference_hint: str


class OrderOut(CamelModel):
    id: int
    pickup_code: str | None = None
    store_id: uuid.UUID
    store_name: str = ""
    customer_id: uuid.UUID
    customer_name: str = ""
    customer_phone: str = ""
    status: OrderStatus
    mode: FulfillmentMode
    place_id: str | None
    place_name: str = ""
    notes: str
    lines: list[OrderLineOut]
    subtotal: int
    product_discount: int
    coupon_discount: int
    coupon_code: str
    delivery_fee: int
    total: int
    payment_kind: PaymentKind
    payment_status: PaymentStatus
    payment_label: str
    payment_reference: str = ""
    pay_to: PayToOut | None = None
    history: dict[str, str]
    next_status: OrderStatus | None = None
    cancel_reason: str
    cancelled_by: str = ""
    paid_cancelled: bool = False
    customer_confirmation: str = ""
    dispute_status: str = ""
    review: ReviewOut | None = None
    created_at: datetime


class OrderStatusIn(InputModel):
    status: OrderStatus
    # Para entregar un pedido de recogida el emprendedor confirma el código del cliente.
    pickup_code: str | None = Field(None, pattern=r"^\d{4}$")
    reason: str = Field("", max_length=200)


class PaymentReportIn(InputModel):
    """El cliente avisa que ya transfirió (Nequi o Bre-B)."""

    reference: str = Field("", max_length=60)


class PaymentConfirmIn(InputModel):
    """La tienda confirma si el dinero llegó."""

    received: bool


class OrderCancelIn(InputModel):
    reason: str = Field("", max_length=200)


class ReviewIn(InputModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field("", max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=10)


class ReviewReplyIn(InputModel):
    reply: str = Field(min_length=1, max_length=1000)


class CheckoutQuoteOut(CamelModel):
    """Vista previa de totales antes de confirmar (misma lógica que crear el pedido)."""

    subtotal: int
    product_discount: int
    coupon_discount: int
    coupon_message: str = ""
    delivery_fee: int
    total: int
    lines: list[OrderLineOut]


class CancelFeedbackIn(InputModel):
    """Respuesta del cliente cuando la tienda cancela: ¿recibiste el pedido?"""

    received: bool


class DisputeDecisionIn(InputModel):
    """Decisión del admin: confirmed = cuenta como venta; dismissed = se descarta."""

    decision: str = Field(pattern="^(confirmed|dismissed)$")
    note: str = Field("", max_length=300)
