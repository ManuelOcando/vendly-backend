from fastapi import APIRouter, Depends, HTTPException, Query
from api.deps import get_current_tenant
from db.supabase import get_supabase_client
from typing import Optional
from datetime import datetime
from pydantic import BaseModel

router = APIRouter(prefix="/orders")


class StatusUpdate(BaseModel):
    status: str


@router.get("")
async def list_orders(
    tenant: dict = Depends(get_current_tenant),
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
):
    """Listar pedidos del vendedor."""
    db = get_supabase_client()

    query = db.table("orders").select("*").eq(
        "tenant_id", tenant["id"]
    )

    if status:
        query = query.eq("status", status)

    query = query.order("created_at", desc=True).limit(limit)
    result = query.execute()

    return result.data or []


@router.get("/{order_id}")
async def get_order(
    order_id: str,
    tenant: dict = Depends(get_current_tenant)
):
    """Detalle de un pedido."""
    db = get_supabase_client()

    result = db.table("orders").select("*").eq(
        "id", order_id
    ).eq("tenant_id", tenant["id"]).execute()

    if not result.data or len(result.data) == 0:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    return result.data[0]


@router.put("/{order_id}/status")
async def update_order_status(
    order_id: str,
    data: StatusUpdate,
    tenant: dict = Depends(get_current_tenant)
):
    """Cambiar estado de un pedido."""
    db = get_supabase_client()

    valid_statuses = [
        "pending_payment", "payment_submitted", "payment_confirmed",
        "processing", "ready", "delivered", "cancelled"
    ]

    if data.status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Estado inválido")

    result = db.table("orders").update({
        "status": data.status,
        "updated_at": datetime.utcnow().isoformat()
    }).eq("id", order_id).eq("tenant_id", tenant["id"]).execute()

    if not result.data or len(result.data) == 0:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    return result.data[0]


@router.put("/{order_id}/confirm")
async def confirm_payment(
    order_id: str,
    tenant: dict = Depends(get_current_tenant)
):
    """Confirmar pago de un pedido."""
    db = get_supabase_client()

    result = db.table("orders").update({
        "status": "payment_confirmed",
        "updated_at": datetime.utcnow().isoformat()
    }).eq("id", order_id).eq("tenant_id", tenant["id"]).execute()

    if not result.data or len(result.data) == 0:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    return result.data[0]