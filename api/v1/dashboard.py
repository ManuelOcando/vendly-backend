from fastapi import APIRouter, Depends
from api.deps import get_current_tenant
from db.supabase import get_supabase_client

router = APIRouter(prefix="/dashboard")


@router.get("/stats")
async def get_stats(
    tenant: dict = Depends(get_current_tenant)
):
    """Métricas básicas del dashboard."""
    db = get_supabase_client()
    tid = tenant["id"]

    # Total productos activos
    items_result = db.table("items").select("id", count="exact").eq(
        "tenant_id", tid
    ).eq("is_active", True).execute()

    # Total pedidos
    orders_result = db.table("orders").select("id, total, status", count="exact").eq(
        "tenant_id", tid
    ).execute()

    # Calcular totales
    total_revenue = 0
    pending_orders = 0
    completed_orders = 0

    if orders_result.data:
        for order in orders_result.data:
            if order.get("status") in ["payment_confirmed", "processing", "ready", "delivered"]:
                total_revenue += float(order.get("total", 0) or 0)
                completed_orders += 1
            if order.get("status") in ["pending_payment", "payment_submitted"]:
                pending_orders += 1

    # Productos con stock bajo
    low_stock = db.table("items").select("id, name, stock_quantity, low_stock_threshold").eq(
        "tenant_id", tid
    ).eq("is_active", True).eq("track_stock", True).execute()

    low_stock_items = []
    if low_stock.data:
        for item in low_stock.data:
            qty = item.get("stock_quantity", 0) or 0
            threshold = item.get("low_stock_threshold", 5) or 5
            if qty <= threshold:
                low_stock_items.append(item)

    return {
        "total_products": items_result.count or 0,
        "total_orders": len(orders_result.data) if orders_result.data else 0,
        "completed_orders": completed_orders,
        "pending_orders": pending_orders,
        "total_revenue": total_revenue,
        "low_stock_items": low_stock_items,
        "currency": "USD"
    }


@router.get("/top-items")
async def get_top_items(
    tenant: dict = Depends(get_current_tenant)
):
    """Top 5 productos más vendidos."""
    db = get_supabase_client()

    result = db.table("items").select("id, name, total_sold, price, images").eq(
        "tenant_id", tenant["id"]
    ).eq("is_active", True).order(
        "total_sold", desc=True
    ).limit(5).execute()

    return result.data or []