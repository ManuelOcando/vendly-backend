from fastapi import APIRouter
import logging

logger = logging.getLogger(__name__)

from api.v1 import health, auth, items, categories, dashboard, storefront, orders, cart, customers, tenants, upload, whatsapp, legal, vendly_pro, post_sale, scheduling, analytics, bot_config

router = APIRouter(prefix="/api/v1")
logger.info("Loading API v1 routers...")

router.include_router(health.router, tags=["Health"])
router.include_router(auth.router, tags=["Auth"])
router.include_router(legal.router, tags=["Legal"])
router.include_router(items.router, tags=["Items"])
router.include_router(categories.router, tags=["Categories"])
router.include_router(dashboard.router, tags=["Dashboard"])
router.include_router(storefront.router, tags=["Storefront (Público)"])
router.include_router(orders.router, tags=["Orders"])
router.include_router(whatsapp.router, prefix="/whatsapp", tags=["WhatsApp"])
router.include_router(bot_config.router, tags=["Bot Config"])
# cart.py declares its paths as "/create", "/{cart_id}" and so on, so without a
# prefix they land directly under /api/v1. That made GET /api/v1/{cart_id} a
# catch-all which, being registered before them, swallowed every single-segment
# GET declared later: /api/v1/customers, /api/v1/post-sale-requests and
# /api/v1/appointments all resolved to get_cart and answered 404 "Cart not found
# or expired". The frontend was already calling /api/v1/cart/... - see
# lib/store-service.ts - so nothing depended on the flat paths.
router.include_router(cart.router, prefix="/cart", tags=["Cart"])
router.include_router(customers.router, tags=["Customers"])
router.include_router(tenants.router, tags=["Tenants"])
router.include_router(upload.router, tags=["Upload"])
router.include_router(vendly_pro.router, tags=["Vendly Pro"])
router.include_router(post_sale.router, tags=["Post-Sale Support"])
router.include_router(scheduling.router, tags=["Service Scheduling"])
router.include_router(analytics.router, tags=["Advanced Analytics"])

logger.info("All API v1 routers loaded successfully")