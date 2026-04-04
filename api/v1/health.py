from fastapi import APIRouter, Depends, Request, Header
from db.supabase import get_supabase_client
from db.redis import get_redis_client
from config import get_settings
from middleware.rate_limiter import limiter
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
@limiter.limit("100/minute")
async def health_check(request: Request):
    """Verifica que el servidor está funcionando."""
    settings = get_settings()
    
    checks = {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": "development" if settings.DEBUG else "production",
        "supabase": "unknown",
        "redis": "unknown"
    }
    
    # Verificar Supabase
    try:
        db = get_supabase_client()
        # Intentar una query simple
        db.table("tenants").select("id").limit(1).execute()
        checks["supabase"] = "connected"
    except Exception as e:
        checks["supabase"] = f"error: {str(e)}"
        logger.warning(f"Supabase health check failed: {e}")
    
    # Verificar Redis
    try:
        redis = get_redis_client()
        await redis.set("health_check", "ok", ex=10)
        result = await redis.get("health_check")
        checks["redis"] = "connected" if result == "ok" else "error"
    except Exception as e:
        checks["redis"] = f"error: {str(e)}"
        logger.warning(f"Redis health check failed: {e}")
    
    # Determinar status general
    if "error" in checks["supabase"] or "error" in checks["redis"]:
        checks["status"] = "degraded"
    
    return checks


@router.get("/debug-auth")
@limiter.limit("100/minute")
async def debug_auth(request: Request, authorization: str = Header(None)):
    """Debug endpoint to check authentication and tenant status."""
    logger.info(f"Debug auth called with authorization: {authorization[:20] if authorization else 'None'}...")
    
    result = {
        "has_auth_header": authorization is not None,
        "auth_header_format": False,
        "user_valid": False,
        "tenant_exists": False,
        "user_id": None,
        "tenant_id": None,
        "error": None
    }
    
    # Check authorization format
    if authorization and authorization.startswith("Bearer "):
        result["auth_header_format"] = True
        token = authorization.replace("Bearer ", "")
        
        try:
            # Check user
            db = get_supabase_client()
            user_response = db.auth.get_user(token)
            if user_response and user_response.user:
                result["user_valid"] = True
                result["user_id"] = user_response.user.id
                logger.info(f"User valid: {user_response.user.id}")
                
                # Check tenant
                tenant_response = db.table("tenants").select("*").eq(
                    "owner_id", user_response.user.id
                ).execute()
                
                if tenant_response.data and len(tenant_response.data) > 0:
                    result["tenant_exists"] = True
                    result["tenant_id"] = tenant_response.data[0]["id"]
                    logger.info(f"Tenant found: {tenant_response.data[0]['id']}")
                else:
                    result["error"] = "No tenant found for user"
                    logger.warning(f"No tenant for user {user_response.user.id}")
            else:
                result["error"] = "Invalid token"
                logger.warning("Invalid token")
                
        except Exception as e:
            result["error"] = f"Auth error: {str(e)}"
            logger.error(f"Auth error: {e}")
    else:
        result["error"] = "Missing or invalid authorization header"
        logger.warning("Missing or invalid auth header")
    
    return result