"""
Refactored WhatsApp Bot Service using Chain of Responsibility pattern
Compatible with Meta WhatsApp API
"""
from typing import Dict, Any, Optional
import logging
import asyncio
from datetime import datetime

from db.supabase import get_supabase_client
from db.whatsapp_config import fetch_config
from db.sesion import merge_session_data, read_session_data
from services.whatsapp.handlers import (
    MenuHandler, WelcomeHandler, ProductOrderHandler, ConfirmationHandler,
    CartHandler, CartConfirmationHandler, SellerMenuHandler, LLMHandler,
    OnboardingHandler, PostSaleHandler, ServiceSchedulingHandler,
    CierreDePedidoHandler, CancelarPedidoHandler
)
from services.whatsapp import estado_pedido
from services.conversational_dashboard import ConversationalDashboard
from services.offline_mode_service import OfflineModeService
from services.i18n import DEFAULT_LANGUAGE, detect_language, normalize_language, t
from api.deps import tenant_has_feature
from utils.log_privacy import preview, tel

logger = logging.getLogger(__name__)

class MetaWhatsAppBotService:
    """WhatsApp Bot Service for Meta API using Chain of Responsibility"""

    def __init__(self):
        self.db = get_supabase_client()
        self.dashboard = ConversationalDashboard(self.db)
        self.offline_service = OfflineModeService(self.db)
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Setup the handler chain (LLM-first architecture)"""
        # LLM handler — first and primary respondent for customer messages
        self.llm_handler = LLMHandler(self.db)

        # Fallback chain, used whenever the LLM is disabled, unconfigured or
        # fails at runtime. It has to be able to carry a whole conversation on
        # its own, so it runs from the most specific handler to the most
        # greedy:
        #   CartHandler            "pedido:<id>" prefix from the storefront
        #   ConfirmationHandler    yes/no while products await confirmation
        #   CartConfirmationHandler yes/no while viewing a storefront cart
        #   PostSaleHandler        order status, returns, changes
        #   ServiceSchedulingHandler appointment booking
        #   CancelarPedidoHandler  "cancelar": empties the order
        #   CierreDePedidoHandler  "eso es todo": shows the summary and asks
        #   MenuHandler            "menu"/"catalog" keywords
        #   WelcomeHandler         a bare greeting on a fresh conversation
        #   ProductOrderHandler    catch-all: treats the text as product names
        #
        # MenuHandler precedes WelcomeHandler so "hola, quiero ver el menu"
        # answers with the catalog rather than a greeting, and
        # ProductOrderHandler is last because its can_handle accepts nearly
        # anything that isn't a known command.
        #
        # CancelarPedidoHandler goes *after* ServiceSchedulingHandler because
        # "cancelar mi cita" contains "cancelar": the appointment claims it
        # first, and cancelling an appointment must not wipe an order.
        cart_handler = CartHandler(self.db)
        confirmation_handler = ConfirmationHandler(self.db)
        cart_confirmation_handler = CartConfirmationHandler(self.db)
        post_sale_handler = PostSaleHandler(self.db)
        scheduling_handler = ServiceSchedulingHandler(self.db)
        cancelar_handler = CancelarPedidoHandler(self.db)
        cierre_handler = CierreDePedidoHandler(self.db)
        menu_handler = MenuHandler(self.db)
        welcome_handler = WelcomeHandler(self.db)
        product_order_handler = ProductOrderHandler(self.db)

        cart_handler.next_handler = confirmation_handler
        confirmation_handler.next_handler = cart_confirmation_handler
        cart_confirmation_handler.next_handler = post_sale_handler
        post_sale_handler.next_handler = scheduling_handler
        scheduling_handler.next_handler = cancelar_handler
        cancelar_handler.next_handler = cierre_handler
        cierre_handler.next_handler = menu_handler
        menu_handler.next_handler = welcome_handler
        welcome_handler.next_handler = product_order_handler

        self.fallback_chain = cart_handler

        # Los dos handlers cuyo can_handle depende del estado de la conversacion
        # y no solo del texto. Se les pregunta antes que al LLM: son los que
        # saben que hacer con un "si" o un "no" que responde a una pregunta que
        # el bot acaba de hacer. Se reutilizan sus predicados en vez de duplicar
        # la condicion dentro del LLM, que se desincronizaria al primer cambio.
        self.handlers_con_estado = (confirmation_handler, cart_confirmation_handler)

        # Seller chain (independent, always active)
        self.seller_chain = SellerMenuHandler(self.db)
        
        # Onboarding chain (for new tenants)
        self.onboarding_chain = OnboardingHandler(self.db)
    
    async def process_message(self, tenant_id: str, phone: str, message: str, phone_number_id: str) -> Optional[str]:
        """Process incoming message and return response"""
        language = DEFAULT_LANGUAGE
        try:
            logger.info("Processing message from %s for tenant %s: %s", tel(phone), tenant_id, preview(message))
            
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
            is_seller = await self._is_seller(config, phone)

            is_onboarding = tenant.get("onboarding_status") in (None, "not_started", "in_progress")

            language = await self._resolve_language(tenant_id, phone, message, session, is_seller)

            if is_seller:
                # Reset the inactivity clock and flush any offline messages
                # left by customers while the seller was away (non-blocking).
                await self.offline_service.record_seller_activity(tenant_id)
                asyncio.create_task(self.offline_service.notify_seller_of_pending_messages(tenant_id))
            elif not is_onboarding and await self.offline_service.is_offline(tenant_id):
                offline_reply = await self.offline_service.get_offline_reply(tenant_id, language)
                await self.offline_service.store_offline_message(tenant_id, phone, message)
                await self._log_message(
                    tenant_id=tenant_id,
                    direction="outbound",
                    phone=phone,
                    content=offline_reply,
                    status="delivered"
                )
                return offline_reply

            # Prepare message data for handlers
            message_data = {
                "tenant_id": tenant_id,
                "tenant_name": tenant.get("name", "Tienda"),
                "phone": phone,
                "message": message,
                "phone_number_id": phone_number_id,
                "config": config,
                "session": session,
                "is_seller": is_seller,
                "language": language
            }
            
            # Process through appropriate chain (LLM-first architecture)
            if is_seller:
                response = await self.seller_chain.process(message_data)
            elif await self._la_conversacion_espera_una_respuesta(message_data):
                # El estado manda sobre el LLM. Sin esto, un "si" a una pregunta
                # que el bot acababa de hacer iba al modelo, que lo recibia
                # suelto y sin anclaje: en la primera conversacion real invento
                # un pedido de 17 hamburguesas con modificadores que se
                # contradecian, y los productos que el cliente si habia pedido
                # se quedaron sin recoger para siempre.
                response = await self.fallback_chain.process(message_data)
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

            if not is_seller:
                response = await self._append_translation_notice(
                    tenant_id, session, response, language
                )

            # Log outbound message
            await self._log_message(
                tenant_id=tenant_id,
                direction="outbound",
                phone=phone,
                content=response,
                status="delivered"
            )
            
            logger.info("Bot response: %s", preview(response))
            
            # Check for smart alerts in background (non-blocking)
            if not is_seller:  # Only check alerts for customer messages
                asyncio.create_task(self._check_alerts_background(tenant_id))
            
            return response
            
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            return t("bot.generic_error", language)

    async def _resolve_language(
        self,
        tenant_id: str,
        phone: str,
        message: str,
        session: Dict[str, Any],
        is_seller: bool,
    ) -> str:
        """Decide which language to answer this message in.

        Sellers always get Spanish (the dashboard/config surface is
        Spanish-only). Tenants without the `multi_language` plan feature
        degrade silently to Spanish - no upsell nag is shown to a customer,
        mirroring how CartHandler treats advanced_recommendations.

        Otherwise the conversation carries a sticky language, and only a
        confident detection on the new message switches it (requirement
        15.4). A short ambiguous reply like "ok" detects as None and keeps
        the conversation where it was instead of snapping back to Spanish.
        """
        if is_seller:
            return DEFAULT_LANGUAGE

        try:
            if not await tenant_has_feature(tenant_id, "multi_language"):
                return DEFAULT_LANGUAGE

            session_data = session.get("session_data") or {}
            stored = session_data.get("language")
            detected = detect_language(message)

            if detected:
                language = detected
            elif stored:
                language = normalize_language(stored)
            else:
                language = await self._get_tenant_default_language(tenant_id)

            if language != stored:
                await self._persist_session_language(session, language)

            return language
        except Exception as e:
            logger.error(f"Could not resolve language for tenant {tenant_id}: {e}", exc_info=True)
            return DEFAULT_LANGUAGE

    async def _la_conversacion_espera_una_respuesta(self, message_data: Dict[str, Any]) -> bool:
        """
        Si algun handler de estado reclama este mensaje.

        Es la pregunta que faltaba en el enrutado: LLMHandler.can_handle mira
        solo el texto y nunca el estado, asi que un "si" que respondia a una
        pregunta del propio bot acababa en el modelo en vez de en el handler
        escrito para ese momento.
        """
        for handler in self.handlers_con_estado:
            try:
                if await handler.can_handle(message_data):
                    return True
            except Exception as e:
                logger.error("Fallo consultando %s: %s", type(handler).__name__, e, exc_info=True)
        return False

    async def _get_tenant_default_language(self, tenant_id: str) -> str:
        """The language the seller authored their content in."""
        try:
            result = self.db.table("bot_configurations").select(
                "default_language"
            ).eq("tenant_id", tenant_id).limit(1).execute()
            if result.data:
                return normalize_language(result.data[0].get("default_language"))
        except Exception as e:
            logger.error(f"Could not read default_language for tenant {tenant_id}: {e}", exc_info=True)
        return DEFAULT_LANGUAGE

    async def _persist_session_language(self, session: Dict[str, Any], language: str) -> None:
        """Store the conversation's language, preserving the rest of session_data.

        Recibe la sesion, no su id. Antes volvia a leer session_data de la base
        para no pisar el resto del diccionario -- pero quien llama acaba de
        traerla entera, asi que era un SELECT por cada mensaje en el que cambia
        el idioma, para releer algo que ya estaba en memoria.
        """
        session_id = session.get("id")
        if not session_id:
            return
        try:
            session_data = session.get("session_data") or {}
            session_data["language"] = language
            # Se actualiza tambien en memoria: los handlers reciben esta misma
            # sesion mas abajo y deben ver el idioma ya resuelto.
            session["session_data"] = session_data

            merge_session_data(self.db, session_id, patch={"language": language})
        except Exception as e:
            logger.error(f"Could not persist language for session {session_id}: {e}", exc_info=True)

    async def _append_translation_notice(
        self,
        tenant_id: str,
        session: Dict[str, Any],
        response: Optional[str],
        language: str,
    ) -> Optional[str]:
        """Tell the customer once that they're reading machine translation.

        Requirement 15.3: product names and descriptions stay in whatever
        language the seller typed them into the catalog, so when we answer
        in a different language the customer is getting mixed content and
        deserves to know why. Sent once per conversation, not per message.
        """
        if not response:
            return response

        try:
            if language == await self._get_tenant_default_language(tenant_id):
                return response

            session_data = session.get("session_data") or {}
            if session_data.get("translation_notice_sent"):
                return response

            session_id = session.get("id")
            if session_id:
                stored = read_session_data(self.db, session_id)
                if stored.get("translation_notice_sent"):
                    return response
                merge_session_data(
                    self.db, session_id, patch={"translation_notice_sent": True}
                )

            return response + t("translation.notice", language)
        except Exception as e:
            logger.error(f"Could not append translation notice for tenant {tenant_id}: {e}", exc_info=True)
            return response


    async def _get_tenant(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get tenant information"""
        try:
            result = self.db.table("tenants").select("id, name, onboarding_status").eq("id", tenant_id).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error getting tenant: {e}")
            return None
    
    async def _get_tenant_config(self, tenant_id: str) -> Dict[str, Any]:
        """Get tenant WhatsApp configuration"""
        try:
            return fetch_config(self.db, tenant_id) or {}
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
    
    async def _is_seller(self, config: Dict[str, Any], phone: str) -> bool:
        """Check if phone number belongs to the seller (business owner) of the tenant.

        Recibe la config ya leida en vez de volver a consultarla: process_message
        la trae unas lineas antes por _get_tenant_config, y esto disparaba un
        segundo SELECT identico sobre whatsapp_configs en cada mensaje.

        Logic:
        - Uses the tenant's whatsapp_configs row.
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
            if not config:
                return False

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
        language = message_data.get("language", DEFAULT_LANGUAGE)
        session = message_data.get("session", {}) or {}
        state = session.get("current_state", "initial")

        if state == "viewing_cart":
            return t("bot.viewing_cart_default", language)

        # Con un pedido a medias no se puede saludar como si no existiera. Es
        # donde caia el "no" que el propio resumen invita a escribir para
        # seguir agregando: no lo reclamaba ningun handler y el cliente recibia
        # el menu de bienvenida, sin rastro de lo que llevaba pedido.
        estado = estado_pedido.leer(session.get("session_data"))
        if estado.carrito:
            return t(
                "bot.ordering_default", language,
                items="\n".join(estado_pedido.linea_texto(l) for l in estado.carrito),
                total=f"{estado.total:.2f}",
            )

        return t("bot.default_menu", language)
    
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
                config = fetch_config(
                    self.db, tenant_id,
                    "seller_phone, phone_number, phone_number_id, access_token",
                )

                if config:
                    seller_phone = config.get("seller_phone") or config.get("phone_number")
                    phone_number_id = config.get("phone_number_id")
                    
                    if seller_phone and phone_number_id:
                        # The tenant's own credentials, and send_message takes
                        # only (to, message). This used to build the service with
                        # no arguments - falling back to the global
                        # META_WHATSAPP_PHONE_ID - then pass phone_number_id= as
                        # a keyword and await it. send_message is synchronous and
                        # has no such parameter, so every call raised TypeError
                        # and no alert was ever delivered.
                        from services.whatsapp.meta_service import MetaWhatsAppService

                        whatsapp_service = MetaWhatsAppService(
                            phone_number_id=phone_number_id,
                            access_token=config.get("access_token"),
                        )

                        for alert_message in alerts:
                            if alert_message:
                                result = await asyncio.to_thread(
                                    whatsapp_service.send_message,
                                    seller_phone,
                                    alert_message,
                                )
                                if result.get("status") == "sent":
                                    logger.info("Alert sent to seller %s", tel(seller_phone))
                                else:
                                    logger.error(
                                        "Alert to %s failed: %s",
                                        seller_phone, result.get("error"),
                                    )
            
        except Exception as e:
            logger.error(f"Error checking alerts in background: {e}")

# Global instance for backward compatibility
bot_service = MetaWhatsAppBotService()
