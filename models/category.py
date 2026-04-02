from pydantic import BaseModel, Field
from typing import Optional


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, examples=["Platos Principales"])
    slug: str = Field(..., min_length=1, max_length=100, pattern=r'^[a-z0-9-]+$', examples=["platos-principales"])
    description: Optional[str] = None
    image_url: Optional[str] = None
    sort_order: int = Field(default=0)


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class CategoryResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    slug: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True
    created_at: Optional[str] = None