"""
Multi-Tenant Orchestrator Service

Manages tenant lifecycle, identification, and resource allocation for Vendly Pro.
Implements multi-tenant architecture with industry-specific templates and automatic scaling.
"""
from typing import Dict, Any, Optional, List
from datetime import datetime
import logging
import uuid

from db.supabase import get_supabase_client
from models.tenant import TenantCreate, TenantUpdate, TenantResponse
from models.vendly_pro import (
    IndustryType, PlanType, SubscriptionStatus, TenantSubscriptionCreate
)

logger = logging.getLogger(__name__)


class MultiTenantOrchestrator:
    """
    Orchestrates multi-tenant operations including:
    - Tenant creation with industry templates
    - Tenant identification by phone_number_id
    - Resource scaling based on usage metrics
    """
    
    def __init__(self):
        self._db = None
        self._templates = None
    
    @property
    def db(self):
        """Lazy load database client"""
        if self._db is None:
            self._db = get_supabase_client()
        return self._db
    
    @db.setter
    def db(self, value):
        """Allow setting db for testing"""
        self._db = value
    
    @property
    def _industry_templates(self):
        """Lazy load industry templates"""
        if self._templates is None:
            self._templates = self._load_industry_templates()
        return self._templates
    
    @_industry_templates.setter
    def _industry_templates(self, value):
        self._templates = value
    
    def _load_industry_templates(self) -> Dict[str, Any]:
        """Load default industry templates"""
        return {
            IndustryType.RESTAURANT: {
                "name": "Restaurant Template",
                "industry": IndustryType.RESTAURANT,
                "configuration": {
                    "default_categories": [
                        {"name": "Entradas", "order": 1},
                        {"name": "Platos Principales", "order": 2},
                        {"name": "Postres", "order": 3},
                        {"name": "Bebidas", "order": 4}
                    ],
                    "workflow_templates": [
                        "order_flow",
                        "customization_flow",
                        "special_requests"
                    ],
                    "message_templates": {
                        "greeting": "¡Hola! 👋 Bienvenido a {store_name}. ¿Qué te gustaría ordenar hoy?",
                        "order_confirmation": "✅ ¡Pedido confirmado! Tu número es {order_number}.",
                        "delivery_estimate": "⏰ Tiempo estimado de entrega: {time} minutos."
                    }
                },
                "default_messages": {
                    "welcome": "¡Bienvenido a {store_name}! 🍽️\n\n¿Qué te gustaría ordenar hoy?\n\nEscribe 'menu' para ver nuestros productos.",
                    "hours": "🕒 Nuestros horarios son:\n• Lunes a Viernes: 11:00 AM - 10:00 PM\n• Sábado: 11:00 AM - 11:00 PM\n• Domingo: 12:00 PM - 9:00 PM",
                    "delivery": "🚚 Realizamos entregas a domicilio en un radio de {distance} km.\n• Entrega gratuita en pedidos mayores a ${amount}"
                }
            },
            IndustryType.RETAIL: {
                "name": "Retail Template",
                "industry": IndustryType.RETAIL,
                "configuration": {
                    "default_categories": [
                        {"name": "Ropa", "order": 1},
                        {"name": "Accesorios", "order": 2},
                        {"name": "Calzado", "order": 3},
                        {"name": "Promociones", "order": 4}
                    ],
                    "workflow_templates": [
                        "product_inquiry",
                        "size_guide",
                        "shipping_info",
                        "return_policy"
                    ],
                    "message_templates": {
                        "greeting": "¡Hola! 👋 Bienvenido a {store_name}. ¿En qué puedo ayudarte?",
                        "order_confirmation": "✅ ¡Orden confirmada! Número: {order_number}",
                        "shipping": "📦 Tu orden será enviada en {days} días hábiles."
                    }
                },
                "default_messages": {
                    "welcome": "¡Bienvenido a {store_name}! 🛍️\n\n¿Qué te gustaría comprar hoy?\n\nEscribe 'menu' para ver nuestros productos.",
                    "shipping": "🚚 Envíos a todo el país:\n• Standard: 3-5 días hábiles\n• Express: 1-2 días hábiles\n• Retiro en tienda: Disponible",
                    "returns": "🔄 Política de devoluciones:\n• 30 días para devolución\n• Productos sin usar\n• Con etiqueta original"
                }
            },
            IndustryType.SERVICES: {
                "name": "Services Template",
                "industry": IndustryType.SERVICES,
                "configuration": {
                    "default_categories": [
                        {"name": "Servicios Básicos", "order": 1},
                        {"name": "Servicios Premium", "order": 2},
                        {"name": "Consultorías", "order": 3}
                    ],
                    "workflow_templates": [
                        "appointment_booking",
                        "service_inquiry",
                        "quote_request",
                        "follow_up"
                    ],
                    "message_templates": {
                        "greeting": "¡Hola! 👋 Bienvenido a {store_name}. ¿Cómo podemos ayudarte?",
                        "appointment_confirmed": "✅ ¡Cita confirmada! {date} a las {time}",
                        "availability": "📅 Disponibilidad actual:\n{days}"
                    }
                },
                "default_messages": {
                    "welcome": "¡Bienvenido a {store_name}! 🛠️\n\n¿Qué servicio te gustaría solicitar hoy?\n\nEscribe 'agendar' para reservar una cita.",
                    "appointments": "📅 Agenda tus citas con nosotros:\n• Lunes a Viernes: 9:00 AM - 8:00 PM\n• Sábado: 10:00 AM - 6:00 PM\n\nEscribe 'agendar' para reservar.",
                    "services": "🔧 Nuestros servicios:\n• Servicio Básico: ${price_basic}\n• Servicio Premium: ${price_premium}\n• Consultoría: ${price_consultation}"
                }
            }
        }
    
    async def create_tenant(
        self,
        owner_id: str,
        industry: str,
        tier: str = "free",
        tenant_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a new tenant with industry-specific template.
        
        Args:
            owner_id: ID of the tenant owner
            industry: Industry type (restaurant, retail, services)
            tier: Subscription tier (free, premium, enterprise)
            tenant_data: Optional additional tenant data
            
        Returns:
            Created tenant information
        """
        try:
            # Validate industry
            if industry not in [ind.value for ind in IndustryType]:
                logger.warning(f"Invalid industry '{industry}', defaulting to restaurant")
                industry = IndustryType.RESTAURANT.value
            
            # Generate slug from name
            name = tenant_data.get("name", f"Tenant {owner_id[:8]}") if tenant_data else f"Tenant {owner_id[:8]}"
            slug = name.lower().replace(" ", "-").replace(".", "")[:50]
            
            # Create base tenant
            tenant_create = {
                "owner_id": owner_id,
                "name": name,
                "slug": slug,
                "type": industry,
                "description": tenant_data.get("description") if tenant_data else None,
                "whatsapp_number": tenant_data.get("whatsapp_number") if tenant_data else None,
                "created_at": datetime.now().isoformat()
            }
            
            result = self.db.table("tenants").insert(tenant_create).execute()
            tenant = result.data[0] if result.data else None
            
            if not tenant:
                raise Exception("Failed to create tenant")
            
            tenant_id = tenant["id"]
            logger.info(f"Created tenant {tenant_id} for owner {owner_id}")
            
            # Apply industry template
            await self._apply_industry_template(tenant_id, industry)
            
            # Create subscription
            await self._create_subscription(tenant_id, tier)
            
            # Create default WhatsApp config
            await self._create_whatsapp_config(tenant_id)
            
            # Create default seller config
            if tenant_data and tenant_data.get("seller_phone"):
                await self._update_seller_phone(tenant_id, tenant_data["seller_phone"])
            
            return tenant
            
        except Exception as e:
            logger.error(f"Error creating tenant: {e}")
            raise
    
    async def _apply_industry_template(self, tenant_id: str, industry: str) -> None:
        """Apply industry-specific template to tenant"""
        try:
            template = self._industry_templates.get(industry)
            if not template:
                logger.warning(f"No template found for industry '{industry}'")
                return
            
            # Update tenant with industry type
            self.db.table("tenants").update({
                "type": industry
            }).eq("id", tenant_id).execute()
            
            # Create default categories from template
            categories = template["configuration"].get("default_categories", [])
            for category in categories:
                self.db.table("categories").insert({
                    "tenant_id": tenant_id,
                    "name": category["name"],
                    "order": category["order"],
                    "is_active": True
                }).execute()
            
            logger.info(f"Applied {industry} template to tenant {tenant_id}")
            
        except Exception as e:
            logger.error(f"Error applying industry template: {e}")
            raise
    
    async def _create_subscription(self, tenant_id: str, tier: str) -> None:
        """Create initial subscription for tenant"""
        try:
            # Determine plan type
            plan_map = {
                "free": PlanType.FREE,
                "premium": PlanType.PREMIUM,
                "enterprise": PlanType.ENTERPRISE
            }
            plan_type = plan_map.get(tier, PlanType.FREE)
            
            # Set features and limits based on tier
            features_limits = self._get_tier_features(plan_type)
            
            # Create subscription
            subscription = TenantSubscriptionCreate(
                tenant_id=tenant_id,
                plan_type=plan_type,
                features=features_limits["features"],
                limits=features_limits["limits"],
                current_period_start=datetime.now(),
                current_period_end=datetime.now().replace(month=datetime.now().month + 1),
                status=SubscriptionStatus.ACTIVE
            )
            
            self.db.table("tenant_subscriptions").insert({
                "tenant_id": tenant_id,
                "plan_type": plan_type.value,
                "features": subscription.features,
                "limits": subscription.limits,
                "current_period_start": subscription.current_period_start.isoformat(),
                "current_period_end": subscription.current_period_end.isoformat(),
                "status": subscription.status.value
            }).execute()
            
            logger.info(f"Created {tier} subscription for tenant {tenant_id}")
            
        except Exception as e:
            logger.error(f"Error creating subscription: {e}")
            raise
    
    def _get_tier_features(self, plan_type: PlanType) -> Dict[str, Any]:
        """Get features and limits for each tier"""
        tiers = {
            PlanType.FREE: {
                "features": {
                    "bot_enabled": True,
                    "conversational_dashboard": False,
                    "loyalty_system": False,
                    "analytics": False,
                    "external_integrations": False,
                    "multi_language": False,
                    "advanced_recommendations": False
                },
                "limits": {
                    "products": 100,
                    "messages_per_hour": 100,
                    "customers": 1000,
                    "storage_mb": 100
                }
            },
            PlanType.PREMIUM: {
                "features": {
                    "bot_enabled": True,
                    "conversational_dashboard": True,
                    "loyalty_system": True,
                    "analytics": True,
                    "external_integrations": True,
                    "multi_language": True,
                    "advanced_recommendations": True
                },
                "limits": {
                    "products": 10000,
                    "messages_per_hour": 1000,
                    "customers": 100000,
                    "storage_mb": 1000
                }
            },
            PlanType.ENTERPRISE: {
                "features": {
                    "bot_enabled": True,
                    "conversational_dashboard": True,
                    "loyalty_system": True,
                    "analytics": True,
                    "external_integrations": True,
                    "multi_language": True,
                    "advanced_recommendations": True,
                    "dedicated_support": True,
                    "custom_integration": True
                },
                "limits": {
                    "products": -1,  # Unlimited
                    "messages_per_hour": -1,  # Unlimited
                    "customers": -1,  # Unlimited
                    "storage_mb": -1  # Unlimited
                }
            }
        }
        return tiers[plan_type]
    
    async def _create_whatsapp_config(self, tenant_id: str) -> None:
        """Create default WhatsApp configuration for tenant"""
        try:
            config = {
                "tenant_id": tenant_id,
                "bot_enabled": True,
                "bot_personality": "casual",
                "bot_schedule": {
                    "monday": {"start": "11:00", "end": "22:00"},
                    "tuesday": {"start": "11:00", "end": "22:00"},
                    "wednesday": {"start": "11:00", "end": "22:00"},
                    "thursday": {"start": "11:00", "end": "22:00"},
                    "friday": {"start": "11:00", "end": "23:00"},
                    "saturday": {"start": "11:00", "end": "23:00"},
                    "sunday": {"start": "12:00", "end": "21:00"}
                },
                "payment_config": {
                    "methods": ["bank_transfer", "cash"],
                    "required": False
                },
                "store_config": {
                    "currency": "VES",
                    "timezone": "America/Caracas"
                }
            }
            
            self.db.table("whatsapp_configs").insert(config).execute()
            logger.info(f"Created WhatsApp config for tenant {tenant_id}")
            
        except Exception as e:
            logger.error(f"Error creating WhatsApp config: {e}")
            raise
    
    async def _update_seller_phone(self, tenant_id: str, seller_phone: str) -> None:
        """Update seller phone in WhatsApp config"""
        try:
            self.db.table("whatsapp_configs").update({
                "seller_phone": seller_phone
            }).eq("tenant_id", tenant_id).execute()
            logger.info(f"Updated seller phone for tenant {tenant_id}")
        except Exception as e:
            logger.error(f"Error updating seller phone: {e}")
            raise
    
    async def get_tenant_by_phone_number(self, phone_number_id: str) -> Optional[Dict[str, Any]]:
        """
        Map WhatsApp phone_number_id to tenant.
        
        Args:
            phone_number_id: Meta WhatsApp phone_number_id
            
        Returns:
            Tenant information or None if not found
        """
        try:
            # First, try to find by phone_number_id in whatsapp_configs
            result = self.db.table("whatsapp_configs").select(
                "tenant_id, phone_number"
            ).eq("phone_number_id", phone_number_id).execute()
            
            if result.data and result.data[0]:
                config = result.data[0]
                tenant_id = config["tenant_id"]
                
                # Get full tenant info
                tenant = await self._get_tenant_by_id(tenant_id)
                if tenant:
                    tenant["phone_number"] = config.get("phone_number")
                    return tenant
            
            # Fallback: search by phone_number in tenants table
            # This handles cases where phone_number_id mapping doesn't exist yet
            result = self.db.table("tenants").select("id, name, slug, type").execute()
            
            for tenant in result.data:
                # Check if this tenant has a WhatsApp config with this phone_number_id
                config_result = self.db.table("whatsapp_configs").select("phone_number_id").eq(
                    "tenant_id", tenant["id"]
                ).execute()
                
                for config in config_result.data:
                    if config.get("phone_number_id") == phone_number_id:
                        return tenant
            
            logger.warning(f"No tenant found for phone_number_id: {phone_number_id}")
            return None
            
        except Exception as e:
            logger.error(f"Error getting tenant by phone_number_id: {e}")
            return None
    
    async def _get_tenant_by_id(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get tenant by ID"""
        try:
            result = self.db.table("tenants").select("*").eq("id", tenant_id).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error getting tenant by ID: {e}")
            return None
    
    async def scale_tenant_resources(
        self,
        tenant_id: str,
        metrics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Scale tenant resources based on usage metrics.
        
        Args:
            tenant_id: Tenant identifier
            metrics: Usage metrics including message_count, active_users, etc.
            
        Returns:
            Scaling action taken and new resource allocation
        """
        try:
            # Get current subscription
            subscription = await self._get_tenant_subscription(tenant_id)
            if not subscription:
                return {"action": "none", "reason": "No subscription found"}
            
            plan_type = subscription.get("plan_type", "free")
            limits = subscription.get("limits", {})
            
            # Check if scaling is needed
            scaling_action = self._determine_scaling_action(plan_type, metrics, limits)
            
            if scaling_action["action"] == "scale_up":
                # Check if tier upgrade is needed
                current_tier = self._get_tier_from_plan(plan_type)
                new_tier = self._suggest_tier_upgrade(current_tier, metrics, limits)
                
                if new_tier != current_tier:
                    await self._upgrade_tenant_tier(tenant_id, new_tier)
                    scaling_action["new_tier"] = new_tier
                    scaling_action["reason"] = f"Upgraded to {new_tier} tier due to high usage"
            
            logger.info(f"Scaling action for tenant {tenant_id}: {scaling_action}")
            return scaling_action
            
        except Exception as e:
            logger.error(f"Error scaling tenant resources: {e}")
            return {"action": "none", "reason": str(e)}
    
    def _determine_scaling_action(
        self,
        plan_type: str,
        metrics: Dict[str, Any],
        limits: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Determine what scaling action is needed"""
        message_count = metrics.get("message_count", 0)
        active_users = metrics.get("active_users", 0)
        
        # Check message limits
        message_limit = limits.get("messages_per_hour", 100)
        if message_limit > 0 and message_count > message_limit * 1.2:  # 20% over limit
            return {
                "action": "scale_up",
                "current_messages": message_count,
                "limit": message_limit,
                "reason": "Message rate exceeds limit"
            }
        
        # Check active user limits
        user_limit = limits.get("customers", 1000)
        if user_limit > 0 and active_users > user_limit * 1.2:
            return {
                "action": "scale_up",
                "current_users": active_users,
                "limit": user_limit,
                "reason": "Active users exceed limit"
            }
        
        return {"action": "none", "reason": "Within limits"}
    
    def _get_tier_from_plan(self, plan_type: str) -> str:
        """Convert plan type to tier name"""
        plan_to_tier = {
            "free": "free",
            "premium": "premium",
            "enterprise": "enterprise"
        }
        return plan_to_tier.get(plan_type, "free")
    
    def _suggest_tier_upgrade(
        self,
        current_tier: str,
        metrics: Dict[str, Any],
        limits: Dict[str, Any]
    ) -> str:
        """Suggest tier upgrade based on usage"""
        message_count = metrics.get("message_count", 0)
        active_users = metrics.get("active_users", 0)
        
        # Check if enterprise tier is needed
        if current_tier == "free":
            if message_count > 500 or active_users > 5000:
                return "premium"
        
        if current_tier == "premium":
            if message_count > 5000 or active_users > 50000:
                return "enterprise"
        
        return current_tier
    
    async def _upgrade_tenant_tier(self, tenant_id: str, new_tier: str) -> None:
        """Upgrade tenant to new tier"""
        try:
            # Get current subscription
            result = self.db.table("tenant_subscriptions").select("*").eq(
                "tenant_id", tenant_id
            ).order("created_at", desc=True).limit(1).execute()
            
            if not result.data:
                return
            
            subscription = result.data[0]
            
            # Update subscription
            features_limits = self._get_tier_features(
                PlanType(new_tier) if new_tier in ["free", "premium", "enterprise"] else PlanType.FREE
            )
            
            self.db.table("tenant_subscriptions").update({
                "plan_type": new_tier,
                "features": features_limits["features"],
                "limits": features_limits["limits"],
                "updated_at": datetime.now().isoformat()
            }).eq("id", subscription["id"]).execute()
            
            logger.info(f"Upgraded tenant {tenant_id} to {new_tier} tier")
            
        except Exception as e:
            logger.error(f"Error upgrading tenant tier: {e}")
            raise
    
    async def get_tenant_subscription(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get tenant subscription information"""
        return await self._get_tenant_subscription(tenant_id)
    
    async def _get_tenant_subscription(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Internal method to get tenant subscription"""
        try:
            result = self.db.table("tenant_subscriptions").select("*").eq(
                "tenant_id", tenant_id
            ).order("created_at", desc=True).limit(1).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error getting tenant subscription: {e}")
            return None
    
    async def get_tenant_metrics(self, tenant_id: str) -> Dict[str, Any]:
        """Get current usage metrics for tenant"""
        try:
            # Get message count (last hour)
            message_result = self.db.table("whatsapp_messages").select(
                "id", count="exact"
            ).eq("tenant_id", tenant_id).gte(
                "created_at", datetime.now().isoformat()
            ).execute()
            
            # Get active customers (last 30 days)
            customer_result = self.db.table("conversation_sessions").select(
                "customer_phone", count="exact"
            ).eq("tenant_id", tenant_id).gte(
                "last_message_at", datetime.now().isoformat()
            ).execute()
            
            return {
                "message_count": message_result.count if hasattr(message_result, 'count') else 0,
                "active_users": customer_result.count if hasattr(customer_result, 'count') else 0,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting tenant metrics: {e}")
            return {"message_count": 0, "active_users": 0, "timestamp": datetime.now().isoformat()}


# Global instance
multi_tenant_orchestrator = MultiTenantOrchestrator()
