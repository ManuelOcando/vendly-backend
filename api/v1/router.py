from fastapi import APIRouter
from api.v1 import health

router = APIRouter(prefix="/api/v1")

# Health check
router.include_router(health.router, tags=["Health"])

# Aquí iremos agregando más routers:
# router.include_router(auth.router, tags=["Auth"])
# router.include_router(tenants.router, tags=["Tenant"])
# router.include_router(items.router, tags=["Items"])
# etc.