"""Motor y sesiones de SQLAlchemy."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=10,  # si no hay conexión libre en 10 s, falla rápido en vez de colgarse
    pool_recycle=1800,
    connect_args={
        # Ninguna consulta puede tardar más de N ms ni quedarse en una transacción abierta.
        "options": f"-c statement_timeout={settings.db_statement_timeout_ms} "
        f"-c idle_in_transaction_session_timeout=30000",
        "application_name": "unimarket-api",
    },
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
