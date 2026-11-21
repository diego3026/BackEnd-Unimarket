"""Dependencias comunes: sesión de BD, usuario autenticado y control de roles."""

from __future__ import annotations

import hmac
import uuid
from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, Query, Request, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import Forbidden, Unauthorized
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User
from app.models.enums import UserRole, UserStatus
from app.schemas.common import PageParams

bearer = HTTPBearer(auto_error=False, description="Access token del login")

DB = Annotated[Session, Depends(get_db)]

app_key_scheme = APIKeyHeader(
    name="X-App-Key",
    auto_error=False,
    description="Clave de la app UniMarket (la app la envía siempre)",
)


def require_app_key(key: Annotated[str | None, Security(app_key_scheme)] = None) -> None:
    """Solo la app (o quien tenga la clave) puede usar la API.

    La clave viaja dentro de la app, así que no es un secreto perfecto: frena bots,
    escáneres y uso casual. La protección real de los datos son el login, los roles
    y la verificación de propietario en cada endpoint.
    """
    keys = settings.app_key_list
    if not keys:
        return
    if key is None or not any(hmac.compare_digest(key.encode(), k.encode()) for k in keys):
        raise Forbidden("Cliente no autorizado", code="client_not_allowed")


def get_current_user(
    db: DB,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise Unauthorized("Inicia sesión para continuar", code="not_authenticated")
    try:
        payload = decode_access_token(creds.credentials)
        user_id = uuid.UUID(payload["sub"])
    except jwt.ExpiredSignatureError:
        raise Unauthorized("Tu sesión expiró", code="token_expired") from None
    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise Unauthorized("Sesión inválida", code="invalid_token") from None

    user = db.get(User, user_id)
    # token_version permite invalidar tokens al cambiar contraseña o suspender.
    if user is None or payload.get("ver") != user.token_version:
        raise Unauthorized("Sesión inválida", code="invalid_token")
    if user.status != UserStatus.active:
        raise Forbidden("Tu cuenta está suspendida", code="account_suspended")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[[User], User]:
    def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise Forbidden("No tienes permiso para esta acción", code="forbidden_role")
        return user

    return checker


Seller = Annotated[User, Depends(require_roles(UserRole.entrepreneur))]
Admin = Annotated[User, Depends(require_roles(UserRole.admin))]


def page_params(
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PageParams:
    return PageParams(page=page, size=size)


Paging = Annotated[PageParams, Depends(page_params)]


def user_agent(request: Request) -> str:
    return request.headers.get("user-agent", "")[:200]
