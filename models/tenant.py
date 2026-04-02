from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class TenantCreate(BaseModel):
    """Se envía cuando un vendedor se registra."""
    name: str = Field(..., min_length=2, max_length=100, examples=["Mi Restaurante"])
    slug: str = Field(..., min_length=2, max_length=50, pattern=r'^[a-z0-9-]+$', examples=["mi-restaurante"])
    type: str = Field(..., examples=["restaurant"])  # store, restaurant, service
    description: Optional[str] = None
    whatsapp_number: Optional[str] = None


class TenantUpdate(BaseModel):
    """Para actualizar config del tenant."""
    name: Optional[str] = None
    description: Optional[str] = None
    whatsapp_number: Optional[str] = None
    bot_personality: Optional[str] = None
    bot_enabled: Optional[bool] = None
    bot_schedule: Optional[dict] = None
    payment_config: Optional[dict] = None
    store_config: Optional[dict] = None


class TenantResponse(BaseModel):
    id: str
    owner_id: str
    name: str
    slug: str
    type: str
    description: Optional[str] = None
    logo_url: Optional[str] = None
    whatsapp_number: Optional[str] = None
    whatsapp_connected: bool = False
    bot_enabled: bool = True
    bot_personality: Optional[str] = None
    bot_schedule: Optional[dict] = None
    payment_config: Optional[dict] = None
    store_config: Optional[dict] = None
    subscription_plan: str = "trial"
    subscription_expires_at: Optional[str] = None
    created_at: Optional[str] = None