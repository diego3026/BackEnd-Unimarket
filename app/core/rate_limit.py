"""Límite de peticiones por IP (protege login, registro y recuperación)."""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import settings


def _client_ip(request: Request) -> str:
    # Railway pone la IP real del cliente en X-Forwarded-For.
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(
    key_func=_client_ip,
    default_limits=[settings.default_rate_limit],
    storage_uri=settings.rate_limit_storage_uri,
    enabled=settings.environment != "test",
    headers_enabled=False,
)
