"""Tiendas, productos y promociones (lado público y lado del emprendedor)."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import encrypt
from app.core.errors import BusinessRuleError, Conflict, Forbidden, NotFound
from app.models import (
    CampusPlace,
    Order,
    OrderLine,
    PayoutAccount,
    Product,
    Promotion,
    Store,
    StoreDocument,
    User,
)
from app.models.enums import OrderStatus, PromotionKind, StoreStatus, UserRole
from app.repositories.repos import (
    CampusRepo,
    ProductRepo,
    PromotionRepo,
    ReviewRepo,
    StoreRepo,
)
from app.schemas.common import Page, PageParams
from app.schemas.product import (
    CouponCheckIn,
    CouponCheckOut,
    ProductIn,
    ProductUpdateIn,
    PromotionIn,
)
from app.schemas.store import (
    EarningsOut,
    PayoutAccountIn,
    StoreCreateIn,
    StoreDocumentIn,
    StoreUpdateIn,
)
from app.services import mappers
from app.services.media import validate_media_url
from app.services.notifications import notify
from app.services.pricing import coupon_discount, discounted_prices, is_running, now


class CatalogService:
    def __init__(self, db: Session):
        self.db = db
        self.stores = StoreRepo(db)
        self.products = ProductRepo(db)
        self.promos = PromotionRepo(db)

    # ------------------------------------------------------------------ campus
    def campus_places(self):
        return [mappers.CampusPlaceOut.model_validate(p) for p in CampusRepo(self.db).all_active()]

    def _check_place(self, place_id: str | None) -> None:
        if place_id and not self.db.get(CampusPlace, place_id):
            raise BusinessRuleError("El lugar del campus no existe", code="invalid_place")

    # ------------------------------------------------------------------ tiendas
    def list_stores(self, *, q, category, open_only, page: PageParams) -> Page:
        stmt = self.stores.public_query(q=q, category=category, open_only=open_only)
        items, total = self.stores.paginate(stmt, offset=page.offset, limit=page.size)
        return Page(items=[mappers.store_out(s) for s in items], total=total, page=page.page, size=page.size)

    def get_public_store(self, store_id: uuid.UUID):
        store = self.stores.with_details(store_id)
        if not store or store.status != StoreStatus.approved:
            raise NotFound("Tienda no encontrada", code="store_not_found")
        return mappers.store_out(store)

    def store_reviews(self, store_id: uuid.UUID, page: PageParams) -> Page:
        items, total = self.stores.paginate(
            ReviewRepo(self.db).for_store(store_id), offset=page.offset, limit=page.size
        )
        return Page(items=[mappers.review_out(r) for r in items], total=total, page=page.page, size=page.size)

    def categories(self) -> list[str]:
        return self.products.categories()

    def create_store(self, user: User, data: StoreCreateIn):
        if user.role == UserRole.admin:
            raise Forbidden("Un administrador no puede tener tienda")
        if self.stores.by_owner(user.id):
            raise Conflict("Ya tienes una tienda registrada", code="store_exists")
        self._check_place(data.pickup_place_id)
        validate_media_url(data.image_url, "store", user.id)
        fields = data.model_dump(exclude_none=True)
        store = Store(owner_id=user.id, **fields)
        store.status = StoreStatus.approved if settings.auto_approve_stores else StoreStatus.pending
        user.role = UserRole.entrepreneur
        try:
            self.stores.add(store)
        except IntegrityError:
            self.db.rollback()
            raise Conflict("Ya tienes una tienda registrada", code="store_exists") from None
        self.db.commit()
        return mappers.store_out(self.stores.with_details(store.id))

    def my_store(self, user: User) -> Store:
        store = self.stores.by_owner(user.id)
        if not store:
            raise NotFound("Aún no tienes una tienda", code="store_not_found")
        return store

    def update_store(self, user: User, data: StoreUpdateIn):
        store = self.my_store(user)
        changes = data.model_dump(exclude_unset=True)
        if "pickup_place_id" in changes:
            self._check_place(changes["pickup_place_id"])
        if changes.get("image_url"):
            validate_media_url(changes["image_url"], "store", user.id)
        for k, v in changes.items():
            if v is not None or k == "pickup_place_id":
                setattr(store, k, v)
        if not store.allows_delivery and not store.allows_pickup:
            raise BusinessRuleError("Activa al menos domicilio o recogida", code="no_fulfillment")
        if store.accepts_nequi and not store.nequi_phone:
            raise BusinessRuleError("Escribe el número de Nequi donde recibirás los pagos", code="missing_nequi")
        if store.accepts_breb and not store.breb_key:
            raise BusinessRuleError("Escribe tu llave Bre-B para recibir transferencias", code="missing_breb_key")
        if store.accepts_card and not settings.card_payment_provider:
            raise BusinessRuleError("El pago con tarjeta todavía no está disponible", code="card_unavailable")
        if not (store.accepts_cash or store.accepts_nequi or store.accepts_breb or store.accepts_card):
            raise BusinessRuleError("Activa al menos un medio de pago", code="no_payment")
        self.db.commit()
        return mappers.store_out(self.stores.with_details(store.id))

    def set_payout(self, user: User, data: PayoutAccountIn):
        store = self.my_store(user)
        acc = self.stores.payout(store.id) or PayoutAccount(store_id=store.id)
        acc.bank_name = data.bank_name
        acc.account_type = data.account_type
        acc.account_number_encrypted = encrypt(data.account_number)
        acc.account_last4 = data.account_number[-4:]
        acc.holder_name = data.holder_name
        acc.holder_document = encrypt(data.holder_document)
        acc.is_verified = False  # cualquier cambio requiere nueva verificación
        self.db.add(acc)
        self.db.commit()
        return mappers.payout_out(acc)

    def get_payout(self, user: User):
        acc = self.stores.payout(self.my_store(user).id)
        if not acc:
            raise NotFound("Aún no registras una cuenta para recibir pagos", code="payout_not_found")
        return mappers.payout_out(acc)

    def add_document(self, user: User, data: StoreDocumentIn):
        store = self.my_store(user)
        validate_media_url(data.file_url, "document", user.id)
        doc = StoreDocument(store_id=store.id, name=data.name, file_url=data.file_url)
        self.db.add(doc)
        self.db.commit()
        return mappers.document_out(doc)

    def documents(self, user: User):
        return [mappers.document_out(d) for d in self.stores.documents(self.my_store(user).id)]

    def earnings(self, user: User, days: int = 30) -> EarningsOut:
        store = self.my_store(user)
        since = now() - timedelta(days=days)
        rows = self.db.execute(
            select(Order.status, func.count(), func.coalesce(func.sum(Order.total), 0))
            .where(Order.store_id == store.id, Order.created_at >= since)
            .group_by(Order.status)
        ).all()
        by_status = {s: (c, t) for s, c, t in rows}
        delivered_count, delivered_total = by_status.get(OrderStatus.delivered, (0, 0))
        cancelled = by_status.get(OrderStatus.cancelled, (0, 0))[0]
        active = sum(c for s, (c, _) in by_status.items() if s.is_active)

        day = func.date(Order.created_at)
        by_day = self.db.execute(
            select(day, func.count(), func.sum(Order.total))
            .where(Order.store_id == store.id, Order.status == OrderStatus.delivered, Order.created_at >= since)
            .group_by(day)
            .order_by(day)
        ).all()
        top = self.db.execute(
            select(OrderLine.name, func.sum(OrderLine.quantity), func.sum(OrderLine.quantity * OrderLine.unit_price))
            .join(Order, Order.id == OrderLine.order_id)
            .where(Order.store_id == store.id, Order.status == OrderStatus.delivered, Order.created_at >= since)
            .group_by(OrderLine.name)
            .order_by(func.sum(OrderLine.quantity).desc())
            .limit(5)
        ).all()
        return EarningsOut(
            total_sales=int(delivered_total),
            delivered_orders=delivered_count,
            active_orders=active,
            cancelled_orders=cancelled,
            average_ticket=int(delivered_total / delivered_count) if delivered_count else 0,
            rating=round(store.rating_avg, 2),
            rating_count=store.rating_count,
            sales_by_day=[{"date": str(d), "orders": c, "total": int(t or 0)} for d, c, t in by_day],
            top_products=[{"name": n, "quantity": int(q), "total": int(t)} for n, q, t in top],
        )

    # ---------------------------------------------------------------- productos
    def _discounts_for(self, products: list[Product]) -> dict[uuid.UUID, int]:
        store_ids = {p.store_id for p in products}
        return discounted_prices(products, self.promos.running_discounts(store_ids, now()))

    def list_products(self, *, page: PageParams, **filters) -> Page:
        stmt = self.products.public_query(**filters)
        items, total = self.products.paginate(stmt, offset=page.offset, limit=page.size)
        prices = self._discounts_for(items)
        return Page(
            items=[mappers.product_out(p, prices.get(p.id)) for p in items], total=total, page=page.page, size=page.size
        )

    def get_product(self, product_id: uuid.UUID):
        p = self.products.get(product_id)
        if not p or p.is_hidden or p.store.status != StoreStatus.approved:
            raise NotFound("Producto no encontrado", code="product_not_found")
        return mappers.product_out(p, self._discounts_for([p]).get(p.id))

    def my_products(self, user: User):
        store = self.my_store(user)
        items = self.products.by_store(store.id)
        prices = self._discounts_for(items)
        return [mappers.product_admin_out(p, prices.get(p.id)) for p in items]

    def _own_product(self, user: User, product_id: uuid.UUID) -> Product:
        store = self.my_store(user)
        p = self.products.get(product_id)
        if not p or p.store_id != store.id:
            raise NotFound("Producto no encontrado", code="product_not_found")
        return p

    def create_product(self, user: User, data: ProductIn):
        store = self.my_store(user)
        validate_media_url(data.image_url, "product", user.id)
        p = Product(store_id=store.id, **data.model_dump())
        self.products.add(p)
        if data.category not in (store.menu_sections or []):
            store.menu_sections = [*(store.menu_sections or []), data.category]
        self.db.commit()
        return mappers.product_admin_out(p)

    def update_product(self, user: User, product_id: uuid.UUID, data: ProductUpdateIn):
        p = self._own_product(user, product_id)
        if data.image_url:
            validate_media_url(data.image_url, "product", user.id)
        for k, v in data.model_dump(exclude_unset=True).items():
            if v is not None:
                setattr(p, k, v)
        self.db.commit()
        return mappers.product_admin_out(p, self._discounts_for([p]).get(p.id))

    def delete_product(self, user: User, product_id: uuid.UUID) -> None:
        p = self._own_product(user, product_id)
        # Los pedidos guardan copia del nombre y precio, así que se puede borrar.
        self.products.delete(p)
        self.db.commit()

    # -------------------------------------------------------------- promociones
    def public_coupons(self, store_id: uuid.UUID | None):
        coupons = self.promos.public_coupons(now(), store_id)
        names = {
            s.id: s.name for s in self.db.scalars(select(Store).where(Store.id.in_({c.store_id for c in coupons})))
        }
        return [mappers.promotion_out(c, names.get(c.store_id, "")) for c in coupons]

    def public_discounts(self):
        """Promociones automáticas vigentes (banners de Inicio y Promos)."""
        stmt = (
            select(Promotion, Store.name)
            .join(Store, Store.id == Promotion.store_id)
            .where(
                Store.status == StoreStatus.approved, Promotion.kind == PromotionKind.product_discount, Promotion.active
            )
        )
        return [mappers.promotion_out(p, name) for p, name in self.db.execute(stmt) if is_running(p)]

    def my_promotions(self, user: User):
        store = self.my_store(user)
        return [mappers.promotion_out(p, store.name) for p in self.promos.by_store(store.id)]

    def _validate_promo_products(self, store: Store, ids: list[uuid.UUID]) -> list[str]:
        if not ids:
            return []
        found = set(self.db.scalars(select(Product.id).where(Product.id.in_(ids), Product.store_id == store.id)))
        if len(found) != len(set(ids)):
            raise BusinessRuleError("Algunos productos no pertenecen a tu tienda", code="invalid_products")
        return [str(i) for i in ids]

    def create_promotion(self, user: User, data: PromotionIn):
        store = self.my_store(user)
        fields = data.model_dump()
        fields["product_ids"] = self._validate_promo_products(store, data.product_ids)
        promo = Promotion(store_id=store.id, **fields)
        try:
            self.promos.add(promo)
        except IntegrityError:
            self.db.rollback()
            raise Conflict("Ya tienes un cupón con ese código", code="coupon_code_taken") from None
        self.db.commit()
        return mappers.promotion_out(promo, store.name)

    def _own_promo(self, user: User, promo_id: uuid.UUID) -> tuple[Store, Promotion]:
        store = self.my_store(user)
        promo = self.promos.get(promo_id)
        if not promo or promo.store_id != store.id:
            raise NotFound("Promoción no encontrada", code="promotion_not_found")
        return store, promo

    def update_promotion(self, user: User, promo_id: uuid.UUID, data: PromotionIn):
        store, promo = self._own_promo(user, promo_id)
        fields = data.model_dump()
        fields["product_ids"] = self._validate_promo_products(store, data.product_ids)
        for k, v in fields.items():
            setattr(promo, k, v)
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            raise Conflict("Ya tienes un cupón con ese código", code="coupon_code_taken") from None
        self.db.commit()
        return mappers.promotion_out(promo, store.name)

    def toggle_promotion(self, user: User, promo_id: uuid.UUID, active: bool):
        store, promo = self._own_promo(user, promo_id)
        promo.active = active
        self.db.commit()
        return mappers.promotion_out(promo, store.name)

    def delete_promotion(self, user: User, promo_id: uuid.UUID) -> None:
        _, promo = self._own_promo(user, promo_id)
        self.promos.delete(promo)
        self.db.commit()

    def check_coupon(self, user: User, data: CouponCheckIn) -> CouponCheckOut:
        coupon = self.promos.coupon(data.store_id, data.code)
        ok, message = self.coupon_status(coupon, user.id, data.subtotal)
        if not ok:
            return CouponCheckOut(valid=False, message=message)
        return CouponCheckOut(
            valid=True,
            discount=coupon_discount(coupon, data.subtotal),
            message=message,
            promotion=mappers.promotion_out(coupon),
        )

    def coupon_status(self, coupon: Promotion | None, user_id: uuid.UUID, subtotal: int) -> tuple[bool, str]:
        if coupon is None or not is_running(coupon):
            return False, "El cupón no existe o ya no está vigente"
        if subtotal < coupon.min_purchase:
            return False, f"Este cupón aplica desde ${coupon.min_purchase:,.0f}".replace(",", ".")
        if coupon.max_uses_per_user and self.promos.uses_by_user(coupon.id, user_id) >= coupon.max_uses_per_user:
            return False, "Ya usaste este cupón"
        return True, "Cupón aplicado"

    # helper usado por pedidos
    def notify_store_owner(self, store: Store, title: str, body: str, data: dict) -> None:
        notify(self.db, store.owner_id, type_="order", title=title, body=body, data=data)
