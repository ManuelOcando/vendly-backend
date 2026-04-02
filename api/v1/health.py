from fastapi import APIRouter, Depends
from db.supabase import get_supabase_client
from db.redis import get_redis_client
from config import get_settings

router = APIRouter()


@router.get("/health")
async def health_check():
    """Verifica que el servidor está funcionando."""
    settings = get_settings()
    
    checks = {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
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
    
    # Verificar Redis
    try:
        redis = get_redis_client()
        await redis.set("health_check", "ok", ex=10)
        result = await redis.get("health_check")
        checks["redis"] = "connected" if result == "ok" else "error"
    except Exception as e:
        checks["redis"] = f"error: {str(e)}"
    
    return checks