"""
Refactored WhatsApp Bot Service using Chain of Responsibility pattern
Compatible with Meta WhatsApp API
"""
from typing import Dict, Any, Optional
import logging
from datetime import datetime

from db.supabase import get_supabase_client
from services.whatsapp.meta_service import MetaWhatsAppService
from services.whatsapp.handlers import (
    WelcomeHandler, MenuHandler, ProductOrderHandler, CartHandler, CartConfirmationHandler, SellerMenuHandler
)

logger = logging.getLogger(__name__)

class MetaWhatsAppBotService:
    """WhatsApp Bot Service for Meta API using Chain of Responsibility"""
    
    def __init__(self):
        self.db = get_supabase_client()
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Setup the handler chain"""
        # Customer handlers
        welcome_handler = WelcomeHandler(self.db)
        menu_handler = MenuHandler(self.db)
        product_order_handler = ProductOrderHandler(self.db)
        cart_handler = CartHandler(self.db)
        cart_confirmation_handler = CartConfirmationHandler(self.db)
        
        # Seller handlers
        seller_handler = SellerMenuHandler(self.db)
        
        # Chain customer handlers: Welcome -> Menu -> ProductOrder -> Cart -> CartConfirmation
        welcome_handler.next_handler = menu_handler
        menu_handler.next_handler = product_order_handler
        product_order_handler.next_handler = cart_handler
        cart_handler.next_handler = cart_confirmation_handler
        
        # Store chains
        self.customer_chain = welcome_handler
        self.seller_chain = seller_handler
    
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
            
            # Process through appropriate chain
            if is_seller:
                response = await self.seller_chain.process(message_data)
            else:
                response = await self.customer_chain.process(message_data)
            
            # If no handler processed the message, send default response
            if not response:
                response = await self._default_response(message_data)
            
            logger.info(f"Bot response: {response[:100]}...")
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
        """Check if phone number belongs to a seller"""
        try:
            # Check if phone is in seller connections
            result = self.db.table("whatsapp_configs").select("*").eq(
                "tenant_id", tenant_id
            ).eq("phone_number", phone).execute()
            
            return len(result.data) > 0
        except Exception as e:
            logger.error(f"Error checking seller status: {e}")
            return False
    
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

# Global instance for backward compatibility
bot_service = MetaWhatsAppBotService()
