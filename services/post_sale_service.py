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
from services.whatsapp.meta_service import MetaWhatsAppService

logger = logging.getLogger(__name__)


ORDER_STATUS_MESSAGES = {
    "payment_pending": "Estamos esperando la confirmación de tu pago.",
    "pending_payment": "Estamos esperando la confirmación de tu pago.",
    "payment_submitted": "Recibimos tu comprobante de pago, lo estamos verificando.",
    "payment_confirmed": "Tu pago fue confirmado, estamos preparando tu pedido.",
    "processing": "Tu pedido está en preparación.",
    "ready": "¡Tu pedido está listo!",
    "delivered": "Tu pedido ya fue entregado.",
    "cancelled": "Este pedido fue cancelado.",
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

    def format_order_status_message(self, order: Dict[str, Any]) -> str:
        """Human-readable Spanish status message for an order"""
        status = order.get("status", "")
        status_text = ORDER_STATUS_MESSAGES.get(status, f"Estado: {status}")
        order_ref = str(order.get("id", ""))[-8:]
        total = order.get("total", 0)
        return f"Pedido #{order_ref} - ${total:.2f}\n{status_text}"

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
            config_result = self.db.table("whatsapp_configs").select(
                "seller_phone, phone_number, phone_number_id, access_token"
            ).eq("tenant_id", tenant_id).limit(1).execute()

            if not config_result.data:
                logger.warning(f"No whatsapp_configs found for tenant {tenant_id}, skipping notification")
                return

            config = config_result.data[0]
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
            logger.warning(f"Could not notify seller for tenant {tenant_id}: {e}")

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
            config_result = self.db.table("whatsapp_configs").select(
                "phone_number_id, access_token"
            ).eq("tenant_id", tenant_id).limit(1).execute()

            if not config_result.data:
                return

            config = config_result.data[0]
            MetaWhatsAppService(
                phone_number_id=config["phone_number_id"],
                access_token=config["access_token"],
            ).send_message(
                customer_phone,
                "Tu solicitud fue resuelta. ¿Cómo calificarías la atención? Responde del 1 al 5.",
            )

            session_result = self.db.table("conversation_sessions").select(
                "id, session_data"
            ).eq("tenant_id", tenant_id).eq("customer_phone", customer_phone).execute()

            if session_result.data:
                session = session_result.data[0]
                session_data = session.get("session_data") or {}
                session_data["awaiting_satisfaction_for"] = request["id"]
                self.db.table("conversation_sessions").update({
                    "session_data": session_data
                }).eq("id", session["id"]).execute()
        except Exception as e:
            logger.warning(f"Could not request satisfaction rating from {customer_phone}: {e}")

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
