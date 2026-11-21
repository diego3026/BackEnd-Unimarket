"""Imágenes y documentos en Cloudinary con subida firmada directa desde la app.

Por qué no en la base de datos: las imágenes inflarían PostgreSQL, harían más
lentas las copias de seguridad y cada foto pasaría por la API. Con subida
directa la app envía el archivo a Cloudinary (que tiene CDN y redimensiona),
y al backend solo llega la URL.

Flujo:
1. La app pide una firma: POST /uploads/sign {"purpose": "product"}.
2. Sube el archivo a `uploadUrl` con los `fields` devueltos (multipart).
3. Guarda la `secure_url` que responde Cloudinary en el producto/tienda/perfil.
   El backend verifica que la URL sea de nuestra cuenta y de la carpeta del usuario.

Los documentos (cédula, carné, RUT) se suben como `private`: no tienen URL pública
y el administrador los ve con un enlace temporal firmado.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Literal
from urllib.parse import urlencode

from app.core.config import settings
from app.core.errors import BusinessRuleError

Purpose = Literal["product", "store", "avatar", "document"]

IMAGE_FORMATS = "jpg,jpeg,png,webp,heic"
DOCUMENT_FORMATS = "jpg,jpeg,png,webp,pdf"


def _sign(params: dict[str, str | int]) -> str:
    """Firma de Cloudinary: SHA-1 de los parámetros ordenados + api_secret."""
    to_sign = "&".join(f"{k}={params[k]}" for k in sorted(params) if params[k] not in ("", None))
    return hashlib.sha1((to_sign + settings.cloudinary_api_secret).encode()).hexdigest()  # noqa: S324 (lo exige Cloudinary)


def folder_for(purpose: Purpose, user_id: uuid.UUID) -> str:
    return f"{settings.media_root_folder}/{purpose}/{user_id}"


def sign_upload(purpose: Purpose, user_id: uuid.UUID) -> dict:
    if not settings.media_enabled:
        raise BusinessRuleError("La subida de imágenes no está configurada en el servidor", code="media_disabled")
    is_doc = purpose == "document"
    params: dict[str, str | int] = {
        "folder": folder_for(purpose, user_id),
        "public_id": uuid.uuid4().hex,
        "timestamp": int(time.time()),
        "allowed_formats": DOCUMENT_FORMATS if is_doc else IMAGE_FORMATS,
        "overwrite": "false",
    }
    if is_doc:
        params["type"] = "private"
    resource = "auto" if is_doc else "image"
    return {
        "upload_url": f"https://api.cloudinary.com/v1_1/{settings.cloudinary_cloud_name}/{resource}/upload",
        "fields": {
            **{k: str(v) for k, v in params.items()},
            "api_key": settings.cloudinary_api_key,
            "signature": _sign(params),
        },
        "max_bytes": 10 * 1024 * 1024 if is_doc else 5 * 1024 * 1024,
        "expires_in": 3600,
    }


def validate_media_url(url: str | None, purpose: Purpose, user_id: uuid.UUID) -> None:
    """Rechaza URLs que no sean de nuestra cuenta de Cloudinary y de la carpeta del usuario.

    Sin Cloudinary configurado (desarrollo) se acepta cualquier URL https.
    """
    if not url:
        return
    if not settings.media_enabled:
        if not url.startswith("https://") and settings.is_production:
            raise BusinessRuleError("La imagen debe ser una URL https", code="invalid_media_url")
        return
    base = f"https://res.cloudinary.com/{settings.cloudinary_cloud_name}/"
    folder = folder_for(purpose, user_id) + "/"
    if not url.startswith(base) or folder not in url or ".." in url:
        raise BusinessRuleError("La imagen no se subió desde UniMarket", code="invalid_media_url")


def private_download_url(file_url: str, ttl_seconds: int = 300) -> str:
    """Enlace temporal para ver un documento privado (solo administradores)."""
    if not settings.media_enabled:
        return file_url
    marker = "/private/"
    if marker not in file_url:
        return file_url
    path = file_url.split(marker, 1)[1]  # v123/unimarket/document/<user>/<id>.pdf
    if path.startswith("v") and "/" in path and path.split("/", 1)[0][1:].isdigit():
        path = path.split("/", 1)[1]
    public_id, _, fmt = path.rpartition(".")
    resource = "image" if "/image/" in file_url else "raw"
    params: dict[str, str | int] = {
        "public_id": public_id,
        "format": fmt,
        "type": "private",
        "timestamp": int(time.time()),
        "expires_at": int(time.time()) + ttl_seconds,
    }
    query = urlencode({**params, "api_key": settings.cloudinary_api_key, "signature": _sign(params)})
    return f"https://api.cloudinary.com/v1_1/{settings.cloudinary_cloud_name}/{resource}/download?{query}"
