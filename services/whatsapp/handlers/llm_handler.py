"""
LLM Handler for WhatsApp Bot
Multi-provider support: Gemini, OpenRouter, etc.
"""
from typing import Dict, Any, Optional, List
import logging
import json
from datetime import datetime

from .base import BaseWhatsAppHandler
from services.bot_personalities import resolve_personality
from services.llm import get_llm_provider, LLMProvider
from services.i18n import DEFAULT_LANGUAGE, matches_intent, t
from config import get_settings

logger = logging.getLogger(__name__)


# Intents that must always be routed to a deterministic handler in the
# fallback chain instead of the LLM, since the LLM has no grounding/tool-
# calling for order data, appointments, etc. and would just chat generically.
# Keywords live in services/i18n.py (shared with post_sale.py and
# scheduling.py, which used to keep their own drifting copies) and are
# matched across every supported language.
DETERMINISTIC_INTENTS = (
    # order status ("mi pedido" alone is deliberately excluded - too broad,
    # would hijack normal LLM shopping conversation like "agregar a mi pedido")
    "order_status", "return", "change", "booking", "cancel_appointment",
)


def _is_deterministic_intent(message: str) -> bool:
    """True if the message matches an intent that must be handled by a
    specific fallback-chain handler (order status/returns/scheduling),
    never by the general-purpose LLM."""
    normalized = message.lower().strip()
    if normalized.startswith("pedido:"):
        return True
    return any(matches_intent(normalized, intent) for intent in DETERMINISTIC_INTENTS)


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
        # Deterministic intents (storefront cart links, order status,
        # returns, scheduling) must always go to their dedicated handler in
        # the fallback chain, never to the LLM - it has no grounding for any
        # of this data and would just produce a generic chat reply.
        if _is_deterministic_intent(message_data.get("message", "")):
            return False

        settings = get_settings()

        # Only handle if LLM is enabled
        if not settings.LLM_ENABLED:
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
        language = message_data.get("language", DEFAULT_LANGUAGE)

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
            
            # Get LLM provider. Per-tenant provider config is not a feature yet:
            # this used to look up whatsapp_configs.llm_config, a column that
            # exists in no table, so the lookup only ever fed its own except and
            # the provider came from settings regardless.
            logger.info("🤖 Getting LLM provider...")
            provider = get_llm_provider()
            
            if not provider:
                logger.error("❌ Could not create LLM provider")
                return self._get_fallback_message(language)
            logger.info(f"✅ Provider created: {type(provider).__name__}")
            
            # Build prompts using provider's methods
            logger.info("📝 Building system prompt...")
            system_prompt = provider.build_system_prompt(
                store_name=tenant_name,
                personality=personality,
                available_products=available_products,
                language=language
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
                return self._get_fallback_message(language)
            
            if not isinstance(llm_response, dict):
                logger.error(f"❌ LLM returned invalid type: {type(llm_response)}")
                return self._get_fallback_message(language)
            
            if llm_response.get("llm_error"):
                logger.warning(f"⚠️ LLM returned error flag: {llm_response.get('response_text', 'Unknown')}")
                return llm_response.get("response_text", self._get_fallback_message(language))
            
            logger.info(f"✅ LLM response received!")
            logger.info(f"   Intention: {llm_response.get('intention', 'unknown')}")
            logger.info(f"   Products: {len(llm_response.get('products', []))}")
            logger.info(f"   Response text: {llm_response.get('response_text', '')[:100]}")
            
            # Process the LLM response
            intention = llm_response.get("intention", "other")
            response_text = llm_response.get("response_text", "")
            products = llm_response.get("products", [])
            
            # Check if this is a modification to existing cart item (not adding new)
            is_modify_intent = self._detect_modify_intent(user_message, products, current_cart)
            
            if is_modify_intent:
                logger.info(f"🔄 Handling as MODIFY existing cart item (not add)")
                return await self._handle_modify_cart_item(
                    products, response_text, session, tenant_id, phone, current_cart, language
                )
            
            # Check if any product requires confirmation
            if intention == "needs_confirmation" or self._any_product_needs_confirmation(products, provider):
                logger.info(f"🔄 Handling needs_confirmation for {len(products)} products")
                return await self._handle_needs_confirmation(
                    products, response_text, session, tenant_id, phone, language
                )
            
            elif intention == "add_to_cart" and products:
                logger.info(f"🛒 Handling add_to_cart for {len(products)} products")
                return await self._handle_add_to_cart(
                    products, response_text, session, tenant_id, phone, current_cart, language
                )
            
            elif intention == "remove_from_cart":
                logger.info("🗑️ Handling remove_from_cart")
                return await self._handle_remove_from_cart(
                    products, response_text, session, current_cart, language
                )
            
            elif intention == "show_menu":
                logger.info("📋 Handling show_menu - delegating to MenuHandler")
                return None
            
            elif intention == "confirm_order":
                logger.info("✅ Handling confirm_order")
                return await self._handle_confirm_order(
                    response_text, session, current_cart, language
                )
            
            elif intention == "cancel":
                logger.info("❌ Handling cancel")
                return await self._handle_cancel(response_text, session, language)
            
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
            return self._get_fallback_message(language)
    
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
        """Get bot personality configuration for tenant.

        Reads the tenants row and lets services.bot_personalities decide: a
        hand-written prompt wins, then the chosen preset, then the industry
        default, then the settings defaults.

        This used to select bot_personality from whatsapp_configs, where the
        column does not exist, and json.loads() the result. PostgREST rejected
        the select, and the column it meant to read holds prose rather than
        JSON, so per-tenant personality had never worked - every tenant got the
        settings defaults.
        """
        try:
            result = self.db.table("tenants").select(
                "bot_personality, bot_personality_preset, type"
            ).eq("id", tenant_id).execute()

            if result.data:
                return resolve_personality(result.data[0])
        except Exception as e:
            logger.error(f"Could not load personality config: {e}", exc_info=True)

        return resolve_personality(None)


    def _any_product_needs_confirmation(self, products: List[Dict[str, Any]], provider: LLMProvider) -> bool:
        """Check if any product requires confirmation"""
        for product in products:
            if provider.should_confirm_product(product):
                return True
        return False
    
    def _detect_modify_intent(self, user_message: str, products: List[Dict[str, Any]], current_cart: List[Dict[str, Any]]) -> bool:
        """
        Detect if user wants to modify existing cart item vs adding new one.
        Examples: "la hamburguesa la quiero sin salsa", "cambiar la hamburguesa sin cebolla"
        """
        if not current_cart or not products:
            return False
        
        msg_lower = user_message.lower()
        
        # Keywords indicating modification intent
        modify_keywords = [
            "la quiero", "la quieres", "quiero que", "ponle", "ponerle",
            "sin ", "con ", "agregarle", "quitarle", "cambiar", "modificar",
            "hazla", "hazlo", "dale", "también"
        ]
        
        has_modify_keyword = any(kw in msg_lower for kw in modify_keywords)
        
        # Check if product mentioned already exists in cart
        for product in products:
            product_name = product.get("name", "").lower()
            for item in current_cart:
                item_name = item.get("name", "").lower()
                # If product is in cart AND has modification keywords
                if (product_name in item_name or item_name in product_name) and has_modify_keyword:
                    logger.info(f"🔄 Detected MODIFY intent: {product_name} already in cart with modifications")
                    return True
        
        return False
    
    async def _handle_needs_confirmation(
        self,
        products: List[Dict[str, Any]],
        response_text: str,
        session: Dict[str, Any],
        tenant_id: str,
        phone: str,
        language: str = DEFAULT_LANGUAGE
    ) -> str:
        """Handle products that need confirmation before adding to cart"""
        session_id = session.get("id")

        if not session_id:
            return t("llm.process_error", language)

        if not products:
            return response_text or t("llm.specify_product", language)
        
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
            return t("llm.products_not_found", language)
        
        # Store pending products in session
        session_data = session.get("session_data", {}) or {}
        session_data["pending_products"] = pending_products  # Store ALL products
        session_data["awaiting_confirmation"] = True
        
        await self.update_session_state(session_id, "awaiting_confirmation", session_data)
        
        # Build confirmation message with all products
        products_text = "\n".join(products_list_text)
        
        return t(
            "order.confirm_products", language,
            items=products_text, total=f"{total:.2f}",
        )
    
    async def _handle_add_to_cart(
        self,
        products: List[Dict[str, Any]],
        response_text: str,
        session: Dict[str, Any],
        tenant_id: str,
        phone: str,
        current_cart: List[Dict[str, Any]],
        language: str = DEFAULT_LANGUAGE
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
                errors.append(product_data.get("name", t("llm.unknown_product", language)))
        
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
            error_text = "\n\n" + t("cart.not_found_header", language) + " " + ", ".join(errors)

        return t(
            "cart.summary", language,
            added=added_text, items=cart_text,
            total=f"{total:.2f}", errors=error_text,
        )
    
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
        current_cart: List[Dict[str, Any]],
        language: str = DEFAULT_LANGUAGE
    ) -> str:
        """Remove products from cart"""
        # TODO: Implement removal logic
        return response_text or t("llm.remove_not_implemented", language)
    
    async def _handle_confirm_order(
        self,
        response_text: str,
        session: Dict[str, Any],
        current_cart: List[Dict[str, Any]],
        language: str = DEFAULT_LANGUAGE
    ) -> str:
        """Handle order confirmation"""
        if not current_cart:
            return t("cart.empty", language)
        
        # Transition to confirming state
        session_id = session.get("id")
        if session_id:
            await self.update_session_state(session_id, "confirming", session.get("session_data", {}))
        
        cart_text = "\n".join([
            f"• {item['name']} x{item['quantity']} - ${item['price'] * item['quantity']:.2f}"
            for item in current_cart
        ])
        
        total = sum(item["price"] * item["quantity"] for item in current_cart)
        
        return t("order.summary", language, items=cart_text, total=f"{total:.2f}")
    
    async def _handle_cancel(
        self, response_text: str, session: Dict[str, Any], language: str = DEFAULT_LANGUAGE
    ) -> str:
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
        
        return response_text or t("order.cancelled", language)
    
    async def _handle_modify_cart_item(
        self,
        products: List[Dict[str, Any]],
        response_text: str,
        session: Dict[str, Any],
        tenant_id: str,
        phone: str,
        current_cart: List[Dict[str, Any]],
        language: str = DEFAULT_LANGUAGE
    ):
        """
        Handle modification of existing cart items (not adding new ones)
        When user says "la hamburguesa la quiero sin salsa" after order is in cart
        """
        session_id = session.get("id")
        
        if not products:
            return response_text or t("llm.what_to_modify", language)
        
        modified_count = 0
        modification_details = []
        
        for product in products:
            product_name = product.get("name", "").lower()
            modifications = product.get("modifications", [])
            
            # Find matching item in cart
            for item in current_cart:
                item_name = item.get("name", "").lower()
                # Match by product name (partial match allowed)
                if product_name in item_name or item_name in product_name:
                    # Apply modifications
                    old_mods = item.get("modifications", [])
                    item["modifications"] = list(set(old_mods + modifications))  # Merge without duplicates
                    modified_count += 1
                    modification_details.append(f"{item.get('name')} ({', '.join(item['modifications'])})")
                    break
        
        # Calculate new total
        total = sum(
            item.get("price", 0) * item.get("quantity", 1) 
            for item in current_cart
        )
        
        # Build cart summary
        cart_summary = "\n".join([
            f"• {item.get('name')}"
            + (f" ({', '.join(item.get('modifications', []))})" if item.get('modifications') else "")
            + f" x{item.get('quantity', 1)}"
            for item in current_cart
        ])
        
        # Response
        if modified_count > 0:
            response = t(
                "llm.modified", language,
                details=", ".join(modification_details),
                items=cart_summary, total=f"{total:.2f}",
            )
        else:
            response = t(
                "llm.not_in_cart", language,
                items=cart_summary, total=f"{total:.2f}",
            )
        
        # Update session
        if session_id:
            await self.update_session_state(session_id, "cart_review", {
                "cart": current_cart,
                "total": total
            })
            await self._update_history(session, f"modificar {product_name}", response)
        
        return response
    
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
    
    def _get_fallback_message(self, language: str = DEFAULT_LANGUAGE) -> str:
        """Get fallback message when LLM fails"""
        return t("llm.fallback", language)
