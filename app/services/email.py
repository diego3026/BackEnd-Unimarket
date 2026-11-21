"""Envío de correos por API HTTPS (Railway Hobby bloquea SMTP).

Proveedores (EMAIL_PROVIDER):
- console: solo se escribe en el log (desarrollo y pruebas).
- gmail:   Gmail API con tu propia cuenta de Gmail. No necesita dominio y Google
           firma el correo, así que llega a la bandeja de entrada. Límite ~500/día.
- brevo:   300 correos/día gratis. Sin dominio propio Brevo cambia el remitente
           a @brevosend.com (sirve, pero se ve menos confiable).
- resend:  3.000/mes gratis, pero exige dominio verificado para enviar a terceros.

Los correos salen en segundo plano para no hacer esperar al usuario.
"""

from __future__ import annotations

import base64
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from email.utils import parseaddr

import httpx

from app.core.config import settings

logger = logging.getLogger("unimarket.email")

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="email")
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class _GmailToken:
    """Access token de Gmail en caché (dura ~1 hora)."""

    _lock = threading.Lock()
    _token = ""
    _expires = 0.0

    @classmethod
    def get(cls) -> str:
        with cls._lock:
            if cls._token and time.time() < cls._expires - 60:
                return cls._token
            r = httpx.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": settings.gmail_client_id,
                    "client_secret": settings.gmail_client_secret,
                    "refresh_token": settings.gmail_refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=_TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
            cls._token = data["access_token"]
            cls._expires = time.time() + int(data.get("expires_in", 3600))
            return cls._token


def _send_gmail(to: str, subject: str, text: str, html: str | None) -> None:
    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = subject
    if settings.email_reply_to:
        msg["Reply-To"] = settings.email_reply_to
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    r = httpx.post(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        headers={"Authorization": f"Bearer {_GmailToken.get()}"},
        json={"raw": raw},
        timeout=_TIMEOUT,
    )
    r.raise_for_status()


def _send_brevo(to: str, subject: str, text: str, html: str | None) -> None:
    name, address = parseaddr(settings.email_from)
    body: dict = {
        "sender": {"name": name or "UniMarket", "email": address},
        "to": [{"email": to}],
        "subject": subject,
        "textContent": text,
    }
    if html:
        body["htmlContent"] = html
    if settings.email_reply_to:
        body["replyTo"] = {"email": settings.email_reply_to}
    r = httpx.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={"api-key": settings.brevo_api_key, "accept": "application/json"},
        json=body,
        timeout=_TIMEOUT,
    )
    r.raise_for_status()


def _send_resend(to: str, subject: str, text: str, html: str | None) -> None:
    body: dict = {"from": settings.email_from, "to": [to], "subject": subject, "text": text}
    if html:
        body["html"] = html
    if settings.email_reply_to:
        body["reply_to"] = settings.email_reply_to
    r = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {settings.resend_api_key}"},
        json=body,
        timeout=_TIMEOUT,
    )
    r.raise_for_status()


_PROVIDERS = {"gmail": _send_gmail, "brevo": _send_brevo, "resend": _send_resend}


def _deliver(to: str, subject: str, text: str, html: str | None) -> None:
    sender = _PROVIDERS.get(settings.email_provider)
    if sender is None:
        logger.info("Correo (consola) para %s: %s\n%s", to, subject, text)
        return
    for attempt in range(3):
        try:
            sender(to, subject, text, html)
            logger.info("Correo enviado (%s): %s", settings.email_provider, subject)
            return
        except httpx.HTTPStatusError as exc:
            # 4xx (salvo 429) no se arregla reintentando.
            if exc.response.status_code < 500 and exc.response.status_code != 429:
                logger.error("Proveedor de correo rechazó el envío: %s", exc.response.text[:300])
                return
        except httpx.HTTPError:
            pass
        time.sleep(2**attempt)
    logger.error("No se pudo enviar el correo '%s' tras 3 intentos", subject)


def send_email(to: str, subject: str, text: str, html: str | None = None) -> None:
    """Encola el correo y regresa de inmediato."""
    if settings.environment == "test":
        _deliver(to, subject, text, html)
        return
    _executor.submit(_deliver, to, subject, text, html)


def code_email(title: str, intro: str, code: str, minutes: int) -> tuple[str, str]:
    """Texto y HTML sencillos para correos con código de 6 dígitos."""
    text = f"{intro}\n\nTu código es: {code}\n\nVence en {minutes} minutos. Si no lo pediste, ignora este correo."
    html = f"""<div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;color:#1f1f29">
  <h2 style="color:#4320A2;margin-bottom:4px">UniMarket</h2>
  <p style="font-size:16px"><b>{title}</b></p>
  <p>{intro}</p>
  <p style="font-size:32px;letter-spacing:8px;font-weight:bold;background:#F4F1FB;
            padding:16px;text-align:center;border-radius:12px">{code}</p>
  <p style="color:#6b6b80;font-size:13px">Vence en {minutes} minutos. Si no lo pediste, ignora este correo.</p>
</div>"""
    return text, html
