from fastapi import APIRouter
import logging

logger = logging.getLogger(__name__)

from api.v1 import health, auth, items, categories, dashboard, storefront, orders, whatsapp, cart

router = APIRouter(prefix="/api/v1")

logger.info(f"Registering health router: {health.router.routes}")
router.include_router(health.router, tags=["Health"])

logger.info(f"Registering auth router: {auth.router.routes}")
router.include_router(auth.router, tags=["Auth"])

logger.info(f"Registering items router: {items.router.routes}")
router.include_router(items.router, tags=["Items"])

logger.info(f"Registering categories router")
router.include_router(categories.router, tags=["Categories"])

logger.info(f"Registering dashboard router")
router.include_router(dashboard.router, tags=["Dashboard"])

logger.info(f"Registering storefront router")
router.include_router(storefront.router, tags=["Storefront (Público)"])

logger.info(f"Registering orders router")
router.include_router(orders.router, tags=["Orders"])

logger.info(f"Registering whatsapp router")
router.include_router(whatsapp.router, tags=["WhatsApp"])

logger.info(f"Registering cart router")
router.include_router(cart.router, tags=["Cart"])