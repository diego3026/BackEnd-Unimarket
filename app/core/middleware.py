"""Middlewares: id de petición, cabeceras de seguridad, caché HTTP/ETag y logs."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
import uuid
from collections import OrderedDict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings

logger = logging.getLogger("unimarket.http")

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}

# Lecturas públicas iguales para todos: se pueden guardar en caché unos segundos
# (en la app, en proxies y en un CDN si se agrega). Reduce mucho la carga.
_PUBLIC_PREFIXES = ("/categories", "/campus/", "/stores", "/products", "/promotions/")
_MAX_ETAG_BODY = 1024 * 1024


class _MicroCache:
    """Caché en memoria (por proceso) de respuestas públicas durante pocos segundos.

    Cuando muchos usuarios abren Inicio o buscan lo mismo a la vez, solo la primera
    petición llega a la BD; las demás se responden desde memoria. Los datos pueden
    tener como máximo `ttl` segundos de atraso (igual que el Cache-Control público).
    """

    def __init__(self, max_items: int = 512):
        self.max_items = max_items
        self._data: OrderedDict[str, tuple[float, bytes, dict]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> tuple[bytes, dict] | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expires, body, headers = item
            if expires < time.monotonic():
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return body, headers

    def set(self, key: str, body: bytes, headers: dict, ttl: float) -> None:
        with self._lock:
            self._data[key] = (time.monotonic() + ttl, body, headers)
            self._data.move_to_end(key)
            while len(self._data) > self.max_items:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


micro_cache = _MicroCache()


def _is_public(path: str) -> bool:
    rel = path.removeprefix(settings.api_prefix)
    return rel.startswith(_PUBLIC_PREFIXES)


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, hsts: bool = False):
        super().__init__(app)
        self.hsts = hsts

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        if len(request_id) > 64:
            request_id = uuid.uuid4().hex
        request.state.request_id = request_id
        start = time.perf_counter()
        path = request.url.path

        cache_key = self._cache_key(request, path)
        cached = micro_cache.get(cache_key) if cache_key else None
        if cached is not None:
            body, headers = cached
            if headers.get("ETag") and headers["ETag"] in request.headers.get("if-none-match", ""):
                response = Response(status_code=304, headers=headers)
            else:
                response = Response(content=body, status_code=200, headers=headers, media_type="application/json")
            response.headers["X-Cache"] = "HIT"
        else:
            response = await call_next(request)
            if path.startswith("/api/"):
                response = await self._http_cache(request, response, path, cache_key)

        elapsed = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["Server-Timing"] = f"app;dur={elapsed:.1f}"
        for k, v in _SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if self.hsts:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        level = logging.WARNING if elapsed > 1000 else logging.INFO
        logger.log(level, "%s %s %s %.1fms rid=%s", request.method, path, response.status_code, elapsed, request_id)
        return response

    @staticmethod
    def _cache_key(request: Request, path: str) -> str | None:
        ttl = settings.public_cache_seconds
        if ttl <= 0 or request.method != "GET" or "authorization" in request.headers or not _is_public(path):
            return None
        return f"{path}?{request.url.query}"

    async def _http_cache(self, request: Request, response: Response, path: str, cache_key: str | None) -> Response:
        """Cache-Control + ETag. Con `If-None-Match` la app recibe 304 sin cuerpo cuando
        nada cambió (ideal para revisar el estado de un pedido cada pocos segundos)."""
        if request.method != "GET" or response.status_code != 200:
            response.headers.setdefault("Cache-Control", "no-store")
            return response

        public = _is_public(path) and "authorization" not in request.headers
        if public:
            max_age = settings.public_cache_seconds
            cache_control = f"public, max-age={max_age}, stale-while-revalidate={max_age * 2}"
        else:
            cache_control = "private, no-cache"

        if not response.headers.get("content-type", "").startswith("application/json"):
            response.headers["Cache-Control"] = cache_control
            return response

        body = b""
        async for chunk in response.body_iterator:  # type: ignore[attr-defined]
            body += chunk
        headers = {k: v for k, v in response.headers.items() if k.lower() not in ("content-length", "content-type")}
        headers["Cache-Control"] = cache_control
        if not public:
            headers["Vary"] = "Authorization"
        if len(body) <= _MAX_ETAG_BODY:
            etag = 'W/"' + hashlib.blake2b(body, digest_size=12).hexdigest() + '"'
            headers["ETag"] = etag
            if cache_key:
                micro_cache.set(cache_key, body, dict(headers), ttl=max(1, settings.public_cache_seconds // 2))
            if etag in request.headers.get("if-none-match", ""):
                return Response(status_code=304, headers=headers)
        return Response(content=body, status_code=200, headers=headers, media_type="application/json")
