"""Reglas de precios: descuentos automáticos y cupones (igual que en la app)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime

from app.models import Product, Promotion
from app.models.enums import DiscountType, PromotionKind


def now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def is_running(p: Promotion, at: datetime | None = None) -> bool:
    at = at or now()
    starts, ends = _aware(p.starts_at), _aware(p.ends_at)
    if not p.active:
        return False
    if starts and starts > at:
        return False
    if ends and ends <= at:
        return False
    if p.max_uses is not None and p.uses >= p.max_uses:
        return False
    return True


def apply_discount(price: int, type_: DiscountType, value: int) -> int:
    """Precio con descuento, redondeado a la centena (como `PromotionEntity.apply`)."""
    discounted = price * (100 - value) / 100 if type_ == DiscountType.percent else price - value
    rounded = int(round(discounted / 100.0)) * 100
    return max(0, min(price, rounded))


def discounted_prices(products: list[Product], discounts: list[Promotion]) -> dict[uuid.UUID, int]:
    """Para cada producto, el mejor precio entre los descuentos automáticos vigentes."""
    by_store: dict[uuid.UUID, list[Promotion]] = defaultdict(list)
    for d in discounts:
        if d.kind == PromotionKind.product_discount and is_running(d):
            by_store[d.store_id].append(d)
    result: dict[uuid.UUID, int] = {}
    for p in products:
        best = p.price
        for d in by_store.get(p.store_id, []):
            if d.product_ids and str(p.id) not in d.product_ids:
                continue
            best = min(best, apply_discount(p.price, d.type, d.value))
        if best < p.price:
            result[p.id] = best
    return result


def coupon_discount(coupon: Promotion, subtotal: int) -> int:
    """Valor a descontar del subtotal con un cupón (nunca más que el subtotal)."""
    if coupon.type == DiscountType.percent:
        value = int(round(subtotal * coupon.value / 100 / 100.0)) * 100
    else:
        value = coupon.value
    return max(0, min(subtotal, value))
