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
    subscription_plan: str = "trial"
    subscription_expires_at: Optional[str] = None
    onboarding_status: str = "not_started"
    created_at: Optional[str] = None