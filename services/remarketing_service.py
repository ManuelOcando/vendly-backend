"""
Remarketing Service for Vendly Pro
Implements inactivity reminders, repeat order suggestions, and new product notifications
"""
from typing import Dict, Any, Optional, List
import logging
from datetime import datetime, date, timedelta
from dataclasses import dataclass
from enum import Enum

from db.supabase import get_supabase_client
from models.vendly_pro import (
    CustomerProfileResponse,
    PurchaseHistoryResponse,
    LoyaltyPointsResponse,
    LoyaltyTier
)

logger = logging.getLogger(__name__)


class InactivityReminderType(str, Enum):
    """Types of inactivity reminders"""
    FIRST_REMINDER = "first_reminder"  # 30 days
    SECOND_REMINDER = "second_reminder"  # 45 days
    THIRD_REMINDER = "third_reminder"  # 60 days
    VIP_REMINDER = "vip_reminder"  # VIP customers at 21 days


class ReminderStatus(str, Enum):
    """Status of reminder campaigns"""
    PENDING = "pending"
    SENT = "sent"
    CLICKED = "clicked"
    CONVERTED = "converted"
    EXPIRED = "expired"
    SKIPPED = "skipped"


@dataclass
class InactivityReminder:
    """Inactivity reminder data"""
    customer_phone: str
    days_inactive: int
    reminder_type: InactivityReminderType
    status: ReminderStatus = ReminderStatus.PENDING
    scheduled_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    campaign_id: Optional[str] = None
    offer_code: Optional[str] = None


@dataclass
class RepeatOrderSuggestion:
    """Repeat order suggestion data"""
    customer_phone: str
    previous_order_id: str
    products: List[Dict[str, Any]]
    days_since_last_order: int
    suggested_at: datetime
    status: str = "pending"  # pending, viewed, repeated, expired


@dataclass
class NewProductNotification:
    """New product notification data"""
    customer_phone: str
    product_id: str
    product_name: str
    reason: str  # why this product was recommended
    sent_at: Optional[datetime] = None
    status: str = "pending"  # pending, sent, viewed, purchased


class RemarketingService:
    """Service for managing remarketing and retention campaigns"""
    
    def __init__(self, db=None):
        self.db = db or get_supabase_client()
        
        # Default configuration
        self.inactivity_thresholds = {
            InactivityReminderType.FIRST_REMINDER: 30,  # 30 days
            InactivityReminderType.SECOND_REMINDER: 45,  # 45 days
            InactivityReminderType.THIRD_REMINDER: 60,  # 60 days
            InactivityReminderType.VIP_REMINDER: 21  # 21 days for VIP
        }
        
        self.repeat_order_threshold = 7  # Suggest repeat order if last order was within 7 days
        self.repeat_order_max_days = 30  # But not older than 30 days
        
        # WhatsApp service for sending messages
        self.whatsapp_service = None
    
    def _get_whatsapp_service(self) -> Any:
        """Get WhatsApp service instance"""
        if self.whatsapp_service is None:
            try:
                from services.whatsapp.meta_service import MetaWhatsAppService
                self.whatsapp_service = MetaWhatsAppService()
            except ImportError:
                logger.warning("WhatsApp service not available")
        return self.whatsapp_service
    
    async def check_inactivity_reminders(self, tenant_id: str) -> List[InactivityReminder]:
        """
        Check for customers who haven't made purchases and need reminders
        
        Args:
            tenant_id: Tenant identifier
            
        Returns:
            List of customers who need inactivity reminders
        """
        try:
            reminders = []
            
            # Get all customers with purchase history
            customers = await self._get_customers_with_purchase_history(tenant_id)
            
            for customer in customers:
                last_purchase_date = customer.get("last_purchase_date")
                if not last_purchase_date:
                    continue
                
                # Calculate days since last purchase
                if isinstance(last_purchase_date, str):
                    last_purchase_date = datetime.fromisoformat(last_purchase_date.replace('Z', '+00:00'))
                
                days_inactive = (datetime.now() - last_purchase_date).days
                
                # Determine reminder type based on days inactive and customer tier
                reminder_type = self._determine_reminder_type(days_inactive, customer)
                
                if reminder_type:
                    reminder = InactivityReminder(
                        customer_phone=customer.get("customer_phone"),
                        days_inactive=days_inactive,
                        reminder_type=reminder_type,
                        scheduled_at=datetime.now()
                    )
                    reminders.append(reminder)
            
            return reminders
            
        except Exception as e:
            logger.error(f"Error checking inactivity reminders: {e}")
            raise
    
    async def send_inactivity_reminder(
        self,
        tenant_id: str,
        customer_phone: str,
        reminder_type: InactivityReminderType
    ) -> Dict[str, Any]:
        """
        Send inactivity reminder to customer
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            reminder_type: Type of reminder to send
            
        Returns:
            Result of sending the reminder
        """
        try:
            # Get customer profile
            profile = await self._get_customer_profile(tenant_id, customer_phone)
            if not profile:
                return {"success": False, "error": "Customer profile not found"}
            
            # Get customer loyalty status
            loyalty = await self._get_customer_loyalty(tenant_id, customer_phone)
            
            # Generate personalized offer
            offer_code = self._generate_offer_code(reminder_type, loyalty)
            
            # Create reminder message
            message = self._create_inactivity_message(
                customer=profile,
                reminder_type=reminder_type,
                offer_code=offer_code,
                loyalty=loyalty
            )
            
            # Send via WhatsApp
            whatsapp = self._get_whatsapp_service()
            if whatsapp:
                result = await whatsapp.send_message(
                    to=customer_phone,
                    message=message
                )
                
                if result.get("status") == "sent":
                    # Record reminder in database
                    await self._record_reminder(
                        tenant_id=tenant_id,
                        customer_phone=customer_phone,
                        reminder_type=reminder_type,
                        offer_code=offer_code,
                        status=ReminderStatus.SENT
                    )
                    
                    return {
                        "success": True,
                        "message_id": result.get("message_id"),
                        "offer_code": offer_code
                    }
                else:
                    return {
                        "success": False,
                        "error": result.get("error", "Failed to send message")
                    }
            else:
                # Log reminder for manual sending (development/testing)
                logger.info(f"[REMINDER] Would send to {customer_phone}: {message[:100]}...")
                return {
                    "success": True,
                    "message_preview": message[:100],
                    "offer_code": offer_code,
                    "whatsapp_service_unavailable": True
                }
            
        except Exception as e:
            logger.error(f"Error sending inactivity reminder: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_repeat_order_suggestions(
        self,
        tenant_id: str,
        customer_phone: str
    ) -> List[RepeatOrderSuggestion]:
        """
        Get repeat order suggestions for a customer
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            
        Returns:
            List of repeat order suggestions
        """
        try:
            suggestions = []
            
            # Get customer's recent orders
            purchase_history = await self._get_purchase_history(
                tenant_id, customer_phone, limit=10
            )
            
            if not purchase_history:
                return suggestions
            
            # Get customer profile for preferences
            profile = await self._get_customer_profile(tenant_id, customer_phone)
            
            # Find frequent orders (orders with 3+ items)
            frequent_orders = self._find_frequent_orders(purchase_history)
            
            for order in frequent_orders:
                days_since = (datetime.now() - order.purchased_at).days
                
                # Only suggest if within threshold
                if self.repeat_order_threshold <= days_since <= self.repeat_order_max_days:
                    # Get products from this order
                    products = await self._get_order_products(tenant_id, order.order_id)
                    
                    suggestion = RepeatOrderSuggestion(
                        customer_phone=customer_phone,
                        previous_order_id=order.order_id,
                        products=products,
                        days_since_last_order=days_since,
                        suggested_at=datetime.now()
                    )
                    suggestions.append(suggestion)
            
            return suggestions
            
        except Exception as e:
            logger.error(f"Error getting repeat order suggestions: {e}")
            raise
    
    async def suggest_repeat_order(
        self,
        tenant_id: str,
        customer_phone: str,
        suggestion: RepeatOrderSuggestion
    ) -> Dict[str, Any]:
        """
        Send repeat order suggestion to customer
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            suggestion: Repeat order suggestion
            
        Returns:
            Result of sending the suggestion
        """
        try:
            # Create suggestion message
            message = self._create_repeat_order_message(
                customer_phone=customer_phone,
                products=suggestion.products,
                days_since=suggestion.days_since_last_order
            )
            
            # Send via WhatsApp
            whatsapp = self._get_whatsapp_service()
            if whatsapp:
                result = await whatsapp.send_message(
                    to=customer_phone,
                    message=message
                )
                
                if result.get("status") == "sent":
                    # Record suggestion
                    await self._record_suggestion(
                        tenant_id=tenant_id,
                        customer_phone=customer_phone,
                        order_id=suggestion.previous_order_id,
                        status="sent"
                    )
                    
                    return {
                        "success": True,
                        "message_id": result.get("message_id")
                    }
                else:
                    return {
                        "success": False,
                        "error": result.get("error", "Failed to send message")
                    }
            else:
                logger.info(f"[SUGGESTION] Would send to {customer_phone}: {message[:100]}...")
                return {
                    "success": True,
                    "message_preview": message[:100],
                    "whatsapp_service_unavailable": True
                }
            
        except Exception as e:
            logger.error(f"Error sending repeat order suggestion: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_new_product_notifications(
        self,
        tenant_id: str,
        product_id: str
    ) -> List[NewProductNotification]:
        """
        Get customers who might be interested in a new product
        
        Args:
            tenant_id: Tenant identifier
            product_id: New product ID
            
        Returns:
            List of customers to notify
        """
        try:
            notifications = []
            
            # Get product information
            product = await self._get_product(tenant_id, product_id)
            if not product:
                return notifications
            
            # Find customers with matching preferences
            interested_customers = await self._find_interested_customers(
                tenant_id, product
            )
            
            for customer in interested_customers:
                notification = NewProductNotification(
                    customer_phone=customer.get("customer_phone"),
                    product_id=product_id,
                    product_name=product.get("name", "Producto"),
                    reason=self._determine_notification_reason(customer, product)
                )
                notifications.append(notification)
            
            return notifications
            
        except Exception as e:
            logger.error(f"Error getting new product notifications: {e}")
            raise
    
    async def send_new_product_notification(
        self,
        tenant_id: str,
        customer_phone: str,
        notification: NewProductNotification
    ) -> Dict[str, Any]:
        """
        Send new product notification to customer
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            notification: New product notification
            
        Returns:
            Result of sending the notification
        """
        try:
            # Create notification message
            message = self._create_new_product_message(
                customer_phone=customer_phone,
                product_name=notification.product_name,
                reason=notification.reason
            )
            
            # Send via WhatsApp
            whatsapp = self._get_whatsapp_service()
            if whatsapp:
                result = await whatsapp.send_message(
                    to=customer_phone,
                    message=message
                )
                
                if result.get("status") == "sent":
                    # Record notification
                    await self._record_notification(
                        tenant_id=tenant_id,
                        customer_phone=customer_phone,
                        product_id=notification.product_id,
                        status="sent"
                    )
                    
                    return {
                        "success": True,
                        "message_id": result.get("message_id")
                    }
                else:
                    return {
                        "success": False,
                        "error": result.get("error", "Failed to send message")
                    }
            else:
                logger.info(f"[NOTIFICATION] Would send to {customer_phone}: {message[:100]}...")
                return {
                    "success": True,
                    "message_preview": message[:100],
                    "whatsapp_service_unavailable": True
                }
            
        except Exception as e:
            logger.error(f"Error sending new product notification: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_remarketing_campaigns(
        self,
        tenant_id: str,
        status: Optional[ReminderStatus] = None
    ) -> List[Dict[str, Any]]:
        """
        Get remarketing campaigns for a tenant
        
        Args:
            tenant_id: Tenant identifier
            status: Optional status filter
            
        Returns:
            List of campaigns
        """
        try:
            query = self.db.table("remarketing_campaigns").select("*").eq(
                "tenant_id", tenant_id
            ).order("created_at", desc=True)
            
            if status:
                query = query.eq("status", status.value)
            
            result = query.execute()
            
            if result.data:
                return result.data
            
            return []
            
        except Exception as e:
            logger.error(f"Error getting remarketing campaigns: {e}")
            raise
    
    async def create_remarketing_campaign(
        self,
        tenant_id: str,
        campaign_type: str,
        target_audience: Dict[str, Any],
        message_template: str,
        offer_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new remarketing campaign
        
        Args:
            tenant_id: Tenant identifier
            campaign_type: Type of campaign (inactivity, repeat_order, new_product)
            target_audience: Target audience criteria
            message_template: Message template to use
            offer_code: Optional offer code
            
        Returns:
            Created campaign
        """
        try:
            campaign_data = {
                "tenant_id": tenant_id,
                "campaign_type": campaign_type,
                "target_audience": target_audience,
                "message_template": message_template,
                "offer_code": offer_code,
                "status": "pending",
                "created_at": datetime.now().isoformat()
            }
            
            result = self.db.table("remarketing_campaigns").insert(campaign_data).execute()
            
            if result.data:
                return result.data[0]
            
            raise ValueError("Failed to create campaign")
            
        except Exception as e:
            logger.error(f"Error creating remarketing campaign: {e}")
            raise
    
    # ============================================
    # PRIVATE HELPER METHODS
    # ============================================
    
    async def _get_customers_with_purchase_history(
        self,
        tenant_id: str
    ) -> List[Dict[str, Any]]:
        """Get customers with purchase history"""
        try:
            # Get customers with their last purchase date
            result = self.db.rpc(
                "get_customers_with_last_purchase",
                {"p_tenant_id": tenant_id}
            ).execute()
            
            if result.data:
                return result.data
            
            return []
            
        except Exception as e:
            logger.error(f"Error getting customers with purchase history: {e}")
            return []
    
    async def _get_customer_profile(
        self,
        tenant_id: str,
        customer_phone: str
    ) -> Optional[CustomerProfileResponse]:
        """Get customer profile"""
        try:
            result = self.db.table("customer_profiles").select("*").eq(
                "tenant_id", tenant_id
            ).eq("phone_number", customer_phone).execute()
            
            if result.data and result.data[0]:
                return CustomerProfileResponse(**result.data[0])
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting customer profile: {e}")
            return None
    
    async def _get_customer_loyalty(
        self,
        tenant_id: str,
        customer_phone: str
    ) -> Optional[LoyaltyPointsResponse]:
        """Get customer loyalty information"""
        try:
            result = self.db.table("loyalty_points").select("*").eq(
                "tenant_id", tenant_id
            ).eq("customer_phone", customer_phone).execute()
            
            if result.data and result.data[0]:
                return LoyaltyPointsResponse(**result.data[0])
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting customer loyalty: {e}")
            return None
    
    async def _get_purchase_history(
        self,
        tenant_id: str,
        customer_phone: str,
        limit: int = 10
    ) -> List[PurchaseHistoryResponse]:
        """Get customer purchase history"""
        try:
            result = self.db.table("purchase_history").select("*").eq(
                "tenant_id", tenant_id
            ).eq("customer_phone", customer_phone).order(
                "purchased_at", desc=True
            ).limit(limit).execute()
            
            if result.data:
                return [PurchaseHistoryResponse(**item) for item in result.data]
            
            return []
            
        except Exception as e:
            logger.error(f"Error getting purchase history: {e}")
            return []
    
    async def _get_order_products(
        self,
        tenant_id: str,
        order_id: str
    ) -> List[Dict[str, Any]]:
        """Get products from an order"""
        try:
            # This would require an order_items table
            # For now, return a placeholder
            return []
            
        except Exception as e:
            logger.error(f"Error getting order products: {e}")
            return []
    
    async def _get_product(
        self,
        tenant_id: str,
        product_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get product information"""
        try:
            result = self.db.table("items").select("*").eq(
                "tenant_id", tenant_id
            ).eq("id", product_id).execute()
            
            if result.data and result.data[0]:
                return result.data[0]
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting product: {e}")
            return None
    
    async def _find_interested_customers(
        self,
        tenant_id: str,
        product: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Find customers who might be interested in a product"""
        try:
            # Get all customer profiles
            result = self.db.table("customer_profiles").select("*").eq(
                "tenant_id", tenant_id
            ).execute()
            
            if not result.data:
                return []
            
            # Filter by product category or preferences
            interested_customers = []
            product_category = product.get("category_id")
            
            for profile in result.data:
                preferences = profile.get("preferences", {})
                
                # Check if customer has preferences matching product category
                if product_category and "category" in preferences:
                    if product_category in preferences["category"]:
                        interested_customers.append(profile)
                
                # Check favorite products
                favorite_products = profile.get("favorite_products", [])
                if product.get("id") in favorite_products:
                    interested_customers.append(profile)
            
            return interested_customers
            
        except Exception as e:
            logger.error(f"Error finding interested customers: {e}")
            return []
    
    def _determine_reminder_type(
        self,
        days_inactive: int,
        customer: Dict[str, Any]
    ) -> Optional[InactivityReminderType]:
        """Determine which type of reminder to send"""
        try:
            # Check if customer is VIP
            loyalty = customer.get("loyalty_tier")
            is_vip = loyalty in [LoyaltyTier.GOLD.value, LoyaltyTier.PLATINUM.value]
            
            # VIP customers get reminded earlier
            if is_vip and days_inactive >= self.inactivity_thresholds[InactivityReminderType.VIP_REMINDER]:
                return InactivityReminderType.VIP_REMINDER
            
            # Regular inactivity reminders
            if days_inactive >= self.inactivity_thresholds[InactivityReminderType.THIRD_REMINDER]:
                return InactivityReminderType.THIRD_REMINDER
            elif days_inactive >= self.inactivity_thresholds[InactivityReminderType.SECOND_REMINDER]:
                return InactivityReminderType.SECOND_REMINDER
            elif days_inactive >= self.inactivity_thresholds[InactivityReminderType.FIRST_REMINDER]:
                return InactivityReminderType.FIRST_REMINDER
            
            return None
            
        except Exception as e:
            logger.error(f"Error determining reminder type: {e}")
            return None
    
    def _generate_offer_code(
        self,
        reminder_type: InactivityReminderType,
        loyalty: Optional[LoyaltyPointsResponse] = None
    ) -> str:
        """Generate personalized offer code"""
        try:
            # Base offer codes
            offer_codes = {
                InactivityReminderType.FIRST_REMINDER: "HOLA20",
                InactivityReminderType.SECOND_REMINDER: "NOSOTROS25",
                InactivityReminderType.THIRD_REMINDER: "VUELVE30",
                InactivityReminderType.VIP_REMINDER: "VIP40"
            }
            
            code = offer_codes.get(reminder_type, "DESCUENTO")
            
            # Add loyalty bonus for VIP customers
            if loyalty and loyalty.tier in [LoyaltyTier.GOLD, LoyaltyTier.PLATINUM]:
                code = code.replace("20", "25").replace("25", "30").replace("30", "35").replace("40", "50")
            
            return code
            
        except Exception as e:
            logger.error(f"Error generating offer code: {e}")
            return "DESCUENTO"
    
    def _create_inactivity_message(
        self,
        customer: CustomerProfileResponse,
        reminder_type: InactivityReminderType,
        offer_code: str,
        loyalty: Optional[LoyaltyPointsResponse] = None
    ) -> str:
        """Create personalized inactivity reminder message"""
        try:
            # Get customer name from phone
            customer_name = customer.phone_number
            
            # Message templates
            templates = {
                InactivityReminderType.FIRST_REMINDER: (
                    f"Hola {customer_name}! 🌟\n\n"
                    f"Hace 30 días que no nos visitas y extrañamos atenderte.\n\n"
                    f"Como agradecimiento por tu fidelidad, te damos un *10% de descuento* en tu próxima compra.\n\n"
                    f"Usa el código: *{offer_code}*\n\n"
                    f"¿Qué tal si vuelves hoy? 🍽️"
                ),
                InactivityReminderType.SECOND_REMINDER: (
                    f"Hola {customer_name}! 👋\n\n"
                    f"Hace 45 días que no nos visitas y queremos saber ¿qué tal ha estado todo?\n\n"
                    f"Te esperamos con un *15% de descuento* especial.\n\n"
                    f"Usa el código: *{offer_code}*\n\n"
                    f"¡Tu mesa/tableta está reservada! 🎁"
                ),
                InactivityReminderType.THIRD_REMINDER: (
                    f"Hola {customer_name}! ❤️\n\n"
                    f"Hace 60 días que no nos visitas y queremos recuperarte.\n\n"
                    f"Te ofrecemos un *20% de descuento* + *envío gratis* en tu próxima compra.\n\n"
                    f"Usa el código: *{offer_code}*\n\n"
                    f"¡Esperamos verte pronto! 🚀"
                ),
                InactivityReminderType.VIP_REMINDER: (
                    f"Hola {customer_name}! ⭐\n\n"
                    f"Hace 21 días que no nos visitas y queremos brindarte atención especial.\n\n"
                    f"Como cliente VIP, te ofrecemos un *25% de descuento* exclusivo.\n\n"
                    f"Usa el código: *{offer_code}*\n\n"
                    f"¡Tu mesa/tableta está reservada! 🌟"
                )
            }
            
            return templates.get(reminder_type, templates[InactivityReminderType.FIRST_REMINDER])
            
        except Exception as e:
            logger.error(f"Error creating inactivity message: {e}")
            return "Hola! Hace tiempo que no nos visitas y queremos recuperarte. ¡Te esperamos!"
    
    def _create_repeat_order_message(
        self,
        customer_phone: str,
        products: List[Dict[str, Any]],
        days_since: int
    ) -> str:
        """Create repeat order suggestion message"""
        try:
            product_names = [p.get("name", "Producto") for p in products[:3]]
            product_list = "\n".join([f"• {name}" for name in product_names])
            
            message = (
                f"¡Hola! 👋\n\n"
                f"Hace {days_since} días hiciste un pedido que te gustó mucho.\n\n"
                f"¿Quieres repetirlo?\n\n"
                f"{product_list}\n\n"
                f"Responde *SÍ* y te ayudo a repetir tu pedido anterior. 🛒"
            )
            
            return message
            
        except Exception as e:
            logger.error(f"Error creating repeat order message: {e}")
            return "¡Hola! ¿Quieres repetir tu pedido anterior?"
    
    def _create_new_product_message(
        self,
        customer_phone: str,
        product_name: str,
        reason: str
    ) -> str:
        """Create new product notification message"""
        try:
            message = (
                f"¡Nuevo producto disponible! 🎉\n\n"
                f"Acabamos de lanzar *{product_name}*\n\n"
                f"Basado en tus preferencias, creemos que te encantará. {reason}\n\n"
                f"¿Quieres verlo? 🌟"
            )
            
            return message
            
        except Exception as e:
            logger.error(f"Error creating new product message: {e}")
            return "¡Tenemos un nuevo producto que creemos te encantará!"
    
    def _find_frequent_orders(
        self,
        purchase_history: List[PurchaseHistoryResponse]
    ) -> List[PurchaseHistoryResponse]:
        """Find orders that customers frequently repeat"""
        try:
            # Group by order pattern (simplified)
            # In production, this would analyze product combinations
            
            # Return orders within the threshold
            return [
                order for order in purchase_history
                if self.repeat_order_threshold <= (datetime.now() - order.purchased_at).days <= self.repeat_order_max_days
            ]
            
        except Exception as e:
            logger.error(f"Error finding frequent orders: {e}")
            return []
    
    def _determine_notification_reason(
        self,
        customer: Dict[str, Any],
        product: Dict[str, Any]
    ) -> str:
        """Determine why this product was recommended to customer"""
        try:
            preferences = customer.get("preferences", {})
            product_category = product.get("category_id")
            
            if product_category and "category" in preferences:
                if product_category in preferences["category"]:
                    return "Basado en tus preferencias de categoría."
            
            favorite_products = customer.get("favorite_products", [])
            if product.get("id") in favorite_products:
                return "Porque te gusta este tipo de producto."
            
            return "Porque creemos que te encantará."
            
        except Exception as e:
            logger.error(f"Error determining notification reason: {e}")
            return "Porque creemos que te encantará."
    
    async def _record_reminder(
        self,
        tenant_id: str,
        customer_phone: str,
        reminder_type: InactivityReminderType,
        offer_code: str,
        status: ReminderStatus
    ) -> None:
        """Record reminder in database"""
        try:
            reminder_data = {
                "tenant_id": tenant_id,
                "customer_phone": customer_phone,
                "reminder_type": reminder_type.value,
                "offer_code": offer_code,
                "status": status.value,
                "created_at": datetime.now().isoformat()
            }
            
            self.db.table("remarketing_reminders").insert(reminder_data).execute()
            
        except Exception as e:
            logger.error(f"Error recording reminder: {e}")
    
    async def _record_suggestion(
        self,
        tenant_id: str,
        customer_phone: str,
        order_id: str,
        status: str
    ) -> None:
        """Record repeat order suggestion in database"""
        try:
            suggestion_data = {
                "tenant_id": tenant_id,
                "customer_phone": customer_phone,
                "order_id": order_id,
                "status": status,
                "created_at": datetime.now().isoformat()
            }
            
            self.db.table("remarketing_suggestions").insert(suggestion_data).execute()
            
        except Exception as e:
            logger.error(f"Error recording suggestion: {e}")
    
    async def _record_notification(
        self,
        tenant_id: str,
        customer_phone: str,
        product_id: str,
        status: str
    ) -> None:
        """Record product notification in database"""
        try:
            notification_data = {
                "tenant_id": tenant_id,
                "customer_phone": customer_phone,
                "product_id": product_id,
                "status": status,
                "created_at": datetime.now().isoformat()
            }
            
            self.db.table("remarketing_notifications").insert(notification_data).execute()
            
        except Exception as e:
            logger.error(f"Error recording notification: {e}")
