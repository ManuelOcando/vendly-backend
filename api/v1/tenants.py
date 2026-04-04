from fastapi import APIRouter, Depends, HTTPException
from api.deps import get_current_tenant, get_current_user
from db.supabase import get_supabase_client
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/tenants")


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    whatsapp_number: Optional[str] = None
    currency: Optional[str] = None
    address: Optional[str] = None
    social_links: Optional[dict] = None


@router.get("/me")
async def get_my_tenant(
    tenant: dict = Depends(get_current_tenant)
):
    """Obtener información del tenant actual."""
    return tenant


@router.put("/me")
async def update_my_tenant(
    data: TenantUpdate,
    tenant: dict = Depends(get_current_tenant)
):
    """Actualizar información del negocio."""
    db = get_supabase_client()
    
    # Construir datos a actualizar
    update_data = {}
    if data.name is not None:
        update_data["name"] = data.name
    if data.slug is not None:
        # Verificar que el slug sea único
        if data.slug != tenant.get("slug"):
            existing = db.table("tenants").select("id").eq("slug", data.slug).execute()
            if existing.data and len(existing.data) > 0:
                raise HTTPException(status_code=400, detail="Este slug ya está en uso")
        update_data["slug"] = data.slug
    if data.description is not None:
        update_data["description"] = data.description
    if data.logo_url is not None:
        update_data["logo_url"] = data.logo_url
    if data.primary_color is not None:
        update_data["primary_color"] = data.primary_color
    if data.secondary_color is not None:
        update_data["secondary_color"] = data.secondary_color
    if data.whatsapp_number is not None:
        update_data["whatsapp_number"] = data.whatsapp_number
    if data.currency is not None:
        update_data["currency"] = data.currency
    if data.address is not None:
        update_data["address"] = data.address
    if data.social_links is not None:
        update_data["social_links"] = data.social_links
    
    if not update_data:
        raise HTTPException(status_code=400, detail="No hay datos para actualizar")
    
    result = db.table("tenants").update(update_data).eq("id", tenant["id"]).execute()
    
    if not result.data:
        raise HTTPException(status_code=500, detail="Error al actualizar")
    
    return result.data[0]


@router.post("/check-slug")
async def check_slug_available(
    slug: str,
    tenant: dict = Depends(get_current_tenant)
):
    """Verificar si un slug está disponible."""
    db = get_supabase_client()
    
    result = db.table("tenants").select("id").eq("slug", slug).execute()
    
    is_available = not (result.data and len(result.data) > 0)
    
    # Si el slug pertenece al tenant actual, está disponible para él
    if result.data and result.data[0]["id"] == tenant["id"]:
        is_available = True
    
    return {"available": is_available, "slug": slug}
