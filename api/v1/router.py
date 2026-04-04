from fastapi import APIRouter

from api.v1 import health, auth, items, categories, dashboard, storefront, orders, whatsapp, cart, customers

router = APIRouter(prefix="/api/v1")

router.include_router(health.router, tags=["Health"])
router.include_router(auth.router, tags=["Auth"])
router.include_router(items.router, tags=["Items"])
router.include_router(categories.router, tags=["Categories"])
router.include_router(dashboard.router, tags=["Dashboard"])
router.include_router(storefront.router, tags=["Storefront (Público)"])
router.include_router(orders.router, tags=["Orders"])
router.include_router(whatsapp.router, tags=["WhatsApp"])
router.include_router(cart.router, tags=["Cart"])
router.include_router(customers.router, tags=["Customers"])