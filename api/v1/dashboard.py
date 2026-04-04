from fastapi import APIRouter, Depends, HTTPException
from api.deps import get_current_tenant
from db.supabase import get_supabase_client
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta

router = APIRouter(prefix="/dashboard")

class StockUpdate(BaseModel):
    item_id: str
    quantity: int

class WhatsAppConnection(BaseModel):
    phone_number: str
    instance_name: str


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


@router.get("/orders")
async def get_orders(
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    tenant: dict = Depends(get_current_tenant)
):
    """Obtener pedidos del vendedor."""
    db = get_supabase_client()
    
    query = db.table("orders").select("*").eq("tenant_id", tenant["id"])
    
    if status:
        query = query.eq("status", status)
    
    query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
    
    result = query.execute()
    return result.data or []


@router.get("/stock")
async def get_stock_status(
    tenant: dict = Depends(get_current_tenant)
):
    """Obtener estado completo del inventario."""
    db = get_supabase_client()
    
    result = db.table("items").select(
        "id, name, stock_quantity, track_stock, low_stock_threshold, price, images"
    ).eq("tenant_id", tenant["id"]).eq("is_active", True).execute()
    
    items = []
    if result.data:
        for item in result.data:
            if item.get("track_stock", False):
                quantity = item.get("stock_quantity", 0) or 0
                threshold = item.get("low_stock_threshold", 5) or 5
                
                items.append({
                    **item,
                    "stock_status": "low" if quantity <= threshold else "normal",
                    "needs_restock": quantity <= threshold
                })
    
    return items


@router.put("/stock")
async def update_stock(
    updates: List[StockUpdate],
    tenant: dict = Depends(get_current_tenant)
):
    """Actualizar stock de productos."""
    db = get_supabase_client()
    
    updated_items = []
    errors = []
    
    for update in updates:
        try:
            # Verificar que el item pertenece al tenant
            item_result = db.table("items").select("id, name").eq(
                "tenant_id", tenant["id"]
            ).eq("id", update.item_id).eq("is_active", True).execute()
            
            if not item_result.data:
                errors.append(f"Item {update.item_id} no encontrado")
                continue
            
            # Actualizar stock
            result = db.table("items").update({
                "stock_quantity": update.quantity,
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", update.item_id).execute()
            
            if result.data:
                updated_items.append({
                    "item_id": update.item_id,
                    "name": item_result.data[0]["name"],
                    "new_quantity": update.quantity
                })
            else:
                errors.append(f"Error actualizando item {update.item_id}")
                
        except Exception as e:
            errors.append(f"Error en item {update.item_id}: {str(e)}")
    
    return {
        "updated_items": updated_items,
        "errors": errors,
        "total_updated": len(updated_items),
        "total_errors": len(errors)
    }


@router.get("/whatsapp/status")
async def get_whatsapp_status(
    tenant: dict = Depends(get_current_tenant)
):
    """Obtener estado de conexión WhatsApp."""
    try:
        db = get_supabase_client()
        
        result = db.table("whatsapp_connections").select("*").eq(
            "tenant_id", tenant["id"]
        ).execute()
        
        if not result.data:
            return {"connected": False, "connections": []}
        
        connections = result.data
        active_connection = None
        
        for conn in connections:
            if conn["status"] == "connected":
                active_connection = conn
                break
        
        return {
            "connected": active_connection is not None,
            "active_connection": active_connection,
            "all_connections": connections
        }
    except Exception as e:
        # Si la tabla no existe, retornar desconectado sin error
        return {"connected": False, "connections": [], "error": str(e)}


@router.post("/whatsapp/connect")
async def connect_whatsapp(
    connection: WhatsAppConnection,
    tenant: dict = Depends(get_current_tenant)
):
    """Iniciar conexión WhatsApp."""
    # Usar el servicio de WhatsApp existente
    from api.v1.whatsapp import WhatsAppConnection as WhatsAppConnectionModel
    
    try:
        # Crear instancia en Evolution API
        whatsapp_conn = WhatsAppConnectionModel(
            store_id=tenant["id"],
            phone_number=connection.phone_number,
            instance_name=connection.instance_name
        )
        
        # Llamar al endpoint de conexión
        from api.v1.whatsapp import connect_whatsapp as connect_service
        result = await connect_service(whatsapp_conn)
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/daily-summary")
async def get_daily_summary(
    days: int = 7,
    tenant: dict = Depends(get_current_tenant)
):
    """Obtener resumen de los últimos días."""
    db = get_supabase_client()
    
    # Calcular fecha de inicio
    start_date = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
    
    # Obtener pedidos del período
    orders_result = db.table("orders").select(
        "created_at, total, status, customer_phone"
    ).eq("tenant_id", tenant["id"]).gte("created_at", start_date).execute()
    
    # Agrupar por día
    daily_data = {}
    total_revenue = 0
    total_orders = 0
    
    if orders_result.data:
        for order in orders_result.data:
            order_date = order["created_at"][:10]  # YYYY-MM-DD
            
            if order_date not in daily_data:
                daily_data[order_date] = {
                    "orders": 0,
                    "revenue": 0,
                    "completed": 0,
                    "pending": 0
                }
            
            daily_data[order_date]["orders"] += 1
            daily_data[order_date]["revenue"] += float(order.get("total", 0) or 0)
            total_orders += 1
            
            if order["status"] in ["completed", "delivered"]:
                daily_data[order_date]["completed"] += 1
                total_revenue += float(order.get("total", 0) or 0)
            elif order["status"] in ["pending", "payment_pending"]:
                daily_data[order_date]["pending"] += 1
    
    return {
        "period_days": days,
        "total_orders": total_orders,
        "total_revenue": total_revenue,
        "daily_breakdown": daily_data,
        "average_daily_orders": total_orders / days if days > 0 else 0,
        "average_daily_revenue": total_revenue / days if days > 0 else 0
    }