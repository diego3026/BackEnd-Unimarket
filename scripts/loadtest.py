"""Prueba de carga: usuarios concurrentes navegando, consultando pedidos y comprando.

    python -m scripts.loadtest --base http://localhost:8000 --users 100 --seconds 30

Crea (o reutiliza) cuentas de prueba, inicia sesión y luego cada "usuario" repite:
60 % catálogo (listar, buscar, ver tienda), 25 % su cuenta (pedidos, notificaciones,
seguimiento con ETag) y 15 % comprar. Al final muestra peticiones por segundo,
latencias p50/p95/p99 y errores. No la corras contra producción con datos reales.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import time
from collections import Counter, defaultdict

import httpx

PASSWORD = "Carga12345"


async def ensure_user(client: httpx.AsyncClient, i: int) -> dict:
    email = f"carga{i}@loadtest.unimarket.app"
    body = {"email": email, "password": PASSWORD}
    r = await client.post("/auth/login", json=body)
    if r.status_code == 401:
        r = await client.post(
            "/auth/register",
            json={
                "fullName": f"Usuario Carga {i}",
                "email": email,
                "phone": f"3{i:09d}",
                "password": PASSWORD,
                "acceptTerms": True,
            },
        )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['accessToken']}"}


async def user_loop(client, headers, catalog, deadline, stats, errors, think):
    my_orders: list[int] = []
    etags: dict[int, str] = {}
    while time.perf_counter() < deadline:
        if think:
            await asyncio.sleep(random.uniform(0, think))
        roll = random.random()
        if roll < 0.60:
            choice = random.random()
            if choice < 0.4:
                name, coro = "GET /products", client.get("/products", params={"page": random.randint(1, 5)})
            elif choice < 0.7:
                q = random.choice(["arepa", "jugo", "pizza", "brownie", "café", "pul"])
                name, coro = "GET /products?q", client.get("/products", params={"q": q})
            else:
                sid = random.choice(catalog["stores"])
                name, coro = "GET /stores/{id}/products", client.get(f"/stores/{sid}/products")
        elif roll < 0.85:
            if my_orders and random.random() < 0.6:
                oid = random.choice(my_orders)
                h = {**headers, **({"If-None-Match": etags[oid]} if oid in etags else {})}
                name, coro = "GET /orders/{id} (ETag)", client.get(f"/orders/{oid}", headers=h)
            elif random.random() < 0.5:
                name, coro = "GET /orders", client.get("/orders", headers=headers)
            else:
                name, coro = "GET /me/notifications", client.get("/me/notifications", headers=headers)
        else:
            store = random.choice(catalog["by_store"])
            items = random.sample(store["products"], k=min(2, len(store["products"])))
            body = {
                "storeId": store["id"],
                "lines": [{"productId": p, "quantity": 1} for p in items],
                "mode": "pickup",
                "paymentKind": "cash",
            }
            name, coro = "POST /orders", client.post("/orders", json=body, headers=headers)
        t0 = time.perf_counter()
        try:
            r = await coro
            ms = (time.perf_counter() - t0) * 1000
            stats[name].append(ms)
            if r.status_code >= 400 and r.status_code != 304:
                errors[f"{name} {r.status_code}"] += 1
            elif name == "POST /orders":
                my_orders.append(r.json()["id"])
            elif name.startswith("GET /orders/{id}") and r.status_code == 200:
                etags[int(str(r.url).rsplit("/", 1)[1])] = r.headers.get("etag", "")
        except httpx.HTTPError as exc:
            errors[f"{name} {type(exc).__name__}"] += 1


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * p))]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--users", type=int, default=100)
    ap.add_argument("--seconds", type=int, default=30)
    ap.add_argument("--think", type=float, default=0, help="Pausa máxima (s) entre acciones de cada usuario")
    args = ap.parse_args()

    limits = httpx.Limits(max_connections=args.users + 10, max_keepalive_connections=args.users + 10)
    async with httpx.AsyncClient(base_url=f"{args.base}/api/v1", timeout=30, limits=limits) as client:
        stores = (await client.get("/stores", params={"size": 100})).json()["items"]
        by_store = []
        for s in stores:
            prods = (await client.get(f"/stores/{s['id']}/products", params={"size": 100})).json()["items"]
            if prods:
                by_store.append({"id": s["id"], "products": [p["id"] for p in prods]})
        catalog = {"stores": [s["id"] for s in stores], "by_store": by_store}

        print(f"Preparando {args.users} usuarios…")
        sem = asyncio.Semaphore(10)

        async def login(i):
            async with sem:
                return await ensure_user(client, i)

        headers = await asyncio.gather(*(login(i) for i in range(args.users)))

        stats: dict[str, list[float]] = defaultdict(list)
        errors: Counter = Counter()
        print(f"Carga: {args.users} usuarios simultáneos durante {args.seconds} s")
        start = time.perf_counter()
        deadline = start + args.seconds
        await asyncio.gather(*(user_loop(client, h, catalog, deadline, stats, errors, args.think) for h in headers))
        elapsed = time.perf_counter() - start

    total = sum(len(v) for v in stats.values())
    all_ms = [x for v in stats.values() for x in v]
    print(f"\n{total} peticiones en {elapsed:.1f} s → {total / elapsed:.0f} req/s")
    print(f"{'endpoint':32} {'n':>6} {'p50':>7} {'p95':>7} {'p99':>7}  (ms)")
    for name, v in sorted(stats.items()):
        print(f"{name:32} {len(v):6} {statistics.median(v):7.0f} {pct(v, 0.95):7.0f} {pct(v, 0.99):7.0f}")
    print(f"{'TOTAL':32} {total:6} {statistics.median(all_ms):7.0f} {pct(all_ms, 0.95):7.0f} {pct(all_ms, 0.99):7.0f}")
    print(f"Errores: {sum(errors.values())} ({sum(errors.values()) / max(total, 1):.2%})", dict(errors) or "")


if __name__ == "__main__":
    asyncio.run(main())
