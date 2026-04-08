from fastapi import APIRouter
import logging

logger = logging.getLogger(__name__)

from api.v1 import health, auth, items, categories, dashboard, storefront, orders, cart, customers, tenants, upload, whatsapp

router = APIRouter(prefix="/api/v1")
logger.info("Loading API v1 routers...")

router.include_router(health.router, tags=["Health"])
router.include_router(auth.router, tags=["Auth"])
router.include_router(items.router, tags=["Items"])
router.include_router(categories.router, tags=["Categories"])
router.include_router(dashboard.router, tags=["Dashboard"])
router.include_router(storefront.router, tags=["Storefront (Público)"])
router.include_router(orders.router, tags=["Orders"])
router.include_router(whatsapp.router, prefix="/whatsapp", tags=["WhatsApp"])
router.include_router(cart.router, tags=["Cart"])
router.include_router(customers.router, tags=["Customers"])
router.include_router(tenants.router, tags=["Tenants"])
router.include_router(upload.router, tags=["Upload"])

logger.info("All API v1 routers loaded successfully")