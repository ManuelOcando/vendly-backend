"""
Post-sale support handler: order-status inquiries, return/change requests,
and satisfaction-rating capture (spec requirement 19).
"""
from typing import Dict, Any, Optional
import logging

from .base import BaseWhatsAppHandler
from services.post_sale_service import PostSaleService
from services.i18n import DEFAULT_LANGUAGE, matches_intent, t

logger = logging.getLogger(__name__)


class PostSaleHandler(BaseWhatsAppHandler):
    """Handles post-purchase order-status/return/change requests"""

    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        message = message_data.get("message", "").lower().strip()
        session = message_data.get("session", {})
        session_data = session.get("session_data") or {}

        # A pending satisfaction rating always takes priority over keyword matching
        if session_data.get("awaiting_satisfaction_for") and message.strip().isdigit():
            return True

        # Don't intercept an active checkout flow - that belongs to
        # CartConfirmationHandler, which owns the `viewing_cart` state and
        # reads a bare "sí" as "confirm my cart".
        #
        # `payment_pending` is deliberately NOT excluded: it is set once the
        # order already exists and is never cleared, so excluding it locked a
        # customer out of order-status/return requests forever after their
        # first purchase. No handler claims that state, so there is nothing
        # to defer to.
        if session.get("current_state") == "viewing_cart":
            return False

        return any(
            matches_intent(message, intent)
            for intent in ("order_status", "return", "change")
        )

    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        tenant_id = message_data.get("tenant_id")
        phone = message_data.get("phone", "")
        message = message_data.get("message", "").strip()
        message_lower = message.lower()
        session = message_data.get("session", {})
        session_data = session.get("session_data") or {}
        language = message_data.get("language", DEFAULT_LANGUAGE)

        service = PostSaleService(db=self.db)

        try:
            awaiting_request_id = session_data.get("awaiting_satisfaction_for")
            if awaiting_request_id and message.isdigit():
                return await self._capture_satisfaction_rating(
                    service, session, session_data, awaiting_request_id, int(message), language
                )

            if matches_intent(message_lower, "order_status"):
                return await self._handle_status_inquiry(service, tenant_id, phone, language)

            if matches_intent(message_lower, "return") or matches_intent(message_lower, "change"):
                request_type = "return" if matches_intent(message_lower, "return") else "change"
                return await self._handle_change_or_return(
                    service, tenant_id, phone, message, request_type, language
                )

            return None
        except Exception as e:
            logger.error(f"Error in PostSaleHandler: {e}")
            return t("post_sale.error", language)

    async def _handle_status_inquiry(
        self, service: PostSaleService, tenant_id: str, phone: str,
        language: str = DEFAULT_LANGUAGE
    ) -> str:
        orders = await service.get_recent_orders(tenant_id, phone, limit=3)
        if not orders:
            return t("post_sale.no_orders", language)
        return "\n\n".join(
            service.format_order_status_message(order, language) for order in orders
        )

    async def _handle_change_or_return(
        self, service: PostSaleService, tenant_id: str, phone: str, message: str,
        request_type: str, language: str = DEFAULT_LANGUAGE
    ) -> str:
        orders = await service.get_recent_orders(tenant_id, phone, limit=1)
        order_id = orders[0]["id"] if orders else None

        request = await service.create_request(tenant_id, phone, order_id, request_type, message)
        if request:
            return t("post_sale.request_received", language)
        return t("post_sale.request_failed", language)

    async def _capture_satisfaction_rating(
        self, service: PostSaleService, session: Dict[str, Any], session_data: Dict[str, Any],
        request_id: str, rating: int, language: str = DEFAULT_LANGUAGE,
    ) -> str:
        if not 1 <= rating <= 5:
            return t("post_sale.rating_range", language)

        await service.rate_satisfaction(request_id, rating)

        session_data = dict(session_data)
        session_data.pop("awaiting_satisfaction_for", None)
        session_id = session.get("id")
        if session_id:
            await self.update_session_state(
                session_id, session.get("current_state", "initial"), session_data
            )

        return t("post_sale.rating_thanks", language)
