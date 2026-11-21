# Servicios externos: qué usamos y por qué

Criterio: gratis o casi gratis al empezar, seguro y que funcione desde Railway (plan Hobby).
Precios revisados en noviembre de 2026; confírmalos en la página de cada proveedor antes de contratar.

---

## 1. Pagos

### Lo que ya funciona (sin comisión)

| Medio | Cómo funciona en UniMarket | Costo |
|---|---|---|
| **Efectivo** | Se paga al recoger o recibir. La tienda lo marca pagado al entregar. | $0 |
| **Bre-B** (`breb`) | El emprendedor registra su **llave Bre-B** en "Configurar tienda". Al pedir, la app muestra la llave, el titular y el valor (`payTo`). El cliente transfiere desde la app de su banco o billetera, toca "Ya pagué" y la tienda confirma cuando ve el dinero. | $0 para personas (plan básico de su entidad) |
| **Nequi** (`nequi`) | Igual que Bre-B, con el número de Nequi del emprendedor. | $0 |

Por qué así: es como ya se pagan los estudiantes en el campus, el dinero llega **directo** al emprendedor
(UniMarket nunca lo recibe ni lo guarda) y no hay datos de tarjetas que proteger.

Flujo en la API:

```
POST /orders {paymentKind: "breb"}            → respuesta trae payTo {key, holderName, amount, referenceHint}
POST /orders/{id}/payment-report {reference}   → paymentStatus = reported, la tienda recibe aviso
POST /seller/orders/{id}/payment-confirm {received: true|false} → paid | failed (el cliente recibe aviso)
```

### Para tarjetas (siguiente fase): Mercado Pago "Split de Pagos 1:1"

| Opción | Tarjeta online | Ventaja para un marketplace | Desventaja |
|---|---|---|---|
| **Mercado Pago** (recomendado) | ≈2,99 % + IVA + $700 crédito; ≈2,69 % débito | **Split 1:1 disponible en Colombia**: cada emprendedor conecta su cuenta (OAuth) y el pago le llega directo; UniMarket puede cobrar una comisión (`marketplace_fee`). Persona natural con cédula puede tener cuenta. | El retiro a banco puede tardar si no se paga por retiro inmediato. |
| Wompi (Bancolombia) | 2,65 % + $700 + IVA | QR al 1 % + IVA, PSE y Nequi integrados, buena API. | No reparte el pago entre vendedores: UniMarket tendría que recibir todo y luego dispersar, lo que exige empresa (NIT) y obligaciones tributarias. |
| ePayco / PayU / Bold | ≈2,8 %–3,5 % + IVA + $700 | Muchos medios de pago. | Mismo problema de dispersión que Wompi para varios vendedores. |

Ninguna pasarela es gratis: todas cobran por transacción aprobada. Para pedidos pequeños (un
sándwich de $9.000) el cargo fijo de $700 pesa casi 8 %, por eso Bre-B/Nequi son la opción principal
y la tarjeta queda como opcional. La tarjeta está **desactivada** (`CARD_PAYMENT_PROVIDER` vacío) hasta
integrar Mercado Pago; el código ya está preparado para agregarlo como proveedor.

Seguridad cuando se active: la app tokeniza la tarjeta con el SDK de Mercado Pago (los datos nunca
pasan por nuestro backend), el estado del pago se confirma **solo** por webhook firmado y consultando
la API de Mercado Pago, nunca por lo que diga la app.

---

## 2. Imágenes y documentos: Cloudinary (plan gratis)

¿Guardarlas en la base de datos? **No**: inflan PostgreSQL (más costo y copias de seguridad lentas),
cada foto pasaría por la API (más latencia y CPU) y no hay CDN ni redimensionado.

| Opción | Gratis | Por qué sí / por qué no |
|---|---|---|
| **Cloudinary** (elegido) | 25 créditos/mes sin tarjeta (p. ej. ~10 GB de almacenamiento + ~10 GB de descarga + miles de transformaciones) | CDN, redimensiona y convierte a WebP al vuelo (`/w_400,f_auto/`), subida firmada directa desde la app y documentos privados. |
| Cloudflare R2 | 10 GB y descargas sin costo | Muy barato al crecer, pero no redimensiona y pide tarjeta para activarse. Buena opción si se supera Cloudinary. |
| Volumen de Railway / BD | — | Se paga por GB, sin CDN; el disco del contenedor se borra en cada despliegue. |

Cómo quedó:

1. La app pide `POST /uploads/sign {purpose: product|store|avatar|document}`.
2. Sube el archivo directo a Cloudinary con los campos firmados (la firma vence en 1 hora y fija la
   carpeta, el nombre y los formatos permitidos; no se puede reutilizar para otra carpeta).
3. Envía la `secure_url` en `imageUrl` / `avatarUrl` / `fileUrl`. El backend rechaza URLs que no sean de
   nuestra cuenta **y** de la carpeta de ese usuario.
4. Documentos (cédula, carné, RUT) se suben como **privados**; el admin los ve con
   `GET /admin/documents/{id}/file`, que da un enlace de 5 minutos y queda en la bitácora.

Configurar: crear cuenta en cloudinary.com → Dashboard → copiar *Cloud name*, *API Key* y *API Secret*
a las variables `CLOUDINARY_*`.

Para mostrar miniaturas en la app basta con insertar la transformación en la URL:
`…/image/upload/w_400,h_400,c_fill,f_auto,q_auto/v123/unimarket/product/...jpg`.

---

## 3. Correo sin dominio propio

Railway (planes Free/Hobby) **bloquea SMTP**; hay que enviar por API HTTPS.

| Opción | Gratis | ¿Sirve sin dominio? |
|---|---|---|
| **Gmail API** con tu cuenta (elegido) | ~500 correos/día | **Sí.** Google firma el correo como tu Gmail, así que llega a la bandeja de entrada. Solo pide permiso de *enviar* (no lee tu correo). |
| Brevo | 300/día | A medias: con remitente @gmail.com Brevo lo cambia a `@brevosend.com` para no ser rechazado. Funciona, pero se ve poco confiable. |
| Resend | 3.000/mes (100/día) | **No**: sin dominio verificado solo envía a tu propio correo. |

Configurar Gmail API (una vez):

1. console.cloud.google.com → nuevo proyecto → habilitar **Gmail API**.
2. Pantalla de consentimiento OAuth (Externo) → agregar tu correo → **publicar** (si queda "en pruebas",
   el token vence a los 7 días).
3. Credenciales → ID de cliente OAuth → **App de escritorio**.
4. `python -m scripts.gmail_token --client-id ... --client-secret ...` y seguir las instrucciones.
5. En Railway: `EMAIL_PROVIDER=gmail`, `EMAIL_FROM=UniMarket <tu-cuenta@gmail.com>`, `GMAIL_CLIENT_ID`,
   `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`.

Recomendación a futuro: un dominio `.com` cuesta ≈ US$10/año. Con él, Resend o Brevo dan mejor
reputación y remitente propio (`no-reply@unimarket.com.co`); solo cambia `EMAIL_PROVIDER` y la clave.

Los correos llevan **códigos de 6 dígitos** (verificar correo y recuperar contraseña) en vez de
enlaces: funcionan sin dominio ni deep links. Vencen en 15–30 minutos, se guardan como HMAC y se
bloquean tras 5 intentos fallidos. El envío va en segundo plano con reintentos, así que no hace
esperar al usuario.
