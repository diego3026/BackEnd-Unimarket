"""Consultas específicas por agregado."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.orm import joinedload, selectinload

from app.models import (
    Address,
    CampusPlace,
    Favorite,
    Notification,
    OneTimeToken,
    Order,
    PaymentMethod,
    PayoutAccount,
    Product,
    Promotion,
    RefreshToken,
    Review,
    Store,
    StoreDocument,
    User,
)
from app.models.enums import OrderStatus, PromotionKind, StoreStatus
from app.repositories.base import Repository


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class UserRepo(Repository[User]):
    model = User

    def by_email(self, email: str) -> User | None:
        return self.db.scalar(select(User).where(User.email == email.lower()))

    def search(self, *, q: str | None, role=None, status=None) -> Select:
        stmt = select(User).order_by(User.created_at.desc())
        if q:
            like = f"%{_escape_like(q)}%"
            stmt = stmt.where(or_(User.email.ilike(like, escape="\\"), User.full_name.ilike(like, escape="\\")))
        if role:
            stmt = stmt.where(User.role == role)
        if status:
            stmt = stmt.where(User.status == status)
        return stmt


class TokenRepo(Repository[RefreshToken]):
    model = RefreshToken

    def refresh_by_hash(self, token_hash: str) -> RefreshToken | None:
        return self.db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update())

    def revoke_family(self, family_id: uuid.UUID, now: datetime) -> None:
        self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    def revoke_user(self, user_id: uuid.UUID, now: datetime) -> None:
        self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    def one_time(self, token_hash: str) -> OneTimeToken | None:
        return self.db.scalar(select(OneTimeToken).where(OneTimeToken.token_hash == token_hash).with_for_update())


class CampusRepo(Repository[CampusPlace]):
    model = CampusPlace

    def all_active(self) -> list[CampusPlace]:
        return list(self.db.scalars(select(CampusPlace).where(CampusPlace.is_active).order_by(CampusPlace.name)))


class StoreRepo(Repository[Store]):
    model = Store

    def by_owner(self, owner_id: uuid.UUID) -> Store | None:
        return self.db.scalar(
            select(Store)
            .options(joinedload(Store.pickup_place), joinedload(Store.owner))
            .where(Store.owner_id == owner_id)
        )

    def with_details(self, store_id: uuid.UUID) -> Store | None:
        return self.db.scalar(
            select(Store).options(joinedload(Store.pickup_place), joinedload(Store.owner)).where(Store.id == store_id)
        )

    def public_query(self, *, q: str | None, category: str | None, open_only: bool) -> Select:
        stmt = (
            select(Store)
            .options(joinedload(Store.pickup_place), joinedload(Store.owner))
            .where(Store.status == StoreStatus.approved)
            .order_by(Store.is_open.desc(), Store.rating_avg.desc(), Store.name)
        )
        if q:
            like = f"%{_escape_like(q)}%"
            stmt = stmt.where(or_(Store.name.ilike(like, escape="\\"), Store.description.ilike(like, escape="\\")))
        if category:
            stmt = stmt.where(Store.category == category)
        if open_only:
            stmt = stmt.where(Store.is_open)
        return stmt

    def admin_query(self, *, status: StoreStatus | None, q: str | None) -> Select:
        stmt = (
            select(Store)
            .options(joinedload(Store.owner), joinedload(Store.pickup_place))
            .order_by(Store.created_at.desc())
        )
        if status:
            stmt = stmt.where(Store.status == status)
        if q:
            stmt = stmt.where(Store.name.ilike(f"%{_escape_like(q)}%", escape="\\"))
        return stmt

    def payout(self, store_id: uuid.UUID) -> PayoutAccount | None:
        return self.db.scalar(select(PayoutAccount).where(PayoutAccount.store_id == store_id))

    def documents(self, store_id: uuid.UUID) -> list[StoreDocument]:
        return list(
            self.db.scalars(
                select(StoreDocument).where(StoreDocument.store_id == store_id).order_by(StoreDocument.created_at)
            )
        )


class ProductRepo(Repository[Product]):
    model = Product

    def public_query(
        self,
        *,
        q: str | None,
        category: str | None,
        store_id: uuid.UUID | None,
        featured: bool | None,
        min_price: int | None,
        max_price: int | None,
        sort: str,
    ) -> Select:
        stmt = (
            select(Product)
            .join(Store, Product.store_id == Store.id)
            .options(joinedload(Product.store))
            .where(Store.status == StoreStatus.approved, Product.is_hidden.is_(False), Product.is_available)
        )
        if q:
            like = f"%{_escape_like(q)}%"
            stmt = stmt.where(
                or_(
                    Product.name.ilike(like, escape="\\"),
                    Product.description.ilike(like, escape="\\"),
                    Product.category.ilike(like, escape="\\"),
                    Store.name.ilike(like, escape="\\"),
                )
            )
        if category:
            stmt = stmt.where(or_(Product.category == category, Store.category == category))
        if store_id:
            stmt = stmt.where(Product.store_id == store_id)
        if featured is not None:
            stmt = stmt.where(Product.is_featured.is_(featured))
        if min_price is not None:
            stmt = stmt.where(Product.price >= min_price)
        if max_price is not None:
            stmt = stmt.where(Product.price <= max_price)
        order = {
            "price_asc": [Product.price.asc()],
            "price_desc": [Product.price.desc()],
            "rating": [Product.rating_avg.desc(), Product.rating_count.desc()],
            "newest": [Product.created_at.desc()],
        }.get(sort, [Product.is_featured.desc(), Product.rating_avg.desc(), Product.created_at.desc()])
        return stmt.order_by(*order, Product.id)

    def by_store(self, store_id: uuid.UUID) -> list[Product]:
        return list(
            self.db.scalars(
                select(Product).where(Product.store_id == store_id).order_by(Product.category, Product.name)
            )
        )

    def many_for_update(self, ids: list[uuid.UUID]) -> list[Product]:
        # Orden fijo para evitar bloqueos cruzados entre pedidos simultáneos.
        return list(self.db.scalars(select(Product).where(Product.id.in_(ids)).order_by(Product.id).with_for_update()))

    def categories(self) -> list[str]:
        stmt = (
            select(Store.category)
            .where(Store.status == StoreStatus.approved)
            .group_by(Store.category)
            .order_by(func.count().desc())
        )
        return list(self.db.scalars(stmt))


class PromotionRepo(Repository[Promotion]):
    model = Promotion

    def by_store(self, store_id: uuid.UUID) -> list[Promotion]:
        return list(
            self.db.scalars(
                select(Promotion).where(Promotion.store_id == store_id).order_by(Promotion.created_at.desc())
            )
        )

    def running_discounts(self, store_ids: set[uuid.UUID], now: datetime) -> list[Promotion]:
        if not store_ids:
            return []
        return list(
            self.db.scalars(
                select(Promotion).where(
                    Promotion.store_id.in_(store_ids),
                    Promotion.kind == PromotionKind.product_discount,
                    Promotion.active,
                    or_(Promotion.starts_at.is_(None), Promotion.starts_at <= now),
                    or_(Promotion.ends_at.is_(None), Promotion.ends_at > now),
                )
            )
        )

    def public_coupons(self, now: datetime, store_id: uuid.UUID | None = None) -> list[Promotion]:
        stmt = (
            select(Promotion)
            .join(Store, Promotion.store_id == Store.id)
            .where(
                Store.status == StoreStatus.approved,
                Promotion.kind == PromotionKind.coupon,
                Promotion.active,
                or_(Promotion.starts_at.is_(None), Promotion.starts_at <= now),
                or_(Promotion.ends_at.is_(None), Promotion.ends_at > now),
                or_(Promotion.max_uses.is_(None), Promotion.uses < Promotion.max_uses),
            )
            .order_by(Promotion.created_at.desc())
        )
        if store_id:
            stmt = stmt.where(Promotion.store_id == store_id)
        return list(self.db.scalars(stmt))

    def coupon(self, store_id: uuid.UUID, code: str, *, lock: bool = False) -> Promotion | None:
        stmt = select(Promotion).where(
            Promotion.store_id == store_id,
            Promotion.kind == PromotionKind.coupon,
            Promotion.code == code.upper(),
        )
        if lock:
            stmt = stmt.with_for_update()
        return self.db.scalar(stmt)

    def uses_by_user(self, promotion_id: uuid.UUID, user_id: uuid.UUID) -> int:
        return (
            self.db.scalar(
                select(func.count())
                .select_from(Order)
                .where(
                    Order.promotion_id == promotion_id,
                    Order.customer_id == user_id,
                    Order.status != OrderStatus.cancelled,
                )
            )
            or 0
        )


class OrderRepo(Repository[Order]):
    model = Order

    def _base(self) -> Select:
        return select(Order).options(
            selectinload(Order.lines),
            joinedload(Order.review),
            joinedload(Order.store),
            joinedload(Order.customer),
            joinedload(Order.place),
        )

    def detail(self, order_id: int, *, lock: bool = False) -> Order | None:
        if lock:
            # FOR UPDATE no admite LEFT JOIN en Postgres: se bloquea primero la fila.
            if self.db.scalar(select(Order.id).where(Order.id == order_id).with_for_update()) is None:
                return None
        return self.db.scalar(self._base().where(Order.id == order_id))

    def for_customer(self, customer_id: uuid.UUID, *, active: bool | None) -> Select:
        stmt = self._base().where(Order.customer_id == customer_id).order_by(Order.created_at.desc())
        return self._filter_active(stmt, active)

    def for_store(self, store_id: uuid.UUID, *, active: bool | None, status: OrderStatus | None) -> Select:
        stmt = self._base().where(Order.store_id == store_id).order_by(Order.created_at.desc())
        if status:
            stmt = stmt.where(Order.status == status)
        return self._filter_active(stmt, active)

    def by_idempotency(self, customer_id: uuid.UUID, key: str) -> Order | None:
        return self.db.scalar(self._base().where(Order.customer_id == customer_id, Order.idempotency_key == key))

    @staticmethod
    def _filter_active(stmt: Select, active: bool | None) -> Select:
        done = (OrderStatus.delivered, OrderStatus.cancelled)
        if active is True:
            stmt = stmt.where(Order.status.not_in(done))
        elif active is False:
            stmt = stmt.where(Order.status.in_(done))
        return stmt


class ReviewRepo(Repository[Review]):
    model = Review

    def for_store(self, store_id: uuid.UUID) -> Select:
        return (
            select(Review)
            .options(joinedload(Review.customer))
            .where(Review.store_id == store_id)
            .order_by(Review.created_at.desc())
        )


class AccountRepo:
    """Billetera, direcciones, favoritos y notificaciones (todo pertenece a un usuario)."""

    def __init__(self, db):
        self.db = db

    def cards(self, user_id: uuid.UUID) -> list[PaymentMethod]:
        return list(
            self.db.scalars(
                select(PaymentMethod)
                .where(PaymentMethod.user_id == user_id)
                .order_by(PaymentMethod.is_default.desc(), PaymentMethod.created_at)
            )
        )

    def card(self, user_id: uuid.UUID, card_id: uuid.UUID) -> PaymentMethod | None:
        return self.db.scalar(
            select(PaymentMethod).where(PaymentMethod.user_id == user_id, PaymentMethod.id == card_id)
        )

    def addresses(self, user_id: uuid.UUID) -> list[Address]:
        return list(
            self.db.scalars(
                select(Address)
                .where(Address.user_id == user_id)
                .order_by(Address.is_default.desc(), Address.created_at)
            )
        )

    def address(self, user_id: uuid.UUID, address_id: uuid.UUID) -> Address | None:
        return self.db.scalar(select(Address).where(Address.user_id == user_id, Address.id == address_id))

    def favorite_products(self, user_id: uuid.UUID) -> list[Product]:
        return list(
            self.db.scalars(
                select(Product)
                .join(Favorite, Favorite.product_id == Product.id)
                .options(joinedload(Product.store))
                .where(Favorite.user_id == user_id)
                .order_by(Favorite.created_at.desc())
            )
        )

    def favorite(self, user_id: uuid.UUID, product_id: uuid.UUID) -> Favorite | None:
        return self.db.get(Favorite, (user_id, product_id))

    def notifications(self, user_id: uuid.UUID) -> Select:
        return select(Notification).where(Notification.user_id == user_id).order_by(Notification.created_at.desc())

    def unread_count(self, user_id: uuid.UUID) -> int:
        return (
            self.db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.user_id == user_id, Notification.read_at.is_(None))
            )
            or 0
        )
