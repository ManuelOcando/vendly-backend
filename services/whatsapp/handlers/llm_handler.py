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
from utils.log_privacy import preview, tel

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


def _linea_de_producto(producto: Dict[str, Any]) -> str:
    """Una linea del pedido: `• hamburguesa (sin cebolla) x2 - $20.00`."""
    modificaciones = producto.get("modifications") or []
    detalle = f" ({', '.join(modificaciones)})" if modificaciones else ""
    cantidad = producto.get("quantity", 1)
    subtotal = producto.get("price", 0) * cantidad
    return f"• {producto.get('name', '')}{detalle} x{cantidad} - ${subtotal:.2f}"


# Como empieza una modificacion en los tres idiomas. Un "producto" que empieza
# asi no es un producto: es lo que hay que hacerle al anterior.
_INICIOS_DE_MODIFICACION = (
    "sin ", "con ", "extra ", "sem ", "com ",
    "without ", "with ", "no ", "add ", "hold the ",
)


def parece_modificacion(nombre: str) -> bool:
    """Si este 'producto' es en realidad una modificacion del anterior."""
    limpio = (nombre or "").strip().lower()
    return limpio.startswith(_INICIOS_DE_MODIFICACION)


def reasignar_modificaciones(
    products: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Devuelve las modificaciones que el modelo mando como productos sueltos.

    Ante "otra hamburguesa sin lechuga y sin tomate" el modelo a veces devuelve
    dos entradas -- {"name": "hamburguesa", ...} y {"name": "sin tomate"} -- y
    la segunda no existe en ningun catalogo. El cliente veia
    'No encontre "sin tomate"' y, peor, se quedaba sin la modificacion: pedia
    una hamburguesa sin tomate y le llegaba con tomate.

    Se arregla aqui y no en el prompt porque el prompt no da garantias: por bien
    redactado que este, el modelo volvera a partirlo alguna vez. Esto lo recoge
    siempre.

    Una modificacion que llega primera, sin producto al que pegarse, se deja
    como estaba y acaba en el "no encontre" de siempre. Es deliberado: pasa
    cuando el cliente se refiere a algo que ya esta en el carrito ("ponte sin
    tomate"), y descartarla en silencio haria que el bot contestara con un visto
    bueno y el carrito sin tocar. El cliente creeria que se aplico y recibiria
    el tomate igual. Que se le diga que no se entendio es peor conversacion y
    mejor pedido.
    """
    resultado = []
    for producto in products or []:
        nombre = producto.get("name", "")
        if parece_modificacion(nombre) and resultado:
            anterior = resultado[-1]
            anterior["modifications"] = list(anterior.get("modifications") or [])
            anterior["modifications"].append(nombre.strip())
        else:
            resultado.append(dict(producto))
    return resultado


def fusionar_pendientes(
    anteriores: Optional[List[Dict[str, Any]]],
    nuevos: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Añade productos a lo que ya estaba pendiente de confirmar, sin perderlo.

    Antes se reemplazaba. Un cliente pidio cinco productos por $50, y al decir
    "ponme otra hamburguesa" la propuesta paso a ser solo esa hamburguesa por
    $10: los cinco anteriores desaparecieron sin aviso, y eso fue lo que
    confirmo.

    Dos lineas se funden solo si son el mismo producto **con las mismas
    modificaciones**: "hamburguesa" y "hamburguesa sin cebolla" son cosas
    distintas en la cocina y tienen que seguir siendo dos lineas.

    Para reemplazar el pedido en vez de ampliarlo, el cliente cancela y vuelve a
    pedir; eso ya existe y responde a "no".
    """
    fusionados = [dict(p) for p in (anteriores or [])]

    for nuevo in nuevos:
        clave_nueva = (nuevo.get("product_id"), tuple(nuevo.get("modifications") or []))
        for existente in fusionados:
            clave = (existente.get("product_id"), tuple(existente.get("modifications") or []))
            if clave == clave_nueva:
                existente["quantity"] = existente.get("quantity", 1) + nuevo.get("quantity", 1)
                break
        else:
            fusionados.append(dict(nuevo))

    return fusionados


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
            logger.info("🟢 LLMHANDLER START - Message: %s", preview(user_message))
            logger.info("Tenant: %s, Phone: %s", tenant_id, tel(phone))
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
                logger.error("❌ Could not create LLM provider, cediendo a la cadena determinista")
                return None
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
            
            # El LLM no dio nada usable: cede a la cadena determinista.
            if not isinstance(llm_response, dict) or not llm_response:
                logger.error(f"❌ LLM unusable ({type(llm_response).__name__}), cediendo a la cadena determinista")
                return None

            # El proveedor no pudo parsear su propia salida y devolvio relleno.
            # Tiene forma de respuesta valida, asi que sin esta comprobacion se
            # cuela como si el LLM hubiera contestado y el cliente recibe una
            # disculpa en vez del saludo o el catalogo que la cadena si sabe dar.
            if llm_response.get("llm_error"):
                logger.warning("⚠️ Relleno del proveedor, cediendo a la cadena determinista")
                return None

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
            # Ceder, no disculparse: la cadena determinista sabe saludar,
            # mostrar el menu y tomar un pedido por nombre sin tocar el LLM.
            return None
    
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
        
        # Mismo rescate que en la rama de añadir al carrito: el modelo elige
        # entre las dos segun le parece, y parte "hamburguesa sin tomate" en dos
        # productos en cualquiera de ellas.
        products = reasignar_modificaciones(products)

        # Match all products in database
        nuevos = []

        for product in products:
            matched_product = await self._find_product_in_db(tenant_id, product.get("name", ""))

            if matched_product:
                nuevos.append({
                    "product_id": matched_product["id"],
                    "name": matched_product["name"],
                    "price": matched_product["price"],
                    "quantity": product.get("quantity", 1),
                    "modifications": product.get("modifications", []),
                })

        if not nuevos:
            return t("llm.products_not_found", language)

        # Se acumulan sobre lo que ya estaba pendiente, no lo reemplazan. Antes
        # era una asignacion directa, asi que un cliente que decia "ponme otra
        # hamburguesa" mientras tenia cinco productos sin confirmar perdia los
        # cinco: el pedido pasaba de $50 a $10 sin avisar, y confirmaba eso.
        session_data = session.get("session_data", {}) or {}
        pending_products = fusionar_pendientes(
            session_data.get("pending_products"), nuevos
        )

        session_data["pending_products"] = pending_products
        session_data["awaiting_confirmation"] = True

        await self.update_session_state(session_id, "awaiting_confirmation", session_data)

        # El mensaje enseña el pedido entero, no solo lo ultimo añadido: es lo
        # que el cliente esta a punto de confirmar.
        total = sum(p["price"] * p["quantity"] for p in pending_products)
        products_text = "\n".join(_linea_de_producto(p) for p in pending_products)
        
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

        cart = [dict(item) for item in (current_cart or [])]

        # Lo que estaba esperando confirmacion pasa al carrito antes de añadir
        # nada. Sin esto se quedaba huerfano: el LLM elige entre esta rama y la
        # de confirmar segun le parece, y no comparten estado, asi que un
        # cliente con cuatro productos pendientes por $40 pedia uno mas y el
        # pedido se quedaba en ese uno. Nada se da por aceptado a la ligera --
        # al final se sigue preguntando "¿Confirmas el pedido?".
        session_data = session.get("session_data", {}) or {}
        pendientes = session_data.get("pending_products") or []
        if pendientes:
            cart = fusionar_pendientes(cart, pendientes)

        # El modelo a veces parte "otra hamburguesa sin lechuga y sin tomate" en
        # dos productos, y el segundo -- "sin tomate" -- no existe en el
        # catalogo: el cliente veia 'No encontre "sin tomate"' y perdia la
        # modificacion.
        products = reasignar_modificaciones(products)

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
            session_data["cart"] = cart
            session_data["total"] = total
            # Ya estan en el carrito: dejarlos pendientes los duplicaria en
            # cuanto el cliente respondiera "si".
            session_data["pending_products"] = None
            session_data["awaiting_confirmation"] = False
            await self.update_session_state(session_id, "ordering", session_data)

        # Build response
        added_text = "\n".join([f"✅ {name}" for name in added_products])

        cart_text = "\n".join(_linea_de_producto(item) for item in cart)
        
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
            # Las dos claves. Solo se limpiaba pending_product, la antigua en
            # singular, y pending_products -- la que se usa -- sobrevivia a la
            # cancelacion. Con _handle_add_to_cart volcando lo pendiente al
            # carrito, eso resucitaba el pedido cancelado en cuanto el cliente
            # pedia cualquier otra cosa.
            session_data["pending_product"] = None
            session_data["pending_products"] = None
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
