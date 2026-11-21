from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk, utcnow
from app.models.enums import TokenPurpose, UserRole, UserStatus

if TYPE_CHECKING:
    from app.models.store import Store


def _enum(e):
    return Enum(e, native_enum=False, length=20, values_callable=lambda x: [m.value for m in x])


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    full_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(20), default="")
    avatar_url: Mapped[str] = mapped_column(String(500), default="")
    role: Mapped[UserRole] = mapped_column(_enum(UserRole), default=UserRole.consumer, index=True)
    status: Mapped[UserStatus] = mapped_column(_enum(UserStatus), default=UserStatus.active)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    # Se incrementa al cambiar la contraseña o al suspender: invalida todos los tokens.
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Bloqueo temporal tras varios intentos fallidos de login
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    store: Mapped[Store | None] = relationship(back_populates="owner", uselist=False)


class RefreshToken(UUIDPk, Base):
    """Refresh tokens rotativos. Si se reutiliza uno ya usado se revoca la familia."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_family", "family_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    user_agent: Mapped[str] = mapped_column(String(200), default="")


class OneTimeToken(UUIDPk, Base):
    """Códigos de 6 dígitos para verificar el correo y recuperar la contraseña."""

    __tablename__ = "one_time_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[TokenPurpose] = mapped_column(_enum(TokenPurpose))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
