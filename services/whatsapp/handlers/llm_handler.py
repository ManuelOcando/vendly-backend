"""
LLM Handler for WhatsApp Bot
Multi-provider support: Gemini, OpenRouter, etc.
"""
from typing import Dict, Any, Optional, List
import logging
import json
from datetime import datetime

from .base import BaseWhatsAppHandler
from services.llm import get_llm_provider, LLMProvider
from config import get_settings

logger = logging.getLogger(__name__)


class LLMHandler(BaseWhatsAppHandler):
    """
    Handler that uses LLM to process natural language messages.
    Supports multiple providers: Gemini, OpenRouter, etc.
    This is a fallback handler when other handlers don't match.
    """
    
    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        """
        This handler can process any message that reaches it.
        It's designed to be a fallback in the chain.
        """
        settings = get_settings()
        
        # Only handle if LLM fallback is enabled
        if not settings.LLM_FALLBACK_ENABLED:
            return False
        
        # Check if we have API key configured for the selected provider
        provider = getattr(settings, 'LLM_PROVIDER', 'gemini')
        
        if provider == "gemini" and not settings.GEMINI_API_KEY:
            logger.warning("Gemini API key not configured, skipping LLM handler")
            return False
        elif provider == "openrouter" and not settings.OPENROUTER_API_KEY:
            logger.warning("OpenRouter API key not configured, skipping LLM handler")
            return False
        
        return True
    
    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        """
        Process message through LLM and return appropriate response
        """
        tenant_id = message_data.get("tenant_id")
        phone = message_data.get("phone")
        user_message = message_data.get("message", "").strip()
        session = message_data.get("session", {})
        tenant_name = message_data.get("tenant_name", "Tienda")
        
        try:
            logger.info("="*60)
            logger.info(f"🟢 LLMHANDLER START - Message: '{user_message[:100]}'")
            logger.info(f"Tenant: {tenant_id}, Phone: {phone}")
            logger.info("="*60)
            
            # Get available products
            logger.info("📦 Getting available products...")
            available_products = await self._get_available_products(tenant_id)
            logger.info(f"✅ Found {len(available_products)} products")
            
            # Get current cart from session
            session_data = session.get("session_data", {}) or {}
            current_cart = session_data.get("cart", [])
            current_state = session.get("current_state", "initial")
            logger.info(f"🛒 Current cart: {len(current_cart)} items, State: {current_state}")
            
            # Get conversation history
            conversation_history = session_data.get("history", [])
            logger.info(f"💬 History length: {len(conversation_history)}")
            
            # Get tenant personality config
            logger.info("👤 Getting personality config...")
            personality = await self._get_personality(tenant_id)
            logger.info(f"✅ Personality: {personality.get('tone', 'casual')}")
            
            # Get LLM provider (supports tenant-specific config)
            logger.info("🤖 Getting LLM provider...")
            tenant_config = await self._get_tenant_llm_config(tenant_id)
            provider = get_llm_provider(tenant_config)
            
            if not provider:
                logger.error("❌ Could not create LLM provider")
                return self._get_fallback_message()
            logger.info(f"✅ Provider created: {type(provider).__name__}")
            
            # Build prompts using provider's methods
            logger.info("📝 Building system prompt...")
            system_prompt = provider.build_system_prompt(
                store_name=tenant_name,
                personality=personality,
                available_products=available_products
            )
            logger.info(f"✅ System prompt built ({len(system_prompt)} chars)")
            
            logger.info("📝 Building context prompt...")
            context_prompt = provider.build_context_prompt(
                current_cart=current_cart,
                conversation_history=conversation_history,
                current_state=current_state
            )
            logger.info(f"✅ Context prompt built ({len(context_prompt)} chars)")
            
            # Call LLM
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "system", "content": context_prompt},
                {"role": "user", "content": user_message}
            ]
            logger.info(f"📤 Calling LLM with {len(messages)} messages...")
            
            llm_response = await provider.generate_response(
                messages=messages,
                temperature=0.7,
                max_tokens=2000,
                response_format={"type": "json_object"}
            )
            
            # Check if there was an LLM error
            if not llm_response:
                logger.error("❌ LLM returned None!")
                return self._get_fallback_message()
            
            if not isinstance(llm_response, dict):
                logger.error(f"❌ LLM returned invalid type: {type(llm_response)}")
                return self._get_fallback_message()
            
            if llm_response.get("llm_error"):
                logger.warning(f"⚠️ LLM returned error flag: {llm_response.get('response_text', 'Unknown')}")
                return llm_response.get("response_text", self._get_fallback_message())
            
            logger.info(f"✅ LLM response received!")
            logger.info(f"   Intention: {llm_response.get('intention', 'unknown')}")
            logger.info(f"   Products: {len(llm_response.get('products', []))}")
            logger.info(f"   Response text: {llm_response.get('response_text', '')[:100]}")
            
            # Process the LLM response
            intention = llm_response.get("intention", "other")
            response_text = llm_response.get("response_text", "")
            products = llm_response.get("products", [])
            
            # Check if any product requires confirmation
            if intention == "needs_confirmation" or self._any_product_needs_confirmation(products, provider):
                logger.info(f"🔄 Handling needs_confirmation for {len(products)} products")
                return await self._handle_needs_confirmation(
                    products, response_text, session, tenant_id, phone
                )
            
            elif intention == "add_to_cart" and products:
                logger.info(f"🛒 Handling add_to_cart for {len(products)} products")
                return await self._handle_add_to_cart(
                    products, response_text, session, tenant_id, phone, current_cart
                )
            
            elif intention == "remove_from_cart":
                logger.info("🗑️ Handling remove_from_cart")
                return await self._handle_remove_from_cart(
                    products, response_text, session, current_cart
                )
            
            elif intention == "show_menu":
                logger.info("📋 Handling show_menu - delegating to MenuHandler")
                return None
            
            elif intention == "confirm_order":
                logger.info("✅ Handling confirm_order")
                return await self._handle_confirm_order(
                    response_text, session, current_cart
                )
            
            elif intention == "cancel":
                logger.info("❌ Handling cancel")
                return await self._handle_cancel(response_text, session)
            
            else:
                logger.info(f"💬 Handling other intention: {intention}")
                # Just return the response text from LLM
                # Update conversation history
                await self._update_history(session, user_message, response_text)
                return response_text
                
        except Exception as e:
            logger.error("="*60)
            logger.error(f"❌ CRITICAL ERROR in LLMHandler.handle")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error message: {str(e)}")
            logger.error(f"Full traceback:", exc_info=True)
            logger.error("="*60)
            return self._get_fallback_message()
    
    async def _get_available_products(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Get list of available products for tenant"""
        try:
            result = self.db.table("items").select(
                "id, name, price, description"
            ).eq("tenant_id", tenant_id).eq("is_active", True).execute()
            
            return result.data or []
        except Exception as e:
            logger.error(f"Error getting products: {e}")
            return []
    
    async def _get_personality(self, tenant_id: str) -> Dict[str, Any]:
        """Get bot personality configuration for tenant"""
        settings = get_settings()
        
        try:
            # Try to get from tenant config
            result = self.db.table("whatsapp_configs").select(
                "bot_personality"
            ).eq("tenant_id", tenant_id).execute()
            
            if result.data and result.data[0].get("bot_personality"):
                personality = result.data[0]["bot_personality"]
                if isinstance(personality, str):
                    personality = json.loads(personality)
                return personality
        except Exception as e:
            logger.warning(f"Could not load personality config: {e}")
        
        # Return defaults
        return {
            "tone": settings.BOT_DEFAULT_TONE,
            "use_emojis": settings.BOT_DEFAULT_EMOJIS,
            "greeting_style": settings.BOT_DEFAULT_GREETING
        }
    
    async def _get_tenant_llm_config(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get tenant-specific LLM configuration"""
        try:
            result = self.db.table("whatsapp_configs").select(
                "llm_config"
            ).eq("tenant_id", tenant_id).execute()
            
            if result.data and result.data[0].get("llm_config"):
                config = result.data[0]["llm_config"]
                if isinstance(config, str):
                    config = json.loads(config)
                return config
        except Exception as e:
            logger.warning(f"Could not load tenant LLM config: {e}")
        
        return None
    
    def _any_product_needs_confirmation(self, products: List[Dict[str, Any]], provider: LLMProvider) -> bool:
        """Check if any product requires confirmation"""
        for product in products:
            if provider.should_confirm_product(product):
                return True
        return False
    
    async def _handle_needs_confirmation(
        self,
        products: List[Dict[str, Any]],
        response_text: str,
        session: Dict[str, Any],
        tenant_id: str,
        phone: str
    ) -> str:
        """Handle products that need confirmation before adding to cart"""
        session_id = session.get("id")
        
        if not session_id:
            return "Lo siento, no pudo procesar tu pedido. Intenta nuevamente."
        
        if not products:
            return response_text or "¿Podrías especificar qué producto deseas?"
        
        # Match all products in database
        pending_products = []
        products_list_text = []
        total = 0
        
        for product in products:
            matched_product = await self._find_product_in_db(tenant_id, product.get("name", ""))
            
            if matched_product:
                quantity = product.get("quantity", 1)
                modifications = product.get("modifications", [])
                price = matched_product["price"] * quantity
                total += price
                
                pending_products.append({
                    "product_id": matched_product["id"],
                    "name": matched_product["name"],
                    "price": matched_product["price"],
                    "quantity": quantity,
                    "modifications": modifications
                })
                
                # Build product line
                mod_text = ""
                if modifications:
                    mod_text = f" ({', '.join(modifications)})"
                
                products_list_text.append(f"• {matched_product['name']}{mod_text} x{quantity} - ${price:.2f}")
        
        if not pending_products:
            return f"No encontré los productos. ¿Podrías verificar los nombres?"
        
        # Store pending products in session
        session_data = session.get("session_data", {}) or {}
        session_data["pending_products"] = pending_products  # Store ALL products
        session_data["awaiting_confirmation"] = True
        
        await self.update_session_state(session_id, "awaiting_confirmation", session_data)
        
        # Build confirmation message with all products
        products_text = "\n".join(products_list_text)
        
        confirmation_msg = f"""🤔 *Confirmar pedido*

¿Deseas agregar:
{products_text}

💰 *Total:* ${total:.2f}

Responde:
✅ *si* / *confirmar* / *sí* - para agregar todo
❌ *no* / *cancelar* - para descartar"""
        
        return confirmation_msg
    
    async def _handle_add_to_cart(
        self,
        products: List[Dict[str, Any]],
        response_text: str,
        session: Dict[str, Any],
        tenant_id: str,
        phone: str,
        current_cart: List[Dict[str, Any]]
    ) -> str:
        """Add products to cart directly (no confirmation needed)"""
        added_products = []
        errors = []
        
        cart = current_cart.copy() if current_cart else []
        
        for product_data in products:
            # Find product in database
            matched_product = await self._find_product_in_db(
                tenant_id, 
                product_data.get("name", "")
            )
            
            if matched_product:
                # Check if already in cart
                existing = next(
                    (item for item in cart if item["product_id"] == matched_product["id"]),
                    None
                )
                
                quantity = product_data.get("quantity", 1)
                modifications = product_data.get("modifications", [])
                
                if existing:
                    existing["quantity"] += quantity
                    if modifications:
                        existing.setdefault("modifications", []).extend(modifications)
                    added_products.append(f"{matched_product['name']} x{existing['quantity']}")
                else:
                    cart_item = {
                        "product_id": matched_product["id"],
                        "name": matched_product["name"],
                        "price": matched_product["price"],
                        "quantity": quantity,
                        "modifications": modifications
                    }
                    cart.append(cart_item)
                    added_products.append(matched_product['name'])
            else:
                errors.append(product_data.get("name", "Producto desconocido"))
        
        # Calculate total
        total = sum(item["price"] * item["quantity"] for item in cart)
        
        # Update session
        session_id = session.get("id")
        if session_id:
            session_data = session.get("session_data", {}) or {}
            session_data["cart"] = cart
            session_data["total"] = total
            await self.update_session_state(session_id, "ordering", session_data)
        
        # Build response
        added_text = "\n".join([f"✅ {name}" for name in added_products])
        
        cart_text = "\n".join([
            f"• {item['name']} x{item['quantity']} - ${item['price'] * item['quantity']:.2f}"
            for item in cart
        ])
        
        error_text = ""
        if errors:
            error_text = f"\n\n⚠️ No encontré: {', '.join(errors)}"
        
        message = f"""{added_text}

🛒 *Tu carrito:*
{cart_text}

💰 *Total:* ${total:.2f}{error_text}

¿Deseas agregar otro producto o confirmar el pedido?"""
        
        return message
    
    async def _find_product_in_db(self, tenant_id: str, search_name: str) -> Optional[Dict[str, Any]]:
        """Find product in database by name (fuzzy matching)"""
        from difflib import SequenceMatcher
        
        search_normalized = search_name.lower().strip()
        
        # Get all products
        products = await self._get_available_products(tenant_id)
        
        best_match = None
        best_ratio = 0.0
        
        for product in products:
            product_name = product.get("name", "").lower().strip()
            
            # Exact match
            if search_normalized == product_name:
                return product
            
            # Partial match
            ratio = SequenceMatcher(None, search_normalized, product_name).ratio()
            if ratio > best_ratio and ratio > 0.6:  # Threshold 60%
                best_ratio = ratio
                best_match = product
        
        return best_match
    
    async def _handle_remove_from_cart(
        self,
        products: List[Dict[str, Any]],
        response_text: str,
        session: Dict[str, Any],
        current_cart: List[Dict[str, Any]]
    ) -> str:
        """Remove products from cart"""
        # TODO: Implement removal logic
        return response_text or "Función de remover productos en desarrollo."
    
    async def _handle_confirm_order(
        self,
        response_text: str,
        session: Dict[str, Any],
        current_cart: List[Dict[str, Any]]
    ) -> str:
        """Handle order confirmation"""
        if not current_cart:
            return "Tu carrito está vacío. Agrega productos primero."
        
        # Transition to confirming state
        session_id = session.get("id")
        if session_id:
            await self.update_session_state(session_id, "confirming", session.get("session_data", {}))
        
        cart_text = "\n".join([
            f"• {item['name']} x{item['quantity']} - ${item['price'] * item['quantity']:.2f}"
            for item in current_cart
        ])
        
        total = sum(item["price"] * item["quantity"] for item in current_cart)
        
        return f"""📋 *Resumen de tu pedido:*

{cart_text}

💰 *Total a pagar:* ${total:.2f}

✅ ¿Confirmas este pedido?
Responde *sí* para confirmar o *no* para seguir agregando."""
    
    async def _handle_cancel(self, response_text: str, session: Dict[str, Any]) -> str:
        """Handle order cancellation"""
        session_id = session.get("id")
        
        if session_id:
            # Clear cart and reset state
            session_data = session.get("session_data", {}) or {}
            session_data["cart"] = []
            session_data["total"] = 0
            session_data["pending_product"] = None
            session_data["awaiting_confirmation"] = False
            await self.update_session_state(session_id, "initial", session_data)
        
        return response_text or "Pedido cancelado. Escribe *hola* para comenzar de nuevo."
    
    async def _update_history(
        self,
        session: Dict[str, Any],
        user_message: str,
        bot_response: str
    ):
        """Update conversation history in session"""
        session_id = session.get("id")
        if not session_id:
            return
        
        session_data = session.get("session_data", {}) or {}
        history = session_data.get("history", [])
        
        # Add new messages
        history.append({"role": "user", "content": user_message, "timestamp": datetime.now().isoformat()})
        history.append({"role": "assistant", "content": bot_response, "timestamp": datetime.now().isoformat()})
        
        # Keep last 20 messages (10 exchanges)
        history = history[-20:]
        
        session_data["history"] = history
        
        # Update without changing state
        try:
            self.db.table("conversation_sessions").update({
                "session_data": session_data,
                "updated_at": datetime.now().isoformat()
            }).eq("id", session_id).execute()
        except Exception as e:
            logger.error(f"Error updating history: {e}")
    
    def _get_fallback_message(self) -> str:
        """Get fallback message when LLM fails"""
        return """🤖 Lo siento, no pude procesar tu mensaje con inteligencia artificial en este momento.

Puedes intentar pedir de estas formas:
• Escribe el nombre exacto del producto (ej: "hamburguesa clásica")
• Escribe "menu" para ver la lista de productos
• Para pedidos simples, escribe: "[producto] y [producto]" (ej: "hamburguesa y papas")

¿En qué puedo ayudarte? Escribe "hola" para comenzar."""
