"""Billetera (tarjetas tokenizadas), direcciones y favoritos."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, NotFound
from app.models import Address, Favorite, PaymentMethod, Product, User
from app.repositories.repos import AccountRepo, PromotionRepo
from app.schemas.account import AddressIn, PaymentMethodIn
from app.services import mappers
from app.services.pricing import discounted_prices, now

MAX_CARDS = 5
MAX_ADDRESSES = 10


class AccountService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AccountRepo(db)

    # ------------------------------------------------------------ tarjetas
    def cards(self, user: User):
        return [mappers.card_out(c) for c in self.repo.cards(user.id)]

    def add_card(self, user: User, data: PaymentMethodIn):
        today = date.today()
        if (data.exp_year, data.exp_month) < (today.year, today.month):
            raise BusinessRuleError("La tarjeta está vencida", code="card_expired")
        existing = self.repo.cards(user.id)
        if len(existing) >= MAX_CARDS:
            raise BusinessRuleError(f"Puedes guardar hasta {MAX_CARDS} tarjetas", code="too_many_cards")
        make_default = data.is_default or not existing
        if make_default:
            self._clear_default_cards(user.id)
        card = PaymentMethod(user_id=user.id, **{**data.model_dump(), "is_default": make_default})
        self.db.add(card)
        self.db.commit()
        return mappers.card_out(card)

    def set_default_card(self, user: User, card_id: uuid.UUID):
        card = self.repo.card(user.id, card_id)
        if not card:
            raise NotFound("Tarjeta no encontrada", code="card_not_found")
        self._clear_default_cards(user.id)
        card.is_default = True
        self.db.commit()
        return mappers.card_out(card)

    def delete_card(self, user: User, card_id: uuid.UUID) -> None:
        card = self.repo.card(user.id, card_id)
        if not card:
            raise NotFound("Tarjeta no encontrada", code="card_not_found")
        was_default = card.is_default
        self.db.delete(card)
        self.db.flush()
        if was_default:
            remaining = self.repo.cards(user.id)
            if remaining:
                remaining[0].is_default = True
        self.db.commit()

    def _clear_default_cards(self, user_id: uuid.UUID) -> None:
        self.db.execute(update(PaymentMethod).where(PaymentMethod.user_id == user_id).values(is_default=False))

    # ---------------------------------------------------------- direcciones
    def addresses(self, user: User):
        return [mappers.address_out(a) for a in self.repo.addresses(user.id)]

    def add_address(self, user: User, data: AddressIn):
        existing = self.repo.addresses(user.id)
        if len(existing) >= MAX_ADDRESSES:
            raise BusinessRuleError(f"Puedes guardar hasta {MAX_ADDRESSES} direcciones", code="too_many_addresses")
        make_default = data.is_default or not existing
        if make_default:
            self.db.execute(update(Address).where(Address.user_id == user.id).values(is_default=False))
        addr = Address(user_id=user.id, **{**data.model_dump(), "is_default": make_default})
        self.db.add(addr)
        self.db.commit()
        return mappers.address_out(addr)

    def update_address(self, user: User, address_id: uuid.UUID, data: AddressIn):
        addr = self.repo.address(user.id, address_id)
        if not addr:
            raise NotFound("Dirección no encontrada", code="address_not_found")
        if data.is_default:
            self.db.execute(update(Address).where(Address.user_id == user.id).values(is_default=False))
        for k, v in data.model_dump().items():
            setattr(addr, k, v)
        self.db.commit()
        return mappers.address_out(addr)

    def delete_address(self, user: User, address_id: uuid.UUID) -> None:
        addr = self.repo.address(user.id, address_id)
        if not addr:
            raise NotFound("Dirección no encontrada", code="address_not_found")
        self.db.delete(addr)
        self.db.commit()

    # ------------------------------------------------------------ favoritos
    def favorites(self, user: User):
        products = [p for p in self.repo.favorite_products(user.id) if not p.is_hidden]
        prices = discounted_prices(
            products, PromotionRepo(self.db).running_discounts({p.store_id for p in products}, now())
        )
        return [mappers.product_out(p, prices.get(p.id)) for p in products]

    def add_favorite(self, user: User, product_id: uuid.UUID) -> None:
        if not self.db.get(Product, product_id):
            raise NotFound("Producto no encontrado", code="product_not_found")
        if not self.repo.favorite(user.id, product_id):
            self.db.add(Favorite(user_id=user.id, product_id=product_id, created_at=now()))
            self.db.commit()

    def remove_favorite(self, user: User, product_id: uuid.UUID) -> None:
        fav = self.repo.favorite(user.id, product_id)
        if fav:
            self.db.delete(fav)
            self.db.commit()
