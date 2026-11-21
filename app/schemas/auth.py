from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import EmailStr, Field, field_validator

from app.core.config import settings
from app.models.enums import UserRole, UserStatus
from app.schemas.common import CamelModel, InputModel

_PHONE = re.compile(r"^3\d{9}$")  # Celular colombiano: 10 dígitos que empiezan por 3


def _check_password(v: str) -> str:
    if len(v) < settings.password_min_length:
        raise ValueError(f"La contraseña debe tener al menos {settings.password_min_length} caracteres")
    if len(v.encode()) > 72:
        raise ValueError("La contraseña es demasiado larga")
    if not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
        raise ValueError("La contraseña debe tener letras y números")
    return v


def _check_phone(v: str) -> str:
    digits = re.sub(r"\D", "", v)
    if digits.startswith("57") and len(digits) == 12:
        digits = digits[2:]
    if not _PHONE.match(digits):
        raise ValueError("Teléfono inválido (10 dígitos)")
    return digits


class RegisterIn(InputModel):
    full_name: str = Field(min_length=3, max_length=120)
    email: EmailStr
    phone: str
    password: str
    accept_terms: bool

    _pw = field_validator("password")(_check_password)
    _ph = field_validator("phone")(_check_phone)

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.lower()

    @field_validator("accept_terms")
    @classmethod
    def _terms(cls, v: bool) -> bool:
        if not v:
            raise ValueError("Debes aceptar los términos y condiciones")
        return v


class LoginIn(InputModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.lower()


class RefreshIn(InputModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class UserOut(CamelModel):
    id: uuid.UUID
    email: str
    full_name: str
    phone: str
    avatar_url: str
    role: UserRole
    status: UserStatus
    email_verified: bool
    store_id: uuid.UUID | None = None
    created_at: datetime


class TokenPair(CamelModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class ForgotPasswordIn(InputModel):
    email: EmailStr


class ResetPasswordIn(InputModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")
    new_password: str

    _pw = field_validator("new_password")(_check_password)


class ChangePasswordIn(InputModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str

    _pw = field_validator("new_password")(_check_password)


class VerifyEmailIn(InputModel):
    code: str = Field(pattern=r"^\d{6}$")


class UpdateProfileIn(InputModel):
    full_name: str | None = Field(None, min_length=3, max_length=120)
    phone: str | None = None
    avatar_url: str | None = Field(None, max_length=500)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return None if v is None else _check_phone(v)
