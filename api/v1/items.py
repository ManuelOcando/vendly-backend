from fastapi import APIRouter, Depends, HTTPException, Query
from api.deps import get_current_tenant
from db.supabase import get_supabase_client
from models.item import ItemCreate, ItemUpdate, ItemResponse, StockUpdate
from typing import Optional, List
from datetime import datetime

router = APIRouter(prefix="/items")


@router.get("", response_model=List[ItemResponse])
async def list_items(
    tenant: dict = Depends(get_current_tenant),
    category_id: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None)
):
    """Listar productos/servicios del vendedor."""
    db = get_supabase_client()

    query = db.table("items").select("*").eq("tenant_id", tenant["id"])

    if category_id:
        query = query.eq("category_id", category_id)
    if type:
        query = query.eq("type", type)
    if is_active is not None:
        query = query.eq("is_active", is_active)
    if search:
        query = query.ilike("name", f"%{search}%")

    query = query.order("created_at", desc=True)
    result = query.execute()

    return result.data or []


@router.post("", response_model=ItemResponse)
async def create_item(
    data: ItemCreate,
    tenant: dict = Depends(get_current_tenant)
):
    """Crear un producto o servicio."""
    db = get_supabase_client()
    
    logger = logging.getLogger(__name__)
    logger.info(f"Creating item for tenant: {tenant['id']}")
    logger.info(f"Item data: {data}")

    item_data = data.model_dump(exclude={'id'})
    item_data["tenant_id"] = tenant["id"]
    item_data["search_text"] = f"{data.name} {data.description or ''}"
    
    logger.info(f"Final item data for insert: {item_data}")

    try:
        result = db.table("items").insert(item_data).execute()
        logger.info(f"Insert result: {result}")
        
        if not result.data or len(result.data) == 0:
            logger.error("Insert returned no data")
            raise HTTPException(status_code=500, detail="Error al crear el producto")

        return result.data[0]
    except Exception as e:
        logger.error(f"Database error during item creation: {str(e)}")
        logger.error(f"Error details: {type(e).__name__}")
        raise HTTPException(status_code=500, detail=f"Error de base de datos: {str(e)}")


@router.get("/{item_id}", response_model=ItemResponse)
async def get_item(
    item_id: str,
    tenant: dict = Depends(get_current_tenant)
):
    """Obtener un producto por ID."""
    db = get_supabase_client()

    result = db.table("items").select("*").eq(
        "id", item_id
    ).eq(
        "tenant_id", tenant["id"]
    ).execute()

    if not result.data or len(result.data) == 0:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    return result.data[0]


@router.put("/{item_id}", response_model=ItemResponse)
async def update_item(
    item_id: str,
    data: ItemUpdate,
    tenant: dict = Depends(get_current_tenant)
):
    """Actualizar un producto."""
    db = get_supabase_client()

    # Verificar que existe y pertenece al tenant
    existing = db.table("items").select("id").eq(
        "id", item_id
    ).eq(
        "tenant_id", tenant["id"]
    ).execute()

    if not existing.data or len(existing.data) == 0:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    # Solo enviar campos que no son None
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    update_data["updated_at"] = datetime.utcnow().isoformat()

    # Actualizar search_text si cambió nombre o descripción
    if "name" in update_data or "description" in update_data:
        current = db.table("items").select("name, description").eq("id", item_id).execute()
        if current.data:
            name = update_data.get("name", current.data[0].get("name", ""))
            desc = update_data.get("description", current.data[0].get("description", ""))
            update_data["search_text"] = f"{name} {desc or ''}"

    result = db.table("items").update(update_data).eq(
        "id", item_id
    ).eq(
        "tenant_id", tenant["id"]
    ).execute()

    if not result.data or len(result.data) == 0:
        raise HTTPException(status_code=500, detail="Error al actualizar")

    return result.data[0]


@router.delete("/{item_id}")
async def delete_item(
    item_id: str,
    tenant: dict = Depends(get_current_tenant)
):
    """Eliminar un producto."""
    db = get_supabase_client()

    result = db.table("items").delete().eq(
        "id", item_id
    ).eq(
        "tenant_id", tenant["id"]
    ).execute()

    if not result.data or len(result.data) == 0:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    return {"message": "Producto eliminado"}


@router.put("/{item_id}/stock", response_model=ItemResponse)
async def update_stock(
    item_id: str,
    data: StockUpdate,
    tenant: dict = Depends(get_current_tenant)
):
    """Actualizar solo el stock de un producto."""
    db = get_supabase_client()

    result = db.table("items").update({
        "stock_quantity": data.stock_quantity,
        "updated_at": datetime.utcnow().isoformat()
    }).eq(
        "id", item_id
    ).eq(
        "tenant_id", tenant["id"]
    ).execute()

    if not result.data or len(result.data) == 0:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    return result.data[0]