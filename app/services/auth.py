"""Registro, login, refresh rotativo, verificación de correo y contraseñas."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import Conflict, Forbidden, Unauthorized
from app.core.security import (
    DUMMY_HASH,
    create_access_token,
    hash_password,
    hash_token,
    new_opaque_token,
    verify_password,
)
from app.models import OneTimeToken, RefreshToken, User
from app.models.enums import TokenPurpose, UserStatus
from app.repositories.repos import StoreRepo, TokenRepo, UserRepo
from app.schemas.auth import (
    ChangePasswordIn,
    LoginIn,
    RegisterIn,
    ResetPasswordIn,
    TokenPair,
    UpdateProfileIn,
)
from app.services import mappers
from app.services.email import send_email
from app.services.pricing import now

logger = logging.getLogger("unimarket.auth")

INVALID_CREDENTIALS = "Correo o contraseña incorrectos"


def _aware(dt):
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.users = UserRepo(db)
        self.tokens = TokenRepo(db)

    # --- Registro y login -------------------------------------------------
    def register(self, data: RegisterIn, user_agent: str = "") -> TokenPair:
        if self.users.by_email(data.email):
            raise Conflict("Ya existe una cuenta con ese correo", code="email_taken")
        user = User(
            email=data.email,
            password_hash=hash_password(data.password),
            full_name=data.full_name,
            phone=data.phone,
        )
        try:
            self.users.add(user)
        except IntegrityError:
            self.db.rollback()
            raise Conflict("Ya existe una cuenta con ese correo", code="email_taken") from None
        self._send_verification(user)
        pair = self._issue(user, user_agent=user_agent)
        self.db.commit()
        return pair

    def login(self, data: LoginIn, user_agent: str = "") -> TokenPair:
        user = self.users.by_email(data.email)
        if user is None:
            verify_password(data.password, DUMMY_HASH)  # mismo tiempo de respuesta
            raise Unauthorized(INVALID_CREDENTIALS, code="invalid_credentials")
        if not verify_password(data.password, user.password_hash):
            logger.info("Intento de login fallido para user=%s", user.id)
            raise Unauthorized(INVALID_CREDENTIALS, code="invalid_credentials")
        if user.status != UserStatus.active:
            raise Forbidden("Tu cuenta está suspendida. Escríbenos a soporte.", code="account_suspended")
        user.last_login_at = now()
        pair = self._issue(user, user_agent=user_agent)
        self.db.commit()
        return pair

    def refresh(self, refresh_token: str, user_agent: str = "") -> TokenPair:
        record = self.tokens.refresh_by_hash(hash_token(refresh_token))
        if record is None:
            raise Unauthorized("Sesión inválida", code="invalid_refresh")
        current = now()
        if record.revoked_at is not None:
            # Reutilización de un token ya rotado: posible robo. Se cierra toda la familia.
            logger.warning("Reutilización de refresh token detectada user=%s", record.user_id)
            self.tokens.revoke_family(record.family_id, current)
            self.db.commit()
            raise Unauthorized("Sesión inválida", code="invalid_refresh")
        if _aware(record.expires_at) <= current:
            raise Unauthorized("La sesión expiró, inicia sesión de nuevo", code="refresh_expired")
        user = self.users.get(record.user_id)
        if user is None or user.status != UserStatus.active:
            self.tokens.revoke_family(record.family_id, current)
            self.db.commit()
            raise Unauthorized("Sesión inválida", code="invalid_refresh")
        pair, new_record = self._issue(user, family_id=record.family_id, user_agent=user_agent, return_record=True)
        record.revoked_at = current
        record.replaced_by = new_record.id
        self.db.commit()
        return pair

    def logout(self, refresh_token: str) -> None:
        record = self.tokens.refresh_by_hash(hash_token(refresh_token))
        if record is not None:
            self.tokens.revoke_family(record.family_id, now())
            self.db.commit()

    def logout_all(self, user: User) -> None:
        user.token_version += 1
        self.tokens.revoke_user(user.id, now())
        self.db.commit()

    # --- Perfil -----------------------------------------------------------
    def me(self, user: User) -> mappers.UserOut:
        store = StoreRepo(self.db).by_owner(user.id)
        return mappers.user_out(user, store.id if store else None)

    def update_profile(self, user: User, data: UpdateProfileIn) -> mappers.UserOut:
        for field, value in data.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(user, field, value)
        self.db.commit()
        return self.me(user)

    def change_password(self, user: User, data: ChangePasswordIn) -> None:
        if not verify_password(data.current_password, user.password_hash):
            raise Unauthorized("La contraseña actual no es correcta", code="invalid_credentials")
        user.password_hash = hash_password(data.new_password)
        user.token_version += 1  # invalida los access tokens emitidos
        self.tokens.revoke_user(user.id, now())
        self.db.commit()

    # --- Correo y recuperación ---------------------------------------------
    def request_password_reset(self, email: str) -> None:
        """Siempre responde igual, exista o no la cuenta (evita enumerar correos)."""
        user = self.users.by_email(email)
        if user is None or user.status != UserStatus.active:
            return
        token = self._one_time(user, TokenPurpose.reset_password, minutes=30)
        send_email(
            user.email,
            "Recupera tu contraseña de UniMarket",
            f"Hola {user.full_name},\n\nUsa este enlace para crear una nueva contraseña "
            f"(vence en 30 minutos):\n{settings.frontend_reset_url}?token={token}\n\n"
            "Si no lo pediste, ignora este correo.",
        )
        self.db.commit()

    def reset_password(self, data: ResetPasswordIn) -> None:
        record = self._consume(data.token, TokenPurpose.reset_password)
        user = self.users.get(record.user_id)
        if user is None:
            raise Unauthorized("El enlace no es válido o ya venció", code="invalid_token")
        user.password_hash = hash_password(data.new_password)
        user.token_version += 1
        self.tokens.revoke_user(user.id, now())
        self.db.commit()

    def verify_email(self, token: str) -> None:
        record = self._consume(token, TokenPurpose.verify_email)
        user = self.users.get(record.user_id)
        if user:
            user.email_verified = True
        self.db.commit()

    def resend_verification(self, user: User) -> None:
        if not user.email_verified:
            self._send_verification(user)
            self.db.commit()

    # --- Internos ---------------------------------------------------------
    def _send_verification(self, user: User) -> None:
        token = self._one_time(user, TokenPurpose.verify_email, minutes=60 * 24)
        send_email(
            user.email,
            "Confirma tu correo en UniMarket",
            f"Hola {user.full_name},\n\nTu código de verificación es:\n{token}\n\nVence en 24 horas.",
        )

    def _one_time(self, user: User, purpose: TokenPurpose, *, minutes: int) -> str:
        token = new_opaque_token()
        self.db.add(
            OneTimeToken(
                user_id=user.id,
                purpose=purpose,
                token_hash=hash_token(token),
                expires_at=now() + timedelta(minutes=minutes),
                created_at=now(),
            )
        )
        return token

    def _consume(self, token: str, purpose: TokenPurpose) -> OneTimeToken:
        record = self.tokens.one_time(hash_token(token))
        if (
            record is None
            or record.purpose != purpose
            or record.used_at is not None
            or _aware(record.expires_at) <= now()
        ):
            raise Unauthorized("El enlace no es válido o ya venció", code="invalid_token")
        record.used_at = now()
        return record

    def _issue(
        self, user: User, *, family_id: uuid.UUID | None = None, user_agent: str = "", return_record: bool = False
    ):
        access, expires_in = create_access_token(user.id, user.role.value, user.token_version)
        refresh = new_opaque_token()
        record = RefreshToken(
            user_id=user.id,
            token_hash=hash_token(refresh),
            family_id=family_id or uuid.uuid4(),
            expires_at=now() + timedelta(days=settings.refresh_token_days),
            created_at=now(),
            user_agent=user_agent[:200],
        )
        self.db.add(record)
        self.db.flush()
        store = StoreRepo(self.db).by_owner(user.id)
        pair = TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_in=expires_in,
            user=mappers.user_out(user, store.id if store else None),
        )
        return (pair, record) if return_record else pair
