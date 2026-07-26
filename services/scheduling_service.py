"""
Service Scheduling service (spec requirement 20).

Appointment booking for professional-services tenants: real-time slot
availability (business hours minus already-booked appointments), booking,
cancellation (respecting a configurable cancellation-policy window), and a
query for reminders that are due to be sent. Sending reminders on a schedule
is a separate, deliberately undeployed concern - see scripts/send_appointment_reminders.py.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, date, time, timedelta
import logging

from db.supabase import get_supabase_client
from services.whatsapp.meta_service import MetaWhatsAppService

logger = logging.getLogger(__name__)

DEFAULT_SERVICE_DURATION_MINUTES = 30
DEFAULT_CANCELLATION_POLICY_HOURS = 24


class SchedulingService:
    """Service for appointment availability, booking, and cancellation"""

    def __init__(self, db=None):
        self.db = db or get_supabase_client()

    async def _get_business_hours_for_day(
        self, tenant_id: str, target_date: date
    ) -> Optional[tuple]:
        """Returns (open_time, close_time) for the given date's weekday, or
        None if the business is closed that day / not configured."""
        try:
            result = self.db.table("bot_configurations").select(
                "business_hours"
            ).eq("tenant_id", tenant_id).limit(1).execute()

            if not result.data:
                return None

            business_hours = result.data[0].get("business_hours") or {}
            weekday_name = target_date.strftime("%A").lower()
            day_hours = business_hours.get(weekday_name)

            if not day_hours or not day_hours.get("open") or not day_hours.get("close"):
                return None

            open_time = datetime.strptime(day_hours["open"], "%H:%M").time()
            close_time = datetime.strptime(day_hours["close"], "%H:%M").time()
            return (open_time, close_time)
        except Exception as e:
            logger.warning(f"Error getting business hours for tenant {tenant_id}: {e}")
            return None

    async def _get_item_duration_minutes(self, tenant_id: str, item_id: str) -> int:
        try:
            result = self.db.table("items").select(
                "service_duration_minutes"
            ).eq("tenant_id", tenant_id).eq("id", item_id).execute()

            if result.data and result.data[0].get("service_duration_minutes"):
                return result.data[0]["service_duration_minutes"]
        except Exception as e:
            logger.warning(f"Error getting service duration for item {item_id}: {e}")

        return DEFAULT_SERVICE_DURATION_MINUTES

    async def _get_cancellation_policy_hours(self, tenant_id: str) -> int:
        try:
            result = self.db.table("bot_configurations").select(
                "cancellation_policy_hours"
            ).eq("tenant_id", tenant_id).limit(1).execute()

            if result.data and result.data[0].get("cancellation_policy_hours") is not None:
                return result.data[0]["cancellation_policy_hours"]
        except Exception as e:
            logger.warning(f"Error getting cancellation policy for tenant {tenant_id}: {e}")

        return DEFAULT_CANCELLATION_POLICY_HOURS

    async def get_available_slots(
        self, tenant_id: str, item_id: str, target_date: date
    ) -> List[datetime]:
        """Real-time availability: business hours for that weekday, chunked
        by the service's duration, minus already-booked appointments."""
        hours = await self._get_business_hours_for_day(tenant_id, target_date)
        if not hours:
            return []
        open_time, close_time = hours

        duration_minutes = await self._get_item_duration_minutes(tenant_id, item_id)
        duration = timedelta(minutes=duration_minutes)

        try:
            day_start = datetime.combine(target_date, time.min)
            day_end = datetime.combine(target_date, time.max)
            existing = self.db.table("appointments").select(
                "scheduled_at, duration_minutes"
            ).eq("tenant_id", tenant_id).eq("item_id", item_id).eq(
                "status", "scheduled"
            ).gte("scheduled_at", day_start.isoformat()).lte(
                "scheduled_at", day_end.isoformat()
            ).execute()
            booked_data = existing.data or []
        except Exception as e:
            logger.warning(f"Error getting existing appointments for item {item_id}: {e}")
            booked_data = []

        booked_ranges = []
        for row in booked_data:
            start = datetime.fromisoformat(row["scheduled_at"])
            end = start + timedelta(minutes=row.get("duration_minutes") or duration_minutes)
            booked_ranges.append((start, end))

        slots = []
        cursor = datetime.combine(target_date, open_time)
        end_of_day = datetime.combine(target_date, close_time)
        now = datetime.now()

        while cursor + duration <= end_of_day:
            slot_end = cursor + duration
            if cursor > now:
                overlaps = any(cursor < b_end and slot_end > b_start for b_start, b_end in booked_ranges)
                if not overlaps:
                    slots.append(cursor)
            cursor += duration

        return slots

    async def create_appointment(
        self,
        tenant_id: str,
        customer_phone: str,
        item_id: str,
        scheduled_at: datetime,
        professional_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Books an appointment after re-checking the slot is still free."""
        available_slots = await self.get_available_slots(tenant_id, item_id, scheduled_at.date())
        if scheduled_at not in available_slots:
            return None

        duration_minutes = await self._get_item_duration_minutes(tenant_id, item_id)

        try:
            result = self.db.table("appointments").insert({
                "tenant_id": tenant_id,
                "customer_phone": customer_phone,
                "item_id": item_id,
                "professional_name": professional_name,
                "scheduled_at": scheduled_at.isoformat(),
                "duration_minutes": duration_minutes,
                "status": "scheduled",
            }).execute()

            appointment = result.data[0] if result.data else None
            if appointment:
                await self._notify_seller(tenant_id, appointment, "Nueva cita agendada")
            return appointment
        except Exception as e:
            logger.error(f"Error creating appointment: {e}")
            return None

    async def cancel_appointment(
        self, tenant_id: str, appointment_id: str, reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """Cancels an appointment if outside the cancellation-policy window."""
        try:
            result = self.db.table("appointments").select("*").eq(
                "id", appointment_id
            ).eq("tenant_id", tenant_id).execute()

            if not result.data:
                return {"success": False, "message": "No encontramos esa cita."}

            appointment = result.data[0]
            scheduled_at = datetime.fromisoformat(appointment["scheduled_at"])
            policy_hours = await self._get_cancellation_policy_hours(tenant_id)
            hours_until = (scheduled_at - datetime.now()).total_seconds() / 3600

            if hours_until < policy_hours:
                return {
                    "success": False,
                    "message": (
                        f"No es posible cancelar con menos de {policy_hours}h de "
                        "anticipación. Por favor contacta directamente al negocio."
                    ),
                }

            self.db.table("appointments").update({
                "status": "cancelled",
                "cancellation_reason": reason,
            }).eq("id", appointment_id).execute()

            await self._notify_seller(tenant_id, appointment, "Cita cancelada")
            return {"success": True, "message": "Tu cita fue cancelada."}
        except Exception as e:
            logger.error(f"Error cancelling appointment {appointment_id}: {e}")
            return {"success": False, "message": "Ocurrió un error al cancelar tu cita."}

    async def get_reminders_due(self, kind: str) -> List[Dict[str, Any]]:
        """Appointments needing a '24h' or '1h' reminder, not yet sent.
        Called by scripts/send_appointment_reminders.py (not scheduled yet)."""
        if kind not in ("24h", "1h"):
            raise ValueError("kind must be '24h' or '1h'")

        now = datetime.now()
        if kind == "24h":
            window_start, window_end = now + timedelta(hours=23, minutes=45), now + timedelta(hours=24, minutes=15)
            field = "reminder_24h_sent_at"
        else:
            window_start, window_end = now + timedelta(minutes=45), now + timedelta(hours=1, minutes=15)
            field = "reminder_1h_sent_at"

        try:
            result = self.db.table("appointments").select("*").eq(
                "status", "scheduled"
            ).gte("scheduled_at", window_start.isoformat()).lte(
                "scheduled_at", window_end.isoformat()
            ).is_(field, "null").execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Error getting due {kind} reminders: {e}")
            return []

    async def mark_reminder_sent(self, appointment_id: str, kind: str) -> None:
        field = "reminder_24h_sent_at" if kind == "24h" else "reminder_1h_sent_at"
        try:
            self.db.table("appointments").update({
                field: datetime.now().isoformat()
            }).eq("id", appointment_id).execute()
        except Exception as e:
            logger.error(f"Error marking {kind} reminder sent for {appointment_id}: {e}")

    async def _notify_seller(self, tenant_id: str, appointment: Dict[str, Any], label: str) -> None:
        """Best-effort seller notification, mirroring the pattern already
        used for new-order notifications in CartConfirmationHandler."""
        try:
            config_result = self.db.table("whatsapp_configs").select(
                "seller_phone, phone_number, phone_number_id, access_token"
            ).eq("tenant_id", tenant_id).limit(1).execute()

            if not config_result.data:
                return

            config = config_result.data[0]
            seller_phone = config.get("seller_phone") or config.get("phone_number")
            customer_phone = appointment.get("customer_phone")

            if not seller_phone or seller_phone == customer_phone:
                return

            scheduled_at = datetime.fromisoformat(appointment["scheduled_at"])
            notification = (
                f"📅 {label}\n"
                f"Cliente: {customer_phone}\n"
                f"Fecha: {scheduled_at.strftime('%d/%m/%Y %H:%M')}"
            )

            MetaWhatsAppService(
                phone_number_id=config["phone_number_id"],
                access_token=config["access_token"],
            ).send_message(seller_phone, notification)
        except Exception as e:
            logger.warning(f"Could not notify seller for tenant {tenant_id}: {e}")
