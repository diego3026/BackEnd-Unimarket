"""Panel del administrador: usuarios, tiendas, productos, documentos y reportes."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, NotFound
from app.models import AuditLog, Order, Product, Store, StoreDocument, User
from app.models.enums import OrderStatus, StoreStatus, UserRole, UserStatus
from app.repositories.repos import ProductRepo, StoreRepo, TokenRepo, UserRepo, _escape_like
from app.schemas.admin import (
    AdminUserOut,
    AdminUserUpdateIn,
    DocumentReviewIn,
    ReportOut,
    StoreReviewIn,
)
from app.schemas.common import Page, PageParams
from app.services import mappers
from app.services.media import private_download_url
from app.services.notifications import notify
from app.services.pricing import now


class AdminService:
    def __init__(self, db: Session, actor: User):
        self.db = db
        self.actor = actor
        self.users = UserRepo(db)
        self.stores = StoreRepo(db)

    def _audit(self, action: str, target_type: str, target_id, detail: str = "") -> None:
        self.db.add(
            AuditLog(
                actor_id=self.actor.id,
                action=action,
                target_type=target_type,
                target_id=str(target_id),
                detail=detail[:1000],
                created_at=now(),
            )
        )

    # ---------------------------------------------------------------- usuarios
    def list_users(self, *, q, role, status, page: PageParams) -> Page:
        items, total = self.users.paginate(
            self.users.search(q=q, role=role, status=status), offset=page.offset, limit=page.size
        )
        stats = {}
        if items:
            rows = self.db.execute(
                select(Order.customer_id, func.count(), func.coalesce(func.sum(Order.total), 0))
                .where(Order.customer_id.in_([u.id for u in items]), Order.status == OrderStatus.delivered)
                .group_by(Order.customer_id)
            ).all()
            stats = {uid: (c, int(t)) for uid, c, t in rows}
        out = []
        for u in items:
            c, t = stats.get(u.id, (0, 0))
            out.append(
                AdminUserOut(
                    id=u.id,
                    email=u.email,
                    full_name=u.full_name,
                    phone=u.phone,
                    role=u.role,
                    status=u.status,
                    email_verified=u.email_verified,
                    created_at=u.created_at,
                    last_login_at=u.last_login_at,
                    total_orders=c,
                    total_spent=t,
                )
            )
        return Page(items=out, total=total, page=page.page, size=page.size)

    def update_user(self, user_id: uuid.UUID, data: AdminUserUpdateIn):
        user = self.users.get(user_id)
        if not user:
            raise NotFound("Usuario no encontrado", code="user_not_found")
        if user.id == self.actor.id:
            raise BusinessRuleError("No puedes cambiar tu propio rol o estado", code="self_update")
        if data.role is not None and data.role != user.role:
            if data.role == UserRole.entrepreneur and not self.stores.by_owner(user.id):
                raise BusinessRuleError("El usuario no tiene tienda registrada", code="no_store")
            self._audit("user.role", "user", user.id, f"{user.role.value} → {data.role.value}")
            user.role = data.role
            user.token_version += 1
        if data.status is not None and data.status != user.status:
            self._audit("user.status", "user", user.id, f"{user.status.value} → {data.status.value}")
            user.status = data.status
            if data.status == UserStatus.suspended:
                # Cierra todas sus sesiones de inmediato.
                user.token_version += 1
                TokenRepo(self.db).revoke_user(user.id, now())
        self.db.commit()
        return mappers.user_out(user)

    # ---------------------------------------------------------------- tiendas
    def list_stores(self, *, status: StoreStatus | None, q: str | None, page: PageParams) -> Page:
        items, total = self.stores.paginate(
            self.stores.admin_query(status=status, q=q), offset=page.offset, limit=page.size
        )
        return Page(items=[mappers.store_admin_out(s) for s in items], total=total, page=page.page, size=page.size)

    def review_store(self, store_id: uuid.UUID, data: StoreReviewIn):
        store = self.stores.with_details(store_id)
        if not store:
            raise NotFound("Tienda no encontrada", code="store_not_found")
        self._audit("store.status", "store", store.id, f"{store.status.value} → {data.status.value}: {data.note}")
        store.status = data.status
        store.review_note = data.note
        messages = {
            StoreStatus.approved: ("¡Tu tienda fue aprobada!", "Ya apareces en UniMarket. Agrega tus productos."),
            StoreStatus.rejected: ("Tu tienda no fue aprobada", data.note or "Revisa los datos y vuelve a intentarlo."),
            StoreStatus.suspended: ("Tu tienda fue suspendida", data.note or "Escríbenos a soporte."),
        }
        if data.status in messages:
            title, body = messages[data.status]
            notify(self.db, store.owner_id, type_="system", title=title, body=body, data={"storeId": str(store.id)})
        self.db.commit()
        return mappers.store_admin_out(store)

    def store_documents(self, store_id: uuid.UUID):
        return [mappers.document_out(d) for d in self.stores.documents(store_id)]

    def review_document(self, document_id: uuid.UUID, data: DocumentReviewIn):
        doc = self.db.get(StoreDocument, document_id)
        if not doc:
            raise NotFound("Documento no encontrado", code="document_not_found")
        doc.status = data.status
        doc.review_note = data.note
        self._audit("document.status", "document", doc.id, data.status.value)
        self.db.commit()
        return mappers.document_out(doc)

    def document_file_url(self, document_id: uuid.UUID) -> str:
        doc = self.db.get(StoreDocument, document_id)
        if not doc:
            raise NotFound("Documento no encontrado", code="document_not_found")
        self._audit("document.view", "document", doc.id)
        self.db.commit()
        return private_download_url(doc.file_url)

    # -------------------------------------------------------------- productos
    def list_products(self, *, q: str | None, hidden: bool | None, page: PageParams) -> Page:
        stmt = select(Product).join(Store).order_by(Product.created_at.desc())
        if q:
            stmt = stmt.where(Product.name.ilike(f"%{_escape_like(q)}%", escape="\\"))
        if hidden is not None:
            stmt = stmt.where(Product.is_hidden.is_(hidden))
        items, total = ProductRepo(self.db).paginate(stmt, offset=page.offset, limit=page.size)
        return Page(items=[mappers.product_admin_out(p) for p in items], total=total, page=page.page, size=page.size)

    def moderate_product(self, product_id: uuid.UUID, hidden: bool):
        p = self.db.get(Product, product_id)
        if not p:
            raise NotFound("Producto no encontrado", code="product_not_found")
        p.is_hidden = hidden
        self._audit("product.hidden" if hidden else "product.visible", "product", p.id)
        if hidden:
            notify(
                self.db,
                p.store.owner_id,
                type_="system",
                title="Ocultamos un producto",
                body=f"«{p.name}» no cumple las normas de UniMarket.",
                data={"productId": str(p.id)},
            )
        self.db.commit()
        return mappers.product_admin_out(p)

    # ---------------------------------------------------------------- reportes
    def report(self, days: int = 30) -> ReportOut:
        to_date = now()
        since = to_date - timedelta(days=days)
        users_by_role = {r.value: c for r, c in self.db.execute(select(User.role, func.count()).group_by(User.role))}
        stores_by_status = {
            s.value: c for s, c in self.db.execute(select(Store.status, func.count()).group_by(Store.status))
        }
        in_range = Order.created_at >= since
        orders_by_status = {
            s.value: c
            for s, c in self.db.execute(select(Order.status, func.count()).where(in_range).group_by(Order.status))
        }
        delivered = (Order.status == OrderStatus.delivered) & in_range
        gross, count = self.db.execute(
            select(func.coalesce(func.sum(Order.total), 0), func.count()).where(delivered)
        ).one()
        day = func.date(Order.created_at)
        by_day = self.db.execute(
            select(day, func.count(), func.coalesce(func.sum(Order.total), 0))
            .where(in_range)
            .group_by(day)
            .order_by(day)
        ).all()
        top_stores = self.db.execute(
            select(Store.name, func.count(Order.id), func.sum(Order.total))
            .join(Order, Order.store_id == Store.id)
            .where(delivered)
            .group_by(Store.name)
            .order_by(func.sum(Order.total).desc())
            .limit(5)
        ).all()
        top_categories = self.db.execute(
            select(Store.category, func.count(Order.id))
            .join(Order, Order.store_id == Store.id)
            .where(delivered)
            .group_by(Store.category)
            .order_by(func.count(Order.id).desc())
            .limit(5)
        ).all()
        return ReportOut(
            users_by_role=users_by_role,
            stores_by_status=stores_by_status,
            orders_total=sum(orders_by_status.values()),
            orders_by_status=orders_by_status,
            gross_sales=int(gross),
            average_ticket=int(gross / count) if count else 0,
            orders_by_day=[{"date": str(d), "orders": c, "total": int(t)} for d, c, t in by_day],
            top_stores=[{"name": n, "orders": c, "total": int(t or 0)} for n, c, t in top_stores],
            top_categories=[{"category": n, "orders": c} for n, c in top_categories],
            from_date=since,
            to_date=to_date,
        )
