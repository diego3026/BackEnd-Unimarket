"""Carga inicial de datos.

    python -m scripts.seed            # crea el admin definido en FIRST_ADMIN_EMAIL/PASSWORD
    python -m scripts.seed --demo     # además crea tiendas, productos y cupones de ejemplo

Es idempotente: si los datos ya existen no los duplica.
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Product, Promotion, Store, User
from app.models.enums import DiscountType, PromotionKind, StoreStatus, UserRole

DEMO_STORES = [
    # email, dueño, tienda, categoría, descripción, punto, secciones, productos
    (
        "otto@demo.unimarket.app",
        "Otto Pérez",
        "Sandwiches Otto",
        "Comida",
        "Sándwiches artesanales hechos al momento con pan de la casa.",
        "b8",
        ["Sándwiches", "Combos", "Bebidas"],
        [
            (
                "Sándwich Otto Clásico",
                "Pan artesanal, jamón, queso costeño, lechuga y salsa de la casa.",
                "Sándwiches",
                9000,
            ),
            ("Combo Otto + Jugo", "Sándwich clásico con jugo natural del día.", "Combos", 14000),
        ],
    ),
    (
        "laura@demo.unimarket.app",
        "Laura Díaz",
        "MaracuMango",
        "Bebidas",
        "Frutas y bebidas tropicales recién preparadas.",
        "plaza",
        ["Bebidas", "Frutas"],
        [
            ("Limón Coco", "Mezcla tropical de limón y coco.", "Bebidas", 7000),
            ("Mango Biche con Sal", "Mango biche picado con sal, limón y pimienta.", "Frutas", 6000),
            ("Picada Tropical", "Bandeja de mango, piña, fresas y mamones con chamoy.", "Frutas", 18000),
        ],
    ),
    (
        "jeison@demo.unimarket.app",
        "Jeison Kol",
        "Jeikol Pizza",
        "Comida",
        "Pizzas personales al horno.",
        "b2",
        ["Pizzas"],
        [
            ("Pizza de Chorizo", "Pizza personal con chorizo santarrosano.", "Pizzas", 8000),
            ("Pizza Hawaiana", "Pizza personal con piña y jamón.", "Pizzas", 8500),
        ],
    ),
    (
        "andres@demo.unimarket.app",
        "Andrés Antequera",
        "Mr Fox",
        "Comida",
        "Hamburguesas y acompañantes.",
        "hangar",
        ["Hamburguesas", "Acompañantes"],
        [
            (
                "Hamburguesa de Carne",
                "Carne a la parrilla, cheddar, tomate y cebolla caramelizada.",
                "Hamburguesas",
                16000,
            ),
            ("Papas Cascos", "Papas en cascos con paprika.", "Acompañantes", 7000),
        ],
    ),
    (
        "martina@demo.unimarket.app",
        "Martina Rojas",
        "Accesorios Martina",
        "Accesorios",
        "Accesorios hechos a mano.",
        "lib",
        ["Aretes", "Pulseras"],
        [
            ("Pendientes Punk", "Aretes en acero quirúrgico hechos a mano.", "Aretes", 12500),
            ("Pulsera tejida", "Pulsera en hilo encerado con dije.", "Pulseras", 8000),
        ],
    ),
    (
        "valentina@demo.unimarket.app",
        "Valentina Gómez",
        "Dulce Campus",
        "Postres",
        "Postres caseros para la tarde.",
        "b5",
        ["Postres"],
        [
            ("Brownie con helado", "Brownie de chocolate con bola de vainilla.", "Postres", 6500),
            ("Torta de zanahoria", "Porción con frosting de queso crema.", "Postres", 5500),
        ],
    ),
]

DEMO_PROMOTIONS = [
    ("Sandwiches Otto", "Combo del día", PromotionKind.product_discount, DiscountType.fixed, 2000, None, 0),
    ("MaracuMango", "Semana tropical", PromotionKind.product_discount, DiscountType.percent, 17, None, 0),
    ("MaracuMango", "Cupón campus", PromotionKind.coupon, DiscountType.percent, 10, "CAMPUS10", 15000),
    ("Sandwiches Otto", "Primera compra", PromotionKind.coupon, DiscountType.fixed, 2000, "OTTO2K", 10000),
]


def ensure_admin(db) -> None:
    email, password = settings.first_admin_email.lower(), settings.first_admin_password
    if not email or not password:
        print("FIRST_ADMIN_EMAIL / FIRST_ADMIN_PASSWORD no están definidos: no se creó admin.")
        return
    if len(password) < 10:
        sys.exit("FIRST_ADMIN_PASSWORD debe tener al menos 10 caracteres.")
    user = db.scalar(select(User).where(User.email == email))
    if user:
        print(f"Admin ya existe: {email}")
        return
    db.add(
        User(
            email=email,
            password_hash=hash_password(password),
            full_name="Administrador UniMarket",
            role=UserRole.admin,
            email_verified=True,
        )
    )
    db.commit()
    print(f"Admin creado: {email}")


def seed_demo(db) -> None:
    password = os.getenv("DEMO_PASSWORD", "Demo12345")
    stores: dict[str, Store] = {}
    for email, owner, name, category, desc, place, sections, products in DEMO_STORES:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email,
                password_hash=hash_password(password),
                full_name=owner,
                phone="3000000000",
                role=UserRole.entrepreneur,
                email_verified=True,
            )
            db.add(user)
            db.flush()
        store = db.scalar(select(Store).where(Store.owner_id == user.id))
        if store is None:
            store = Store(
                owner_id=user.id,
                name=name,
                category=category,
                description=desc,
                pickup_place_id=place,
                menu_sections=sections,
                status=StoreStatus.approved,
                phone="3000000000",
                accepts_card=True,
            )
            db.add(store)
            db.flush()
            for pname, pdesc, pcat, price in products:
                db.add(
                    Product(
                        store_id=store.id,
                        name=pname,
                        description=pdesc,
                        category=pcat,
                        price=price,
                        stock=30,
                        is_featured=price >= 12000,
                    )
                )
        stores[name] = store
    db.flush()
    for store_name, title, kind, type_, value, code, min_purchase in DEMO_PROMOTIONS:
        store = stores[store_name]
        exists = db.scalar(select(Promotion).where(Promotion.store_id == store.id, Promotion.title == title))
        if not exists:
            db.add(
                Promotion(
                    store_id=store.id,
                    title=title,
                    kind=kind,
                    type=type_,
                    value=value,
                    code=code,
                    min_purchase=min_purchase,
                )
            )
    customer = db.scalar(select(User).where(User.email == "cliente@demo.unimarket.app"))
    if customer is None:
        db.add(
            User(
                email="cliente@demo.unimarket.app",
                password_hash=hash_password(password),
                full_name="Laura Cliente",
                phone="3001234567",
                email_verified=True,
            )
        )
    db.commit()
    print(f"Datos de demo listos ({len(stores)} tiendas). Contraseña de las cuentas demo: {password}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="Crea tiendas y productos de ejemplo")
    parser.add_argument("--force", action="store_true", help="Permite --demo en producción")
    args = parser.parse_args()
    if args.demo and settings.is_production and not args.force:
        sys.exit("No se cargan datos de demo en producción (usa --force si de verdad lo quieres).")
    with SessionLocal() as db:
        ensure_admin(db)
        if args.demo:
            seed_demo(db)


if __name__ == "__main__":
    main()
