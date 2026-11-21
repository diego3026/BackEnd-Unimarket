"""Convierte modelos de la BD en schemas de respuesta (sin filtrar datos sensibles por error)."""

from __future__ import annotations

import uuid

from app.core.crypto import mask
from app.models import (
    Address,
    Notification,
    Order,
    PaymentMethod,
    PayoutAccount,
    Product,
    Promotion,
    Review,
    Store,
    StoreDocument,
    User,
)
from app.models.enums import FulfillmentMode, OrderStatus, PaymentKind, PaymentStatus
from app.schemas.account import AddressOut, NotificationOut, PaymentMethodOut
from app.schemas.auth import UserOut
from app.schemas.order import OrderLineOut, OrderOut, PayToOut, ReviewOut
from app.schemas.product import ProductAdminOut, ProductOut, PromotionOut
from app.schemas.store import (
    CampusPlaceOut,
    PayoutAccountOut,
    StoreAdminOut,
    StoreDocumentOut,
    StoreOut,
)
from app.services.pricing import is_running

PICKUP_FLOW = [OrderStatus.pending, OrderStatus.preparing, OrderStatus.ready, OrderStatus.delivered]
DELIVERY_FLOW = [OrderStatus.pending, OrderStatus.preparing, OrderStatus.on_the_way, OrderStatus.delivered]


def flow_for(mode: FulfillmentMode) -> list[OrderStatus]:
    return PICKUP_FLOW if mode == FulfillmentMode.pickup else DELIVERY_FLOW


def next_status(order: Order) -> OrderStatus | None:
    if not order.status.is_active:
        return None
    flow = flow_for(order.mode)
    i = flow.index(order.status) if order.status in flow else -1
    return flow[i + 1] if 0 <= i < len(flow) - 1 else None


def user_out(u: User, store_id: uuid.UUID | None = None) -> UserOut:
    return UserOut(
        id=u.id,
        email=u.email,
        full_name=u.full_name,
        phone=u.phone,
        avatar_url=u.avatar_url,
        role=u.role,
        status=u.status,
        email_verified=u.email_verified,
        store_id=store_id,
        created_at=u.created_at,
    )


def _store_fields(s: Store) -> dict:
    return dict(
        id=s.id,
        name=s.name,
        category=s.category,
        description=s.description,
        image_url=s.image_url,
        schedule=s.schedule,
        menu_sections=list(s.menu_sections or []),
        owner_name=s.owner.full_name if s.owner else "",
        status=s.status,
        rating=round(s.rating_avg or 0, 2),
        rating_count=s.rating_count,
        pickup_place=CampusPlaceOut.model_validate(s.pickup_place) if s.pickup_place else None,
        created_at=s.created_at,
        is_open=s.is_open,
        allows_delivery=s.allows_delivery,
        allows_pickup=s.allows_pickup,
        delivery_fee=s.delivery_fee,
        min_order=s.min_order,
        prep_minutes=s.prep_minutes,
        pickup_place_id=s.pickup_place_id,
        pickup_notes=s.pickup_notes,
        accepts_cash=s.accepts_cash,
        accepts_nequi=s.accepts_nequi,
        accepts_card=s.accepts_card,
        accepts_breb=s.accepts_breb,
        phone=s.phone,
        address=s.address or "",
        latitude=s.latitude,
        longitude=s.longitude,
    )


def store_out(s: Store) -> StoreOut:
    return StoreOut(**_store_fields(s))


def store_admin_out(s: Store) -> StoreAdminOut:
    return StoreAdminOut(
        **_store_fields(s),
        owner_id=s.owner_id,
        owner_email=s.owner.email if s.owner else "",
        review_note=s.review_note,
    )


def _product_fields(p: Product, discount: int | None) -> dict:
    return dict(
        id=p.id,
        store_id=p.store_id,
        store_name=p.store.name if p.store else "",
        name=p.name,
        description=p.description,
        category=p.category,
        price=p.price,
        discount_price=discount,
        image_url=p.image_url,
        stock=p.stock,
        is_available=p.is_available,
        is_featured=p.is_featured,
        rating=round(p.rating_avg or 0, 2),
        rating_count=p.rating_count,
        created_at=p.created_at,
    )


def product_out(p: Product, discount: int | None = None) -> ProductOut:
    return ProductOut(**_product_fields(p, discount))


def product_admin_out(p: Product, discount: int | None = None) -> ProductAdminOut:
    return ProductAdminOut(**_product_fields(p, discount), is_hidden=p.is_hidden)


def promotion_out(p: Promotion, store_name: str = "") -> PromotionOut:
    return PromotionOut(
        id=p.id,
        store_id=p.store_id,
        store_name=store_name,
        title=p.title,
        kind=p.kind,
        type=p.type,
        value=p.value,
        product_ids=list(p.product_ids or []),
        code=p.code,
        min_purchase=p.min_purchase,
        starts_at=p.starts_at,
        ends_at=p.ends_at,
        active=p.active,
        uses=p.uses,
        max_uses=p.max_uses,
        max_uses_per_user=p.max_uses_per_user,
        is_running=is_running(p),
    )


def review_out(r: Review) -> ReviewOut:
    name = r.customer.full_name if r.customer else ""
    # Solo el primer nombre e inicial del apellido, por privacidad.
    parts = name.split()
    short = f"{parts[0]} {parts[1][0]}." if len(parts) > 1 else name
    return ReviewOut(
        id=r.id,
        order_id=r.order_id,
        store_id=r.store_id,
        customer_name=short,
        rating=r.rating,
        comment=r.comment,
        tags=list(r.tags or []),
        seller_reply=r.seller_reply,
        created_at=r.created_at,
    )


def pay_to(o: Order) -> PayToOut | None:
    """Instrucciones para transferir, solo mientras el pago está pendiente."""
    if not o.payment_kind.is_transfer or not o.status.is_active or not o.store:
        return None
    if o.payment_status not in (PaymentStatus.pending, PaymentStatus.failed):
        return None
    key = o.store.nequi_phone if o.payment_kind == PaymentKind.nequi else o.store.breb_key
    return PayToOut(
        kind=o.payment_kind,
        key=key,
        holder_name=o.store.owner.full_name if o.store.owner else o.store.name,
        amount=o.total,
        reference_hint=f"UniMarket #{o.id}",
    )


def order_out(o: Order, *, viewer: str) -> OrderOut:
    """`viewer` es "customer", "seller" o "admin".

    El código de recogida solo lo ve el cliente: lo dicta al recoger y el
    emprendedor lo confirma, así nadie más puede reclamar el pedido.
    """
    return OrderOut(
        id=o.id,
        pickup_code=o.pickup_code if viewer == "customer" and o.mode == FulfillmentMode.pickup else None,
        store_id=o.store_id,
        store_name=o.store.name if o.store else "",
        customer_id=o.customer_id,
        customer_name=o.customer.full_name if o.customer else "",
        customer_phone=o.customer.phone if (o.customer and viewer != "customer" and o.status.is_active) else "",
        status=o.status,
        mode=o.mode,
        place_id=o.place_id,
        place_name=o.place.name if o.place else "",
        notes=o.notes,
        lines=[
            OrderLineOut(
                product_id=ln.product_id,
                name=ln.name,
                category=ln.category,
                image_url=ln.image_url,
                list_price=ln.list_price,
                unit_price=ln.unit_price,
                quantity=ln.quantity,
                total=ln.unit_price * ln.quantity,
            )
            for ln in o.lines
        ],
        subtotal=o.subtotal,
        product_discount=o.product_discount,
        coupon_discount=o.coupon_discount,
        coupon_code=o.coupon_code,
        delivery_fee=o.delivery_fee,
        total=o.total,
        payment_kind=o.payment_kind,
        payment_status=o.payment_status,
        payment_label=o.payment_label,
        payment_reference=o.payment_reference,
        pay_to=pay_to(o) if viewer == "customer" else None,
        history=dict(o.history or {}),
        next_status=next_status(o) if viewer != "customer" else None,
        cancel_reason=o.cancel_reason,
        cancelled_by=o.cancelled_by or "",
        paid_cancelled=o.paid_cancelled,
        customer_confirmation=o.customer_confirmation or "",
        dispute_status=o.dispute_status or "",
        review=review_out(o.review) if o.review else None,
        created_at=o.created_at,
    )


def card_out(c: PaymentMethod) -> PaymentMethodOut:
    return PaymentMethodOut(
        id=c.id,
        brand=c.brand,
        last4=c.last4,
        holder=c.holder,
        expiry=f"{c.exp_month:02d}/{c.exp_year % 100:02d}",
        is_default=c.is_default,
        created_at=c.created_at,
    )


def address_out(a: Address) -> AddressOut:
    return AddressOut.model_validate(a)


def notification_out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        type=n.type,
        title=n.title,
        body=n.body,
        data=dict(n.data or {}),
        is_read=n.read_at is not None,
        created_at=n.created_at,
    )


def payout_out(p: PayoutAccount) -> PayoutAccountOut:
    return PayoutAccountOut(
        bank_name=p.bank_name,
        account_type=p.account_type,
        account_number_masked=mask(p.account_last4),
        holder_name=p.holder_name,
        is_verified=p.is_verified,
        updated_at=p.updated_at,
    )


def document_out(d: StoreDocument) -> StoreDocumentOut:
    return StoreDocumentOut.model_validate(d)
