"""Envío de correos. Sin SMTP configurado solo se registra en el log (desarrollo)."""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger("unimarket.email")


def send_email(to: str, subject: str, body: str) -> None:
    if not settings.smtp_host:
        if settings.is_production:
            logger.warning("SMTP no configurado: no se envió el correo '%s'", subject)
        else:
            logger.info("Correo (simulado) para %s: %s\n%s", to, subject, body)
        return
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
    except Exception:  # El fallo del correo no debe tumbar la petición
        logger.exception("No se pudo enviar el correo a %s", to)
