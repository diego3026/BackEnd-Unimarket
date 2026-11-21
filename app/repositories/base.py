"""Repositorio genérico: acceso a datos sin reglas de negocio."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.db.base import Base

M = TypeVar("M", bound=Base)


class Repository(Generic[M]):
    model: type[M]

    def __init__(self, db: Session):
        self.db = db

    def get(self, id_: Any) -> M | None:
        return self.db.get(self.model, id_)

    def get_for_update(self, id_: Any) -> M | None:
        return self.db.get(self.model, id_, with_for_update=True)

    def add(self, obj: M) -> M:
        self.db.add(obj)
        self.db.flush()
        return obj

    def delete(self, obj: M) -> None:
        self.db.delete(obj)
        self.db.flush()

    def paginate(self, stmt: Select, *, offset: int, limit: int) -> tuple[list, int]:
        total = self.db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
        items = list(self.db.scalars(stmt.offset(offset).limit(limit)))
        return items, total
