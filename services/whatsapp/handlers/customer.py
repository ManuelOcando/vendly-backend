"""
Customer message handlers for WhatsApp bot
"""
from typing import Dict, Any, Optional
import re
import logging
from datetime import datetime

from .base import BaseWhatsAppHandler
from api.v1.cart import get_cart as get_cart_service

logger = logging.getLogger(__name__)

class WelcomeHandler(BaseWhatsAppHandler):
    """Handles welcome messages and greetings"""
    
    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        """Check if message is a greeting"""
        message = message_data.get("message", "").lower().strip()
        state = message_data.get("session", {}).get("current_state", "initial")
        
        return state == "initial" and any(
            greeting in message 
            for greeting in ["hola", "hi", "hello", "buenos días", "buenas tardes", "buenas noches"]
        )
    
    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        """Handle greeting message"""
        tenant_name = message_data.get("tenant_name", "Tienda")
        config = message_data.get("config", {})
        
        welcome_msg = config.get("welcome_message", "¡Hola! Soy el asistente de {store_name}. ¿En qué puedo ayudarte?")
        message = welcome_msg.format(store_name=tenant_name)
        
        # Add quick options
        message += """

🛒 *Opciones:*
• Escribe "menu" para ver nuestros productos
• Escribe "pedido:TU_CARRO_ID" si vienes de la web
• Escribe "hola" para empezar"""
        
        # Update session state
        session_id = message_data.get("session", {}).get("id")
        if session_id:
            await self.update_session_state(session_id, "initial")
        
        return message

class MenuHandler(BaseWhatsAppHandler):
    """Handles menu/catalog requests"""
    
    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        """Check if message is requesting menu"""
        message = message_data.get("message", "").lower().strip()
        
        return any(keyword in message for keyword in ["menu", "catálogo", "catalogo", "ver productos", "productos"])
    
    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        """Handle menu request"""
        tenant_id = message_data.get("tenant_id")
        
        try:
            # Get all active products (not just featured)
            items_result = self.db.table("items").select(
                "name, price, description"
            ).eq("tenant_id", tenant_id).eq("is_active", True).limit(10).execute()
            
            if not items_result.data:
                return "No hay productos disponibles en este momento."
            
            items_text = "\n\n".join([
                f"🍔 {item['name']}\n💲 ${item['price']:.2f}\n{item.get('description', '')}"
                for item in items_result.data
            ])
            
            message = f"""📋 *Nuestros Productos:*

{items_text}

🛍️ Para ordenar, visita nuestra tienda o escríbeme lo que deseas."""
            
            return message
            
        except Exception as e:
            logger.error(f"Error getting menu: {e}")
            return "Lo siento, no puedo mostrar el menú en este momento. Intenta más tarde."

class ProductOrderHandler(BaseWhatsAppHandler):
    """Handles ordering products by name"""
    
    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        """Check if message could be a product name (not a command)"""
        message = message_data.get("message", "").lower().strip()
        
        # Skip if it's a known command
        commands = ["hola", "hi", "hello", "menu", "catálogo", "catalogo", 
                   "ver productos", "productos", "pedido:", "si", "sí", 
                   "confirmar", "confirmo", "acepto", "no", "cancelar"]
        
        # Must be at least 2 characters and not a command
        return len(message) >= 2 and not any(cmd in message for cmd in commands)
    
    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        """Handle product order by name"""
        tenant_id = message_data.get("tenant_id")
        phone = message_data.get("phone")
        product_name = message_data.get("message", "").strip()
        session = message_data.get("session", {})
        
        try:
            # Search for product by name (case-insensitive partial match)
            items_result = self.db.table("items").select(
                "id, name, price, description"
            ).eq("tenant_id", tenant_id).eq("is_active", True).ilike("name", f"%{product_name}%").limit(5).execute()
            
            if not items_result.data:
                return f"No encontré productos con \"{product_name}\".\n\n🛒 Escribe \"menu\" para ver todos los productos disponibles."
            
            # If multiple matches, ask user to be more specific
            if len(items_result.data) > 1:
                products_list = "\n".join([f"• {item['name']} - ${item['price']:.2f}" for item in items_result.data])
                return f"Encontré varios productos:\n\n{products_list}\n\nPor favor, escribe el nombre más específico del que deseas."
            
            # Single match - add to cart
            product = items_result.data[0]
            
            # Get or create session cart
            session_data = session.get("session_data", {}) or {}
            cart = session_data.get("cart", [])
            
            # Add product to cart
            cart_item = {
                "product_id": product["id"],
                "name": product["name"],
                "price": product["price"],
                "quantity": 1
            }
            cart.append(cart_item)
            
            # Calculate total
            total = sum(item["price"] * item["quantity"] for item in cart)
            
            # Update session with cart
            session_id = session.get("id")
            if session_id:
                await self.update_session_state(
                    session_id, 
                    "ordering", 
                    {"cart": cart, "total": total}
                )
            
            # Build cart summary
            cart_text = "\n".join([
                f"• {item['name']} x{item['quantity']} - ${item['price'] * item['quantity']:.2f}"
                for item in cart
            ])
            
            message = f"""✅ *Agregado al carrito:*
{product['name']} - ${product['price']:.2f}

🛒 *Tu carrito:*
{cart_text}

💰 *Total:* ${total:.2f}

¿Deseas agregar otro producto o confirmar el pedido?"""
            
            return message
            
        except Exception as e:
            logger.error(f"Error processing product order: {e}")
            return "Lo siento, no pude procesar tu pedido. Intenta escribir \"menu\" para ver los productos."

class CartHandler(BaseWhatsAppHandler):
    """Handles cart-related messages from storefront"""
    
    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        """Check if message contains cart ID"""
        message = message_data.get("message", "").lower().strip()
        return message.startswith("pedido:")
    
    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        """Handle cart from storefront"""
        cart_id = message_data.get("message", "").lower().replace("pedido:", "").strip()
        tenant_id = message_data.get("tenant_id")
        phone = message_data.get("phone")
        session = message_data.get("session", {})
        
        try:
            # Get cart from Redis
            cart = await get_cart_service(cart_id)
            
            if not cart:
                return "El carrito ha expirado. Por favor, crea uno nuevo desde la tienda."
            
            # Update session with cart
            session_id = session.get("id")
            if session_id:
                await self.update_session_state(session_id, "viewing_cart", {"cart_id": cart_id})
            
            # Send cart summary
            items_text = "\n".join([
                f"{item['quantity']}x {item['name']} - ${item['price'] * item['quantity']:.2f}"
                for item in cart["items"]
            ])
            
            message = f"""¡Hola! Soy el asistente de Vendly.

Tu pedido:
{items_text}

Total: ${cart['total']:.2f}

¿Deseas agregar algo más o confirmar el pedido?"""
            
            return message
            
        except Exception as e:
            logger.error(f"Error processing cart: {e}")
            return "No puedo encontrar tu carrito. Por favor, intenta nuevamente."

class CartConfirmationHandler(BaseWhatsAppHandler):
    """Handles cart confirmation and payment"""
    
    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        """Check if message is confirming cart"""
        state = message_data.get("session", {}).get("current_state", "")
        message = message_data.get("message", "").lower().strip()
        
        return state == "viewing_cart" and any(
            word in message for word in ["sí", "si", "confirmo", "confirmar", "acepto"]
        )
    
    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        """Handle cart confirmation"""
        tenant_id = message_data.get("tenant_id")
        phone = message_data.get("phone")
        session = message_data.get("session", {})
        
        try:
            # Get cart from session
            cart_id = session.get("session_data", {}).get("cart_id")
            if not cart_id:
                return "No encuentro tu carrito. Por favor, inicia nuevamente."
            
            cart = await get_cart_service(cart_id)
            if not cart:
                return "Tu carrito ha expirado. Por favor, crea uno nuevo."
            
            # Get payment configuration
            config = await self.get_tenant_config(tenant_id)
            payment_info = config.get("payment_info", {})
            
            # Create order in database
            order_data = {
                "tenant_id": tenant_id,
                "customer_phone": phone,
                "total": cart["total"],
                "status": "payment_pending",
                "source": "whatsapp",
                "items": cart["items"]
            }
            
            order_result = self.db.table("orders").insert(order_data).execute()
            order = order_result.data[0] if order_result.data else None
            
            if not order:
                return "Error al procesar tu pedido. Por favor, intenta nuevamente."
            
            # Send payment instructions
            payment_message = f"""¡Pedido confirmado! 🎉

Orden #{order['id'][-8:]}

Total: ${cart['total']:.2f}

💳 Datos para Pago Móvil:
Banco: {payment_info.get('bank', 'Banesco')}
CI: {payment_info.get('ci', 'V-12345678')}
Teléfono: {payment_info.get('phone', '0412-XXX-XXXX')}
Monto: ${cart['total']:.2f}

Por favor, envía el comprobante de pago cuando hayas realizado la transferencia."""
            
            # Update session state
            session_id = session.get("id")
            if session_id:
                await self.update_session_state(
                    session_id, 
                    "payment_pending", 
                    {"order_id": order["id"]}
                )
            
            return payment_message
            
        except Exception as e:
            logger.error(f"Error confirming order: {e}")
            return "Error al procesar tu pedido. Por favor, intenta nuevamente."
