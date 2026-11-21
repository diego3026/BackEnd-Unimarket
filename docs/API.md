# Contrato de la API ↔ app UniMarket

Base: `https://<dominio>/api/v1` · JSON en **camelCase** · fechas ISO 8601 en UTC · dinero en **pesos enteros**.

## Convenciones

**Autenticación**

1. `POST /auth/login` o `/auth/register` → `{accessToken, refreshToken, expiresIn, user}`.
2. Cada petición: `Authorization: Bearer <accessToken>`.
3. Si responde `401` con `code: "token_expired"`, llamar `POST /auth/refresh {refreshToken}` y reintentar una vez. Guardar el **nuevo** refresh (el anterior deja de servir).
4. Si el refresh responde `401`, cerrar sesión y llevar al login.
5. Guardar los tokens en `flutter_secure_storage`, no en `shared_preferences`.

**Errores** (siempre la misma forma)

```json
{ "error": { "code": "out_of_stock", "message": "Solo quedan 2 unidades de Sándwich", "details": {"productId": "…", "available": 2} } }
```

`message` está en español y se puede mostrar tal cual. `code` sirve para decidir qué hacer en la app.

| HTTP | Cuándo |
|---|---|
| 401 | Sin sesión / token vencido o inválido |
| 403 | Rol sin permiso o cuenta suspendida |
| 404 | No existe (o no es tuyo) |
| 409 | Duplicado (correo, cupón, tienda) |
| 422 | Datos inválidos (`validation_error`, con `details[].field`) o regla de negocio |
| 429 | Demasiados intentos |

**Paginación**: `?page=1&size=20` → `{items, total, page, size}`.

**Caché y seguimiento en vivo**: todo `GET` responde con `ETag`. Para revisar un pedido o la lista de
pedidos cada 5–10 s, enviar `If-None-Match: <etag anterior>`; si nada cambió llega `304` sin cuerpo
(casi sin datos móviles). El catálogo público puede tener hasta 15–30 s de atraso.

**Imágenes**: `POST /uploads/sign {purpose}` → subir el archivo (multipart) a `uploadUrl` con todos los
`fields` → usar la `secure_url` que responde Cloudinary. Ver `docs/SERVICIOS.md`.

**Enums** (mismos nombres que en Dart): `UserRole` consumer · entrepreneur · admin · `FulfillmentMode` delivery · pickup · `OrderStatus` pending · preparing · ready · onTheWay · delivered · cancelled · `PromotionKind` productDiscount · coupon · `DiscountType` percent · fixed · `PaymentKind` cash · nequi · breb · card (desactivado por ahora) · `PaymentStatus` pending · reported · paid · failed · refunded.

---

## Pantallas → endpoints

### Acceso
| Pantalla | Endpoint |
|---|---|
| Login | `POST /auth/login` |
| Registro | `POST /auth/register` `{fullName, email, phone, password, acceptTerms}` |
| Confirmar correo | `POST /auth/verify-email {code}` (con sesión; código de 6 dígitos enviado al registrarse) · `POST /me/resend-verification` |
| Recuperar contraseña | `POST /auth/forgot-password {email}` → `POST /auth/reset-password {email, code, newPassword}` (5 intentos por código) |
| Cerrar sesión | `POST /auth/logout {refreshToken}` · todos: `POST /me/logout-all` |

### Cliente
| Pantalla | Endpoint |
|---|---|
| Inicio (banners) | `GET /promotions/discounts` · destacados `GET /products?featured=true` · tiendas `GET /stores` |
| Buscar | `GET /products?q=&category=&sort=price_asc\|price_desc\|rating\|newest` · `GET /categories` |
| Detalle de producto | `GET /products/{id}` (usar `discountPrice ?? price`) |
| Tienda | `GET /stores/{id}` · `/stores/{id}/products` · `/stores/{id}/reviews` · `/stores/{id}/coupons` |
| Promos (cupones) | `GET /promotions/coupons` |
| Mapa de recogida / entrega | `GET /campus/places` (x, y de 0 a 1 para el mapa ilustrado) |
| Carrito → Finalizar compra | `POST /orders/quote` (mismo cuerpo que crear) para mostrar totales · `POST /orders/coupon-check` |
| Confirmar pedido | `POST /orders` + cabecera `Idempotency-Key: <uuid generado al abrir el checkout>` |
| Mis pedidos | `GET /orders?active=true` / `?active=false` |
| Seguir pedido | `GET /orders/{id}` (`history` trae la hora de cada estado; `pickupCode` para recoger) |
| Pagar por transferencia | Si `paymentKind` es `breb` o `nequi`, el pedido trae `payTo {kind, key, holderName, amount, referenceHint}`: mostrar la llave/número con botón de copiar. Luego `POST /orders/{id}/payment-report {reference}` ("Ya pagué") |
| Cancelar | `POST /orders/{id}/cancel {reason}` (solo mientras está `pending`) |
| Reseña | `POST /orders/{id}/review {rating, comment, tags}` (solo `delivered`, una vez) |
| Métodos de pago | `GET/POST /me/payment-methods` · `POST /me/payment-methods/{id}/default` · `DELETE …/{id}` |
| Direcciones | `GET/POST /me/addresses` · `PUT/DELETE /me/addresses/{id}` |
| Favoritos | `GET /me/favorites` · `PUT/DELETE /me/favorites/{productId}` |
| Notificaciones | `GET /me/notifications` · `GET /me/notifications/unread-count` · `POST …/{id}/read` · `POST …/read-all` |
| Perfil | `GET/PATCH /me` · `POST /me/password` |

**Cuerpo de `POST /orders`** (y `/orders/quote`):

```json
{
  "storeId": "uuid",
  "lines": [{ "productId": "uuid", "quantity": 2 }],
  "mode": "pickup",
  "placeId": "b2",
  "notes": "Sin cebolla",
  "couponCode": "CAMPUS10",
  "paymentKind": "card",
  "paymentMethodId": "uuid"
}
```

`placeId` es obligatorio para `delivery`; en `pickup` el servidor usa el punto de la tienda. `paymentMethodId` es obligatorio para `card`.
El carrito de la app agrupa por tienda: se crea **un pedido por tienda**.

### Emprendedor
| Pantalla | Endpoint |
|---|---|
| Quiero vender | `POST /seller/store` → queda `pending` hasta que el admin la apruebe; el usuario pasa a `entrepreneur` |
| Inicio de la tienda | `GET /seller/store` · pedidos `GET /seller/orders?active=true` |
| Avanzar pedido | `POST /seller/orders/{id}/status {status: nextStatus}`; al entregar un pedido de recogida enviar `pickupCode` |
| Rechazar pedido | `POST /seller/orders/{id}/status {status: "cancelled", reason}` |
| Confirmar transferencia | `POST /seller/orders/{id}/payment-confirm {received: true\|false}` (cuando `paymentStatus` es `reported`) |
| Configurar tienda | `PATCH /seller/store` (abierto, domicilio, recogida, costo de envío, pedido mínimo, minutos de preparación, punto de recogida, medios de pago: `acceptsCash`, `acceptsNequi` + `nequiPhone`, `acceptsBreb` + `brebKey`) |
| Fotos de productos / tienda | `POST /uploads/sign {purpose: "product"\|"store"}` |
| Menú | `GET/POST /seller/products` · `PATCH/DELETE /seller/products/{id}` |
| Promociones | `GET/POST /seller/promotions` · `PUT/DELETE …/{id}` · `POST …/{id}/pause` · `…/resume` |
| Ganancias | `GET /seller/earnings?days=30` |
| Datos bancarios | `GET/PUT /seller/payout-account` |
| Documentos | `GET/POST /seller/documents` |
| Responder reseña | `POST /seller/orders/{id}/review-reply {reply}` |

### Administrador
| Pantalla | Endpoint |
|---|---|
| Usuarios | `GET /admin/users?q=&role=&status=` · `PATCH /admin/users/{id} {role?, status?}` |
| Negocios | `GET /admin/stores?status=pending` · `POST /admin/stores/{id}/review {status, note}` |
| Documentos | `GET /admin/stores/{id}/documents` · `GET /admin/documents/{id}/file` (enlace de 5 min) · `POST /admin/documents/{id}/review` |
| Productos | `GET /admin/products?hidden=` · `POST /admin/products/{id}/moderate {isHidden}` |
| Reportes | `GET /admin/reports?days=30` |

---

## Correspondencia de modelos

| Dart (`lib/domain/entities`) | API |
|---|---|
| `StoreEntity` + `StoreSettings` | `StoreOut` (un solo objeto con la configuración incluida) |
| `ProductEntity` (`discountPrice`, `finalPrice`) | `ProductOut` (`discountPrice` ya calculado por el servidor) |
| `PromotionEntity` | `PromotionOut` (`isRunning` indica si está vigente) |
| `MarketOrder` / `OrderLine` | `OrderOut` / `OrderLineOut` (`total`, `pickupCode`, `history`, `review`) |
| `PaymentCard` | `PaymentMethodOut` (`expiry` = "MM/AA") |
| `CampusPlace` (`position`) | `CampusPlaceOut` (`x`, `y`) |
| `UserRole` | `role` en `UserOut` |
