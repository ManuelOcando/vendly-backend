"""
Post-sale support handler: order-status inquiries, return/change requests,
and satisfaction-rating capture (spec requirement 19).
"""
from typing import Dict, Any, Optional
import logging

from .base import BaseWhatsAppHandler
from services.post_sale_service import PostSaleService

logger = logging.getLogger(__name__)

ORDER_STATUS_KEYWORDS = [
    "estado de mi pedido", "dónde está mi pedido", "donde esta mi pedido",
    "seguimiento de mi pedido", "rastrear mi pedido",
]
RETURN_KEYWORDS = ["devolver", "devolución", "devolucion", "reembolso"]
CHANGE_KEYWORDS = ["cambiar mi pedido", "cambio de producto"]


class PostSaleHandler(BaseWhatsAppHandler):
    """Handles post-purchase order-status/return/change requests"""

    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        message = message_data.get("message", "").lower().strip()
        session = message_data.get("session", {})
        session_data = session.get("session_data") or {}

        # A pending satisfaction rating always takes priority over keyword matching
        if session_data.get("awaiting_satisfaction_for") and message.strip().isdigit():
            return True

        # Don't intercept an active checkout flow - that belongs to CartHandler/CartConfirmationHandler
        if session.get("current_state") in ("viewing_cart", "payment_pending"):
            return False

        keywords = ORDER_STATUS_KEYWORDS + RETURN_KEYWORDS + CHANGE_KEYWORDS
        return any(keyword in message for keyword in keywords)

    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        tenant_id = message_data.get("tenant_id")
        phone = message_data.get("phone", "")
        message = message_data.get("message", "").strip()
        message_lower = message.lower()
        session = message_data.get("session", {})
        session_data = session.get("session_data") or {}

        service = PostSaleService(db=self.db)

        try:
            awaiting_request_id = session_data.get("awaiting_satisfaction_for")
            if awaiting_request_id and message.isdigit():
                return await self._capture_satisfaction_rating(
                    service, session, session_data, awaiting_request_id, int(message)
                )

            if any(keyword in message_lower for keyword in ORDER_STATUS_KEYWORDS):
                return await self._handle_status_inquiry(service, tenant_id, phone)

            if any(keyword in message_lower for keyword in RETURN_KEYWORDS + CHANGE_KEYWORDS):
                request_type = "return" if any(k in message_lower for k in RETURN_KEYWORDS) else "change"
                return await self._handle_change_or_return(service, tenant_id, phone, message, request_type)

            return None
        except Exception as e:
            logger.error(f"Error in PostSaleHandler: {e}")
            return "Ocurrió un error al procesar tu solicitud. Por favor intenta nuevamente."

    async def _handle_status_inquiry(self, service: PostSaleService, tenant_id: str, phone: str) -> str:
        orders = await service.get_recent_orders(tenant_id, phone, limit=3)
        if not orders:
            return "No encontré pedidos recientes asociados a tu número."
        return "\n\n".join(service.format_order_status_message(order) for order in orders)

    async def _handle_change_or_return(
        self, service: PostSaleService, tenant_id: str, phone: str, message: str, request_type: str
    ) -> str:
        orders = await service.get_recent_orders(tenant_id, phone, limit=1)
        order_id = orders[0]["id"] if orders else None

        request = await service.create_request(tenant_id, phone, order_id, request_type, message)
        if request:
            return "Recibimos tu solicitud. El vendedor se pondrá en contacto contigo pronto. 📋"
        return "No pudimos procesar tu solicitud. Por favor intenta nuevamente."

    async def _capture_satisfaction_rating(
        self, service: PostSaleService, session: Dict[str, Any], session_data: Dict[str, Any],
        request_id: str, rating: int,
    ) -> str:
        if not 1 <= rating <= 5:
            return "Por favor responde con un número del 1 al 5."

        await service.rate_satisfaction(request_id, rating)

        session_data = dict(session_data)
        session_data.pop("awaiting_satisfaction_for", None)
        session_id = session.get("id")
        if session_id:
            await self.update_session_state(
                session_id, session.get("current_state", "initial"), session_data
            )

        return "¡Gracias por tu calificación! 🙌"
