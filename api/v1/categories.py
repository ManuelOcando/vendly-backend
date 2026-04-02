from fastapi import APIRouter, Depends, HTTPException
from api.deps import get_current_tenant
from db.supabase import get_supabase_client
from models.category import CategoryCreate, CategoryUpdate, CategoryResponse
from typing import List

router = APIRouter(prefix="/categories")


@router.get("", response_model=List[CategoryResponse])
async def list_categories(
    tenant: dict = Depends(get_current_tenant)
):
    db = get_supabase_client()
    result = db.table("categories").select("*").eq(
        "tenant_id", tenant["id"]
    ).order("sort_order").execute()
    return result.data or []


@router.post("", response_model=CategoryResponse)
async def create_category(
    data: CategoryCreate,
    tenant: dict = Depends(get_current_tenant)
):
    db = get_supabase_client()
    existing = db.table("categories").select("id").eq(
        "tenant_id", tenant["id"]
    ).eq("slug", data.slug).execute()

    if existing.data and len(existing.data) > 0:
        raise HTTPException(status_code=400, detail="Ya existe una categoria con ese slug")

    cat_data = data.model_dump()
    cat_data["tenant_id"] = tenant["id"]
    result = db.table("categories").insert(cat_data).execute()

    if not result.data or len(result.data) == 0:
        raise HTTPException(status_code=500, detail="Error al crear la categoria")
    return result.data[0]


@router.put("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: str,
    data: CategoryUpdate,
    tenant: dict = Depends(get_current_tenant)
):
    db = get_supabase_client()
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    result = db.table("categories").update(update_data).eq(
        "id", category_id
    ).eq("tenant_id", tenant["id"]).execute()

    if not result.data or len(result.data) == 0:
        raise HTTPException(status_code=404, detail="Categoria no encontrada")
    return result.data[0]


@router.delete("/{category_id}")
async def delete_category(
    category_id: str,
    tenant: dict = Depends(get_current_tenant)
):
    db = get_supabase_client()
    result = db.table("categories").delete().eq(
        "id", category_id
    ).eq("tenant_id", tenant["id"]).execute()

    if not result.data or len(result.data) == 0:
        raise HTTPException(status_code=404, detail="Categoria no encontrada")
    return {"message": "Categoria eliminada"}