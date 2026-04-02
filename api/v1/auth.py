from fastapi import APIRouter, Depends, HTTPException
from api.deps import get_current_user
from db.supabase import get_supabase_client
from models.tenant import TenantCreate, TenantResponse

router = APIRouter(prefix="/auth")


@router.post("/register-tenant", response_model=TenantResponse)
async def register_tenant(
    data: TenantCreate,
    current_user: dict = Depends(get_current_user)
):
    """
    Crear tenant para el usuario recién registrado.
    El frontend primero hace signup con Supabase Auth,
    luego llama a este endpoint para crear el negocio.
    """
    db = get_supabase_client()

    # Verificar que no tenga ya un tenant
    existing = db.table("tenants").select("id").eq(
        "owner_id", current_user["id"]
    ).execute()

    if existing.data and len(existing.data) > 0:
        raise HTTPException(status_code=400, detail="Ya tienes un negocio registrado")

    # Verificar que el slug no exista
    slug_check = db.table("tenants").select("id").eq(
        "slug", data.slug
    ).execute()

    if slug_check.data and len(slug_check.data) > 0:
        raise HTTPException(status_code=400, detail="Ese nombre de tienda ya está en uso")

    # Crear tenant
    tenant_data = {
        "owner_id": current_user["id"],
        "name": data.name,
        "slug": data.slug,
        "type": data.type,
        "description": data.description,
        "whatsapp_number": data.whatsapp_number,
    }

    result = db.table("tenants").insert(tenant_data).execute()

    if not result.data or len(result.data) == 0:
        raise HTTPException(status_code=500, detail="Error al crear el negocio")

    return result.data[0]


@router.get("/me")
async def get_me(
    current_user: dict = Depends(get_current_user)
):
    """
    Retorna el usuario actual y su tenant (si tiene).
    """
    db = get_supabase_client()

    tenant_response = db.table("tenants").select("*").eq(
        "owner_id", current_user["id"]
    ).execute()

    tenant = tenant_response.data[0] if tenant_response.data and len(tenant_response.data) > 0 else None

    return {
        "user": current_user,
        "tenant": tenant
    }