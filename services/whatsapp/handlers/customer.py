"""
Customer message handlers for WhatsApp bot
"""
from typing import Any, Dict, List, NamedTuple, Optional
import re
import json
import logging
from datetime import datetime

from .base import BaseWhatsAppHandler
from db.redis import get_redis_client
from db.whatsapp_config import fetch_config
from services.payment_instructions import compose as compose_payment_instructions
from services.whatsapp.meta_service import MetaWhatsAppService
from services.customer_profile import CustomerProfileService
from services.recommendation_engine import RecommendationEngine
from services.recommendation_tracker import RecommendationTracker
from models.recommendation import RecommendationRequest
from api.deps import tenant_has_feature
from services.i18n import DEFAULT_LANGUAGE, matches_intent, matches_word_intent, t

logger = logging.getLogger(__name__)

class WelcomeHandler(BaseWhatsAppHandler):
    """Handles welcome messages and greetings"""
    
    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        """Check if message is a greeting"""
        message = message_data.get("message", "").lower().strip()
        state = message_data.get("session", {}).get("current_state", "initial")
        
        return state == "initial" and matches_intent(message, "greeting")
    
    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        """Handle greeting message"""
        tenant_name = message_data.get("tenant_name", "Tienda")
        config = message_data.get("config", {})
        language = message_data.get("language", DEFAULT_LANGUAGE)

        # A seller-authored welcome_message is used as-is (it's their own
        # wording); only the built-in default gets translated.
        welcome_msg = config.get("welcome_message")
        if welcome_msg:
            message = welcome_msg.format(store_name=tenant_name)
        else:
            message = t("welcome.default", language, store_name=tenant_name)

        message += t("welcome.options", language)
        
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
        return matches_intent(message, "menu")
    
    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        """Handle menu request"""
        tenant_id = message_data.get("tenant_id")
        language = message_data.get("language", DEFAULT_LANGUAGE)

        try:
            # Get all active products (not just featured)
            items_result = self.db.table("items").select(
                "name, price, description"
            ).eq("tenant_id", tenant_id).eq("is_active", True).limit(10).execute()

            if not items_result.data:
                return t("menu.empty", language)
            
            items_text = "\n\n".join([
                f"🍔 {item['name']}\n💲 ${item['price']:.2f}\n{item.get('description', '')}"
                for item in items_result.data
            ])
            
            return t("menu.header", language, items=items_text)

        except Exception as e:
            logger.error(f"Error getting menu: {e}")
            return t("menu.error", language)

class ProductOrderHandler(BaseWhatsAppHandler):
    """Handles ordering products by name - supports multiple products in one message"""
    
    # Separadores para detectar múltiples productos
    PRODUCT_SEPARATORS = [" y ", " + ", ", ", " mas ", " más ", "; ", " | "]
    
    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        """Check if message could be a product name (not a command)"""
        message = message_data.get("message", "").lower().strip()

        # Must be at least 2 characters and not a command
        if len(message) < 2:
            return False

        if message.startswith("pedido:") or "carrito" in message or "cart" in message:
            return False

        # Greeting/menu keywords are long enough to match as substrings;
        # confirm/reject are short words ("no", "si", "ok") that must match
        # as whole words or they fire inside product names like "normal".
        if matches_intent(message, "greeting") or matches_intent(message, "menu"):
            return False
        if matches_word_intent(message, "confirm") or matches_word_intent(message, "reject"):
            return False

        return True
    
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
    
    async def _find_product(
        self, tenant_id: str, search_term: str, language: str = DEFAULT_LANGUAGE
    ) -> tuple:
        """Find product by search term. Returns (product, error_message)"""
        search_normalized = self._normalize_text(search_term)
        
        # Search for products
        items_result = self.db.table("items").select(
            "id, name, price, description"
        ).eq("tenant_id", tenant_id).eq("is_active", True).execute()
        
        if not items_result.data:
            return None, t("product.none_available", language)
        
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
            return None, t("product.not_found", language, name=search_term)
        elif len(matches) == 1:
            return matches[0], None
        else:
            # Multiple matches - return list for user to choose
            product_list = "\n".join([f"• {m['name']} - ${m['price']:.2f}" for m in matches[:5]])
            return None, t("product.which_one", language, options=product_list)
    
    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        """Handle product order by name - supports multiple products"""
        tenant_id = message_data.get("tenant_id")
        phone = message_data.get("phone")
        raw_message = message_data.get("message", "").strip()
        session = message_data.get("session", {})
        language = message_data.get("language", DEFAULT_LANGUAGE)

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
                product, error = await self._find_product(tenant_id, product_name, language)
                
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
                return t("product.could_not_add", language, errors="\n".join(errors))
            
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
                error_text = "\n\n" + t("cart.not_found_header", language) + "\n" + "\n".join(errors)
            
            return t(
                "cart.summary", language,
                added=added_text, items=cart_text,
                total=f"{total:.2f}", errors=error_text,
            )
            
        except Exception as e:
            logger.error(f"Error processing product order: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return t("product.order_error", language)

class ConfirmationHandler(BaseWhatsAppHandler):
    """Handles confirmation responses (yes/no) when there's a pending product"""
    
    
    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        """Check if message is a confirmation response and there's a pending product"""
        message = message_data.get("message", "").lower().strip()
        session = message_data.get("session", {})
        
        # Check if we're awaiting confirmation
        session_data = session.get("session_data", {}) or {}
        is_awaiting = session_data.get("awaiting_confirmation", False)
        
        # Support both single product (backward compat) and multiple products
        has_pending = (
            session_data.get("pending_products") is not None or 
            session_data.get("pending_product") is not None
        )
        
        if not (is_awaiting and has_pending):
            return False
        
        # Check if message is a confirmation response. Whole-word matching:
        # a bare substring "no" fires inside product names like "normal".
        return (
            matches_word_intent(message, "confirm")
            or matches_word_intent(message, "reject")
        )
    
    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        """Handle confirmation or rejection of pending product(s)"""
        message = message_data.get("message", "").lower().strip()
        session = message_data.get("session", {})
        language = message_data.get("language", DEFAULT_LANGUAGE)

        session_data = session.get("session_data", {}) or {}
        current_cart = session_data.get("cart", [])
        
        # Support both single product (backward compat) and multiple products
        pending_products = session_data.get("pending_products")
        if not pending_products:
            # Try old format (backward compatibility)
            single_product = session_data.get("pending_product")
            if single_product:
                pending_products = [single_product]
            else:
                return t("confirmation.no_pending", language)
        
        # Ensure it's a list
        if not isinstance(pending_products, list):
            pending_products = [pending_products]
        
        # Check if confirmed or rejected
        is_confirmed = matches_word_intent(message, "confirm")
        is_rejected = matches_word_intent(message, "reject")
        
        session_id = session.get("id")
        
        if is_confirmed:
            # Add all pending products to cart
            added_products_text = []
            
            for pending_product in pending_products:
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
                
                # Build added product text
                modifications = pending_product.get("modifications", [])
                mod_text = ""
                if modifications:
                    mod_text = f" ({', '.join(modifications)})"
                
                added_products_text.append(f"✅ {pending_product['name']}{mod_text} x{pending_product.get('quantity', 1)}")
            
            # Clear pending products and update state
            session_data["pending_products"] = None
            session_data["pending_product"] = None  # Clear both formats
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
            
            added_text = "\n".join(added_products_text)
            
            return t(
                "cart.summary", language,
                added=added_text, items=cart_text,
                total=f"{total:.2f}", errors="",
            )
        
        elif is_rejected:
            # Clear pending products (both formats)
            session_data["pending_products"] = None
            session_data["pending_product"] = None
            session_data["awaiting_confirmation"] = False
            
            if session_id:
                await self.update_session_state(session_id, "ordering", session_data)
            
            return t("confirmation.discarded", language)
        
        return None  # Let next handler process

def normalizar_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Una sola forma de item, vengan de donde vengan.

    Habia dos carritos con claves incompatibles: el de la tienda web, que vive
    en Redis y llama `item_id` al producto, y el de la conversacion, que vive en
    session_data["cart"] y lo llama `product_id`. Esa diferencia es la razon de
    que crear el pedido estuviera atado a uno solo de los dos.
    """
    normalizados = []
    for item in items or []:
        id_producto = item.get("item_id") or item.get("product_id") or item.get("id")
        cantidad = item.get("quantity", 1) or 1
        precio = item.get("price", 0) or 0
        normalizados.append({
            "id": id_producto,
            "name": item.get("name", ""),
            "price": precio,
            "quantity": cantidad,
            "subtotal": precio * cantidad,
        })
    return normalizados


class PedidoCreado(NamedTuple):
    """El identificador hace falta aparte: la sesion lo guarda para la postventa."""
    order_id: str
    mensaje: str


async def crear_pedido(
    db,
    tenant_id: str,
    phone: str,
    items: List[Dict[str, Any]],
    language: str = DEFAULT_LANGUAGE,
) -> Optional[PedidoCreado]:
    """
    Crea el pedido y devuelve su id y el mensaje de confirmacion para el cliente.

    Unico sitio del backend que inserta en `orders`. Antes vivia dentro de
    CartConfirmationHandler, que exige el estado `viewing_cart`, y ese estado
    solo lo pone CartHandler al recibir un enlace `pedido:` de la tienda web.
    Consecuencia: pedir hablando con el bot no podia producir un pedido, por
    construccion. Cuatro meses y cero filas en `orders` lo confirman.

    Se extrajo en vez de duplicarse porque aqui dentro pasan cinco cosas
    -- pedido, lineas, historial de compra, aviso al vendedor y datos de cobro --
    y una copia perderia la mitad en la primera divergencia.

    Devuelve None si el pedido no llego a crearse; el llamante decide que decir.
    """
    items = normalizar_items(items)
    if not items:
        return None

    total = sum(item["subtotal"] for item in items)

    order_data = {
        "tenant_id": tenant_id,
        "customer_phone": phone,
        "total": total,
        "subtotal": total,
        "status": "payment_pending",
    }

    order_result = db.table("orders").insert(order_data).execute()
    order = order_result.data[0] if order_result.data else None
    if not order:
        return None

    # Lineas del pedido. Se registra el fallo en vez de propagarlo: la fila del
    # pedido ya esta escrita, y reventar aqui le diria al cliente que su compra
    # no salio cuando si salio.
    try:
        db.table("order_items").insert([
            {
                "tenant_id": tenant_id,
                "order_id": order["id"],
                "item_id": item["id"],
                "item_name": item["name"],
                "quantity": item["quantity"],
                "unit_price": item["price"],
                "subtotal": item["subtotal"],
            }
            for item in items
        ]).execute()
    except Exception as e:
        logger.error("No se pudieron registrar las lineas del pedido %s: %s",
                     order["id"], e, exc_info=True)

    # Historial de compra, para recomendaciones futuras. Nunca bloquea.
    try:
        await CustomerProfileService(db=db).record_purchase(
            tenant_id, phone, order["id"],
            [{"product_id": i["id"], "quantity": i["quantity"], "amount": i["subtotal"]}
             for i in items],
        )
    except Exception as e:
        logger.error("No se pudo registrar el historial de compra de %s: %s",
                     tenant_id, e, exc_info=True)

    await _avisar_al_vendedor(db, tenant_id, phone, order, items, total)

    return PedidoCreado(
        order_id=order["id"],
        mensaje=t(
            "order.confirmed", language,
            order_ref=order["id"][-8:],
            total=f"{total:.2f}",
            payment_instructions=_instrucciones_de_pago(db, tenant_id, total, language),
        ),
    )


async def _avisar_al_vendedor(db, tenant_id, phone, order, items, total) -> None:
    """Aviso al vendedor. Best-effort: su fallo no afecta al pedido del cliente."""
    try:
        config = fetch_config(
            db, tenant_id, "seller_phone, phone_number, phone_number_id, access_token",
        )
        if not config:
            logger.warning("Sin whatsapp_configs para %s, no se avisa al vendedor", tenant_id)
            return

        seller_phone = config.get("seller_phone") or config.get("phone_number")
        if not seller_phone or seller_phone == phone:
            logger.warning("Sin telefono de vendedor para %s, no se avisa", tenant_id)
            return

        resumen = ", ".join(f"{i['quantity']}x {i['name']}" for i in items)
        MetaWhatsAppService(
            phone_number_id=config["phone_number_id"],
            access_token=config["access_token"],
        ).send_message(
            seller_phone,
            f"🛒 Nuevo pedido #{order['id'][-8:]}\n"
            f"Cliente: {phone}\n"
            f"Total: ${total:.2f}\n"
            f"Items: {resumen}"
        )
    except Exception as e:
        logger.error("No se pudo avisar al vendedor de %s: %s", tenant_id, e, exc_info=True)


def _instrucciones_de_pago(db, tenant_id: str, total: float, language: str) -> str:
    """Los datos de cobro del vendedor, en el idioma del cliente."""
    try:
        resultado = db.table("bot_configurations").select(
            "payment_info, payment_instructions"
        ).eq("tenant_id", tenant_id).limit(1).execute()

        if resultado.data:
            fila = resultado.data[0]
            return compose_payment_instructions(
                fila.get("payment_info"), total, language,
                legacy_text=fila.get("payment_instructions"),
            )
    except Exception as e:
        logger.error("No se pudo leer bot_configurations de %s: %s", tenant_id, e, exc_info=True)

    return t("order.payment_default", language)


async def _get_cart_from_redis(cart_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a cart from Redis by cart_id. Returns None if not found or expired."""
    try:
        redis_client = get_redis_client()
        cart_data = await redis_client.get(f"cart:{cart_id}")
        if not cart_data:
            return None
        cart = json.loads(cart_data)
        # Check expiration
        expires_at_str = cart.get("expires_at")
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str)
            if datetime.utcnow() > expires_at:
                await redis_client.delete(f"cart:{cart_id}")
                return None
        return cart
    except Exception as e:
        logger.error(f"Error retrieving cart {cart_id} from Redis: {e}")
        return None


class CartHandler(BaseWhatsAppHandler):
    """Handles cart-related messages from storefront"""
    
    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        """Check if message contains cart ID (case-insensitive prefix check)"""
        message = message_data.get("message", "").strip()
        return message.lower().startswith("pedido:")
    
    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        """Handle cart from storefront"""
        raw_message = message_data.get("message", "").strip()
        # Preserve original case of cart_id — only strip the "pedido:" prefix
        cart_id = raw_message[len("pedido:"):].strip()
        tenant_id = message_data.get("tenant_id")
        phone = message_data.get("phone", "")
        session = message_data.get("session", {})
        language = message_data.get("language", DEFAULT_LANGUAGE)
        tenant_name = message_data.get("tenant_name", "Vendly")

        try:
            # Get cart directly from Redis (not via API endpoint)
            cart = await _get_cart_from_redis(cart_id)

            if not cart:
                return t("cart.expired", language)

            # Update session with cart_id and transition to viewing_cart
            session_id = session.get("id")
            if session_id:
                await self.update_session_state(session_id, "viewing_cart", {"cart_id": cart_id})

            # Send cart summary
            items_text = "\n".join([
                f"{item['quantity']}x {item['name']} - ${item['price'] * item['quantity']:.2f}"
                for item in cart["items"]
            ])

            message = t(
                "cart.storefront_summary", language,
                store_name=tenant_name, items=items_text,
                total=f"{cart['total']:.2f}",
            )

            recommendations_section = await self._build_recommendations_section(
                tenant_id, phone, cart, language
            )
            if recommendations_section:
                message += f"\n\n{recommendations_section}"

            message += t("cart.add_more_or_confirm", language)

            return message

        except Exception as e:
            logger.error(f"Error processing cart: {e}")
            return t("cart.lookup_error", language)

    async def _build_recommendations_section(
        self, tenant_id: str, phone: str, cart: Dict[str, Any],
        language: str = DEFAULT_LANGUAGE
    ) -> Optional[str]:
        """Build a short "you might also like" section based on what's
        already in the cart. Premium-only (advanced_recommendations); never
        raises - a failure here must not break the cart summary reply."""
        try:
            if not await tenant_has_feature(tenant_id, "advanced_recommendations"):
                return None

            # Ensure a profile row exists so generate_recommendations takes the
            # real (cart-aware) path instead of always falling back to cold-start.
            await CustomerProfileService(db=self.db).get_or_create_profile(tenant_id, phone)

            cart_item_ids = [item["item_id"] for item in cart["items"]]
            request = RecommendationRequest(
                tenant_id=tenant_id,
                customer_phone=phone,
                limit=3,
                exclude_product_ids=cart_item_ids,
                current_cart_items=[{"product_id": item_id} for item_id in cart_item_ids],
            )
            response = await RecommendationEngine(db=self.db).generate_recommendations(request)

            if not response.recommendations:
                return None

            tracker = RecommendationTracker(db=self.db)
            lines = []
            for rec in response.recommendations:
                lines.append(f"• {rec.product_name} - ${rec.current_price:.2f}")
                try:
                    await tracker.track_shown(tenant_id, phone, rec.product_id, rec.recommendation_type)
                except Exception as tracking_err:
                    logger.error(f"Could not track shown recommendation: {tracking_err}", exc_info=True)

            return t("cart.recommendations_header", language) + "\n" + "\n".join(lines)
        except Exception as e:
            logger.error(f"Could not build recommendations for tenant {tenant_id}: {e}", exc_info=True)
            return None


class CartConfirmationHandler(BaseWhatsAppHandler):
    """
    Cierra el pedido, venga el carrito de donde venga.

    Dos origenes, un solo desenlace:

      * Tienda web -> el cliente manda "pedido:<id>", CartHandler deja el estado
        en `viewing_cart` y el carrito en Redis.
      * Conversacion -> el cliente pide hablando, ConfirmationHandler mete los
        productos en session_data["cart"] y deja el estado en `ordering`.

    El segundo no tenia salida: `viewing_cart` solo lo escribe CartHandler, y
    este handler era el unico sitio que insertaba en `orders`. Pedir hablando no
    podia terminar en un pedido.
    """

    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        message = message_data.get("message", "").lower().strip()
        if not matches_word_intent(message, "confirm"):
            return False

        session = message_data.get("session", {}) or {}
        state = session.get("current_state", "")

        if state == "viewing_cart":
            return True

        session_data = session.get("session_data") or {}
        return state == "ordering" and bool(session_data.get("cart"))

    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        tenant_id = message_data.get("tenant_id")
        phone = message_data.get("phone")
        session = message_data.get("session", {}) or {}
        language = message_data.get("language", DEFAULT_LANGUAGE)
        session_data = session.get("session_data") or {}

        try:
            if session.get("current_state") == "viewing_cart":
                cart_id = session_data.get("cart_id")
                if not cart_id:
                    return t("cart.not_found", language)
                cart = await _get_cart_from_redis(cart_id)
                if not cart:
                    return t("cart.expired_simple", language)
                items = cart.get("items", [])
            else:
                items = session_data.get("cart", [])

            if not items:
                return t("cart.empty", language)

            pedido = await crear_pedido(self.db, tenant_id, phone, items, language)
            if not pedido:
                return t("order.process_error", language)

            # El carrito ya es un pedido: vaciarlo evita que un segundo "si"
            # cree el mismo pedido otra vez. El order_id se guarda porque la
            # postventa lo busca ahi.
            session_id = session.get("id")
            if session_id:
                await self.update_session_state(
                    session_id, "payment_pending",
                    {"order_id": pedido.order_id, "cart": [], "cart_id": None, "total": 0},
                )

            return pedido.mensaje

        except Exception as e:
            logger.error(f"Error confirming order: {e}", exc_info=True)
            return t("order.process_error", language)
