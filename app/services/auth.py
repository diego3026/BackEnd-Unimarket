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
    codes_match,
    create_access_token,
    hash_code,
    hash_password,
    hash_token,
    new_numeric_code,
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
from app.services.email import code_email, send_email
from app.services.media import validate_media_url
from app.services.pricing import now

logger = logging.getLogger("unimarket.auth")

INVALID_CREDENTIALS = "Correo o contraseña incorrectos"
INVALID_CODE = "El código no es válido"
MAX_CODE_ATTEMPTS = 5
RESET_MINUTES = 15
VERIFY_MINUTES = 30


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
        if data.avatar_url:
            validate_media_url(data.avatar_url, "avatar", user.id)
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

    # --- Correo y recuperación (códigos de 6 dígitos) ---------------------
    def request_password_reset(self, email: str) -> None:
        """Siempre responde igual, exista o no la cuenta (evita enumerar correos)."""
        user = self.users.by_email(email)
        if user is None or user.status != UserStatus.active:
            return
        code = self._new_code(user, TokenPurpose.reset_password, minutes=RESET_MINUTES)
        text, html = code_email(
            "Recupera tu contraseña",
            f"Hola {user.full_name.split()[0]}, escribe este código en la app para crear una nueva contraseña.",
            code,
            RESET_MINUTES,
        )
        self.db.commit()
        send_email(user.email, "Tu código para recuperar la contraseña", text, html)

    def reset_password(self, data: ResetPasswordIn) -> None:
        user = self.users.by_email(data.email)
        if user is None or user.status != UserStatus.active:
            raise Unauthorized(INVALID_CODE, code="invalid_code")
        self._consume_code(user, TokenPurpose.reset_password, data.code)
        user.password_hash = hash_password(data.new_password)
        user.token_version += 1
        self.tokens.revoke_user(user.id, now())
        self.db.commit()

    def verify_email(self, user: User, code: str) -> None:
        if user.email_verified:
            return
        self._consume_code(user, TokenPurpose.verify_email, code)
        user.email_verified = True
        self.db.commit()

    def resend_verification(self, user: User) -> None:
        if not user.email_verified:
            self._send_verification(user)

    # --- Internos ---------------------------------------------------------
    def _send_verification(self, user: User) -> None:
        code = self._new_code(user, TokenPurpose.verify_email, minutes=VERIFY_MINUTES)
        text, html = code_email(
            "Confirma tu correo",
            f"Hola {user.full_name.split()[0]}, bienvenido a UniMarket. Escribe este código en la app.",
            code,
            VERIFY_MINUTES,
        )
        self.db.commit()
        send_email(user.email, "Tu código de verificación de UniMarket", text, html)

    def _new_code(self, user: User, purpose: TokenPurpose, *, minutes: int) -> str:
        """Invalida los códigos anteriores y crea uno nuevo (solo se guarda su HMAC)."""
        current = now()
        self.tokens.void_codes(user.id, purpose, current)
        code = new_numeric_code()
        record_id = uuid.uuid4()
        self.db.add(
            OneTimeToken(
                id=record_id,
                user_id=user.id,
                purpose=purpose,
                token_hash=hash_code(str(record_id), code),
                expires_at=current + timedelta(minutes=minutes),
                created_at=current,
            )
        )
        return code

    def _consume_code(self, user: User, purpose: TokenPurpose, code: str) -> None:
        record = self.tokens.latest_code(user.id, purpose, now())
        if record is None:
            raise Unauthorized("El código venció. Pide uno nuevo.", code="code_expired")
        if not codes_match(record.token_hash, str(record.id), code):
            record.attempts += 1
            if record.attempts >= MAX_CODE_ATTEMPTS:
                record.used_at = now()  # se bloquea: hay que pedir otro
            self.db.commit()
            left = MAX_CODE_ATTEMPTS - record.attempts
            message = f"Código incorrecto. Te quedan {left} intentos." if left > 0 else "Pide un código nuevo."
            raise Unauthorized(message, code="invalid_code")
        record.used_at = now()

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
