from fastapi import APIRouter
from api.v1 import health, auth, items, categories, dashboard

router = APIRouter(prefix="/api/v1")

router.include_router(health.router, tags=["Health"])
router.include_router(auth.router, tags=["Auth"])
router.include_router(items.router, tags=["Items"])
router.include_router(categories.router, tags=["Categories"])
router.include_router(dashboard.router, tags=["Dashboard"])