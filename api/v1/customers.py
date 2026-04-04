from fastapi import APIRouter, Depends
from api.deps import get_current_tenant
from db.supabase import get_supabase_client
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

router = APIRouter(prefix="/customers")


class CustomerResponse(BaseModel):
    name: Optional[str]
    phone: str
    email: Optional[str]
    total_orders: int
    total_spent: float
    last_order_date: Optional[str]
    first_order_date: Optional[str]


@router.get("", response_model=List[CustomerResponse])
async def list_customers(
    tenant: dict = Depends(get_current_tenant),
    search: Optional[str] = None,
    limit: int = 50,
):
    """Listar clientes únicos del vendedor basado en órdenes."""
    db = get_supabase_client()
    
    # Obtener todas las órdenes con info de cliente
    result = db.table("orders").select(
        "customer_name, customer_phone, customer_email, total, created_at"
    ).eq("tenant_id", tenant["id"]).execute()
    
    orders = result.data or []
    
    # Agrupar por teléfono (identificador único)
    customers_map = {}
    
    for order in orders:
        phone = order.get("customer_phone", "").strip()
        if not phone:
            continue
            
        if phone not in customers_map:
            customers_map[phone] = {
                "name": order.get("customer_name") or "Cliente",
                "phone": phone,
                "email": order.get("customer_email"),
                "total_orders": 0,
                "total_spent": 0,
                "orders_dates": []
            }
        
        customers_map[phone]["total_orders"] += 1
        customers_map[phone]["total_spent"] += float(order.get("total", 0))
        if order.get("created_at"):
            customers_map[phone]["orders_dates"].append(order["created_at"])
    
    # Convertir a lista y calcular fechas
    customers = []
    for phone, data in customers_map.items():
        dates = sorted(data["orders_dates"])
        customer = CustomerResponse(
            name=data["name"],
            phone=data["phone"],
            email=data["email"],
            total_orders=data["total_orders"],
            total_spent=data["total_spent"],
            first_order_date=dates[0] if dates else None,
            last_order_date=dates[-1] if dates else None
        )
        customers.append(customer)
    
    # Filtrar por búsqueda si se especifica
    if search:
        search_lower = search.lower()
        customers = [
            c for c in customers 
            if search_lower in (c.name or "").lower() 
            or search_lower in c.phone.lower()
            or (c.email and search_lower in c.email.lower())
        ]
    
    # Ordenar por total de órdenes (más activos primero)
    customers.sort(key=lambda x: x.total_orders, reverse=True)
    
    return customers[:limit]


@router.get("/{phone}/orders")
async def get_customer_orders(
    phone: str,
    tenant: dict = Depends(get_current_tenant)
):
    """Obtener historial de órdenes de un cliente específico."""
    db = get_supabase_client()
    
    result = db.table("orders").select("*").eq(
        "tenant_id", tenant["id"]
    ).eq("customer_phone", phone).order("created_at", desc=True).execute()
    
    return result.data or []
