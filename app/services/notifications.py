"""Notificaciones dentro de la app (y punto único para agregar push en el futuro)."""

from __future__ import annotations

import uuid

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.models import Notification
from app.repositories.base import Repository
from app.repositories.repos import AccountRepo
from app.schemas.common import Page, PageParams
from app.services import mappers
from app.services.pricing import now


def notify(
    db: Session, user_id: uuid.UUID, *, type_: str, title: str, body: str = "", data: dict | None = None
) -> None:
    db.add(Notification(user_id=user_id, type=type_, title=title, body=body, data=data or {}, created_at=now()))


class NotificationService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AccountRepo(db)

    def list(self, user_id: uuid.UUID, page: PageParams) -> Page:
        stmt = self.repo.notifications(user_id)
        items, total = Repository(self.db).paginate(stmt, offset=page.offset, limit=page.size)
        return Page(items=[mappers.notification_out(n) for n in items], total=total, page=page.page, size=page.size)

    def unread(self, user_id: uuid.UUID) -> int:
        return self.repo.unread_count(user_id)

    def mark_read(self, user_id: uuid.UUID, notification_id: uuid.UUID) -> None:
        n = self.db.get(Notification, notification_id)
        if not n or n.user_id != user_id:
            raise NotFound("Notificación no encontrada")
        if n.read_at is None:
            n.read_at = now()
        self.db.commit()

    def mark_all_read(self, user_id: uuid.UUID) -> None:
        self.db.execute(
            update(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
            .values(read_at=now())
        )
        self.db.commit()
