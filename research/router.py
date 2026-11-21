"""Endpoints del proyecto de investigación (5G Fog-Cloud, MOTOA, JROF).

Se montan en /api/v1/research para no mezclarse con el marketplace.
Usan su propio almacenamiento (SQLite) definido en research/persistence.py.
"""
from fastapi import APIRouter

from research.api.routes.routes import (
    infra_router,
    jrof_router,
    payments_router,
    products_router,
    reco_router,
    users_router,
)
from research.api.routes.tasks import router as tasks_router

research_router = APIRouter()
for r in (tasks_router, products_router, payments_router, reco_router, users_router, infra_router, jrof_router):
    research_router.include_router(r)
