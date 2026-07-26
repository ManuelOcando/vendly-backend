"""
Refactored WhatsApp Bot Service using Chain of Responsibility pattern
Compatible with Meta WhatsApp API
"""
from typing import Dict, Any, Optional
import logging
import asyncio
from datetime import datetime

from db.supabase import get_supabase_client
from services.whatsapp.handlers import (
    MenuHandler,
    CartHandler, CartConfirmationHandler, SellerMenuHandler, LLMHandler,
    OnboardingHandler, PostSaleHandler, ServiceSchedulingHandler
)
from services.conversational_dashboard import ConversationalDashboard

logger = logging.getLogger(__name__)

class MetaWhatsAppBotService:
    """WhatsApp Bot Service for Meta API using Chain of Responsibility"""
    
    def __init__(self):
        self.db = get_supabase_client()
        self.dashboard = ConversationalDashboard(self.db)
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Setup the handler chain (LLM-first architecture)"""
        # LLM handler — first and primary respondent for customer messages
        self.llm_handler = LLMHandler(self.db)

        # Fallback chain: CartHandler → CartConfirmationHandler → PostSaleHandler
        # → ServiceSchedulingHandler → MenuHandler
        # (OrderConfirmationHandler not yet implemented, skipped)
        cart_handler = CartHandler(self.db)
        cart_confirmation_handler = CartConfirmationHandler(self.db)
        post_sale_handler = PostSaleHandler(self.db)
        scheduling_handler = ServiceSchedulingHandler(self.db)
        menu_handler = MenuHandler(self.db)

        cart_handler.next_handler = cart_confirmation_handler
        cart_confirmation_handler.next_handler = post_sale_handler
        post_sale_handler.next_handler = scheduling_handler
        scheduling_handler.next_handler = menu_handler

        self.fallback_chain = cart_handler

        # Seller chain (independent, always active)
        self.seller_chain = SellerMenuHandler(self.db)
        
        # Onboarding chain (for new tenants)
        self.onboarding_chain = OnboardingHandler(self.db)
    
    async def process_message(self, tenant_id: str, phone: str, message: str, phone_number_id: str) -> Optional[str]:
        """Process incoming message and return response"""
        try:
            logger.info(f"Processing message from {phone} for tenant {tenant_id}: {message[:50]}...")
            
            # Get tenant information
            tenant = await self._get_tenant(tenant_id)
            if not tenant:
                logger.error(f"Tenant {tenant_id} not found")
                return None
            
            # Get tenant configuration
            config = await self._get_tenant_config(tenant_id)
            
            # Get or create session
            session = await self._get_or_create_session(tenant_id, phone)
            
            # Log inbound message
            await self._log_message(
                tenant_id=tenant_id,
                direction="inbound",
                phone=phone,
                content=message,
                status="received"
            )
            
            # Check if user is seller
            is_seller = await self._is_seller(tenant_id, phone)
            
            # Prepare message data for handlers
            message_data = {
                "tenant_id": tenant_id,
                "tenant_name": tenant.get("name", "Tienda"),
                "phone": phone,
                "message": message,
                "phone_number_id": phone_number_id,
                "config": config,
                "session": session,
                "is_seller": is_seller
            }
            
            # Process through appropriate chain (LLM-first architecture)
            if is_seller:
                response = await self.seller_chain.process(message_data)
            elif await self.llm_handler.can_handle(message_data):
                response = await self.llm_handler.handle(message_data)
                if response is None:  # LLM failed at runtime
                    response = await self.fallback_chain.process(message_data)
            else:
                # LLM not configured or disabled
                response = await self.fallback_chain.process(message_data)
            
            # If no handler processed the message, try onboarding
            if not response:
                response = await self.onboarding_chain.process(message_data)
            
            # If still no response, send default response
            if not response:
                response = await self._default_response(message_data)
            
            # Log outbound message
            await self._log_message(
                tenant_id=tenant_id,
                direction="outbound",
                phone=phone,
                content=response,
                status="delivered"
            )
            
            logger.info(f"Bot response: {response[:100]}...")
            
            # Check for smart alerts in background (non-blocking)
            if not is_seller:  # Only check alerts for customer messages
                asyncio.create_task(self._check_alerts_background(tenant_id))
            
            return response
            
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            return "Lo siento, tuve un problema procesando tu mensaje. Intenta nuevamente."
    
    async def _get_tenant(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get tenant information"""
        try:
            result = self.db.table("tenants").select("id, name").eq("id", tenant_id).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error getting tenant: {e}")
            return None
    
    async def _get_tenant_config(self, tenant_id: str) -> Dict[str, Any]:
        """Get tenant WhatsApp configuration"""
        try:
            result = self.db.table("whatsapp_configs").select("*").eq("tenant_id", tenant_id).execute()
            return result.data[0] if result.data else {}
        except Exception as e:
            logger.error(f"Error getting tenant config: {e}")
            return {}
    
    async def _get_or_create_session(self, tenant_id: str, phone: str) -> Dict[str, Any]:
        """Get or create conversation session"""
        try:
            # Try to get existing session
            result = self.db.table("conversation_sessions").select("*").eq(
                "tenant_id", tenant_id
            ).eq("customer_phone", phone).execute()
            
            if result.data:
                session = result.data[0]
                # Update last message time
                self.db.table("conversation_sessions").update({
                    "last_message_at": datetime.now().isoformat()
                }).eq("id", session["id"]).execute()
                return session
            
            # Create new session
            session_data = {
                "tenant_id": tenant_id,
                "customer_phone": phone,
                "current_state": "initial",
                "created_at": datetime.now().isoformat(),
                "last_message_at": datetime.now().isoformat()
            }
            
            result = self.db.table("conversation_sessions").insert(session_data).execute()
            return result.data[0] if result.data else {}
            
        except Exception as e:
            logger.error(f"Error managing session: {e}")
            return {}
    
    async def _is_seller(self, tenant_id: str, phone: str) -> bool:
        """Check if phone number belongs to the seller (business owner) of the tenant.

        Logic:
        - Queries whatsapp_configs for the tenant.
        - If the record has a non-empty `seller_phone` field, compares `phone` against it.
          This is the preferred approach: `seller_phone` is the personal phone of the
          business owner, distinct from `phone_number` (the WhatsApp Business number / bot number).
        - Falls back to comparing against `phone_number` if `seller_phone` is not set.

        NOTE: A `seller_phone` column should be added to `whatsapp_configs` for proper
        seller identification. Without it, the fallback compares against `phone_number`
        (the WhatsApp Business account number), which may not match the seller's personal
        phone in all deployments.
        """
        try:
            result = self.db.table("whatsapp_configs").select("*").eq(
                "tenant_id", tenant_id
            ).execute()

            if not result.data:
                return False

            config = result.data[0]

            # Prefer seller_phone if the column exists and has a value
            seller_phone = config.get("seller_phone")
            if seller_phone:
                return phone == seller_phone

            # Fallback: compare against phone_number (the WhatsApp Business account number)
            # TODO: Add `seller_phone` column to `whatsapp_configs` for proper seller
            # identification. See migrations/ — no migration for seller_phone exists yet.
            business_phone = config.get("phone_number")
            return bool(business_phone and phone == business_phone)

        except Exception as e:
            logger.error(f"Error checking seller status: {e}")
            return False
    
    async def _log_message(
        self,
        tenant_id: str,
        direction: str,  # "inbound" or "outbound"
        phone: str,      # sender_phone for inbound, receiver_phone for outbound
        content: str,
        status: str = "received"
    ) -> None:
        """Log a message to whatsapp_messages table. Never raises exceptions."""
        try:
            record: Dict[str, Any] = {
                "tenant_id": tenant_id,
                "direction": direction,
                "content": content,
                "status": status,
                "created_at": datetime.now().isoformat(),
            }
            if direction == "inbound":
                record["sender_phone"] = phone
                record["message_type"] = "text"
            else:
                record["receiver_phone"] = phone

            self.db.table("whatsapp_messages").insert(record).execute()
        except Exception as e:
            logger.error(f"Failed to log {direction} message for tenant {tenant_id}: {e}")

    async def _default_response(self, message_data: Dict[str, Any]) -> str:
        """Default response when no handler matches"""
        tenant_name = message_data.get("tenant_name", "Tienda")
        state = message_data.get("session", {}).get("current_state", "initial")
        
        if state == "viewing_cart":
            return """¿Deseas agregar algo más o confirmar el pedido?
• Responde "sí" para confirmar
• Responde "agregar" para añadir productos
• Responde "cancelar" para cancelar"""
        
        return f"""Gracias por tu mensaje. Soy el asistente de {tenant_name}.

🛒 *Opciones disponibles:*
• Escribe "hola" para empezar
• Escribe "menu" para ver productos
• Escribe "pedido:TU_CARRO_ID" si vienes de la web

¿En qué puedo ayudarte?"""
    
    async def _check_alerts_background(self, tenant_id: str):
        """Check for smart alerts in background (non-blocking)"""
        try:
            # Check if tenant has conversational dashboard enabled
            subscription_result = self.db.table("tenant_subscriptions").select(
                "features"
            ).eq("tenant_id", tenant_id).eq("status", "active").execute()
            
            if not subscription_result.data:
                return
            
            features = subscription_result.data[0].get("features", {})
            if not features.get("conversational_dashboard", False):
                return
            
            # Check alerts using dashboard
            alerts = await self.dashboard.check_and_send_alerts(tenant_id)
            
            if alerts:
                logger.info(f"Found {len(alerts)} alerts for tenant {tenant_id}")
                
                # Get seller phone to send alerts
                config_result = self.db.table("whatsapp_configs").select(
                    "seller_phone, phone_number, phone_number_id"
                ).eq("tenant_id", tenant_id).execute()
                
                if config_result.data:
                    config = config_result.data[0]
                    seller_phone = config.get("seller_phone") or config.get("phone_number")
                    phone_number_id = config.get("phone_number_id")
                    
                    if seller_phone and phone_number_id:
                        # Send alerts via WhatsApp service
                        from services.whatsapp.meta_service import MetaWhatsAppService
                        whatsapp_service = MetaWhatsAppService()
                        
                        for alert_message in alerts:
                            if alert_message:
                                await whatsapp_service.send_message(
                                    phone_number_id=phone_number_id,
                                    to=seller_phone,
                                    message=alert_message
                                )
                                logger.info(f"Alert sent to seller {seller_phone}")
            
        except Exception as e:
            logger.error(f"Error checking alerts in background: {e}")

# Global instance for backward compatibility
bot_service = MetaWhatsAppBotService()
