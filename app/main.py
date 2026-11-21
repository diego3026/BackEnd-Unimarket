"""UniMarket API — punto de entrada.

Local:      uvicorn app.main:app --reload
Railway:    ver railway.json / Dockerfile (aplica migraciones y arranca uvicorn)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from starlette.responses import JSONResponse

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


def create_app() -> FastAPI:
    docs = settings.enable_docs
    app = FastAPI(
        title=settings.app_name,
        version="2.0.0",
        description=(
            "API del marketplace de emprendedores de la Universidad del Magdalena.\n\n"
            "Autenticación: `Authorization: Bearer <accessToken>` (ver `/auth/login`)."
        ),
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
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

    register_exception_handlers(app)

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limited(_, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=429,
            content={"error": {"code": "rate_limited", "message": "Demasiados intentos. Espera un momento."}},
        )

    app.include_router(api_router, prefix=settings.api_prefix)

    if settings.enable_research_api:
        try:
            from research.router import research_router

            app.include_router(research_router, prefix=f"{settings.api_prefix}/research")
        except Exception:  # El módulo de investigación es opcional
            logger.exception("No se pudo cargar el módulo de investigación")

    @app.get("/health", tags=["Sistema"])
    def health():
        """Railway usa este endpoint para saber si el servicio está vivo."""
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            db_ok = True
        except Exception:
            db_ok = False
        return JSONResponse(
            status_code=200 if db_ok else 503,
            content={"status": "ok" if db_ok else "degraded", "database": db_ok},
        )

    @app.get("/", include_in_schema=False)
    def root():
        return {"name": settings.app_name, "docs": "/docs" if docs else None}

    return app


app = create_app()
