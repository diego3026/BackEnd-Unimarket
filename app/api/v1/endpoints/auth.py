from __future__ import annotations

from fastapi import APIRouter, Request, status

from app.api.deps import DB, CurrentUser, user_agent
from app.core.config import settings
from app.core.rate_limit import limiter
from app.schemas.auth import (
    ChangePasswordIn,
    ForgotPasswordIn,
    LoginIn,
    RefreshIn,
    RegisterIn,
    ResetPasswordIn,
    TokenPair,
    UpdateProfileIn,
    UserOut,
    VerifyEmailIn,
)
from app.schemas.common import Message
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["Autenticación"])
me_router = APIRouter(prefix="/me", tags=["Mi cuenta"])


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def register(request: Request, data: RegisterIn, db: DB):
    """Crea una cuenta de cliente e inicia sesión."""
    return AuthService(db).register(data, user_agent(request))


@router.post("/login", response_model=TokenPair)
@limiter.limit(settings.login_rate_limit)
def login(request: Request, data: LoginIn, db: DB):
    return AuthService(db).login(data, user_agent(request))


@router.post("/refresh", response_model=TokenPair)
@limiter.limit("30/minute")
def refresh(request: Request, data: RefreshIn, db: DB):
    """Cambia el refresh token por uno nuevo (el anterior deja de servir)."""
    return AuthService(db).refresh(data.refresh_token, user_agent(request))


@router.post("/logout", response_model=Message)
def logout(data: RefreshIn, db: DB):
    AuthService(db).logout(data.refresh_token)
    return Message(message="Sesión cerrada")


@router.post("/forgot-password", response_model=Message, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("3/minute")
def forgot_password(request: Request, data: ForgotPasswordIn, db: DB):
    AuthService(db).request_password_reset(data.email.lower())
    return Message(message="Si el correo está registrado, te enviamos las instrucciones")


@router.post("/reset-password", response_model=Message)
@limiter.limit("5/minute")
def reset_password(request: Request, data: ResetPasswordIn, db: DB):
    AuthService(db).reset_password(data)
    return Message(message="Contraseña actualizada. Inicia sesión de nuevo")


@router.post("/verify-email", response_model=Message)
@limiter.limit("10/minute")
def verify_email(request: Request, data: VerifyEmailIn, db: DB):
    AuthService(db).verify_email(data.token)
    return Message(message="Correo verificado")


# ------------------------------------------------------------------ /me
@me_router.get("", response_model=UserOut)
def me(user: CurrentUser, db: DB):
    return AuthService(db).me(user)


@me_router.patch("", response_model=UserOut)
def update_me(data: UpdateProfileIn, user: CurrentUser, db: DB):
    return AuthService(db).update_profile(user, data)


@me_router.post("/password", response_model=Message)
@limiter.limit("5/minute")
def change_password(request: Request, data: ChangePasswordIn, user: CurrentUser, db: DB):
    AuthService(db).change_password(user, data)
    return Message(message="Contraseña actualizada. Inicia sesión de nuevo")


@me_router.post("/logout-all", response_model=Message)
def logout_all(user: CurrentUser, db: DB):
    """Cierra la sesión en todos los dispositivos."""
    AuthService(db).logout_all(user)
    return Message(message="Cerraste sesión en todos tus dispositivos")


@me_router.post("/resend-verification", response_model=Message)
@limiter.limit("3/minute")
def resend_verification(request: Request, user: CurrentUser, db: DB):
    AuthService(db).resend_verification(user)
    return Message(message="Te enviamos un nuevo código")
