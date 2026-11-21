"""Contraseñas (bcrypt), tokens JWT y tokens opacos de un solo uso."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

ACCESS = "access"


def hash_password(password: str) -> str:
    # bcrypt solo usa los primeros 72 bytes; se valida la longitud en los schemas.
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


# Hash fijo para igualar el tiempo de respuesta cuando el correo no existe.
DUMMY_HASH = hash_password("dummy-password-for-timing")


def create_access_token(user_id: uuid.UUID, role: str, token_version: int) -> tuple[str, int]:
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=settings.access_token_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "ver": token_version,
        "type": ACCESS,
        "iat": now,
        "exp": expires,
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return token, settings.access_token_minutes * 60


def decode_access_token(token: str) -> dict[str, Any]:
    payload = jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub", "type"]},
    )
    if payload.get("type") != ACCESS:
        raise jwt.InvalidTokenError("Tipo de token inválido")
    return payload


def new_opaque_token() -> str:
    """Token aleatorio para refresh, verificación de correo y recuperación."""
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """En la BD solo se guarda el SHA-256 del token, nunca el token."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_numeric_code(digits: int = 6) -> str:
    return f"{secrets.randbelow(10**digits):0{digits}d}"


def hash_code(scope: str, code: str) -> str:
    """HMAC con la clave del servidor: un código de 6 dígitos no se puede
    adivinar desde la BD aunque alguien la copie."""
    return hmac.new(settings.secret_key.encode(), f"{scope}:{code}".encode(), hashlib.sha256).hexdigest()


def codes_match(expected_hash: str, scope: str, code: str) -> bool:
    return hmac.compare_digest(expected_hash, hash_code(scope, code))


def new_pickup_code() -> str:
    return f"{secrets.randbelow(10_000):04d}"
