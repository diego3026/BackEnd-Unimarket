from fastapi import APIRouter

from app.api.v1.endpoints import account, admin, auth, catalog, orders, seller

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(auth.me_router)
api_router.include_router(account.router)
api_router.include_router(catalog.router)
api_router.include_router(orders.router)
api_router.include_router(seller.router)
api_router.include_router(admin.router)
