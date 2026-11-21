"""Configuración leída de variables de entorno (Railway, .env local)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- General -----------------------------------------------------------
    app_name: str = "UniMarket API"
    environment: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"

    # --- Base de datos -----------------------------------------------------
    # Railway entrega DATABASE_URL como postgres://... o postgresql://...
    database_url: str = "postgresql+psycopg://unimarket:unimarket@localhost:5432/unimarket"
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # --- Seguridad ---------------------------------------------------------
    # Clave para firmar los JWT. En producción debe ser larga y secreta.
    secret_key: str = Field(default="dev-only-change-me-dev-only-change-me", min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 30
    # Clave Fernet (base64, 32 bytes) para cifrar datos bancarios en la BD.
    # Se genera con: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    data_encryption_key: str = ""
    password_min_length: int = 8
    login_rate_limit: str = "10/minute"
    default_rate_limit: str = "240/minute"
    # memory:// sirve para una instancia. Con varias réplicas usa Redis: redis://default:clave@host:6379
    rate_limit_storage_uri: str = "memory://"

    # --- HTTP --------------------------------------------------------------
    # Lista separada por comas. La app móvil no usa CORS; esto es para web/admin.
    cors_origins: str = ""
    allowed_hosts: str = "*"
    enable_docs: bool = True

    # --- Negocio -----------------------------------------------------------
    # Si es True las tiendas nuevas quedan aprobadas sin revisión del admin.
    auto_approve_stores: bool = False
    # Expone los endpoints del proyecto de investigación (MOTOA/JROF) en /research.
    enable_research_api: bool = True

    # --- Correo (recuperar contraseña / verificar correo) -------------------
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "UniMarket <no-reply@unimarket.app>"
    frontend_reset_url: str = "unimarket://reset-password"

    # --- Administrador inicial (se crea al ejecutar scripts/seed.py) -------
    first_admin_email: str = ""
    first_admin_password: str = ""

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        # SQLAlchemy necesita indicar el driver psycopg 3.
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://") :]
        if v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v[len("postgresql://") :]
        return v

    @model_validator(mode="after")
    def _check_production(self) -> Settings:
        if self.environment == "production":
            if self.secret_key.startswith("dev-only"):
                raise ValueError("SECRET_KEY debe configurarse en producción")
            if not self.data_encryption_key:
                raise ValueError("DATA_ENCRYPTION_KEY debe configurarse en producción")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_host_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()] or ["*"]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
