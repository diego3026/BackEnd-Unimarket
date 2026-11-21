"""UniMarket API — punto de entrada.

Local:      uvicorn app.main:app --reload
Railway:    ver railway.json / Dockerfile (aplica migraciones y arranca uvicorn)
"""

from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.deps import require_app_key
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.middleware import RequestContextMiddleware
from app.core.rate_limit import limiter
from app.db.session import engine

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("unimarket")


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("UniMarket API iniciando (entorno=%s)", settings.environment)
    yield
    engine.dispose()


_docs_basic = HTTPBasic(realm="UniMarket docs")


def _check_docs_user(creds: Annotated[HTTPBasicCredentials, Depends(_docs_basic)]) -> None:
    """En producción /docs pide usuario y clave (DOCS_USERNAME / DOCS_PASSWORD)."""
    if not settings.is_production:
        return
    ok_user = hmac.compare_digest(creds.username.encode(), settings.docs_username.encode())
    ok_pass = hmac.compare_digest(creds.password.encode(), settings.docs_password.encode())
    if not (ok_user and ok_pass):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales inválidas", {"WWW-Authenticate": "Basic"})


def create_app() -> FastAPI:
    docs = settings.docs_available
    app = FastAPI(
        title=settings.app_name,
        version="2.0.0",
        description=(
            "API del marketplace de emprendedores de la Universidad del Magdalena.\n\n"
            "Autenticación: `Authorization: Bearer <accessToken>` (ver `/auth/login`)."
        ),
        lifespan=lifespan,
        # Las rutas de documentación se agregan abajo, protegidas en producción.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    # Orden: el último agregado es el primero en ejecutarse.
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
            max_age=600,
        )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)
    app.add_middleware(RequestContextMiddleware, hsts=settings.is_production)
    # Comprime respuestas JSON grandes (listas de productos): menos datos móviles y menos latencia.
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)

    register_exception_handlers(app)

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limited(_, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=429,
            content={"error": {"code": "rate_limited", "message": "Demasiados intentos. Espera un momento."}},
        )

    @app.middleware("http")
    async def _limit_body(request: Request, call_next):
        """Rechaza cuerpos gigantes antes de leerlos (las imágenes van a Cloudinary, no aquí)."""
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > settings.max_body_bytes:
            return JSONResponse(
                status_code=413,
                content={"error": {"code": "payload_too_large", "message": "La petición es demasiado grande"}},
            )
        return await call_next(request)

    # Toda la API exige la clave de la app (X-App-Key) si APP_CLIENT_KEYS está definida.
    app.include_router(api_router, prefix=settings.api_prefix, dependencies=[Depends(require_app_key)])

    if docs:
        guard = [Depends(_check_docs_user)] if settings.is_production else []

        @app.get("/openapi.json", include_in_schema=False, dependencies=guard)
        def openapi_json():
            return JSONResponse(app.openapi())

        @app.get("/docs", include_in_schema=False, dependencies=guard)
        def swagger():
            return get_swagger_ui_html(
                openapi_url="/openapi.json",
                title=f"{settings.app_name} · Docs",
                swagger_ui_parameters={"persistAuthorization": True, "displayRequestDuration": True},
            )

    if settings.enable_research_api:
        try:
            from research.router import research_router

            app.include_router(
                research_router, prefix=f"{settings.api_prefix}/research", dependencies=[Depends(require_app_key)]
            )
        except Exception:  # El módulo de investigación es opcional
            logger.exception("No se pudo cargar el módulo de investigación")

    @app.get("/health/live", tags=["Sistema"])
    def live():
        """Vivo (no toca la BD)."""
        return {"status": "ok"}

    @app.get("/health", tags=["Sistema"])
    def health():
        """Listo para atender: verifica la conexión con PostgreSQL (lo usa Railway)."""
        schema = None
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                try:
                    schema = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
                except Exception:
                    schema = None  # tablas sin crear: faltan las migraciones
            db_ok = True
        except Exception:
            db_ok = False
        ok = db_ok and schema is not None
        return JSONResponse(
            status_code=200 if ok else 503,
            content={"status": "ok" if ok else "degraded", "database": db_ok, "schema": schema},
        )

    @app.get("/", include_in_schema=False)
    def root():
        # No revela nada útil a quien escanee el dominio.
        return {"status": "ok"}

    return app


app = create_app()
