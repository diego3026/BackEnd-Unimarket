# UniMarket API

Backend del marketplace de emprendedores de la Universidad del Magdalena.
FastAPI + PostgreSQL, pensado para desplegarse en **Railway**.

- **Cliente:** catálogo, cupones, checkout, pedidos con seguimiento, reseñas, billetera, direcciones, favoritos, notificaciones.
- **Emprendedor:** su tienda ("Configurar tienda"), menú, promociones/cupones, pedidos en vivo, ganancias, cuenta de pagos, documentos.
- **Administrador:** usuarios, aprobación de tiendas, moderación de productos, documentos y reportes.
- **Investigación:** los endpoints del proyecto 5G Fog-Cloud (MOTOA/JROF) siguen disponibles en `/api/v1/research`.

Servicios externos (todos con plan gratis): pagos por **Bre-B / Nequi** directo al emprendedor, imágenes en **Cloudinary**, correo por **Gmail API**. Comparación y configuración en [`docs/SERVICIOS.md`](docs/SERVICIOS.md).

---

## Arquitectura

```
app/
├── main.py               # create_app(): middlewares, routers, /health
├── core/                 # configuración, seguridad, errores, middlewares
│   ├── config.py         # variables de entorno (pydantic-settings)
│   ├── security.py       # bcrypt, JWT, tokens opacos
│   ├── crypto.py         # cifrado Fernet de datos bancarios
│   ├── errors.py         # errores de dominio → JSON uniforme
│   ├── middleware.py     # X-Request-ID, cabeceras de seguridad, logs
│   └── rate_limit.py     # límite de intentos por IP
├── db/                   # Base declarativa y sesión SQLAlchemy
├── models/               # tablas (SQLAlchemy 2.0)
├── schemas/              # entrada/salida (Pydantic, JSON en camelCase)
├── repositories/         # consultas a la BD (sin reglas de negocio)
├── services/             # reglas de negocio y transacciones
└── api/v1/endpoints/     # HTTP: valida, llama al servicio, responde
alembic/                  # migraciones (incluye los lugares del campus)
scripts/seed.py           # admin inicial y datos de demo
research/                 # código del proyecto de investigación (sin cambios de lógica)
tests/                    # pruebas contra PostgreSQL real
```

Flujo de una petición: **endpoint → servicio → repositorio → modelo**.
Los endpoints no tocan la BD y los repositorios no deciden reglas; así cada capa se prueba y cambia por separado.

### Decisiones importantes

| Tema | Decisión |
|---|---|
| Precios | Enteros en pesos (COP no usa centavos). **El servidor calcula todo**: precios, descuentos, cupones, envío y total. El cliente solo envía productos y cantidades. |
| Inventario | Al crear un pedido se bloquean las filas de los productos (`SELECT … FOR UPDATE`), así nunca se vende más de lo que hay aunque compren al tiempo. Cancelar devuelve el stock y el uso del cupón. |
| Pedidos | Id numérico (`#1045`) para dictarlo fácil. Estados: `pending → preparing → ready (recoger) / onTheWay (domicilio) → delivered`, o `cancelled`. No se pueden saltar estados. |
| Recogida | El código de 4 dígitos solo lo ve el cliente; el emprendedor lo confirma al entregar. |
| Reintentos | `POST /orders` acepta la cabecera `Idempotency-Key`: si la red falla y la app reintenta, no se duplica el pedido. |
| IDs | UUID para usuarios, tiendas y productos (no se pueden adivinar). |
| JSON | camelCase, igual que los modelos de Dart. Se aceptan también campos en snake_case al recibir. |

### Seguridad

- Contraseñas con **bcrypt** (12 rondas); mínimo 8 caracteres con letras y números.
- **JWT** de acceso corto (30 min) + **refresh token rotativo** de un solo uso guardado como hash. Si alguien reutiliza un refresh viejo, se cierra toda la sesión (detección de robo).
- Cambiar contraseña, suspender un usuario o "cerrar sesión en todos los dispositivos" invalida al instante todos sus tokens (`token_version`).
- Login con respuesta idéntica exista o no el correo y tiempo constante; recuperar contraseña no revela si la cuenta existe.
- Verificación de correo y recuperación con **códigos de 6 dígitos** guardados como HMAC, que vencen en 15–30 min y se bloquean tras 5 intentos.
- Imágenes: subida firmada directa a Cloudinary; el backend solo acepta URLs de nuestra cuenta y de la carpeta del usuario. Documentos de identidad privados con enlace temporal para el admin.
- Pagos por transferencia: el dinero va directo al emprendedor; UniMarket no maneja fondos ni datos de tarjetas.
- **Límite de intentos** por IP en login, registro, refresh y recuperación.
- Roles verificados en cada endpoint y **propiedad del recurso** (un emprendedor solo toca su tienda; un pedido ajeno responde 404, no revela que existe).
- Los cuerpos JSON rechazan campos desconocidos: nadie puede enviar `role: admin` ni `price` en un pedido.
- Tarjetas: **nunca** se guarda el número completo ni el CVV, solo marca, últimos 4 y el token de la pasarela.
- Cuenta bancaria del emprendedor **cifrada** (Fernet) y enmascarada en las respuestas.
- Cabeceras de seguridad (`nosniff`, `DENY`, `no-referrer`, HSTS en producción), `Cache-Control: no-store` en la API, `TrustedHost`, CORS restringido por variable.
- Errores internos nunca se envían al cliente; cada respuesta lleva `X-Request-ID` para rastrear en los logs.
- Bitácora (`audit_logs`) de acciones del administrador.
- En producción la app **no arranca** sin `SECRET_KEY` y `DATA_ENCRYPTION_KEY`.

---

## Correr en local

Requisitos: Python 3.12+ y PostgreSQL 14+.

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                 # ajusta DATABASE_URL

alembic upgrade head                 # crea las tablas
FIRST_ADMIN_EMAIL=admin@unimarket.app FIRST_ADMIN_PASSWORD=UnaClaveLarga2026 python -m scripts.seed --demo
uvicorn app.main:app --reload
```

- Documentación interactiva: http://localhost:8000/docs
- Desde el emulador de Android la API está en `http://10.0.2.2:8000/api/v1` (ya configurado en la app).
- Cuentas demo (`--demo`): `cliente@demo.unimarket.app`, `otto@demo.unimarket.app`… contraseña `Demo12345`.

### Pruebas

```bash
createdb unimarket_test               # una vez
pytest                                # usa TEST_DATABASE_URL o la BD unimarket_test local
ruff check app tests scripts
```

Las pruebas (60) cubren el flujo completo cliente ↔ emprendedor, pagos por Bre-B/Nequi, cupones, descuentos, inventario con compras simultáneas, idempotencia, roles, rotación de tokens, códigos de verificación con bloqueo, subidas firmadas, caché/ETag, cifrado y suspensión de cuentas.

---

## Desplegar en Railway

1. **Crea el proyecto** en Railway → *Deploy from GitHub repo* → este repositorio (rama `api-marketplace`, o `main` cuando la unas).
2. **Agrega PostgreSQL**: *New → Database → PostgreSQL*.
3. En el servicio de la API, pestaña **Variables**:

   | Variable | Valor |
   |---|---|
   | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (referencia a la BD) |
   | `ENVIRONMENT` | `production` |
   | `SECRET_KEY` | salida de `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
   | `DATA_ENCRYPTION_KEY` | salida de `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
   | `ALLOWED_HOSTS` | el dominio que te da Railway, p. ej. `unimarket-api.up.railway.app` |
   | `ENABLE_DOCS` | `true` mientras desarrollas; `false` cuando sea público |
   | `FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD` | tu correo y una clave de 10+ caracteres |
   | `EMAIL_PROVIDER`, `EMAIL_FROM`, `GMAIL_*` | ver [`docs/SERVICIOS.md`](docs/SERVICIOS.md#3-correo-sin-dominio-propio) |
   | `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` | del dashboard de Cloudinary |
   | `WEB_CONCURRENCY` | `2` (súbelo si aumentas la CPU del servicio) |

   ⚠️ Guarda `DATA_ENCRYPTION_KEY` en un lugar seguro: si la pierdes, no se pueden leer las cuentas bancarias guardadas.
4. **Deploy.** Railway usa el `Dockerfile`; `railway.json` corre `alembic upgrade head` antes de cada despliegue y revisa `/health`.
5. **Genera el dominio** en *Settings → Networking → Generate Domain*.
6. **Crea el admin** (una sola vez) desde la consola del servicio o con la CLI:
   ```bash
   railway run python -m scripts.seed           # agrega --demo --force solo si quieres datos de ejemplo
   ```
7. En la app, cambia `apiBaseUrl` a `https://<tu-dominio>/api/v1`.

Si escalas a varias réplicas, agrega Redis en Railway, pon `RATE_LIMIT_STORAGE_URI=${{Redis.REDIS_URL}}` y añade `redis` a `requirements.txt` para que el límite de intentos sea compartido.

---

## Concurrencia y latencia

- **Procesos**: `WEB_CONCURRENCY` (≈ núcleos de CPU). Cada proceso atiende muchas peticiones a la vez con su pool de hilos.
- **Conexiones a la BD**: `WEB_CONCURRENCY × (DB_POOL_SIZE + DB_MAX_OVERFLOW)` debe quedar por debajo de `max_connections` de PostgreSQL (100 por defecto). Con 2 procesos y 10+10 son 40. Si no hay conexión libre en 10 s la petición falla rápido en vez de colgarse.
- **Protecciones**: ninguna consulta puede tardar más de `DB_STATEMENT_TIMEOUT_MS`; las transacciones inactivas se cierran a los 30 s.
- **Catálogo en caché**: las lecturas públicas (productos, tiendas, cupones) se guardan 15 s en memoria por proceso y llevan `Cache-Control: public` y `ETag`. Cuando muchos abren Inicio a la vez, solo una petición llega a la BD.
- **ETag en todo GET**: la app puede revisar un pedido cada pocos segundos con `If-None-Match`; si nada cambió recibe `304` sin cuerpo.
- **GZip** en respuestas grandes y **búsqueda con índices trigram** (`pg_trgm`) para `ILIKE '%texto%'`.
- **Inventario sin sobreventa**: filas bloqueadas en orden fijo al comprar (probado con compras simultáneas).
- **Escalar**: más réplicas en Railway (agrega Redis para compartir el límite de intentos, ver abajo) o un CDN delante del catálogo.

Prueba de carga (`python -m scripts.loadtest`), 2 procesos en una máquina de **2 vCPU** compartida con el generador de carga, 2.000 productos:

| Escenario | Throughput | p50 | p95 | p99 | Errores |
|---|---|---|---|---|---|
| 300 usuarios navegando y comprando (pausa 0–6 s) | 93 req/s | 7 ms | 73 ms | 115 ms | 0 % |
| 100 usuarios sin pausa (saturación) | 155 req/s | 427 ms | 1,9 s | 3,2 s | 0 % |

En el escenario realista, crear un pedido tarda 51 ms (p50) y ver el catálogo 3 ms. La saturación muestra el techo de 2 vCPU: con más tráfico se agregan procesos o réplicas.

---

## Variables de entorno

Todas están documentadas en [`.env.example`](.env.example). Las más importantes: `DATABASE_URL`, `ENVIRONMENT`, `SECRET_KEY`, `DATA_ENCRYPTION_KEY`, `ALLOWED_HOSTS`, `EMAIL_PROVIDER` + `GMAIL_*`, `CLOUDINARY_*`, `WEB_CONCURRENCY`.

---

## Contrato con la app

El detalle de cada endpoint y cómo se conecta con cada pantalla de la app está en [`docs/API.md`](docs/API.md). La lista completa con ejemplos está en `/docs` (Swagger).

## Pendiente (siguientes pasos)

- **Tarjetas** con Mercado Pago Split 1:1 (el dinero llega directo a cada emprendedor). Ver [`docs/SERVICIOS.md`](docs/SERVICIOS.md).
- **Notificaciones push** (Firebase Cloud Messaging, gratis): el punto único para enviarlas es `app/services/notifications.py::notify`.
- **Dominio propio** (≈ US$10/año) para enviar correo desde `no-reply@tu-dominio` con Resend o Brevo.
