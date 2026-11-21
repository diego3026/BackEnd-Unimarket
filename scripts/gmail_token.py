"""Obtiene el GMAIL_REFRESH_TOKEN para enviar correos con tu cuenta de Gmail (una sola vez).

Pasos previos (5 minutos, gratis):
1. https://console.cloud.google.com → crea un proyecto → "APIs y servicios" → habilita "Gmail API".
2. "Pantalla de consentimiento de OAuth": tipo Externo, agrega tu correo como usuario de prueba
   y luego publícala ("En producción") para que el token no venza a los 7 días.
3. "Credenciales" → "Crear credenciales" → "ID de cliente de OAuth" → tipo "App de escritorio".
4. Ejecuta:  python -m scripts.gmail_token --client-id XXX --client-secret YYY

Abre el enlace, autoriza con la cuenta que enviará los correos y pega la URL a la que te
redirige (http://localhost/?code=...). El script imprime el refresh token.
"""

from __future__ import annotations

import argparse
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

SCOPE = "https://www.googleapis.com/auth/gmail.send"  # solo enviar, no leer tu correo
REDIRECT = "http://localhost"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-id", required=True)
    ap.add_argument("--client-secret", required=True)
    args = ap.parse_args()

    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
        {
            "client_id": args.client_id,
            "redirect_uri": REDIRECT,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    print("\n1) Abre este enlace y autoriza:\n\n" + url + "\n")
    pasted = input("2) Pega aquí la URL completa a la que te llevó (http://localhost/?code=...): ").strip()
    code = parse_qs(urlparse(pasted).query).get("code", [pasted])[0]
    r = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "redirect_uri": REDIRECT,
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    r.raise_for_status()
    token = r.json().get("refresh_token")
    if not token:
        raise SystemExit("Google no devolvió refresh_token. Revoca el acceso en tu cuenta y vuelve a intentarlo.")
    print("\nGMAIL_REFRESH_TOKEN=" + token + "\n\nGuárdalo como variable en Railway (no lo subas a GitHub).")


if __name__ == "__main__":
    main()
