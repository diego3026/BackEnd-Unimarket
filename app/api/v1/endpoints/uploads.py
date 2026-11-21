"""Firmas para subir imágenes y documentos directo a Cloudinary desde la app."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request

from app.api.deps import CurrentUser
from app.core.errors import Forbidden
from app.core.rate_limit import limiter
from app.models.enums import UserRole
from app.schemas.common import CamelModel, InputModel
from app.services.media import sign_upload

router = APIRouter(prefix="/uploads", tags=["Imágenes"])


class SignIn(InputModel):
    purpose: Literal["product", "store", "avatar", "document"]


class SignOut(CamelModel):
    upload_url: str
    fields: dict[str, str]
    max_bytes: int
    expires_in: int


@router.post("/sign", response_model=SignOut)
@limiter.limit("60/minute")
def sign(request: Request, data: SignIn, user: CurrentUser):
    """Devuelve la URL y los campos firmados para subir un archivo (multipart) a Cloudinary.

    Responde con `secure_url`; esa URL es la que se envía luego en `imageUrl`, `avatarUrl` o `fileUrl`.
    """
    if data.purpose in ("product", "document") and user.role != UserRole.entrepreneur:
        raise Forbidden("Solo los emprendedores pueden subir este tipo de archivo")
    return sign_upload(data.purpose, user.id)
