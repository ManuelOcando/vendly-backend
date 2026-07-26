from fastapi import Depends, HTTPException, Header
from db.supabase import get_supabase_client
from services.multi_tenant_orchestrator import MultiTenantOrchestrator
from models.vendly_pro import PlanType


async def get_current_user(
    authorization: str = Header(None)
) -> dict:
    """
    Verifica el token JWT de Supabase y retorna el usuario.
    El frontend envía: Authorization: Bearer <token>
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no proporcionado")

    token = authorization.replace("Bearer ", "")
    db = get_supabase_client()

    try:
        user_response = db.auth.get_user(token)
        if not user_response or not user_response.user:
            raise HTTPException(status_code=401, detail="Token inválido")

        return {
            "id": user_response.user.id,
            "email": user_response.user.email,
            "metadata": user_response.user.user_metadata or {}
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Error de autenticación: {str(e)}")


async def get_current_tenant(
    current_user: dict = Depends(get_current_user)
) -> dict:
    """
    Obtiene el tenant del usuario autenticado.
    """
    db = get_supabase_client()

    response = db.table("tenants").select("*").eq(
        "owner_id", current_user["id"]
    ).execute()

    if not response.data or len(response.data) == 0:
        raise HTTPException(
            status_code=404,
            detail="No tienes un negocio configurado. Completa el registro."
        )

    return response.data[0]


async def _resolve_tenant_features(tenant_id: str) -> dict:
    """
    Obtiene las features habilitadas para un tenant según su fila en
    tenant_subscriptions. Si no existe (tenant legado, o cualquier caso
    borde), retorna las features del tier free por seguridad (fail-safe,
    nunca fail-open a premium).
    """
    orchestrator = MultiTenantOrchestrator()
    subscription = await orchestrator.get_tenant_subscription(tenant_id)
    if subscription and subscription.get("features"):
        return subscription["features"]
    return orchestrator._get_tier_features(PlanType.FREE)["features"]


async def get_tenant_features(
    tenant: dict = Depends(get_current_tenant)
) -> dict:
    """Dependencia de FastAPI: features habilitadas para el tenant actual."""
    return await _resolve_tenant_features(tenant["id"])


def require_feature(feature_name: str):
    """
    Fábrica de dependencias de FastAPI que bloquea el acceso a un endpoint
    si el tenant no tiene `feature_name` habilitada en su plan actual.

    Uso: `tenant: dict = Depends(get_current_tenant), _=Depends(require_feature("loyalty_system"))`
    """
    async def _checker(
        features: dict = Depends(get_tenant_features)
    ) -> dict:
        if not features.get(feature_name, False):
            raise HTTPException(
                status_code=403,
                detail={
                    "message": f"Esta función requiere el plan premium ({feature_name}).",
                    "feature": feature_name,
                    "upgrade_required": True
                }
            )
        return features
    return _checker


async def tenant_has_feature(tenant_id: str, feature_name: str) -> bool:
    """
    Helper de uso directo (fuera del sistema de Depends de FastAPI, p.ej.
    desde el flujo del bot de WhatsApp) para verificar si un tenant tiene
    una feature habilitada en su plan actual.
    """
    features = await _resolve_tenant_features(tenant_id)
    return bool(features.get(feature_name, False))