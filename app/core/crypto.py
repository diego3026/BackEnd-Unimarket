"""Cifrado simétrico (Fernet) para datos sensibles guardados en la BD."""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

# Solo para desarrollo y pruebas. En producción DATA_ENCRYPTION_KEY es obligatoria.
_DEV_KEY = b"uQqI-6Ly4qYYtyOn26F7dZEi3v-lmdH6mFTPY3AV4Tw="


@lru_cache
def _fernet() -> Fernet:
    key = settings.data_encryption_key.encode() if settings.data_encryption_key else _DEV_KEY
    return Fernet(key)


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return ""


def mask(value: str, visible: int = 4) -> str:
    if len(value) <= visible:
        return value
    return "•" * 4 + value[-visible:]
