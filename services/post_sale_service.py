"""
Post-Sale Support service (spec requirement 19).

Handles order-status lookups and change/return requests for customers who
already placed an order. Per product decision, this is intentionally simple:
requests are logged and the seller is notified to resolve manually - there is
no automated approval/refund workflow (no payment gateway exists to refund
through anyway).
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
import logging

from db.supabase import get_supabase_client
from db.whatsapp_config import fetch_config
from services.whatsapp.meta_service import MetaWhatsAppService
from services.i18n import DEFAULT_LANGUAGE, t

logger = logging.getLogger(__name__)


# Order status -> catalog key. The messages themselves live in
# services/i18n.py so they can be shown in the customer's language.
ORDER_STATUS_KEYS = {
    "payment_pending": "order_status.payment_pending",
    "pending_payment": "order_status.payment_pending",
    "payment_submitted": "order_status.payment_submitted",
    "payment_confirmed": "order_status.payment_confirmed",
    "processing": "order_status.processing",
    "ready": "order_status.ready",
    "delivered": "order_status.delivered",
    "cancelled": "order_status.cancelled",
}


class PostSaleService:
    """Service for order-status inquiries and post-sale change/return requests"""

    def __init__(self, db=None):
        self.db = db or get_supabase_client()

    async def get_recent_orders(
        self, tenant_id: str, customer_phone: str, limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Get a customer's most recent orders, newest first"""
        try:
            result = self.db.table("orders").select("*").eq(
                "tenant_id", tenant_id
            ).eq("customer_phone", customer_phone).order(
                "created_at", desc=True
            ).limit(limit).execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting recent orders for {customer_phone}: {e}")
            return []

    def format_order_status_message(
        self, order: Dict[str, Any], language: str = DEFAULT_LANGUAGE
    ) -> str:
        """Human-readable status message for an order, in the customer's language"""
        status = order.get("status", "")
        status_key = ORDER_STATUS_KEYS.get(status)
        status_text = (
            t(status_key, language) if status_key
            else t("order_status.unknown", language, status=status)
        )
        order_ref = str(order.get("id", ""))[-8:]
        total = order.get("total", 0)
        return t(
            "post_sale.order_line", language,
            order_ref=order_ref, total=f"{total:.2f}", status=status_text,
        )

    async def create_request(
        self,
        tenant_id: str,
        customer_phone: str,
        order_id: Optional[str],
        request_type: str,
        description: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Create a post-sale change/return/question request and notify the seller.
        Returns the created request row, or None on failure.
        """
        try:
            insert_data = {
                "tenant_id": tenant_id,
                "customer_phone": customer_phone,
                "order_id": order_id,
                "request_type": request_type,
                "description": description,
                "status": "open",
            }
            result = self.db.table("post_sale_requests").insert(insert_data).execute()
            request = result.data[0] if result.data else None

            if request:
                await self._notify_seller(tenant_id, customer_phone, request_type, description)

            return request
        except Exception as e:
            logger.error(f"Error creating post-sale request: {e}")
            return None

    async def _notify_seller(
        self, tenant_id: str, customer_phone: str, request_type: str, description: str
    ) -> None:
        """Best-effort seller notification - mirrors the pattern already used
        for new-order notifications in CartConfirmationHandler."""
        try:
            config = fetch_config(
                self.db, tenant_id,
                "seller_phone, phone_number, phone_number_id, access_token",
            )

            if not config:
                logger.warning(f"No whatsapp_configs found for tenant {tenant_id}, skipping notification")
                return
            seller_phone = config.get("seller_phone") or config.get("phone_number")

            if not seller_phone or seller_phone == customer_phone:
                logger.warning(f"No seller phone configured for tenant {tenant_id}, skipping notification")
                return

            type_labels = {"question": "Pregunta", "change": "Solicitud de cambio", "return": "Solicitud de devolución"}
            label = type_labels.get(request_type, "Solicitud post-venta")
            notification = f"📋 {label}\nCliente: {customer_phone}\n{description}"

            MetaWhatsAppService(
                phone_number_id=config["phone_number_id"],
                access_token=config["access_token"],
            ).send_message(seller_phone, notification)
        except Exception as e:
            logger.error(f"Could not notify seller for tenant {tenant_id}: {e}", exc_info=True)

    async def resolve_request(self, tenant_id: str, request_id: str) -> bool:
        """Mark a request resolved and ask the customer to rate the resolution."""
        try:
            result = self.db.table("post_sale_requests").update({
                "status": "resolved",
                "resolved_at": datetime.now().isoformat(),
            }).eq("id", request_id).eq("tenant_id", tenant_id).execute()

            if not result.data:
                return False

            request = result.data[0]
            await self._request_satisfaction_rating(tenant_id, request)
            return True
        except Exception as e:
            logger.error(f"Error resolving post-sale request {request_id}: {e}")
            return False

    async def _request_satisfaction_rating(self, tenant_id: str, request: Dict[str, Any]) -> None:
        """Push a message to the customer asking them to rate 1-5, and flag
        their session to capture the next numeric reply as that rating."""
        customer_phone = request["customer_phone"]
        try:
            config = fetch_config(self.db, tenant_id, "phone_number_id, access_token")

            if not config:
                return

            # Read the session first: it carries the language this customer
            # has been conversing in, so the push goes out in that language.
            session_result = self.db.table("conversation_sessions").select(
                "id, session_data"
            ).eq("tenant_id", tenant_id).eq("customer_phone", customer_phone).execute()

            session_data = {}
            if session_result.data:
                session_data = session_result.data[0].get("session_data") or {}

            MetaWhatsAppService(
                phone_number_id=config["phone_number_id"],
                access_token=config["access_token"],
            ).send_message(
                customer_phone,
                t("post_sale.rate_prompt", session_data.get("language", DEFAULT_LANGUAGE)),
            )

            if session_result.data:
                session = session_result.data[0]
                session_data["awaiting_satisfaction_for"] = request["id"]
                self.db.table("conversation_sessions").update({
                    "session_data": session_data
                }).eq("id", session["id"]).execute()
        except Exception as e:
            logger.error(f"Could not request satisfaction rating from {customer_phone}: {e}", exc_info=True)

    async def rate_satisfaction(self, request_id: str, rating: int) -> bool:
        """Record a 1-5 satisfaction rating for a resolved request"""
        try:
            result = self.db.table("post_sale_requests").update({
                "satisfaction_rating": rating
            }).eq("id", request_id).execute()
            return bool(result.data)
        except Exception as e:
            logger.error(f"Error rating satisfaction for request {request_id}: {e}")
            return False
