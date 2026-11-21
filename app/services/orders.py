"""Pedidos: cotización, creación segura, estados, cancelación y reseñas."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import BusinessRuleError, Forbidden, NotFound
from app.core.security import new_pickup_code
from app.models import Order, OrderLine, Product, Review, Store, User
from app.models.enums import (
    FulfillmentMode,
    OrderStatus,
    PaymentKind,
    PaymentStatus,
    StoreStatus,
    UserRole,
)
from app.repositories.repos import AccountRepo, OrderRepo, ProductRepo, PromotionRepo
from app.schemas.common import Page, PageParams
from app.schemas.order import (
    CheckoutQuoteOut,
    OrderCreateIn,
    OrderLineOut,
    OrderStatusIn,
    ReviewIn,
)
from app.services import mappers
from app.services.catalog import CatalogService
from app.services.integrity import check_cancel_rate, notify_admins
from app.services.notifications import notify
from app.services.pricing import coupon_discount, discounted_prices, now

STATUS_MESSAGES = {
    OrderStatus.preparing: ("Estamos preparando tu pedido", "La tienda aceptó tu pedido #{id}."),
    OrderStatus.ready: ("Tu pedido está listo", "Pasa a recoger el pedido #{id} con tu código."),
    OrderStatus.on_the_way: ("Tu pedido va en camino", "El pedido #{id} salió hacia {place}."),
    OrderStatus.delivered: ("Pedido entregado", "¿Qué tal estuvo? Califica el pedido #{id}."),
    OrderStatus.cancelled: ("Pedido cancelado", "El pedido #{id} fue cancelado. {reason}"),
}


@dataclass
class _Priced:
    store: Store
    products: dict[uuid.UUID, Product]
    lines: list[OrderLine]
    subtotal: int  # con descuentos automáticos
    product_discount: int
    coupon: object | None
    coupon_discount: int
    coupon_message: str
    delivery_fee: int

    @property
    def total(self) -> int:
        return max(0, self.subtotal - self.coupon_discount + self.delivery_fee)


class OrderService:
    def __init__(self, db: Session):
        self.db = db
        self.orders = OrderRepo(db)
        self.products = ProductRepo(db)
        self.promos = PromotionRepo(db)
        self.catalog = CatalogService(db)

    # ----------------------------------------------------------- cálculo único
    def _price(self, user: User, data: OrderCreateIn, *, lock: bool) -> _Priced:
        store = self.db.get(Store, data.store_id, with_for_update=False)
        if not store or store.status != StoreStatus.approved:
            raise NotFound("Tienda no encontrada", code="store_not_found")
        if store.owner_id == user.id:
            raise BusinessRuleError("No puedes comprar en tu propia tienda", code="own_store")
        if not store.is_open:
            raise BusinessRuleError("La tienda está cerrada en este momento", code="store_closed")
        if data.mode == FulfillmentMode.delivery and not store.allows_delivery:
            raise BusinessRuleError("Esta tienda no hace domicilios", code="delivery_unavailable")
        if data.mode == FulfillmentMode.pickup and not store.allows_pickup:
            raise BusinessRuleError("Esta tienda no permite recoger", code="pickup_unavailable")
        accepted = {
            PaymentKind.cash: store.accepts_cash,
            PaymentKind.nequi: store.accepts_nequi and bool(store.nequi_phone),
            PaymentKind.breb: store.accepts_breb and bool(store.breb_key),
            PaymentKind.card: store.accepts_card and bool(settings.card_payment_provider),
        }
        if not accepted[data.payment_kind]:
            raise BusinessRuleError("La tienda no acepta ese medio de pago", code="payment_not_accepted")
        if data.mode == FulfillmentMode.delivery:
            self.catalog._check_place(data.place_id)

        ids = [ln.product_id for ln in data.lines]
        found = (
            self.products.many_for_update(ids)
            if lock
            else list(self.db.scalars(select(Product).where(Product.id.in_(ids))))
        )
        products = {p.id: p for p in found}
        prices = discounted_prices(found, self.promos.running_discounts({store.id}, now()))

        lines: list[OrderLine] = []
        list_total = subtotal = 0
        for ln in data.lines:
            p = products.get(ln.product_id)
            if not p or p.store_id != store.id or p.is_hidden:
                raise BusinessRuleError(
                    "Un producto del pedido ya no existe",
                    code="product_unavailable",
                    details={"productId": str(ln.product_id)},
                )
            if not p.is_available:
                raise BusinessRuleError(
                    f"{p.name} no está disponible", code="product_unavailable", details={"productId": str(p.id)}
                )
            if p.stock < ln.quantity:
                raise BusinessRuleError(
                    f"Solo quedan {p.stock} unidades de {p.name}",
                    code="out_of_stock",
                    details={"productId": str(p.id), "available": p.stock},
                )
            unit = prices.get(p.id, p.price)
            list_total += p.price * ln.quantity
            subtotal += unit * ln.quantity
            lines.append(
                OrderLine(
                    product_id=p.id,
                    name=p.name,
                    category=p.category,
                    image_url=p.image_url,
                    list_price=p.price,
                    unit_price=unit,
                    quantity=ln.quantity,
                )
            )
        if subtotal < store.min_order:
            raise BusinessRuleError(
                f"El pedido mínimo en esta tienda es ${store.min_order:,.0f}".replace(",", "."),
                code="below_min_order",
            )

        coupon, c_discount, c_message = None, 0, ""
        if data.coupon_code:
            coupon = self.promos.coupon(store.id, data.coupon_code, lock=lock)
            ok, c_message = self.catalog.coupon_status(coupon, user.id, subtotal)
            if ok:
                c_discount = coupon_discount(coupon, subtotal)
            elif lock:
                raise BusinessRuleError(c_message, code="invalid_coupon")
            else:
                coupon = None

        fee = store.delivery_fee if data.mode == FulfillmentMode.delivery else 0
        return _Priced(store, products, lines, subtotal, list_total - subtotal, coupon, c_discount, c_message, fee)

    def quote(self, user: User, data: OrderCreateIn) -> CheckoutQuoteOut:
        priced = self._price(user, data, lock=False)
        return CheckoutQuoteOut(
            subtotal=priced.subtotal,
            product_discount=priced.product_discount,
            coupon_discount=priced.coupon_discount,
            coupon_message=priced.coupon_message,
            delivery_fee=priced.delivery_fee,
            total=priced.total,
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
                for ln in priced.lines
            ],
        )

    # ----------------------------------------------------------------- crear
    def create(self, user: User, data: OrderCreateIn, idempotency_key: str | None = None):
        if user.role == UserRole.admin:
            raise Forbidden("Los administradores no pueden comprar")
        if idempotency_key:
            existing = self.orders.by_idempotency(user.id, idempotency_key)
            if existing:
                return mappers.order_out(existing, viewer="customer")

        card = None
        if data.payment_kind == PaymentKind.card:
            card = AccountRepo(self.db).card(user.id, data.payment_method_id)
            if not card:
                raise BusinessRuleError("La tarjeta no existe", code="invalid_card")

        priced = self._price(user, data, lock=True)
        for ln in priced.lines:
            priced.products[ln.product_id].stock -= ln.quantity
        if priced.coupon is not None:
            priced.coupon.uses += 1

        label = {
            PaymentKind.cash: "Efectivo al recoger"
            if data.mode == FulfillmentMode.pickup
            else "Efectivo contra entrega",
            PaymentKind.nequi: "Transferencia Nequi",
            PaymentKind.breb: "Transferencia Bre-B",
            PaymentKind.card: f"{card.brand} •••• {card.last4}" if card else "Tarjeta",
        }[data.payment_kind]
        order = Order(
            customer_id=user.id,
            store_id=priced.store.id,
            status=OrderStatus.pending,
            mode=data.mode,
            place_id=data.place_id if data.mode == FulfillmentMode.delivery else priced.store.pickup_place_id,
            notes=data.notes,
            pickup_code=new_pickup_code(),
            subtotal=priced.subtotal,
            product_discount=priced.product_discount,
            coupon_discount=priced.coupon_discount,
            coupon_code=priced.coupon.code if priced.coupon is not None else "",
            promotion_id=priced.coupon.id if priced.coupon is not None else None,
            delivery_fee=priced.delivery_fee,
            total=priced.total,
            payment_kind=data.payment_kind,
            # Efectivo se marca pagado al entregar; transferencias cuando la tienda confirma.
            payment_status=PaymentStatus.pending,
            payment_method_id=card.id if card else None,
            payment_label=label,
            history={OrderStatus.pending.value: now().isoformat()},
            idempotency_key=idempotency_key,
            lines=priced.lines,
        )
        self.db.add(order)
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            if idempotency_key:
                existing = self.orders.by_idempotency(user.id, idempotency_key)
                if existing:
                    return mappers.order_out(existing, viewer="customer")
            raise
        self.catalog.notify_store_owner(
            priced.store,
            f"Nuevo pedido #{order.id}",
            f"{user.full_name} pidió {sum(ln.quantity for ln in priced.lines)} producto(s) · "
            f"{'Recoge en tu punto' if data.mode == FulfillmentMode.pickup else 'Domicilio'}",
            {"orderId": order.id},
        )
        self.db.commit()
        return mappers.order_out(self.orders.detail(order.id), viewer="customer")

    # -------------------------------------------------------------- consultar
    def my_orders(self, user: User, *, active: bool | None, page: PageParams) -> Page:
        items, total = self.orders.paginate(
            self.orders.for_customer(user.id, active=active), offset=page.offset, limit=page.size
        )
        return Page(
            items=[mappers.order_out(o, viewer="customer") for o in items], total=total, page=page.page, size=page.size
        )

    def store_orders(self, user: User, *, active: bool | None, status: OrderStatus | None, page: PageParams) -> Page:
        store = self.catalog.my_store(user)
        items, total = self.orders.paginate(
            self.orders.for_store(store.id, active=active, status=status), offset=page.offset, limit=page.size
        )
        return Page(
            items=[mappers.order_out(o, viewer="seller") for o in items], total=total, page=page.page, size=page.size
        )

    def get(self, user: User, order_id: int):
        order = self.orders.detail(order_id)
        viewer = self._viewer(user, order)
        return mappers.order_out(order, viewer=viewer)

    def _viewer(self, user: User, order: Order | None) -> str:
        if order is None:
            raise NotFound("Pedido no encontrado", code="order_not_found")
        if order.customer_id == user.id:
            return "customer"
        if order.store and order.store.owner_id == user.id:
            return "seller"
        if user.role == UserRole.admin:
            return "admin"
        # Mismo error que "no existe" para no revelar qué pedidos hay.
        raise NotFound("Pedido no encontrado", code="order_not_found")

    # ---------------------------------------------------------------- estados
    def change_status(self, user: User, order_id: int, data: OrderStatusIn):
        order = self.orders.detail(order_id, lock=True)
        viewer = self._viewer(user, order)
        if viewer != "seller":
            raise Forbidden("Solo la tienda puede actualizar el estado")
        if data.status == OrderStatus.cancelled:
            return self._cancel(order, by="seller", reason=data.reason or "La tienda no pudo atender el pedido.")
        expected = mappers.next_status(order)
        if expected is None or data.status != expected:
            raise BusinessRuleError(
                f"El pedido está «{order.status.value}» y no puede pasar a «{data.status.value}»",
                code="invalid_transition",
                details={"expected": expected.value if expected else None},
            )
        if (
            data.status == OrderStatus.delivered
            and order.mode == FulfillmentMode.pickup
            and data.pickup_code is not None
            and data.pickup_code != order.pickup_code
        ):
            raise BusinessRuleError("El código de recogida no coincide", code="invalid_pickup_code")
        order.status = data.status
        order.history = {**(order.history or {}), data.status.value: now().isoformat()}
        if data.status == OrderStatus.delivered:
            order.delivered_at = now()
        if data.status == OrderStatus.delivered and order.payment_kind == PaymentKind.cash:
            order.payment_status = PaymentStatus.paid
            order.payment_confirmed_at = now()
        self._notify_customer(order)
        self.db.commit()
        return mappers.order_out(self.orders.detail(order.id), viewer="seller")

    def cancel_by_customer(self, user: User, order_id: int, reason: str):
        order = self.orders.detail(order_id, lock=True)
        if self._viewer(user, order) != "customer":
            raise Forbidden("Solo quien hizo el pedido puede cancelarlo")
        if order.status != OrderStatus.pending:
            raise BusinessRuleError(
                "La tienda ya empezó a preparar tu pedido; escríbele para cancelarlo", code="cannot_cancel"
            )
        return self._cancel(order, by="customer", reason=reason or "Cancelado por el cliente.")

    def _cancel(self, order: Order, *, by: str, reason: str):
        if not order.status.is_active:
            raise BusinessRuleError("El pedido ya terminó", code="cannot_cancel")
        if by == "seller" and order.status not in (OrderStatus.pending, OrderStatus.preparing):
            raise BusinessRuleError("El pedido ya salió; no se puede cancelar", code="cannot_cancel")
        # Devuelve el inventario y el uso del cupón.
        ids = [ln.product_id for ln in order.lines if ln.product_id]
        products = {p.id: p for p in self.products.many_for_update(ids)} if ids else {}
        for ln in order.lines:
            if ln.product_id in products:
                products[ln.product_id].stock += ln.quantity
        if order.promotion_id:
            promo = self.promos.get_for_update(order.promotion_id)
            if promo and promo.uses > 0:
                promo.uses -= 1
        paid = order.payment_status in (PaymentStatus.reported, PaymentStatus.paid, PaymentStatus.authorized)
        order.status = OrderStatus.cancelled
        order.cancel_reason = reason
        order.cancelled_at = now()
        order.cancelled_by = by
        order.history = {**(order.history or {}), OrderStatus.cancelled.value: now().isoformat()}
        if by == "seller":
            if paid:
                # El dinero ya se transfirió (o eso reportó el cliente): la tienda debe
                # devolverlo y el pedido queda para revisión del admin.
                order.paid_cancelled = True
                order.dispute_status = "open"
                notify_admins(
                    self.db,
                    f"Pedido #{order.id} cancelado con pago",
                    f"{order.store.name} canceló un pedido con el pago "
                    f"{'confirmado' if order.payment_status == PaymentStatus.paid else 'reportado'}. "
                    f"Motivo: {reason}",
                    {"orderId": order.id, "storeId": str(order.store_id)},
                )
            notify(
                self.db,
                order.customer_id,
                type_="order",
                title=f"{order.store.name} canceló tu pedido #{order.id}",
                body=(
                    f"Motivo: {reason} "
                    + ("La tienda debe devolverte el dinero. " if paid else "")
                    + "¿Recibiste el pedido de todas formas? Cuéntanos en el detalle del pedido."
                ),
                data={"orderId": order.id, "status": "cancelled", "askReceived": True},
            )
            check_cancel_rate(self.db, order.store)
        else:
            if order.payment_status in (PaymentStatus.paid, PaymentStatus.authorized):
                order.payment_status = PaymentStatus.refunded
            self.catalog.notify_store_owner(order.store, f"Pedido #{order.id} cancelado", reason, {"orderId": order.id})
        self.db.commit()
        return mappers.order_out(self.orders.detail(order.id), viewer=by)

    def _notify_customer(self, order: Order) -> None:
        title, body = STATUS_MESSAGES[order.status]
        notify(
            self.db,
            order.customer_id,
            type_="order",
            title=title,
            body=body.format(
                id=order.id, place=order.place.name if order.place else "tu punto", reason=order.cancel_reason
            ),
            data={"orderId": order.id, "status": order.status.value},
        )

    def cancel_feedback(self, user: User, order_id: int, received: bool):
        """El cliente dice si recibió un pedido que la tienda canceló.

        Si dice que sí, se abre una disputa y el pedido cuenta como venta para la
        comisión mientras el admin no la descarte.
        """
        order = self.orders.detail(order_id, lock=True)
        if self._viewer(user, order) != "customer":
            raise Forbidden("Solo quien hizo el pedido puede responder")
        if order.status != OrderStatus.cancelled or order.cancelled_by != "seller":
            raise BusinessRuleError("Este pedido no fue cancelado por la tienda", code="not_cancelled_by_store")
        if order.customer_confirmation:
            raise BusinessRuleError("Ya respondiste sobre este pedido", code="already_answered")
        if order.cancelled_at and now() - order.cancelled_at > timedelta(days=settings.cancel_feedback_days):
            raise BusinessRuleError("Ya pasó el plazo para responder", code="feedback_expired")
        order.customer_confirmation = "received" if received else "not_received"
        if received:
            order.dispute_status = "open"
            notify_admins(
                self.db,
                f"Disputa en el pedido #{order.id}",
                f"{order.store.name} canceló el pedido, pero el cliente dice que sí lo recibió.",
                {"orderId": order.id, "storeId": str(order.store_id)},
            )
            self.catalog.notify_store_owner(
                order.store,
                f"Revisión del pedido #{order.id}",
                "El cliente indicó que sí recibió el pedido que cancelaste. "
                "Cuenta como venta mientras el equipo de UniMarket lo revisa.",
                {"orderId": order.id},
            )
        self.db.commit()
        return mappers.order_out(self.orders.detail(order.id), viewer="customer")

    # ------------------------------------------------------- transferencias
    def report_payment(self, user: User, order_id: int, reference: str):
        """El cliente avisa que ya transfirió al Nequi o a la llave Bre-B de la tienda."""
        order = self.orders.detail(order_id, lock=True)
        if self._viewer(user, order) != "customer":
            raise Forbidden("Solo quien hizo el pedido puede reportar el pago")
        if not order.payment_kind.is_transfer:
            raise BusinessRuleError("Este pedido no se paga por transferencia", code="not_transfer")
        if not order.status.is_active:
            raise BusinessRuleError("El pedido ya terminó", code="order_closed")
        if order.payment_status not in (PaymentStatus.pending, PaymentStatus.failed):
            raise BusinessRuleError("Ya reportaste este pago", code="already_reported")
        order.payment_status = PaymentStatus.reported
        order.payment_reference = reference
        order.payment_reported_at = now()
        self.catalog.notify_store_owner(
            order.store,
            f"Revisa el pago del pedido #{order.id}",
            f"El cliente reporta una transferencia de ${order.total:,.0f}".replace(",", ".")
            + (f" (ref. {reference})" if reference else ""),
            {"orderId": order.id},
        )
        self.db.commit()
        return mappers.order_out(self.orders.detail(order.id), viewer="customer")

    def confirm_payment(self, user: User, order_id: int, received: bool):
        """La tienda confirma (o no) que el dinero llegó a su cuenta."""
        order = self.orders.detail(order_id, lock=True)
        if self._viewer(user, order) != "seller":
            raise Forbidden("Solo la tienda puede confirmar el pago")
        if order.payment_kind == PaymentKind.card:
            raise BusinessRuleError("Los pagos con tarjeta los confirma la pasarela", code="card_payment")
        if order.payment_status == PaymentStatus.paid:
            raise BusinessRuleError("El pago ya estaba confirmado", code="already_paid")
        order.payment_status = PaymentStatus.paid if received else PaymentStatus.failed
        order.payment_confirmed_at = now() if received else None
        notify(
            self.db,
            order.customer_id,
            type_="order",
            title="Pago confirmado" if received else "La tienda no ve tu pago",
            body=(
                f"La tienda recibió el pago del pedido #{order.id}."
                if received
                else f"Revisa la transferencia del pedido #{order.id} o escríbele a la tienda."
            ),
            data={"orderId": order.id},
        )
        self.db.commit()
        return mappers.order_out(self.orders.detail(order.id), viewer="seller")

    # ---------------------------------------------------------------- reseñas
    def review(self, user: User, order_id: int, data: ReviewIn):
        order = self.orders.detail(order_id, lock=True)
        if self._viewer(user, order) != "customer":
            raise Forbidden("Solo quien hizo el pedido puede calificarlo")
        if order.status != OrderStatus.delivered:
            raise BusinessRuleError("Podrás calificar cuando recibas el pedido", code="not_delivered")
        if order.review:
            raise BusinessRuleError("Ya calificaste este pedido", code="already_reviewed")
        review = Review(
            order_id=order.id,
            store_id=order.store_id,
            customer_id=user.id,
            rating=data.rating,
            comment=data.comment,
            tags=[t[:30] for t in data.tags],
        )
        self.db.add(review)
        self.db.flush()
        self._recompute_ratings(order)
        self.catalog.notify_store_owner(
            order.store, f"Nueva reseña: {'★' * data.rating}", data.comment[:120], {"orderId": order.id}
        )
        self.db.commit()
        return mappers.review_out(self.db.get(Review, review.id))

    def reply_review(self, user: User, order_id: int, reply: str):
        order = self.orders.detail(order_id)
        if self._viewer(user, order) != "seller" or not order.review:
            raise NotFound("Reseña no encontrada", code="review_not_found")
        order.review.seller_reply = reply
        self.db.commit()
        return mappers.review_out(order.review)

    def _recompute_ratings(self, order: Order) -> None:
        store = self.db.get(Store, order.store_id, with_for_update=True)
        avg, count = self.db.execute(
            select(func.avg(Review.rating), func.count()).where(Review.store_id == store.id)
        ).one()
        store.rating_avg, store.rating_count = float(avg or 0), int(count)
        # Cada producto del pedido hereda la calificación (aprox. por producto).
        for ln in order.lines:
            if not ln.product_id:
                continue
            p_avg, p_count = self.db.execute(
                select(func.avg(Review.rating), func.count())
                .join(OrderLine, OrderLine.order_id == Review.order_id)
                .where(OrderLine.product_id == ln.product_id)
            ).one()
            product = self.db.get(Product, ln.product_id)
            if product:
                product.rating_avg, product.rating_count = float(p_avg or 0), int(p_count)
