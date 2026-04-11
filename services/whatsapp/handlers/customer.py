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
        
        # Normalizar acentos para comparación
        message_normalized = message.replace("ú", "u").replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o")
        
        keywords = ["menu", "catalogo", "ver productos", "productos", "catalogo"]
        keywords_with_accents = ["menú", "catálogo"]
        
        return any(keyword in message_normalized for keyword in keywords) or \
               any(keyword in message for keyword in keywords_with_accents)
    
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
    """Handles ordering products by name - supports multiple products in one message"""
    
    # Separadores para detectar múltiples productos
    PRODUCT_SEPARATORS = [" y ", " + ", ", ", " mas ", " más ", "; ", " | "]
    
    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        """Check if message could be a product name (not a command)"""
        message = message_data.get("message", "").lower().strip()
        
        # Normalizar para comparar comandos
        message_normalized = message.replace("ú", "u").replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o")
        
        # Skip if it's a known command
        commands = ["hola", "hi", "hello", "menu", "catalogo", "catálogo",
                   "ver productos", "productos", "pedido:", "si", "sí", 
                   "confirmar", "confirmo", "acepto", "no", "cancelar", "ver carrito", "carrito"]
        
        # Must be at least 2 characters and not a command
        if len(message) < 2:
            return False
            
        return not any(cmd in message_normalized for cmd in commands)
    
    def _normalize_text(self, text: str) -> str:
        """Remove accents for better matching"""
        return text.lower().replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u").replace("ñ", "n").strip()
    
    def _split_products(self, message: str) -> list:
        """Split message into multiple product names"""
        # Reemplazar todos los separadores por un marcador común
        temp = message
        for sep in self.PRODUCT_SEPARATORS:
            temp = temp.replace(sep, "||")
        
        # Dividir y limpiar
        products = [p.strip() for p in temp.split("||") if p.strip()]
        return products
    
    async def _find_product(self, tenant_id: str, search_term: str) -> tuple:
        """Find product by search term. Returns (product, error_message)"""
        search_normalized = self._normalize_text(search_term)
        
        # Search for products
        items_result = self.db.table("items").select(
            "id, name, price, description"
        ).eq("tenant_id", tenant_id).eq("is_active", True).execute()
        
        if not items_result.data:
            return None, f"No hay productos disponibles"
        
        # Buscar coincidencia exacta primero (sin acentos)
        for item in items_result.data:
            item_name_normalized = self._normalize_text(item['name'])
            if search_normalized == item_name_normalized:
                return item, None
        
        # Buscar coincidencia parcial
        matches = []
        for item in items_result.data:
            item_name_normalized = self._normalize_text(item['name'])
            if search_normalized in item_name_normalized or item_name_normalized in search_normalized:
                matches.append(item)
        
        if len(matches) == 0:
            return None, f"No encontré \"{search_term}\""
        elif len(matches) == 1:
            return matches[0], None
        else:
            # Multiple matches - return list for user to choose
            product_list = "\n".join([f"• {m['name']} - ${m['price']:.2f}" for m in matches[:5]])
            return None, f"¿Cuál de estos?\n{product_list}"
    
    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        """Handle product order by name - supports multiple products"""
        tenant_id = message_data.get("tenant_id")
        phone = message_data.get("phone")
        raw_message = message_data.get("message", "").strip()
        session = message_data.get("session", {})
        
        try:
            # Split message into multiple products
            product_names = self._split_products(raw_message)
            
            if not product_names:
                return None  # Let next handler handle it
            
            logger.info(f"Processing {len(product_names)} product(s): {product_names}")
            
            # Get or create session cart
            session_data = session.get("session_data", {}) or {}
            cart = session_data.get("cart", [])
            
            added_products = []
            errors = []
            
            # Process each product
            for product_name in product_names:
                product, error = await self._find_product(tenant_id, product_name)
                
                if product:
                    # Check if already in cart (increment quantity)
                    existing = next((item for item in cart if item["product_id"] == product["id"]), None)
                    if existing:
                        existing["quantity"] += 1
                        added_products.append(f"{product['name']} x{existing['quantity']}")
                    else:
                        cart_item = {
                            "product_id": product["id"],
                            "name": product["name"],
                            "price": product["price"],
                            "quantity": 1
                        }
                        cart.append(cart_item)
                        added_products.append(product['name'])
                else:
                    errors.append(f"• {product_name}: {error}")
            
            # If nothing was added and there are errors
            if not added_products and errors:
                return f"❌ No pude agregar:\n" + "\n".join(errors) + "\n\n🛒 Escribe \"menu\" para ver los productos"
            
            # Calculate total
            total = sum(item["price"] * item["quantity"] for item in cart)
            
            # Update session
            session_id = session.get("id")
            if session_id:
                await self.update_session_state(
                    session_id, 
                    "ordering", 
                    {"cart": cart, "total": total}
                )
            
            # Build response
            added_text = "\n".join([f"✅ {name}" for name in added_products])
            
            cart_text = "\n".join([
                f"• {item['name']} x{item['quantity']} - ${item['price'] * item['quantity']:.2f}"
                for item in cart
            ])
            
            error_text = ""
            if errors:
                error_text = f"\n\n⚠️ No encontré:\n" + "\n".join(errors)
            
            message = f"""{added_text}

🛒 *Tu carrito:*
{cart_text}

💰 *Total:* ${total:.2f}{error_text}

¿Deseas agregar otro producto o confirmar el pedido?"""
            
            return message
            
        except Exception as e:
            logger.error(f"Error processing product order: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return "Lo siento, no pude procesar tu pedido. Intenta escribir \"menu\" para ver los productos."

class ConfirmationHandler(BaseWhatsAppHandler):
    """Handles confirmation responses (yes/no) when there's a pending product"""
    
    CONFIRM_KEYWORDS = ["si", "sí", "yes", "confirmar", "confirmo", "acepto", "dale", "ok", "okay"]
    REJECT_KEYWORDS = ["no", "cancelar", "nope", "rechazar", "denegar"]
    
    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        """Check if message is a confirmation response and there's a pending product"""
        message = message_data.get("message", "").lower().strip()
        session = message_data.get("session", {})
        
        # Check if we're awaiting confirmation
        session_data = session.get("session_data", {}) or {}
        is_awaiting = session_data.get("awaiting_confirmation", False)
        has_pending = session_data.get("pending_product") is not None
        
        if not (is_awaiting and has_pending):
            return False
        
        # Check if message is a confirmation response
        return any(keyword in message for keyword in self.CONFIRM_KEYWORDS + self.REJECT_KEYWORDS)
    
    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        """Handle confirmation or rejection of pending product"""
        message = message_data.get("message", "").lower().strip()
        session = message_data.get("session", {})
        
        session_data = session.get("session_data", {}) or {}
        pending_product = session_data.get("pending_product", {})
        current_cart = session_data.get("cart", [])
        
        if not pending_product:
            return "No hay ningún producto pendiente de confirmación."
        
        # Check if confirmed or rejected
        is_confirmed = any(keyword in message for keyword in self.CONFIRM_KEYWORDS)
        is_rejected = any(keyword in message for keyword in self.REJECT_KEYWORDS)
        
        session_id = session.get("id")
        
        if is_confirmed:
            # Add product to cart
            product_id = pending_product.get("product_id")
            existing = next((item for item in current_cart if item["product_id"] == product_id), None)
            
            if existing:
                existing["quantity"] += pending_product.get("quantity", 1)
                if pending_product.get("modifications"):
                    existing.setdefault("modifications", []).extend(pending_product["modifications"])
            else:
                cart_item = {
                    "product_id": product_id,
                    "name": pending_product["name"],
                    "price": pending_product["price"],
                    "quantity": pending_product.get("quantity", 1),
                    "modifications": pending_product.get("modifications", [])
                }
                current_cart.append(cart_item)
            
            # Clear pending product and update state
            session_data["pending_product"] = None
            session_data["awaiting_confirmation"] = False
            session_data["cart"] = current_cart
            
            total = sum(item["price"] * item["quantity"] for item in current_cart)
            session_data["total"] = total
            
            if session_id:
                await self.update_session_state(session_id, "ordering", session_data)
            
            # Build cart summary
            cart_text = "\n".join([
                f"• {item['name']} x{item['quantity']} - ${item['price'] * item['quantity']:.2f}"
                for item in current_cart
            ])
            
            modifications = pending_product.get("modifications", [])
            mod_text = ""
            if modifications:
                mod_text = f" {' '.join(modifications)}"
            
            return f"""✅ *Agregado:*
{pending_product['name']}{mod_text} x{pending_product.get('quantity', 1)}

🛒 *Tu carrito:*
{cart_text}

💰 *Total:* ${total:.2f}

¿Deseas agregar otro producto o confirmar el pedido?"""
        
        elif is_rejected:
            # Clear pending product
            session_data["pending_product"] = None
            session_data["awaiting_confirmation"] = False
            
            if session_id:
                await self.update_session_state(session_id, "ordering", session_data)
            
            return """❌ Producto descartado.

¿Deseas intentar con otro producto? Escribe:
• "menu" para ver la lista
• El nombre de otro producto"""
        
        return None  # Let next handler process

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
