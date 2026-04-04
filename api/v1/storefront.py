from fastapi import APIRouter, HTTPException, Query
from db.supabase import get_supabase_client
from typing import Optional

router = APIRouter(prefix="/store")


@router.get("/{slug}")
async def get_store(slug: str):
    """Info pública de la tienda por slug."""
    db = get_supabase_client()

    result = db.table("tenants").select(
        "id, name, slug, type, description, logo_url, whatsapp_number, store_config, subscription_plan, subscription_expires_at"
    ).eq("slug", slug).execute()

    if not result.data or len(result.data) == 0:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")

    tenant = result.data[0]

    # Verificar suscripción activa
    from datetime import datetime
    if tenant.get("subscription_expires_at"):
        expires = datetime.fromisoformat(
            tenant["subscription_expires_at"].replace("Z", "+00:00")
        )
        if expires < datetime.now(expires.tzinfo):
            raise HTTPException(status_code=403, detail="Esta tienda no está activa")

    return tenant


@router.get("/{slug}/items")
async def get_store_items(
    slug: str,
    category_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(20, le=50),
    offset: int = Query(0)
):
    """Productos públicos de la tienda."""
    db = get_supabase_client()

    # Obtener tenant
    tenant_result = db.table("tenants").select("id").eq("slug", slug).execute()
    if not tenant_result.data or len(tenant_result.data) == 0:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")

    tenant_id = tenant_result.data[0]["id"]

    # Query de items
    query = db.table("items").select(
        "id, name, description, price, currency, images, stock_quantity, track_stock, type, is_featured, category_id, likes_count, total_sold"
    ).eq("tenant_id", tenant_id).eq("is_active", True)

    if category_id:
        query = query.eq("category_id", category_id)

    if search:
        query = query.ilike("name", f"%{search}%")

    query = query.order("is_featured", desc=True).order("created_at", desc=True)
    query = query.range(offset, offset + limit - 1)

    result = query.execute()
    return result.data or []


@router.get("/{slug}/categories")
async def get_store_categories(slug: str):
    """Categorías públicas de la tienda."""
    db = get_supabase_client()

    tenant_result = db.table("tenants").select("id").eq("slug", slug).execute()
    if not tenant_result.data or len(tenant_result.data) == 0:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")

    tenant_id = tenant_result.data[0]["id"]

    result = db.table("categories").select("*").eq(
        "tenant_id", tenant_id
    ).eq("is_active", True).order("sort_order").execute()

    return result.data or []


@router.post("/{slug}/cart")
async def create_cart(slug: str, data: dict):
    """Crear un carrito para un cliente usando Redis."""
    from api.v1.cart import CreateCartRequest, CartItem, create_cart as create_cart_service
    
    db = get_supabase_client()

    tenant_result = db.table("tenants").select("id").eq("slug", slug).execute()
    if not tenant_result.data or len(tenant_result.data) == 0:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")

    tenant_id = tenant_result.data[0]["id"]

    # Convertir items al formato esperado
    cart_items = []
    for item_req in data.get("items", []):
        # Verificar que el item existe y está activo
        item_result = db.table("items").select("id, name, price, stock_quantity, track_stock").eq(
            "id", item_req["item_id"]
        ).eq("tenant_id", tenant_id).eq("is_active", True).execute()

        if not item_result.data:
            continue

        item = item_result.data[0]
        quantity = item_req.get("quantity", 1)
        
        cart_items.append(CartItem(
            item_id=item["id"],
            name=item["name"],
            price=item["price"],
            quantity=quantity
        ))

    if not cart_items:
        raise HTTPException(status_code=400, detail="No valid items in cart")

    # Usar el servicio de carrito con Redis
    cart_request = CreateCartRequest(
        store_id=tenant_id,
        items=cart_items
    )
    
    result = await create_cart_service(cart_request)
    
    return result