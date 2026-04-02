from pydantic import BaseModel, Field
from typing import Optional, List


class ItemCreate(BaseModel):
    """Para crear un producto o servicio."""
    name: str = Field(..., min_length=1, max_length=200, examples=["Hamburguesa Clásica"])
    description: Optional[str] = Field(None, examples=["Hamburguesa con queso, lechuga y tomate"])
    price: float = Field(..., gt=0, examples=[8.50])
    currency: str = Field(default="USD")
    category_id: Optional[str] = None
    type: str = Field(default="product")  # product o service
    stock_quantity: Optional[int] = Field(default=0, ge=0)
    low_stock_threshold: Optional[int] = Field(default=5, ge=0)
    track_stock: bool = Field(default=True)
    service_duration_minutes: Optional[int] = None
    is_active: bool = Field(default=True)
    is_featured: bool = Field(default=False)
    images: List[str] = Field(default=[])
    metadata: Optional[dict] = Field(default={})


class ItemUpdate(BaseModel):
    """Para actualizar un producto o servicio."""
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    category_id: Optional[str] = None
    stock_quantity: Optional[int] = None
    low_stock_threshold: Optional[int] = None
    track_stock: Optional[bool] = None
    service_duration_minutes: Optional[int] = None
    is_active: Optional[bool] = None
    is_featured: Optional[bool] = None
    images: Optional[List[str]] = None
    metadata: Optional[dict] = None


class StockUpdate(BaseModel):
    """Para actualizar solo el stock."""
    stock_quantity: int = Field(..., ge=0)


class ItemResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: Optional[str] = None
    price: float
    currency: str = "USD"
    category_id: Optional[str] = None
    type: str = "product"
    stock_quantity: Optional[int] = 0
    low_stock_threshold: Optional[int] = 5
    track_stock: bool = True
    service_duration_minutes: Optional[int] = None
    is_active: bool = True
    is_featured: bool = False
    images: Optional[List[str]] = []
    metadata: Optional[dict] = {}
    total_sold: int = 0
    likes_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None