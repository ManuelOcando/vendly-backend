from fastapi import APIRouter, Depends, HTTPException, Query
from api.deps import get_current_tenant
from db.supabase import get_supabase_client
from typing import Optional
from pydantic import BaseModel

from services.post_sale_service import PostSaleService

router = APIRouter(prefix="/post-sale-requests")


@router.get("")
async def list_post_sale_requests(
    tenant: dict = Depends(get_current_tenant),
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
):
    """Listar solicitudes post-venta del tenant."""
    db = get_supabase_client()

    query = db.table("post_sale_requests").select("*").eq("tenant_id", tenant["id"])

    if status:
        query = query.eq("status", status)

    query = query.order("created_at", desc=True).limit(limit)
    result = query.execute()

    return result.data or []


@router.put("/{request_id}/resolve")
async def resolve_post_sale_request(
    request_id: str,
    tenant: dict = Depends(get_current_tenant),
):
    """Marcar una solicitud post-venta como resuelta y pedir calificación al cliente."""
    service = PostSaleService()
    resolved = await service.resolve_request(tenant["id"], request_id)

    if not resolved:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    return {"message": "Solicitud marcada como resuelta"}
