"""Billetera, direcciones, favoritos y notificaciones del usuario."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import DB, CurrentUser, Paging
from app.schemas.account import (
    AddressIn,
    AddressOut,
    NotificationOut,
    PaymentMethodIn,
    PaymentMethodOut,
    UnreadCountOut,
)
from app.schemas.common import Page
from app.schemas.product import ProductOut
from app.services.account import AccountService
from app.services.notifications import NotificationService

router = APIRouter(prefix="/me", tags=["Mi cuenta"])

NO_CONTENT = status.HTTP_204_NO_CONTENT


@router.get("/payment-methods", response_model=list[PaymentMethodOut])
def cards(user: CurrentUser, db: DB):
    return AccountService(db).cards(user)


@router.post("/payment-methods", response_model=PaymentMethodOut, status_code=status.HTTP_201_CREATED)
def add_card(data: PaymentMethodIn, user: CurrentUser, db: DB):
    """Guarda una tarjeta ya tokenizada por la pasarela (nunca el número completo)."""
    return AccountService(db).add_card(user, data)


@router.post("/payment-methods/{card_id}/default", response_model=PaymentMethodOut)
def default_card(card_id: uuid.UUID, user: CurrentUser, db: DB):
    return AccountService(db).set_default_card(user, card_id)


@router.delete("/payment-methods/{card_id}", status_code=NO_CONTENT)
def delete_card(card_id: uuid.UUID, user: CurrentUser, db: DB):
    AccountService(db).delete_card(user, card_id)
    return Response(status_code=NO_CONTENT)


@router.get("/addresses", response_model=list[AddressOut])
def addresses(user: CurrentUser, db: DB):
    return AccountService(db).addresses(user)


@router.post("/addresses", response_model=AddressOut, status_code=status.HTTP_201_CREATED)
def add_address(data: AddressIn, user: CurrentUser, db: DB):
    return AccountService(db).add_address(user, data)


@router.put("/addresses/{address_id}", response_model=AddressOut)
def update_address(address_id: uuid.UUID, data: AddressIn, user: CurrentUser, db: DB):
    return AccountService(db).update_address(user, address_id, data)


@router.delete("/addresses/{address_id}", status_code=NO_CONTENT)
def delete_address(address_id: uuid.UUID, user: CurrentUser, db: DB):
    AccountService(db).delete_address(user, address_id)
    return Response(status_code=NO_CONTENT)


@router.get("/favorites", response_model=list[ProductOut])
def favorites(user: CurrentUser, db: DB):
    return AccountService(db).favorites(user)


@router.put("/favorites/{product_id}", status_code=NO_CONTENT)
def add_favorite(product_id: uuid.UUID, user: CurrentUser, db: DB):
    AccountService(db).add_favorite(user, product_id)
    return Response(status_code=NO_CONTENT)


@router.delete("/favorites/{product_id}", status_code=NO_CONTENT)
def remove_favorite(product_id: uuid.UUID, user: CurrentUser, db: DB):
    AccountService(db).remove_favorite(user, product_id)
    return Response(status_code=NO_CONTENT)


@router.get("/notifications", response_model=Page[NotificationOut])
def notifications(user: CurrentUser, db: DB, paging: Paging):
    return NotificationService(db).list(user.id, paging)


@router.get("/notifications/unread-count", response_model=UnreadCountOut)
def unread_count(user: CurrentUser, db: DB):
    return UnreadCountOut(unread=NotificationService(db).unread(user.id))


@router.post("/notifications/{notification_id}/read", status_code=NO_CONTENT)
def mark_read(notification_id: uuid.UUID, user: CurrentUser, db: DB):
    NotificationService(db).mark_read(user.id, notification_id)
    return Response(status_code=NO_CONTENT)


@router.post("/notifications/read-all", status_code=NO_CONTENT)
def mark_all_read(user: CurrentUser, db: DB):
    NotificationService(db).mark_all_read(user.id)
    return Response(status_code=NO_CONTENT)
